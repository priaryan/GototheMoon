"""Analyze shock regime behavior on actual TOMATOES data."""
import csv
import math

HISTORY_LEN = 8

# Current thresholds from bestfornow.py
SHOCK_MOVE_THRESH = 4.0
SHOCK_VOL_THRESH = 1.75
SHOCK_REVERSAL_THRESH = 2.5

def load_tomatoes_data(path):
    ticks = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] != 'TOMATOES':
                continue
            bp = [int(row[f'bid_price_{i}']) for i in range(1,4) if row.get(f'bid_price_{i}')]
            ap = [int(row[f'ask_price_{i}']) for i in range(1,4) if row.get(f'ask_price_{i}')]
            bv = [int(row[f'bid_volume_{i}']) for i in range(1,4) if row.get(f'bid_volume_{i}')]
            av = [int(row[f'ask_volume_{i}']) for i in range(1,4) if row.get(f'ask_volume_{i}')]
            if bp and ap:
                bid_wall = min(bp)
                ask_wall = max(ap)
                best_bid = max(bp)
                best_ask = min(ap)
                wall_mid = (bid_wall + ask_wall) / 2
                spread = best_ask - best_bid
                ticks.append({
                    'timestamp': int(row['timestamp']),
                    'wall_mid': wall_mid,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'bid_wall': bid_wall,
                    'ask_wall': ask_wall,
                    'spread': spread,
                })
    return ticks

def compute_regime(mids, move_thresh, vol_thresh, reversal_thresh):
    if len(mids) < 4:
        return "normal", {}
    last = mids[-1]
    prev = mids[-2]
    short_move = last - prev
    medium_move = last - mids[-4]
    diffs = [mids[i] - mids[i-1] for i in range(1, len(mids))]
    realized_vol = sum(abs(x) for x in diffs[-5:]) / max(1, len(diffs[-5:]))
    prev_medium = mids[-2] - mids[-5] if len(mids) >= 5 else 0.0
    reversal = (abs(short_move) >= reversal_thresh 
                and abs(prev_medium) >= reversal_thresh
                and short_move * prev_medium < 0)
    large_move = abs(medium_move) >= move_thresh
    high_vol = realized_vol >= vol_thresh
    
    info = {
        'short_move': short_move,
        'medium_move': medium_move,
        'realized_vol': realized_vol,
        'prev_medium': prev_medium,
        'reversal': reversal,
        'large_move': large_move,
        'high_vol': high_vol,
    }
    if reversal or (large_move and high_vol):
        return "shock", info
    return "normal", info

def analyze_day(path, day_label):
    ticks = load_tomatoes_data(path)
    print(f"\n{'='*60}")
    print(f"Day {day_label}: {len(ticks)} TOMATOES ticks")
    
    mid_history = []
    shock_count = 0
    normal_count = 0
    shock_episodes = []
    in_shock = False
    shock_start = None
    
    # Track wall_mid changes
    mids = [t['wall_mid'] for t in ticks]
    diffs = [mids[i] - mids[i-1] for i in range(1, len(mids))]
    
    print(f"\n--- Wall-mid statistics ---")
    print(f"  Range: {min(mids):.1f} to {max(mids):.1f}")
    print(f"  Mean: {sum(mids)/len(mids):.2f}")
    print(f"  Max 1-tick move: {max(abs(d) for d in diffs):.1f}")
    
    # Realized vol distribution
    vols = []
    for i in range(5, len(mids)):
        window = [abs(mids[j] - mids[j-1]) for j in range(i-4, i+1)]
        vols.append(sum(window) / len(window))
    
    if vols:
        vols_sorted = sorted(vols)
        print(f"\n--- Realized vol (5-tick window) ---")
        print(f"  Median: {vols_sorted[len(vols_sorted)//2]:.3f}")
        print(f"  p75: {vols_sorted[int(len(vols_sorted)*0.75)]:.3f}")
        print(f"  p90: {vols_sorted[int(len(vols_sorted)*0.90)]:.3f}")
        print(f"  p95: {vols_sorted[int(len(vols_sorted)*0.95)]:.3f}")
        print(f"  p99: {vols_sorted[int(len(vols_sorted)*0.99)]:.3f}")
        print(f"  Max: {max(vols):.3f}")
    
    # Medium move distribution
    med_moves = []
    for i in range(4, len(mids)):
        med_moves.append(abs(mids[i] - mids[i-4]))
    if med_moves:
        med_sorted = sorted(med_moves)
        print(f"\n--- Medium move (4-tick, absolute) ---")
        print(f"  Median: {med_sorted[len(med_sorted)//2]:.3f}")
        print(f"  p75: {med_sorted[int(len(med_sorted)*0.75)]:.3f}")
        print(f"  p90: {med_sorted[int(len(med_sorted)*0.90)]:.3f}")
        print(f"  p95: {med_sorted[int(len(med_sorted)*0.95)]:.3f}")
        print(f"  p99: {med_sorted[int(len(med_sorted)*0.99)]:.3f}")
        print(f"  Max: {max(med_moves):.3f}")
    
    # Spread distribution
    spreads = [t['spread'] for t in ticks]
    from collections import Counter
    spread_counts = Counter(spreads)
    print(f"\n--- Spread distribution ---")
    for s in sorted(spread_counts):
        pct = spread_counts[s] / len(spreads) * 100
        print(f"  Spread {s:3d}: {spread_counts[s]:5d} ({pct:5.1f}%)")
    
    # Now run shock detection
    for i, t in enumerate(ticks):
        mid_history = (mid_history + [t['wall_mid']])[-HISTORY_LEN:]
        regime, info = compute_regime(mid_history, SHOCK_MOVE_THRESH, SHOCK_VOL_THRESH, SHOCK_REVERSAL_THRESH)
        
        if regime == "shock":
            shock_count += 1
            if not in_shock:
                in_shock = True
                shock_start = i
        else:
            normal_count += 1
            if in_shock:
                in_shock = False
                shock_episodes.append((shock_start, i - 1, i - shock_start))
    
    if in_shock:
        shock_episodes.append((shock_start, len(ticks)-1, len(ticks) - shock_start))
    
    total = shock_count + normal_count
    print(f"\n--- Shock regime (current thresholds) ---")
    print(f"  move_thresh={SHOCK_MOVE_THRESH}, vol_thresh={SHOCK_VOL_THRESH}, reversal_thresh={SHOCK_REVERSAL_THRESH}")
    print(f"  Normal: {normal_count}/{total} ({normal_count/total*100:.1f}%)")
    print(f"  Shock:  {shock_count}/{total} ({shock_count/total*100:.1f}%)")
    print(f"  Episodes: {len(shock_episodes)}")
    if shock_episodes:
        durations = [e[2] for e in shock_episodes]
        print(f"  Episode durations: min={min(durations)}, max={max(durations)}, mean={sum(durations)/len(durations):.1f}")
        print(f"  First 10 episodes (tick range):")
        for s, e, d in shock_episodes[:10]:
            mid_at_start = ticks[s]['wall_mid']
            mid_at_end = ticks[e]['wall_mid']
            print(f"    [{s:5d}-{e:5d}] dur={d:3d} mid: {mid_at_start:.0f} -> {mid_at_end:.0f} (Δ={mid_at_end-mid_at_start:+.0f})")
    
    # Test different thresholds
    print(f"\n--- Shock count at different thresholds ---")
    for move_t in [2.0, 3.0, 4.0, 5.0, 6.0]:
        for vol_t in [1.0, 1.5, 1.75, 2.0, 2.5]:
            cnt = 0
            mh = []
            for t in ticks:
                mh = (mh + [t['wall_mid']])[-HISTORY_LEN:]
                r, _ = compute_regime(mh, move_t, vol_t, SHOCK_REVERSAL_THRESH)
                if r == "shock":
                    cnt += 1
            pct = cnt / len(ticks) * 100
            if pct > 0.5 or (move_t == SHOCK_MOVE_THRESH and vol_t == SHOCK_VOL_THRESH):
                print(f"  move={move_t:.0f} vol={vol_t:.2f}: {cnt:4d} shocks ({pct:5.2f}%)")

    return ticks, shock_episodes

# Analyze both days
for day, path in [("-1", "data/raw/prices_round_0_day_-1.csv"), 
                   ("-2", "data/raw/prices_round_0_day_-2.csv")]:
    analyze_day(path, day)
