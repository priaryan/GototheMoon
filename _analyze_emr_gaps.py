#!/usr/bin/env python3
"""Analyze EMERALDS book structure to understand why trades are sparse."""
import csv
from collections import Counter

DATA = "data/raw/prices_round_0_day_-1.csv"

rows = []
with open(DATA) as f:
    for r in csv.DictReader(f, delimiter=";"):
        if r.get("product") == "EMERALDS":
            rows.append(r)

print(f"Total EMERALDS ticks: {len(rows)}")

# Categorize each tick's book shape
narrow_ticks = []  # spread <= 8
wide_ticks = []    # spread = 16

for i, r in enumerate(rows):
    b1 = int(float(r.get("bid_price_1", 0) or 0))
    a1 = int(float(r.get("ask_price_1", 0) or 0))
    b2 = int(float(r.get("bid_price_2", 0) or 0))
    a2 = int(float(r.get("ask_price_2", 0) or 0))
    b3 = int(float(r.get("bid_price_3", 0) or 0))
    a3 = int(float(r.get("ask_price_3", 0) or 0))
    bv1 = int(float(r.get("bid_volume_1", 0) or 0))
    av1 = abs(int(float(r.get("ask_volume_1", 0) or 0)))
    spread = a1 - b1

    ts = int(r["timestamp"])

    if spread <= 8:
        narrow_ticks.append((ts, b1, a1, bv1, av1, b2, a2, b3, a3))
    else:
        wide_ticks.append((ts, b1, a1, bv1, av1, b2, a2, b3, a3))

print(f"\nNarrow spread (<=8): {len(narrow_ticks)} ticks ({100*len(narrow_ticks)/len(rows):.1f}%)")
print(f"Wide spread (>8):   {len(wide_ticks)} ticks ({100*len(wide_ticks)/len(rows):.1f}%)")

# What does a narrow tick look like?
print(f"\nSample narrow ticks:")
for ts, b1, a1, bv1, av1, b2, a2, b3, a3 in narrow_ticks[:10]:
    print(f"  ts={ts:>7} bid1={b1}@{bv1} ask1={a1}@{av1} bid2={b2} ask2={a2} spread={a1-b1}")

# What does a wide tick look like?
print(f"\nSample wide ticks:")
for ts, b1, a1, bv1, av1, b2, a2, b3, a3 in wide_ticks[:5]:
    print(f"  ts={ts:>7} bid1={b1}@{bv1} ask1={a1}@{av1} bid2={b2} ask2={a2} spread={a1-b1}")

# Our strategy places making orders at bid_wall+1 and ask_wall-1
# bid_wall = min(all bids), ask_wall = max(all asks)
# On wide ticks: walls at 9990/10010, so make at 9991/10009
# But best bid=9992 and best ask=10008 — our 9991 bid is BELOW best bid,
# and our 10009 ask is ABOVE best ask. So we can't get filled by existing book.
# We'd need someone to sell at 9991 or buy at 10009.

# On narrow ticks: walls differ. Let's check
print(f"\nNarrow tick wall analysis:")
for ts, b1, a1, bv1, av1, b2, a2, b3, a3 in narrow_ticks[:15]:
    all_bids = [x for x in [b1, b2, b3] if x > 0]
    all_asks = [x for x in [a1, a2, a3] if x > 0]
    bid_wall = min(all_bids) if all_bids else b1
    ask_wall = max(all_asks) if all_asks else a1
    wall_mid = (bid_wall + ask_wall) / 2
    make_bid = bid_wall + 1
    make_ask = ask_wall - 1
    # Can our make_bid buy from book? Only if make_bid >= a1
    buy_fill = make_bid >= a1
    sell_fill = make_ask <= b1
    print(f"  ts={ts:>7} walls={bid_wall}/{ask_wall} mid={wall_mid} make={make_bid}/{make_ask} "
          f"b1={b1} a1={a1} fill_buy={buy_fill} fill_sell={sell_fill}")

# Gap analysis: consecutive wide-spread ticks
print(f"\nLongest streaks without narrow spread:")
streak = 0
max_streak = 0
streak_start = 0
streaks = []
for i, r in enumerate(rows):
    b1 = int(float(r.get("bid_price_1", 0) or 0))
    a1 = int(float(r.get("ask_price_1", 0) or 0))
    if a1 - b1 > 8:
        if streak == 0:
            streak_start = int(r["timestamp"])
        streak += 1
    else:
        if streak > 20:
            streaks.append((streak, streak_start, int(r["timestamp"])))
        streak = 0

streaks.sort(key=lambda x: -x[0])
for length, start, end in streaks[:10]:
    print(f"  {length} ticks wide: ts {start} -> {end}")
