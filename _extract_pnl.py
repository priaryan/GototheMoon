#!/usr/bin/env python3
"""Extract early PnL from Rust backtester submission log."""
import json, sys

log_path = sys.argv[1] if len(sys.argv) > 1 else "runs/backtest-1775379362823-tutorial-submission-day-1/submission.log"

with open(log_path) as f:
    data = json.load(f)

activities = data.get("activitiesLog", data.get("activities", ""))
if isinstance(activities, str):
    lines = activities.strip().split("\n")
    tom_pnl = {}
    emr_pnl = {}
    for line in lines:
        parts = line.split(";")
        if len(parts) < 4:
            continue
        if parts[1] == "timestamp":
            continue
        ts = int(parts[1])
        product = parts[2]
        pnl = float(parts[-1])
        if product == "TOMATOES":
            tom_pnl[ts] = pnl
        elif product == "EMERALDS":
            emr_pnl[ts] = pnl

    print("Tick     TOM_PnL  EMR_PnL  TOTAL")
    all_ts = sorted(set(list(tom_pnl.keys()) + list(emr_pnl.keys())))
    min_tom = 99999
    min_ts = 0
    for ts in all_ts:
        tp = tom_pnl.get(ts, 0)
        ep = emr_pnl.get(ts, 0)
        if tp < min_tom:
            min_tom = tp
            min_ts = ts
        if ts <= 20000 or ts % 10000 == 0 or ts == all_ts[-1]:
            print(f"{ts:>8}  {tp:>8.1f}  {ep:>8.1f}  {tp+ep:>8.1f}")

    print(f"\nMin TOMATOES PnL: {min_tom:.1f} at tick {min_ts}")
    print(f"Final: TOM={tom_pnl.get(all_ts[-1], 0):.1f}  EMR={emr_pnl.get(all_ts[-1], 0):.1f}")
