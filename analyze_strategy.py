import csv

# Deep analysis of EMERALDS order book and what wall-mid does
for day in [-2, -1]:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    rows = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'EMERALDS':
                bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
                bid2 = int(float(row['bid_price_2'])) if row['bid_price_2'] else None
                ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
                ask2 = int(float(row['ask_price_2'])) if row['ask_price_2'] else None
                bv1 = int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0
                bv2 = int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0
                av1 = int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0
                av2 = int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0
                rows.append({
                    'bid1': bid1, 'bv1': bv1, 'bid2': bid2, 'bv2': bv2,
                    'ask1': ask1, 'av1': av1, 'ask2': ask2, 'av2': av2,
                })

    # What wall-mid computes
    print(f"\n=== EMERALDS Day {day} ===")
    for r in rows[:5]:
        bid_wall = min(r['bid1'], r['bid2']) if r['bid2'] else r['bid1']
        ask_wall = max(r['ask1'], r['ask2']) if r['ask2'] else r['ask1']
        wall_mid = (bid_wall + ask_wall) / 2
        
        # What the strategy would compute for MAKING
        bid_price = int(bid_wall + 1)  # e.g. 9991
        ask_price = int(ask_wall - 1)  # e.g. 10009
        
        # Overbid logic
        best_bid = r['bid1']
        overbid = best_bid + 1  # e.g. 9993
        if r['bv1'] > 1 and overbid < wall_mid:
            bid_price = max(bid_price, overbid)
        
        best_ask = r['ask1']
        underbid = best_ask - 1  # e.g. 10007
        if r['av1'] > 1 and underbid > wall_mid:
            ask_price = min(ask_price, underbid)
        
        print(f"  Book: {r['bid1']}x{r['bv1']}, {r['bid2']}x{r['bv2']} | {r['ask1']}x{r['av1']}, {r['ask2']}x{r['av2']}")
        print(f"  wall_mid={wall_mid}, bid_wall={bid_wall}, ask_wall={ask_wall}")
        print(f"  Strategy quotes: BID@{bid_price}, ASK@{ask_price} (spread={ask_price-bid_price})")
        print()

    # Count how far from 10000 the quotes end up
    bid_prices = []
    ask_prices = []
    for r in rows:
        bid_wall = min(r['bid1'], r['bid2']) if r['bid2'] else r['bid1']
        ask_wall = max(r['ask1'], r['ask2']) if r['ask2'] else r['ask1']
        wall_mid = (bid_wall + ask_wall) / 2
        
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)
        
        best_bid = r['bid1']
        overbid = best_bid + 1
        if r['bv1'] > 1 and overbid < wall_mid:
            bid_price = max(bid_price, overbid)
        
        best_ask = r['ask1']
        underbid = best_ask - 1
        if r['av1'] > 1 and underbid > wall_mid:
            ask_price = min(ask_price, underbid)
        
        bid_prices.append(bid_price)
        ask_prices.append(ask_price)
    
    from collections import Counter
    print(f"  Bid quote distribution: {Counter(bid_prices).most_common(5)}")
    print(f"  Ask quote distribution: {Counter(ask_prices).most_common(5)}")
    print(f"  Avg spread: {sum(a - b for a, b in zip(ask_prices, bid_prices)) / len(rows):.1f}")

# TOMATOES wall-mid vs best bid/ask analysis
print("\n\n=== TOMATOES: wall_mid vs mid_price ===")
for day in [-2, -1]:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    diffs = []
    spreads_wm = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
                bid2 = int(float(row['bid_price_2'])) if row['bid_price_2'] else None
                ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
                ask2 = int(float(row['ask_price_2'])) if row['ask_price_2'] else None
                bv1 = int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0
                bv2 = int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0
                av1 = int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0
                av2 = int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0
                
                if bid1 and ask1:
                    mid = (bid1 + ask1) / 2
                    bid_wall = min(bid1, bid2) if bid2 else bid1
                    ask_wall = max(ask1, ask2) if ask2 else ask1
                    wall_mid = (bid_wall + ask_wall) / 2
                    diffs.append(abs(mid - wall_mid))
                    spreads_wm.append(ask_wall - bid_wall)
    
    print(f"  Day {day}: avg |mid - wall_mid| = {sum(diffs)/len(diffs):.2f}, avg wall spread = {sum(spreads_wm)/len(spreads_wm):.1f}")

# What if we use best_bid/best_ask mid instead for TOMATOES?
print("\n=== TOMATOES: What the strategy actually quotes ===")
for day in [-2, -1]:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    quote_spreads = []
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
                bid2 = int(float(row['bid_price_2'])) if row['bid_price_2'] else None
                ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
                ask2 = int(float(row['ask_price_2'])) if row['ask_price_2'] else None
                bv1 = int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0
                bv2 = int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0
                av1 = int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0
                av2 = int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0
                
                if bid1 and ask1 and bid2 and ask2:
                    bid_wall = min(bid1, bid2)
                    ask_wall = max(ask1, ask2)
                    wall_mid = (bid_wall + ask_wall) / 2
                    
                    bid_price = int(bid_wall + 1)
                    ask_price = int(ask_wall - 1)
                    
                    overbid = bid1 + 1
                    if bv1 > 1 and overbid < wall_mid:
                        bid_price = max(bid_price, overbid)
                    elif bid1 < wall_mid:
                        bid_price = max(bid_price, bid1)
                    
                    underbid = ask1 - 1
                    if av1 > 1 and underbid > wall_mid:
                        ask_price = min(ask_price, underbid)
                    elif ask1 > wall_mid:
                        ask_price = min(ask_price, ask1)
                    
                    quote_spreads.append(ask_price - bid_price)
    
    print(f"  Day {day}: avg quote spread = {sum(quote_spreads)/len(quote_spreads):.1f}, min={min(quote_spreads)}, max={max(quote_spreads)}")
