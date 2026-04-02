"""Deep analysis of TOMATOES volume imbalance and microprice for strategy improvement."""
import csv
import numpy as np

for day in [-1, -2]:
    print(f"\n{'='*60}")
    print(f"DAY {day}")
    print(f"{'='*60}")
    
    rows = []
    with open(f'data/raw/prices_round_0_day_{day}.csv') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                rows.append(row)
    
    # Build arrays
    bid1 = np.array([float(r['bid_price_1']) for r in rows])
    ask1 = np.array([float(r['ask_price_1']) for r in rows])
    bv1 = np.array([float(r['bid_volume_1']) for r in rows])
    av1 = np.array([float(r['ask_volume_1']) for r in rows])
    mid = (bid1 + ask1) / 2
    spread = ask1 - bid1
    
    # Get L2/L3 data
    bid2 = []
    ask2 = []
    for r in rows:
        b2 = float(r['bid_price_2']) if r.get('bid_price_2') else 0
        a2 = float(r['ask_price_2']) if r.get('ask_price_2') else 0
        bid2.append(b2)
        ask2.append(a2)
    bid2 = np.array(bid2)
    ask2 = np.array(ask2)
    
    bid3 = []
    ask3 = []
    for r in rows:
        b3 = float(r['bid_price_3']) if r.get('bid_price_3') else 0
        a3 = float(r['ask_price_3']) if r.get('ask_price_3') else 0
        bid3.append(b3)
        ask3.append(a3)
    bid3 = np.array(bid3)
    ask3 = np.array(ask3)
    
    # Wall mid (outermost level)
    wall_bid = np.where(bid3 > 0, bid3, np.where(bid2 > 0, bid2, bid1))
    wall_ask = np.where(ask3 > 0, ask3, np.where(ask2 > 0, ask2, ask1))
    wall_mid = (wall_bid + wall_ask) / 2
    
    # Microprice
    microprice = (bv1 * ask1 + av1 * bid1) / (bv1 + av1)
    
    # Volume imbalance
    vimb = (bv1 - av1) / (bv1 + av1)
    
    # How many unique values does vimb take?
    unique_vimb = np.unique(vimb)
    print(f"Volume imbalance: {len(unique_vimb)} unique values")
    print(f"  Min={vimb.min():.4f}, Max={vimb.max():.4f}, Mean={vimb.mean():.4f}, Std={vimb.std():.4f}")
    print(f"  Quartiles: {np.percentile(vimb, [25, 50, 75])}")
    
    # Distribution of vimb
    hist, bin_edges = np.histogram(vimb, bins=10)
    print(f"  Histogram (10 bins):")
    for i in range(len(hist)):
        print(f"    [{bin_edges[i]:.3f}, {bin_edges[i+1]:.3f}): {hist[i]} ({100*hist[i]/len(vimb):.1f}%)")
    
    # === KEY ANALYSIS: When we overbid/underbid, what's the edge? ===
    # Current strategy: overbid = max(bid1 + 1, ob where bv1 > 1)
    # If bid changes by +1 compared to wall_mid, that's bullish
    
    # Price relative to wall_mid
    bid1_rel = bid1 - wall_mid  # How far is L1 bid from wall_mid
    ask1_rel = ask1 - wall_mid
    
    print(f"\n  L1 bid relative to wall_mid: mean={bid1_rel.mean():.2f}, std={bid1_rel.std():.2f}")
    print(f"  L1 ask relative to wall_mid: mean={ask1_rel.mean():.2f}, std={ask1_rel.std():.2f}")
    
    # === ANALYSIS: Microprice vs wall_mid for predicting next tick ===
    for fwd in [1, 3, 5, 10]:
        future_mid = mid[fwd:]
        n = len(future_mid)
        mid_chg = future_mid - mid[:n]
        
        # Microprice signal
        mp_signal = microprice[:n] - mid[:n]
        corr_mp = np.corrcoef(mp_signal, mid_chg)[0, 1]
        
        # Wall mid signal  
        wm_signal = wall_mid[:n] - mid[:n]
        corr_wm = np.corrcoef(wm_signal, mid_chg)[0, 1]
        
        # Volume imbalance signal
        vi_signal = vimb[:n]
        corr_vi = np.corrcoef(vi_signal, mid_chg)[0, 1]
        
        # Spread signal (narrow spread = more fills?)
        sp_signal = spread[:n]
        corr_sp = np.corrcoef(sp_signal, np.abs(mid_chg))[0, 1]
        
        print(f"\n  {fwd}-tick forward return correlation:")
        print(f"    Microprice deviation: {corr_mp:.4f}")
        print(f"    Wall-mid deviation:   {corr_wm:.4f}")
        print(f"    Volume imbalance:     {corr_vi:.4f}")
        print(f"    Spread vs |ret|:      {corr_sp:.4f}")
    
    # === ANALYSIS: Can we use microprice to improve TAKING decisions? ===
    # When microprice > mid by X, next tick mid tends to move up by Y
    mp_dev = microprice - mid
    print(f"\n  Microprice deviation from mid: mean={mp_dev.mean():.4f}, std={mp_dev.std():.4f}")
    
    # Quintile analysis of microprice deviation
    for fwd in [1, 5, 10]:
        mid_fwd = mid[fwd:] - mid[:len(mid)-fwd]
        mp_d = mp_dev[:len(mid_fwd)]
        pcts = np.percentile(mp_d, [20, 40, 60, 80])
        bins = np.digitize(mp_d, pcts)
        print(f"\n  Microprice dev quintiles → {fwd}-tick fwd return:")
        for q in range(5):
            mask = bins == q
            if mask.any():
                avg_ret = np.mean(mid_fwd[mask])
                print(f"    Q{q} (mp_dev ~ {np.mean(mp_d[mask]):.3f}): n={mask.sum()}, avg fwd mid chg = {avg_ret:.4f}")
    
    # === ANALYSIS: When both microprice AND wall_mid agree on direction ===
    wm_dev = wall_mid - mid
    for fwd in [1, 5]:
        mid_fwd = mid[fwd:] - mid[:len(mid)-fwd]
        mp_d = mp_dev[:len(mid_fwd)]
        wm_d = wm_dev[:len(mid_fwd)]
        
        both_bull = (mp_d > 0) & (wm_d > 0)
        both_bear = (mp_d < 0) & (wm_d < 0)
        disagree = ~both_bull & ~both_bear
        
        print(f"\n  Signal agreement → {fwd}-tick fwd return:")
        for name, mask in [("Both bullish", both_bull), ("Both bearish", both_bear), ("Disagree", disagree)]:
            if mask.any():
                avg_ret = np.mean(mid_fwd[mask])
                print(f"    {name}: n={mask.sum()} ({100*mask.sum()/len(mask):.1f}%), avg ret = {avg_ret:.4f}")
    
    # === ANALYSIS: Can we widen/narrow quotes based on spread? ===
    # When spread is narrow (5-8), can we quote wider? When spread is wide (13+), quote tighter?
    print(f"\n  Spread distribution:")
    for s_val in sorted(np.unique(spread)):
        n = (spread == s_val).sum()
        if n > 10:
            print(f"    spread={s_val:.0f}: {n} ticks ({100*n/len(spread):.1f}%)")
    
    # Analyze: when spread is narrow, what happens next?
    for fwd in [1, 5, 10]:
        spread_chg = spread[fwd:] - spread[:len(spread)-fwd]
        sp_now = spread[:len(spread_chg)]
        narrow_mask = sp_now <= 8
        wide_mask = sp_now >= 14
        if narrow_mask.any():
            print(f"  Narrow spread ({narrow_mask.sum()} ticks) → {fwd}-tick spread chg: {np.mean(spread_chg[narrow_mask]):.3f}")
        if wide_mask.any():
            print(f"  Wide spread ({wide_mask.sum()} ticks) → {fwd}-tick spread chg: {np.mean(spread_chg[wide_mask]):.3f}")
