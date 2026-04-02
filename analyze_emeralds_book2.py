import csv
from collections import defaultdict

for fname in ["data/raw/prices_round_0_day_-2.csv", "data/raw/prices_round_0_day_-1.csv"]:
    print(f"\n{fname}")
    bp1 = defaultdict(int)
    ap1 = defaultdict(int)
    bp2 = defaultdict(int)
    ap2 = defaultdict(int)
    total = 0
    with open(fname) as f:
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != "EMERALDS":
                continue
            total += 1
            bp1[int(row["bid_price_1"])] += 1
            ap1[int(row["ask_price_1"])] += 1
            if row.get("bid_price_2", "").strip():
                bp2[int(row["bid_price_2"])] += 1
            if row.get("ask_price_2", "").strip():
                ap2[int(row["ask_price_2"])] += 1
    print(f"  Total rows: {total}")
    print(f"  Best bid prices: {dict(sorted(bp1.items()))}")
    print(f"  Best ask prices: {dict(sorted(ap1.items()))}")
    print(f"  2nd bid prices:  {dict(sorted(bp2.items()))}")
    print(f"  2nd ask prices:  {dict(sorted(ap2.items()))}")

    # Volume analysis at each level
    print("\n  Volume at best bid/ask:")
    with open(fname) as f:
        vols = defaultdict(list)
        for row in csv.DictReader(f, delimiter=";"):
            if row["product"] != "EMERALDS":
                continue
            vols["bv1"].append(int(row["bid_volume_1"]))
            vols["av1"].append(int(row["ask_volume_1"]))
            if row.get("bid_volume_2", "").strip():
                vols["bv2"].append(int(row["bid_volume_2"]))
            if row.get("ask_volume_2", "").strip():
                vols["av2"].append(int(row["ask_volume_2"]))
        for k in sorted(vols):
            v = vols[k]
            print(f"    {k}: min={min(v)}, max={max(v)}, avg={sum(v)/len(v):.1f}")
