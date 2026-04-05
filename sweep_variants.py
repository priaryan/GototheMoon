#!/usr/bin/env python3
"""
Sweep all TOMATOES variants (A-F) using the Rust backtester.

Modifies bestfornow.py in-place for each config, runs the Rust backtest,
extracts SUB PnL (total + TOMATOES), min TOMATOES PnL (drawdown proxy),
and per-day PnL.

Variants:
  A: INV_PENALTY only
  B: MOMENTUM_WEIGHT only
  C: Regime filter (MOMENTUM_THRESHOLD) only
  D: INV_PENALTY + MOMENTUM_WEIGHT
  E: INV_PENALTY + MOMENTUM_THRESHOLD
  F: INV_PENALTY + MOMENTUM_WEIGHT + MOMENTUM_THRESHOLD
"""
import os, re, subprocess, json, sys, time, itertools

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")

# ── Save original ──────────────────────────────────────────────────────
with open(TRADER) as f:
    ORIGINAL = f.read()


def patch_trader(inv_penalty, momentum_weight, threshold):
    """
    Rewrite bestfornow.py with specified TOMATOES params.
    If threshold > 0, inject the regime filter logic.
    """
    src = ORIGINAL

    # Patch class-level constants in TomatoesMM
    src = re.sub(r"(class TomatoesMM[\s\S]*?INV_PENALTY\s*=\s*)[\d.]+", rf"\g<1>{inv_penalty}", src)
    src = re.sub(r"(class TomatoesMM[\s\S]*?MOMENTUM_WEIGHT\s*=\s*)[\d.]+", rf"\g<1>{momentum_weight}", src)

    # Inject/remove regime filter
    if threshold > 0:
        # Add MOMENTUM_THRESHOLD constant if not present
        if "MOMENTUM_THRESHOLD" not in src:
            src = src.replace(
                "    WARMUP_TICKS = 5",
                f"    MOMENTUM_THRESHOLD = {threshold}\n\n    WARMUP_TICKS = 5",
            )
        else:
            src = re.sub(r"(MOMENTUM_THRESHOLD\s*=\s*)[\d.]+", rf"\g<1>{threshold}", src)

        # Inject filter logic right after `momentum = fast_ema - slow_ema`
        if "effective_momentum" not in src:
            src = src.replace(
                "        momentum = fast_ema - slow_ema\n",
                "        momentum = fast_ema - slow_ema\n"
                "        if abs(momentum) < self.MOMENTUM_THRESHOLD:\n"
                "            momentum = 0.0\n",
            )
    else:
        # Remove filter if present from a prior patch
        if "MOMENTUM_THRESHOLD" in src:
            src = re.sub(r"    MOMENTUM_THRESHOLD = [\d.]+\n\n", "", src)
            src = re.sub(
                r"        if abs\(momentum\) < self\.MOMENTUM_THRESHOLD:\n"
                r"            momentum = 0\.0\n",
                "",
                src,
            )

    with open(TRADER, "w") as f:
        f.write(src)


def run_backtest():
    """Run Rust backtester and parse results."""
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "run_rust_backtest.sh"), "bestfornow.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    out = result.stdout
    sub_pnl = d1_pnl = d2_pnl = tom_sub = emr_sub = None
    sub_run_dir = None

    for line in out.strip().split("\n"):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "SUB":
            sub_pnl = float(parts[4])
            sub_run_dir = parts[5]
        elif parts[0] == "D-1":
            d1_pnl = float(parts[4])
        elif parts[0] == "D-2":
            d2_pnl = float(parts[4])
        elif parts[0] == "TOM":
            tom_sub = float(parts[3])
        elif parts[0] == "EMR":
            emr_sub = float(parts[3])

    # Extract min TOMATOES PnL from submission log
    min_tom = 0.0
    min_ts = 0
    if sub_run_dir:
        log_path = os.path.join(RUST_BT, sub_run_dir, "submission.log")
        if os.path.exists(log_path):
            with open(log_path) as f:
                data = json.load(f)
            activities = data.get("activitiesLog", "")
            if isinstance(activities, str):
                for ln in activities.strip().split("\n"):
                    p = ln.split(";")
                    if len(p) < 4 or p[1] == "timestamp":
                        continue
                    if p[2] == "TOMATOES":
                        pnl = float(p[-1])
                        if pnl < min_tom:
                            min_tom = pnl
                            min_ts = int(p[1])
    return {
        "sub": sub_pnl, "d1": d1_pnl, "d2": d2_pnl,
        "tom_sub": tom_sub, "emr_sub": emr_sub,
        "min_tom": min_tom, "min_ts": min_ts,
    }


def fmt(val, w=8):
    if val is None:
        return " " * w
    return f"{val:>{w}.1f}"


# ── Header ─────────────────────────────────────────────────────────────
HDR = (
    f"{'Variant':<10} {'IP':>5} {'MW':>5} {'Thr':>5} | "
    f"{'SUB':>8} {'TOM_SUB':>8} {'MinTOM':>8} {'D1':>10} {'D2':>10}"
)
SEP = "-" * len(HDR)

all_results = []


def test(variant, ip, mw, thr):
    patch_trader(ip, mw, thr)
    r = run_backtest()
    row = {
        "variant": variant, "ip": ip, "mw": mw, "thr": thr,
        **r,
    }
    all_results.append(row)
    print(
        f"{variant:<10} {ip:>5.2f} {mw:>5.2f} {thr:>5.2f} | "
        f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} "
        f"{fmt(r['d1'], 10)} {fmt(r['d2'], 10)}"
    )
    return r


# ══════════════════════════════════════════════════════════════════════
print("\n" + SEP)
print(HDR)
print(SEP)

# Baseline
print("\n── Baseline ──")
test("BASE", 0.0, 0.5, 0.0)

# Variant A: INV_PENALTY only
print("\n── Variant A: INV_PENALTY only (MW=0.5, Thr=0) ──")
for ip in [0.01, 0.02, 0.03, 0.05, 0.08, 0.10]:
    test("A", ip, 0.5, 0.0)

# Variant B: MOMENTUM_WEIGHT only
print("\n── Variant B: MOMENTUM_WEIGHT only (IP=0, Thr=0) ──")
for mw in [0.15, 0.2, 0.25, 0.3, 0.35, 0.4]:
    test("B", 0.0, mw, 0.0)

# Variant C: Regime filter only
print("\n── Variant C: Regime filter only (IP=0, MW=0.5) ──")
for thr in [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]:
    test("C", 0.0, 0.5, thr)

# Variant D: INV_PENALTY + MOMENTUM_WEIGHT
print("\n── Variant D: IP + MW (Thr=0) ──")
for ip in [0.01, 0.02, 0.03]:
    for mw in [0.15, 0.2, 0.25, 0.3]:
        test("D", ip, mw, 0.0)

# Variant E: INV_PENALTY + Regime filter
print("\n── Variant E: IP + Thr (MW=0.5) ──")
for ip in [0.01, 0.02, 0.03]:
    for thr in [0.25, 0.5, 0.75, 1.0]:
        test("E", ip, 0.5, thr)

# Variant F: All three
print("\n── Variant F: IP + MW + Thr ──")
for ip in [0.01, 0.02, 0.03]:
    for mw in [0.2, 0.25, 0.3]:
        for thr in [0.5, 0.75, 1.0]:
            test("F", ip, mw, thr)

# ── Summary ────────────────────────────────────────────────────────────
print("\n" + "=" * len(HDR))
print("TOP 10 BY SUB PnL:")
print(SEP)
print(HDR)
print(SEP)
top = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)[:10]
for r in top:
    print(
        f"{r['variant']:<10} {r['ip']:>5.2f} {r['mw']:>5.2f} {r['thr']:>5.2f} | "
        f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} "
        f"{fmt(r['d1'], 10)} {fmt(r['d2'], 10)}"
    )

print(f"\n{'TOP 10 BY MIN DRAWDOWN (least negative MinTOM, SUB > baseline*0.95):'}")
base_sub = all_results[0]["sub"] or 0
threshold_sub = base_sub * 0.95
filtered = [r for r in all_results if (r["sub"] or -9999) >= threshold_sub]
top_dd = sorted(filtered, key=lambda r: r["min_tom"] or -9999, reverse=True)[:10]
print(SEP)
print(HDR)
print(SEP)
for r in top_dd:
    print(
        f"{r['variant']:<10} {r['ip']:>5.2f} {r['mw']:>5.2f} {r['thr']:>5.2f} | "
        f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} "
        f"{fmt(r['d1'], 10)} {fmt(r['d2'], 10)}"
    )

# Best balanced: highest SUB among those with MinTOM > -120
balanced = [r for r in all_results if (r["min_tom"] or -999) > -120]
if balanced:
    best_bal = max(balanced, key=lambda r: r["sub"] or -9999)
    print(f"\nBEST BALANCED (MinTOM > -120, max SUB):")
    print(
        f"  {best_bal['variant']} IP={best_bal['ip']} MW={best_bal['mw']} "
        f"Thr={best_bal['thr']} → SUB={best_bal['sub']} TOM={best_bal['tom_sub']} "
        f"MinTOM={best_bal['min_tom']}"
    )

# Absolute best SUB
best = max(all_results, key=lambda r: r["sub"] or -9999)
print(f"\nBEST SUB PnL:")
print(
    f"  {best['variant']} IP={best['ip']} MW={best['mw']} "
    f"Thr={best['thr']} → SUB={best['sub']} TOM={best['tom_sub']} "
    f"MinTOM={best['min_tom']}"
)

# Save all results to JSON
with open(os.path.join(ROOT, "sweep_variants_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

# ── Restore original ──────────────────────────────────────────────────
with open(TRADER, "w") as f:
    f.write(ORIGINAL)
print("\nOriginal bestfornow.py restored.")
