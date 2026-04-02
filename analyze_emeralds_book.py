"""Analyze EMERALDS order book structure in detail to understand what price levels exist."""
import csv
import json
from collections import defaultdict

files = [
    "data/raw/prices_round_0_day_-2.csv",
    "data/raw/prices_round_0_day_-1.csv",
]

for fname in files:
    print(f"\n{'='*60}")
    print(f"FILE: {fname}")
    print(f"{'='*60}")
    
    bid_price_counts = defaultdict(int)
    ask_price_counts = defaultdict(int)
    bid_ask_spread = defaultdict(int)
    
    cross_fair_asks = 0  # asks <= 10000
    cross_fair_bids = 0  # bids >= 10000
    total_rows = 0
    
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row["product"] != "EMERALDS":
                continue
            total_rows += 1
            
            # Parse sell orders (asks)
            sells_str = row.get("sell_orders", "{}")
            buys_str = row.get("buy_orders", "{}")
            
            sells = json.loads(sells_str.replace("'", '"')) if sells_str and sells_str != '{}' else {}
            buys = json.loads(buys_str.replace("'", '"')) if buys_str and buys_str != '{}' else {}
            
            for p in sells:
                ask_price_counts[int(p)] += 1
                if int(p) <= 10000:
                    cross_fair_asks += 1
            
            for p in buys:
                bid_price_counts[int(p)] += 1
                if int(p) >= 10000:
                    cross_fair_bids += 1
            
            if buys and sells:
                best_bid = max(int(p) for p in buys)
                best_ask = min(int(p) for p in sells)
                spread = best_ask - best_bid
                bid_ask_spread[spread] += 1
    
    print(f"\nTotal EMERALDS rows: {total_rows}")
    print(f"\nAsks <= 10000 (takeable buys): {cross_fair_asks} ({100*cross_fair_asks/total_rows:.1f}%)")
    print(f"Bids >= 10000 (takeable sells): {cross_fair_bids} ({100*cross_fair_bids/total_rows:.1f}%)")
    
    print(f"\nBid prices (sorted):")
    for p in sorted(bid_price_counts):
        print(f"  {p}: {bid_price_counts[p]} times ({100*bid_price_counts[p]/total_rows:.1f}%)")
    
    print(f"\nAsk prices (sorted):")
    for p in sorted(ask_price_counts):
        print(f"  {p}: {ask_price_counts[p]} times ({100*ask_price_counts[p]/total_rows:.1f}%)")
    
    print(f"\nBest bid-ask spread distribution:")
    for s in sorted(bid_ask_spread):
        print(f"  {s} ticks: {bid_ask_spread[s]} times ({100*bid_ask_spread[s]/total_rows:.1f}%)")
