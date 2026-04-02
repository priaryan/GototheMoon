"""Debug: trace why v4 gets fills but v5 doesn't."""
import csv
from collections import defaultdict

def load_prices(path):
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for r in reader:
            rows.append(r)
    return rows

def analyze_fills(day_file):
    print(f'\n=== {day_file} ===')
    rows = [r for r in load_prices(day_file) if r['product'] == 'TOMATOES']
    
    v4_take_count = 0
    v4_make_count = 0
    v5_take_count = 0
    v5_make_count = 0
    
    for i, r in enumerate(rows):
        bp1, bv1 = int(float(r['bid_price_1'])), int(r['bid_volume_1'])
        ap1, av1 = int(float(r['ask_price_1'])), int(r['ask_volume_1'])
        bp2 = int(float(r['bid_price_2'])) if r.get('bid_price_2') and r['bid_price_2'] else None
        ap2 = int(float(r['ask_price_2'])) if r.get('ask_price_2') and r['ask_price_2'] else None
        bp3 = int(float(r['bid_price_3'])) if r.get('bid_price_3') and r['bid_price_3'] else None
        ap3 = int(float(r['ask_price_3'])) if r.get('ask_price_3') and r['ask_price_3'] else None
        bv2 = int(r['bid_volume_2']) if r.get('bid_volume_2') and r['bid_volume_2'] else 0
        av2 = int(r['ask_volume_2']) if r.get('ask_volume_2') and r['ask_volume_2'] else 0
        
        # Walls
        bid_wall = bp3 if bp3 else (bp2 if bp2 else bp1)
        ask_wall = ap3 if ap3 else (ap2 if ap2 else ap1)
        wall_mid = (bid_wall + ask_wall) / 2
        
        # Microprice
        total_vol = bv1 + av1
        microprice = (bv1 * ap1 + av1 * bp1) / total_vol if total_vol > 0 else (bp1+ap1)/2
        
        spread = ap1 - bp1
        
        # v4 TAKE conditions (position=0 for simplicity)
        v4_buy_takes = ap1 <= wall_mid - 1
        v4_sell_takes = bp1 >= wall_mid + 1
        
        # v4 MAKE: check if overbid/underbid crosses the spread
        # Overbid
        v4_bid = bid_wall + 1
        if bv1 > 1 and bp1 + 1 < wall_mid:
            v4_bid = max(v4_bid, bp1 + 1)
        elif bp1 < wall_mid:
            v4_bid = max(v4_bid, bp1)
        
        v4_ask = ask_wall - 1
        if av1 > 1 and ap1 - 1 > wall_mid:
            v4_ask = min(v4_ask, ap1 - 1)
        elif ap1 > wall_mid:
            v4_ask = min(v4_ask, ap1)
        
        # Check if v4 making orders would fill
        v4_make_buy_fills = v4_bid >= ap1  # our bid crosses their ask
        v4_make_sell_fills = v4_ask <= bp1  # our ask crosses their bid
        
        # v5 conditions
        fair = microprice
        v5_buy_takes = ap1 <= fair - 0.5
        v5_sell_takes = bp1 >= fair + 0.5
        
        # v5 make
        v5_bid = v4_bid  # same overbid logic
        v5_ask = v4_ask
        int_fair = int(round(fair))
        v5_bid = min(v5_bid, int_fair - 1)
        v5_ask = max(v5_ask, int_fair + 1)
        v5_make_buy_fills = v5_bid >= ap1
        v5_make_sell_fills = v5_ask <= bp1
        
        if v4_buy_takes: v4_take_count += 1
        if v4_sell_takes: v4_take_count += 1
        if v4_make_buy_fills: v4_make_count += 1
        if v4_make_sell_fills: v4_make_count += 1
        if v5_buy_takes: v5_take_count += 1
        if v5_sell_takes: v5_take_count += 1
        if v5_make_buy_fills: v5_make_count += 1
        if v5_make_sell_fills: v5_make_count += 1
        
        # Print the first 5 ticks where v4 gets a fill but v5 doesn't
        v4_fills = v4_buy_takes or v4_sell_takes or v4_make_buy_fills or v4_make_sell_fills
        v5_fills = v5_buy_takes or v5_sell_takes or v5_make_buy_fills or v5_make_sell_fills
        
        if v4_fills and i < 500:
            print(f'  tick {i}: L1={bp1}/{ap1}(spread={spread}), wall={bid_wall}/{ask_wall}, '
                  f'wall_mid={wall_mid:.1f}, micro={microprice:.1f}')
            print(f'    v4: take_buy={v4_buy_takes}, take_sell={v4_sell_takes}, '
                  f'make_buy_fills={v4_make_buy_fills}(bid={v4_bid}), make_sell_fills={v4_make_sell_fills}(ask={v4_ask})')
            if not v5_fills:
                print(f'    v5: NO FILLS. take_buy={v5_buy_takes}(thr={fair-0.5:.1f}), '
                      f'take_sell={v5_sell_takes}(thr={fair+0.5:.1f}), '
                      f'make_buy_fills={v5_make_buy_fills}(bid={v5_bid}), make_sell_fills={v5_make_sell_fills}(ask={v5_ask})')
    
    print(f'\nv4: {v4_take_count} take opportunities, {v4_make_count} make fills')
    print(f'v5: {v5_take_count} take opportunities, {v5_make_count} make fills')

analyze_fills('data/raw/prices_round_0_day_-1.csv')
analyze_fills('data/raw/prices_round_0_day_-2.csv')
