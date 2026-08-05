#!/usr/bin/env python3
"""
Sweep INV_PENALTY + other params for bestfornow.py using the Rust backtester.
Modifies the .py file, runs Rust backtest, parses results + dip.
"""
import os, re, subprocess, json, time, sys, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")
EXTRACT = os.path.join(ROOT, "_extract_pnl.py")


def set_param(content, param, value):
    """Replace a class-level parameter value in the trader code."""
    pattern = rf"(\s+{param}\s*=\s*)([\d.]+)"
    return re.sub(pattern, rf"\g<1>{value}", content)


def run_backtest(content, label=""):
    """Write modified trader, run Rust backtester, return results."""
    # Write modified trader
    with open(TRADER, 'w') as f:
        f.write(content)

    # Run Rust backtester via shell script (handles cargo env setup)
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "run_rust_backtest.sh"), "bestfornow.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=60
    )

    # Parse output
    output = result.stdout
    lines = output.strip().split('\n')
    
    # Find SUB line
    sub_pnl = None
    sub_run_dir = None
    d1_pnl = None
    d2_pnl = None
    tom_sub = None
    
    for line in lines:
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
        if parts[0] == "TOM":
            tom_sub = float(parts[3])

    # Extract min PnL from submission log
    min_tom = 0.0
    if sub_run_dir:
        log_path = os.path.join(RUST_BT, sub_run_dir, "submission.log")
        if os.path.exists(log_path):
            with open(log_path) as f:
                data = json.load(f)
            activities = data.get("activitiesLog", "")
            if isinstance(activities, str):
                for line in activities.strip().split("\n"):
                    p = line.split(";")
                    if len(p) < 4 or p[1] == "timestamp":
                        continue
                    if p[2] == "TOMATOES":
                        pnl = float(p[-1])
                        min_tom = min(min_tom, pnl)

    return {
        "sub_pnl": sub_pnl,
        "d1_pnl": d1_pnl,
        "d2_pnl": d2_pnl,
        "tom_sub": tom_sub,
        "min_tom_pnl": min_tom,
    }


def main():
    # Read original content
    with open(TRADER) as f:
        original = f.read()

    results = []
    best_sub = -9999
    best_config = None

    print(f"{'INV_PEN':>8} {'TAKE_M':>8} {'WARMUP':>8} | {'SUB':>8} {'TOM_SUB':>8} {'MinTOM':>8} {'D1':>8} {'D2':>8}")
    print("-" * 85)

    # Phase 1: Sweep INV_PENALTY
    for ip in [0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]:
        content = set_param(original, "INV_PENALTY", ip)
        r = run_backtest(content, f"ip={ip}")
        print(f"{ip:>8.2f} {'0.00':>8} {'5':>8} | {r['sub_pnl']:>8.1f} {r['tom_sub']:>8.1f} {r['min_tom_pnl']:>8.1f} {r['d1_pnl']:>8.1f} {r['d2_pnl']:>8.1f}")
        results.append(("ip", ip, r))
        if r['sub_pnl'] and r['sub_pnl'] > best_sub:
            best_sub = r['sub_pnl']
            best_config = {"INV_PENALTY": ip, "TAKE_MARGIN": 0.0, "WARMUP_TICKS": 5}

    print(f"\nBest Phase 1: SUB={best_sub:.1f}  config={best_config}")

    best_ip = best_config["INV_PENALTY"]

    # Phase 2: Sweep TAKE_MARGIN with best IP
    print(f"\nPhase 2: TAKE_MARGIN sweep (IP={best_ip})")
    print("-" * 85)
    for tm in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50]:
        content = set_param(original, "INV_PENALTY", best_ip)
        content = set_param(content, "TAKE_MARGIN", tm)
        r = run_backtest(content, f"tm={tm}")
        print(f"{best_ip:>8.2f} {tm:>8.2f} {'5':>8} | {r['sub_pnl']:>8.1f} {r['tom_sub']:>8.1f} {r['min_tom_pnl']:>8.1f} {r['d1_pnl']:>8.1f} {r['d2_pnl']:>8.1f}")
        results.append(("tm", tm, r))
        if r['sub_pnl'] and r['sub_pnl'] > best_sub:
            best_sub = r['sub_pnl']
            best_config["TAKE_MARGIN"] = tm

    best_tm = best_config.get("TAKE_MARGIN", 0.0)

    # Phase 3: Sweep WARMUP_TICKS
    print(f"\nPhase 3: WARMUP_TICKS sweep (IP={best_ip}, TM={best_tm})")
    print("-" * 85)
    for wt in [0, 3, 5, 10, 15, 20, 30, 50]:
        content = set_param(original, "INV_PENALTY", best_ip)
        content = set_param(content, "TAKE_MARGIN", best_tm)
        content = set_param(content, "WARMUP_TICKS", wt)
        r = run_backtest(content, f"wt={wt}")
        print(f"{best_ip:>8.2f} {best_tm:>8.2f} {wt:>8} | {r['sub_pnl']:>8.1f} {r['tom_sub']:>8.1f} {r['min_tom_pnl']:>8.1f} {r['d1_pnl']:>8.1f} {r['d2_pnl']:>8.1f}")
        results.append(("wt", wt, r))
        if r['sub_pnl'] and r['sub_pnl'] > best_sub:
            best_sub = r['sub_pnl']
            best_config["WARMUP_TICKS"] = wt

    best_wt = best_config.get("WARMUP_TICKS", 5)

    # Phase 4: Fine grid around best
    print(f"\nPhase 4: Fine grid around best (IP={best_ip}, TM={best_tm}, WT={best_wt})")
    print("-" * 85)
    for ip_d in [-0.02, -0.01, 0.0, 0.01, 0.02]:
        ip = max(0, best_ip + ip_d)
        for tm_d in [-0.05, 0.0, 0.05]:
            tm = max(0, best_tm + tm_d)
            content = set_param(original, "INV_PENALTY", ip)
            content = set_param(content, "TAKE_MARGIN", tm)
            content = set_param(content, "WARMUP_TICKS", best_wt)
            r = run_backtest(content)
            marker = " ***" if r['sub_pnl'] and r['sub_pnl'] > best_sub else ""
            print(f"{ip:>8.2f} {tm:>8.2f} {best_wt:>8} | {r['sub_pnl']:>8.1f} {r['tom_sub']:>8.1f} {r['min_tom_pnl']:>8.1f} {r['d1_pnl']:>8.1f} {r['d2_pnl']:>8.1f}{marker}")
            if r['sub_pnl'] and r['sub_pnl'] > best_sub:
                best_sub = r['sub_pnl']
                best_config = {"INV_PENALTY": ip, "TAKE_MARGIN": tm, "WARMUP_TICKS": best_wt}

    print(f"\n{'='*85}")
    print(f"FINAL BEST: SUB={best_sub:.1f}  Config={best_config}")

    # Restore best config
    content = original
    for k, v in best_config.items():
        content = set_param(content, k, v)
    with open(TRADER, 'w') as f:
        f.write(content)
    print(f"Best config written to {TRADER}")


if __name__ == "__main__":
    main()
