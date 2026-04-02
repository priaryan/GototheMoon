#!/usr/bin/env python3
"""Quick analysis of EMERALDS data to understand price structure."""
import csv
from collections import Counter

for day in ["-1", "-2"]:
    path = f"data/raw/prices_round_0_day_{day}.csv"
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = [r for r in reader if r.get("product") == "EMERALDS"]

    print(f"\n=== Day {day}: {len(rows)} EMERALDS ticks ===")
    spreads = []
    bids = []
    asks = []
    for r in rows[:5]:
        print(f"  ts={r['timestamp']} b1={r.get('bid_price_1','')}@{r.get('bid_volume_1','')} "
              f"a1={r.get('ask_price_1','')}@{r.get('ask_volume_1','')} "
              f"b2={r.get('bid_price_2','')} a2={r.get('ask_price_2','')}")

    for r in rows:
        b1 = r.get("bid_price_1", "")
        a1 = r.get("ask_price_1", "")
        if b1 and a1:
            b = float(b1)
            a = float(a1)
            bids.append(int(b))
            asks.append(int(a))
            spreads.append(a - b)

    if spreads:
        print(f"  Spread: min={min(spreads)} max={max(spreads)} avg={sum(spreads)/len(spreads):.2f}")
        c = Counter(int(s) for s in spreads)
        print(f"  Spread dist: {c.most_common(10)}")
        print(f"  Bid range: {min(bids)}-{max(bids)}")
        print(f"  Ask range: {min(asks)}-{max(asks)}")
        # How many ticks have asks < 10000 or bids > 10000?
        cross = sum(1 for b, a in zip(bids, asks) if b >= 10000 or a <= 10000)
        print(f"  Ticks crossing fair (10000): {cross}/{len(bids)}")
