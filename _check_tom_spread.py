#!/usr/bin/env python3
"""Quick check of TOMATOES spread distribution to calibrate spread_neutral."""
import csv
from collections import Counter

for day in ["-1", "-2"]:
    path = f"data/raw/prices_round_0_day_{day}.csv"
    spreads = []
    with open(path) as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("product") != "TOMATOES":
                continue
            b1 = r.get("bid_price_1", "")
            a1 = r.get("ask_price_1", "")
            if b1 and a1:
                spreads.append(int(float(a1)) - int(float(b1)))
    c = Counter(spreads)
    print(f"Day {day}: {len(spreads)} ticks")
    for sp, cnt in sorted(c.items()):
        pct = 100 * cnt / len(spreads)
        bar = "#" * int(pct / 2)
        print(f"  spread={sp:>3}: {cnt:>5} ({pct:>5.1f}%) {bar}")
