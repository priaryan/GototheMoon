import csv

# Detailed TOMATOES analysis - what the best strategy looks like
fname = '/Users/rishit_gadre/IMCProsperity4/GototheMoon/data/raw/prices_round_0_day_-1.csv'

rows = []
with open(fname) as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        if row['product'] == 'TOMATOES':
            rows.append({
                'ts': int(row['timestamp']),
                'bid1': int(float(row['bid_price_1'])) if row['bid_price_1'] else None,
                'ask1': int(float(row['ask_price_1'])) if row['ask_price_1'] else None,
                'bv1': int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0,
                'av1': int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0,
                'bid2': int(float(row['bid_price_2'])) if row['bid_price_2'] else None,
                'ask2': int(float(row['ask_price_2'])) if row['ask_price_2'] else None,
                'bv2': int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0,
                'av2': int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0,
                'mid': float(row['mid_price']),
            })

# Where EMERALDS has 10000 on a side
with open(fname) as f:
    reader = csv.DictReader(f, delimiter=';')
    e_at_fair = 0
    e_total = 0
    for row in reader:
        if row['product'] == 'EMERALDS':
            e_total += 1
            bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
            ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
            if bid1 == 10000 or ask1 == 10000:
                e_at_fair += 1
print(f"EMERALDS ticks where 10000 appears in L1: {e_at_fair}/{e_total}")

# TOMATOES: simulate ideal PnL from taking favorable 
# (buying ask < EMA, selling bid > EMA)  
from collections import deque

def simulate_mm(rows, ema_alpha, take_margin, pos_limit):
    ema = None
    pos = 0
    pnl = 0.0
    trades = 0
    
    for r in rows:
        bid1, ask1 = r['bid1'], r['ask1']
        if bid1 is None or ask1 is None:
            continue
        mid = (bid1 + ask1) / 2
        
        if ema is None:
            ema = mid
        else:
            ema = ema_alpha * mid + (1 - ema_alpha) * ema
        
        fair = round(ema)
        
        # Take
        if ask1 <= fair - take_margin and pos < pos_limit:
            size = min(r['av1'], pos_limit - pos)
            pnl -= ask1 * size
            pos += size
            trades += 1
        
        if bid1 >= fair + take_margin and pos > -pos_limit:
            size = min(r['bv1'], pos_limit + pos)
            pnl += bid1 * size
            pos -= size
            trades += 1
    
    # Mark to market final position
    final_mid = rows[-1]['mid']
    pnl += pos * final_mid
    return pnl, trades, pos

print("\n=== TOMATOES Strategy Sweep (day -1) ===")
print(f"{'alpha':>8} {'margin':>8} {'pnl':>10} {'trades':>8} {'final_pos':>10}")
for alpha in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    for margin in [0, 1, 2, 3]:
        pnl, trades, fpos = simulate_mm(rows, alpha, margin, 20)
        print(f"{alpha:8.2f} {margin:8d} {pnl:10.1f} {trades:8d} {fpos:10d}")

# Day -2
rows2 = []
fname2 = '/Users/rishit_gadre/IMCProsperity4/GototheMoon/data/raw/prices_round_0_day_-2.csv'
with open(fname2) as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        if row['product'] == 'TOMATOES':
            rows2.append({
                'ts': int(row['timestamp']),
                'bid1': int(float(row['bid_price_1'])) if row['bid_price_1'] else None,
                'ask1': int(float(row['ask_price_1'])) if row['ask_price_1'] else None,
                'bv1': int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0,
                'av1': int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0,
                'bid2': int(float(row['bid_price_2'])) if row['bid_price_2'] else None,
                'ask2': int(float(row['ask_price_2'])) if row['ask_price_2'] else None,
                'bv2': int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0,
                'av2': int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0,
                'mid': float(row['mid_price']),
            })

print("\n=== TOMATOES Strategy Sweep (day -2) ===")
print(f"{'alpha':>8} {'margin':>8} {'pnl':>10} {'trades':>8} {'final_pos':>10}")
for alpha in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50]:
    for margin in [0, 1, 2, 3]:
        pnl, trades, fpos = simulate_mm(rows2, alpha, margin, 20)
        print(f"{alpha:8.2f} {margin:8d} {pnl:10.1f} {trades:8d} {fpos:10d}")
