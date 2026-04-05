#!/usr/bin/env python3
"""
Fine-tune around top configs from sweep_variants.py.

Top performers from broad sweep:
  E: IP=0.02  MW=0.5   Thr=0.75  → SUB=2519.5
  F: IP=0.03  MW=0.30  Thr=0.75  → SUB=2505.5
  E: IP=0.03  MW=0.5   Thr=0.75  → SUB=2503.5
  A: IP=0.05  MW=0.5   Thr=0     → SUB=2468.5

Fine-tune plan:
  1. Thr ∈ [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90] with IP,MW from top configs
  2. IP fine grid around 0.02-0.05 with best Thr
"""
import os, re, subprocess, json, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")

with open(TRADER) as f:
    ORIGINAL = f.read()


def patch_trader(inv_penalty, momentum_weight, threshold):
    src = ORIGINAL
    src = re.sub(r"(class TomatoesMM[\s\S]*?INV_PENALTY\s*=\s*)[\d.]+", rf"\g<1>{inv_penalty}", src)
    src = re.sub(r"(class TomatoesMM[\s\S]*?MOMENTUM_WEIGHT\s*=\s*)[\d.]+", rf"\g<1>{momentum_weight}", src)
    if threshold > 0:
        if "MOMENTUM_THRESHOLD" not in src:
            src = src.replace(
                "    WARMUP_TICKS = 5",
                f"    MOMENTUM_THRESHOLD = {threshold}\n\n    WARMUP_TICKS = 5",
            )
        else:
            src = re.sub(r"(MOMENTUM_THRESHOLD\s*=\s*)[\d.]+", rf"\g<1>{threshold}", src)
        if "effective_momentum" not in src:
            src = src.replace(
                "        momentum = fast_ema - slow_ema\n",
                "        momentum = fast_ema - slow_ema\n"
                "        if abs(momentum) < self.MOMENTUM_THRESHOLD:\n"
                "            momentum = 0.0\n",
            )
    else:
        if "MOMENTUM_THRESHOLD" in src:
            src = re.sub(r"    MOMENTUM_THRESHOLD = [\d.]+\n\n", "", src)
            src = re.sub(
                r"        if abs\(momentum\) < self\.MOMENTUM_THRESHOLD:\n"
                r"            momentum = 0\.0\n", "", src)
    with open(TRADER, "w") as f:
        f.write(src)


def run_backtest():
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
    return " " * w if val is None else f"{val:>{w}.1f}"


HDR = f"{'IP':>5} {'MW':>5} {'Thr':>5} | {'SUB':>8} {'TOM':>8} {'MinTOM':>8} {'D1':>10} {'D2':>10}"
SEP = "-" * len(HDR)
all_results = []


def test(ip, mw, thr):
    patch_trader(ip, mw, thr)
    r = run_backtest()
    row = {"ip": ip, "mw": mw, "thr": thr, **r}
    all_results.append(row)
    print(f"{ip:>5.3f} {mw:>5.2f} {thr:>5.2f} | {fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")
    return r


print(SEP)
print(HDR)
print(SEP)

# Phase 1: Fine-tune Thr around 0.75 with best IP/MW combos
print("\n── Phase 1: Threshold fine-tune (IP=0.02, MW=0.5) ──")
for thr in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    test(0.02, 0.5, thr)

print("\n── Phase 2: Threshold fine-tune (IP=0.03, MW=0.5) ──")
for thr in [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    test(0.03, 0.5, thr)

# Phase 3: IP fine-tune with Thr fixed at best
best_thr_results = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)
best_thr = best_thr_results[0]["thr"]
print(f"\n── Phase 3: IP fine-tune (Thr={best_thr}, MW=0.5) ──")
for ip in [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05, 0.06]:
    test(ip, 0.5, best_thr)

# Phase 4: Also test the F-style (lower MW) with best Thr
print(f"\n── Phase 4: MW fine-tune (IP=0.03, Thr={best_thr}) ──")
for mw in [0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    test(0.03, mw, best_thr)

# Phase 5: Best IP from phase 3 + IP-only (no filter) for drawdown comparison
best_p3 = sorted([r for r in all_results if r["thr"] == best_thr and r["mw"] == 0.5],
                  key=lambda r: r["sub"] or -9999, reverse=True)
best_ip = best_p3[0]["ip"] if best_p3 else 0.02
print(f"\n── Phase 5: Drawdown check (IP={best_ip}, MW=0.5, no filter) ──")
test(best_ip, 0.5, 0.0)

# Summary
print("\n" + "=" * len(HDR))
print("TOP 10:")
print(SEP)
print(HDR)
print(SEP)
top = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)[:10]
for r in top:
    print(f"{r['ip']:>5.3f} {r['mw']:>5.2f} {r['thr']:>5.2f} | {fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")

best = top[0]
print(f"\nBEST: IP={best['ip']} MW={best['mw']} Thr={best['thr']} → SUB={best['sub']} TOM={best['tom_sub']} MinTOM={best['min_tom']}")

# Save
with open(os.path.join(ROOT, "sweep_finetune_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

with open(TRADER, "w") as f:
    f.write(ORIGINAL)
print("Original bestfornow.py restored.")
