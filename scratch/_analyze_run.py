#!/usr/bin/env python3
"""Analyze backtest trades and position/PnL data."""
import csv

RUN = "runs/backtest-f3187ef4"

for day in ["-1", "-2"]:
    trades = []
    with open(f"{RUN}/trades.csv") as f:
        for r in csv.DictReader(f):
            if r["day"] == day:
                trades.append(r)

    buys = [t for t in trades if int(t["quantity"]) > 0]
    sells = [t for t in trades if int(t["quantity"]) < 0]
    buy_vol = sum(int(t["quantity"]) for t in buys)
    sell_vol = sum(abs(int(t["quantity"])) for t in sells)
    buy_avg = sum(float(t["price"]) * int(t["quantity"]) for t in buys) / buy_vol if buy_vol else 0
    sell_avg = sum(float(t["price"]) * abs(int(t["quantity"])) for t in sells) / sell_vol if sell_vol else 0

    print(f"=== Day {day}: {len(trades)} fills ===")
    print(f"  Buys:  {len(buys)} fills, {buy_vol} units, avg px {buy_avg:.1f}")
    print(f"  Sells: {len(sells)} fills, {sell_vol} units, avg px {sell_avg:.1f}")
    if buy_vol and sell_vol:
        print(f"  Edge:  sell_avg - buy_avg = {sell_avg - buy_avg:.1f}")

    # Timing
    ts_list = sorted(set(int(t["timestamp"]) for t in trades))
    if ts_list:
        print(f"  First trade: ts={ts_list[0]}, Last trade: ts={ts_list[-1]}")
        gaps = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        if gaps:
            print(f"  Avg gap between trade ticks: {sum(gaps)/len(gaps):.0f}")

    # Cluster analysis: where do most trades happen?
    early = [t for t in trades if int(t["timestamp"]) < 333000]
    mid = [t for t in trades if 333000 <= int(t["timestamp"]) < 666000]
    late = [t for t in trades if int(t["timestamp"]) >= 666000]
    print(f"  Trade distribution: early(0-333k)={len(early)} mid(333k-666k)={len(mid)} late(666k+)={len(late)}")

    # Activity / position
    act = []
    with open(f"{RUN}/activity.csv") as f:
        for r in csv.DictReader(f):
            if r["day"] == day:
                act.append(r)

    positions = [int(float(a.get("pos_TOMATOES", 0) or 0)) for a in act]
    pnls = [float(a.get("pnl_TOMATOES", 0) or 0) for a in act]

    if positions:
        max_long = max(positions)
        max_short = min(positions)
        time_long = sum(1 for p in positions if p > 0)
        time_short = sum(1 for p in positions if p < 0)
        time_flat = sum(1 for p in positions if p == 0)
        print(f"  Max long: {max_long}, Max short: {max_short}")
        print(f"  Time: long={time_long} flat={time_flat} short={time_short} (of {len(positions)} ticks)")
        # Position at key timestamps
        final_pos = positions[-1]
        print(f"  Final position: {final_pos}")
        # How often at limit
        at_limit = sum(1 for p in positions if abs(p) >= 20)
        near_limit = sum(1 for p in positions if abs(p) >= 15)
        print(f"  At limit (|pos|>=20): {at_limit} ticks, Near limit (|pos|>=15): {near_limit} ticks")

    if pnls:
        min_pnl = min(pnls)
        max_pnl = max(pnls)
        final_pnl = pnls[-1]
        print(f"  PnL: min={min_pnl:.1f} max={max_pnl:.1f} final={final_pnl:.1f}")
        peak = pnls[0]
        max_dd = 0
        for p in pnls:
            peak = max(peak, p)
            max_dd = min(max_dd, p - peak)
        print(f"  Max drawdown: {max_dd:.1f}")

    # Price where we buy vs sell
    buy_prices = sorted(set(int(float(t["price"])) for t in buys))
    sell_prices = sorted(set(int(float(t["price"])) for t in sells))
    print(f"  Buy prices:  {buy_prices}")
    print(f"  Sell prices: {sell_prices}")
    print()
