#!/usr/bin/env python3
"""
Sweep alpha parameters for the order-book imbalance signal.
Tests ALPHA_DECAY, ALPHA_WEIGHT, ALPHA_TAKE_FILTER, and quote skew threshold.
"""
import os, re, subprocess, json

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")

with open(TRADER) as f:
    ORIGINAL = f.read()


def set_params(content, params):
    """Set class-level params in TomatoesMM section only."""
    # Find TomatoesMM class section
    tom_start = content.index("class TomatoesMM:")
    tom_end = content.index("\nclass Trader:")
    tom_section = content[tom_start:tom_end]

    for param, value in params.items():
        if isinstance(value, bool):
            tom_section = re.sub(
                rf"(\s+{param}\s*=\s*)(True|False)",
                rf"\g<1>{value}",
                tom_section,
            )
        else:
            tom_section = re.sub(
                rf"(\s+{param}\s*=\s*)[\d.]+",
                rf"\g<1>{value}",
                tom_section,
            )

    # Also handle the skew threshold (hardcoded in code)
    if "SKEW_THR" in params:
        thr = params["SKEW_THR"]
        tom_section = re.sub(r"alpha > [\d.]+", f"alpha > {thr}", tom_section)
        tom_section = re.sub(r"alpha < -[\d.]+", f"alpha < -{thr}", tom_section)

    return content[:tom_start] + tom_section + content[tom_end:]


def run_backtest(content):
    with open(TRADER, "w") as f:
        f.write(content)
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "run_rust_backtest.sh"), "bestfornow.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    out = result.stdout
    sub_pnl = d1_pnl = d2_pnl = tom_sub = None
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

    min_tom = 0.0
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
                        min_tom = min(min_tom, pnl)
    return {"sub": sub_pnl, "d1": d1_pnl, "d2": d2_pnl,
            "tom_sub": tom_sub, "min_tom": min_tom}


def fmt(v, w=8):
    return " " * w if v is None else f"{v:>{w}.1f}"


HDR = f"{'Decay':>6} {'AWt':>5} {'Filter':>6} {'SkThr':>6} | {'SUB':>8} {'TOM':>8} {'MinTOM':>8} {'D1':>10} {'D2':>10}"
SEP = "-" * len(HDR)
all_results = []


def test(decay, aw, filt, skew_thr):
    content = set_params(ORIGINAL, {
        "ALPHA_DECAY": decay,
        "ALPHA_WEIGHT": aw,
        "ALPHA_TAKE_FILTER": filt,
        "SKEW_THR": skew_thr,
    })
    r = run_backtest(content)
    row = {"decay": decay, "aw": aw, "filt": filt, "skew_thr": skew_thr, **r}
    all_results.append(row)
    f_str = "Y" if filt else "N"
    print(f"{decay:>6.2f} {aw:>5.2f} {f_str:>6} {skew_thr:>6.2f} | "
          f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")


print(SEP)
print(HDR)
print(SEP)

# ── Baseline: no alpha (weight=0, filter=off) ──
print("\n── Baseline (alpha off) ──")
test(0.8, 0.0, False, 0.15)

# ── Phase 1: ALPHA_WEIGHT sweep (decay=0.8, filter=on, skew=0.15) ──
print("\n── P1: ALPHA_WEIGHT sweep (decay=0.8, filter=on) ──")
for aw in [0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0]:
    test(0.8, aw, True, 0.15)

# ── Phase 2: ALPHA_WEIGHT sweep with filter OFF ──
print("\n── P2: ALPHA_WEIGHT sweep (decay=0.8, filter=off) ──")
for aw in [0.1, 0.2, 0.3, 0.5]:
    test(0.8, aw, False, 0.15)

# ── Phase 3: ALPHA_DECAY sweep (aw=best from rough scan) ──
print("\n── P3: ALPHA_DECAY sweep (aw=0.3, filter=on) ──")
for decay in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]:
    test(decay, 0.3, True, 0.15)

# ── Phase 4: Skew threshold sweep ──
print("\n── P4: Skew threshold sweep (aw=0.3, decay=0.8, filter=on) ──")
for st in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    test(0.8, 0.3, True, st)

# ── Phase 5: Alpha without quote skew (skew very high = effectively off) ──
print("\n── P5: No skew (aw=0.3, filter=on vs off) ──")
test(0.8, 0.3, True, 99.0)
test(0.8, 0.3, False, 99.0)

# ── Summary ──
print("\n" + "=" * len(HDR))
print("TOP 10:")
print(SEP)
print(HDR)
print(SEP)
top = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)[:10]
for r in top:
    f_str = "Y" if r["filt"] else "N"
    print(f"{r['decay']:>6.2f} {r['aw']:>5.2f} {f_str:>6} {r['skew_thr']:>6.2f} | "
          f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")

best = top[0]
print(f"\nBEST: decay={best['decay']} aw={best['aw']} filter={best['filt']} "
      f"skew_thr={best['skew_thr']} → SUB={best['sub']} TOM={best['tom_sub']} MinTOM={best['min_tom']}")

with open(os.path.join(ROOT, "sweep_alpha_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

with open(TRADER, "w") as f:
    f.write(ORIGINAL)
print("Original restored.")
