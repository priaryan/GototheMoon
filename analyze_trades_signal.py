"""Analyze market trades as predictive signals for price movement."""
import csv
import numpy as np

def load_prices(filename):
    """Load prices into dict keyed by (timestamp, product)."""
    data = {}
    with open(filename) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ts = int(row['timestamp'])
            sym = row['product']
            bid1 = float(row['bid_price_1'])
            ask1 = float(row['ask_price_1'])
            mid = float(row['mid_price'])
            # L3 walls
            bid3 = float(row.get('bid_price_3', 0) or 0) or float(row.get('bid_price_2', 0) or 0) or bid1
            ask3 = float(row.get('ask_price_3', 0) or 0) or float(row.get('ask_price_2', 0) or 0) or ask1
            data.setdefault(sym, []).append({
                'ts': ts, 'bid1': bid1, 'ask1': ask1, 'mid': mid,
                'bid3': bid3, 'ask3': ask3
            })
    return data

def load_trades(filename):
    """Load trades."""
    data = {}
    with open(filename) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            ts = int(row['timestamp'])
            sym = row['symbol']
            price = float(row['price'])
            qty = int(row['quantity'])
            data.setdefault(sym, []).append({'ts': ts, 'price': price, 'qty': qty})
    return data

for day in [-1, -2]:
    print(f"\n{'='*60}")
    print(f"DAY {day}")
    print(f"{'='*60}")
    
    prices = load_prices(f'data/raw/prices_round_0_day_{day}.csv')
    trades = load_trades(f'data/raw/trades_round_0_day_{day}.csv')
    
    for sym in ['TOMATOES', 'EMERALDS']:
        print(f"\n--- {sym} ---")
        p = prices.get(sym, [])
        t = trades.get(sym, [])
        print(f"  {len(t)} trades, {len(p)} price ticks")
        
        if not t or not p:
            continue
        
        # Create timestamp -> price mapping
        ts_to_price = {}
        for px in p:
            ts_to_price[px['ts']] = px
        
        # For each trade, find the price at the trade tick and 1-5 ticks later
        tss = sorted(ts_to_price.keys())
        ts_idx = {ts: i for i, ts in enumerate(tss)}
        
        trade_signals = []
        for tr in t:
            trade_ts = tr['ts']
            # Find nearest tick at or before trade
            nearest_ts = None
            for ts in tss:
                if ts <= trade_ts:
                    nearest_ts = ts
                else:
                    break
            if nearest_ts is None:
                continue
            idx = ts_idx[nearest_ts]
            if idx + 5 >= len(tss):
                continue
            
            px_now = ts_to_price[nearest_ts]
            mid_now = px_now['mid']
            wall_mid_now = (px_now['bid3'] + px_now['ask3']) / 2
            
            # Trade direction: above mid = buy aggressor, below mid = sell aggressor
            direction = 1 if tr['price'] > mid_now else (-1 if tr['price'] < mid_now else 0)
            
            # Future mids
            future_mids = []
            for k in [1, 2, 3, 5, 10, 20]:
                if idx + k < len(tss):
                    future_mids.append(ts_to_price[tss[idx + k]]['mid'])
            
            trade_signals.append({
                'ts': trade_ts,
                'price': tr['price'],
                'qty': tr['qty'],
                'mid_now': mid_now,
                'wall_mid_now': wall_mid_now,
                'direction': direction,
                'future_mids': future_mids
            })
        
        if not trade_signals:
            continue
        
        # Analyze: does trade direction predict future mid change?
        print(f"  Trades classified: {len(trade_signals)}")
        buys = [s for s in trade_signals if s['direction'] == 1]
        sells = [s for s in trade_signals if s['direction'] == -1]
        mids = [s for s in trade_signals if s['direction'] == 0]
        print(f"  Buy aggressor: {len(buys)}, Sell aggressor: {len(sells)}, Mid: {len(mids)}")
        
        for horizon_name, horizon_idx in [('1-tick', 0), ('3-tick', 2), ('5-tick', 3), ('10-tick', 4), ('20-tick', 5)]:
            buy_chg = [s['future_mids'][horizon_idx] - s['mid_now'] for s in buys if len(s['future_mids']) > horizon_idx]
            sell_chg = [s['future_mids'][horizon_idx] - s['mid_now'] for s in sells if len(s['future_mids']) > horizon_idx]
            if buy_chg and sell_chg:
                print(f"  {horizon_name}: After buy aggressor: avg mid chg = {np.mean(buy_chg):.3f}, After sell: {np.mean(sell_chg):.3f}")

print("\n\n=== CROSS-PRODUCT CORRELATION ===")
for day in [-1, -2]:
    prices = load_prices(f'data/raw/prices_round_0_day_{day}.csv')
    em = prices.get('EMERALDS', [])
    tom = prices.get('TOMATOES', [])
    
    # Match by timestamp
    em_dict = {p['ts']: p for p in em}
    tom_dict = {p['ts']: p for p in tom}
    
    common_ts = sorted(set(em_dict.keys()) & set(tom_dict.keys()))
    if len(common_ts) < 100:
        continue
    
    em_mids = np.array([em_dict[ts]['mid'] for ts in common_ts])
    tom_mids = np.array([tom_dict[ts]['mid'] for ts in common_ts])
    
    em_ret = np.diff(em_mids)
    tom_ret = np.diff(tom_mids)
    
    corr = np.corrcoef(em_ret, tom_ret)[0, 1]
    print(f"Day {day}: EM-TOM return correlation = {corr:.4f}")
    
    # Lead-lag: does EM change predict TOM change?
    for lag in [1, 2, 3, 5]:
        if lag < len(em_ret):
            corr_lead = np.corrcoef(em_ret[:-lag], tom_ret[lag:])[0, 1]
            corr_lag = np.corrcoef(tom_ret[:-lag], em_ret[lag:])[0, 1]
            print(f"  Lag {lag}: EM leads TOM = {corr_lead:.4f}, TOM leads EM = {corr_lag:.4f}")


print("\n\n=== TOMATOES: SPREAD DYNAMICS & FILL PROBABILITY ===")
for day in [-1, -2]:
    prices = load_prices(f'data/raw/prices_round_0_day_{day}.csv')
    trades = load_trades(f'data/raw/trades_round_0_day_{day}.csv')
    
    tom = prices.get('TOMATOES', [])
    tom_trades = trades.get('TOMATOES', [])
    
    # Analyze spread dynamics
    spreads = [p['ask1'] - p['bid1'] for p in tom]
    print(f"\nDay {day} TOMATOES:")
    print(f"  Spread: mean={np.mean(spreads):.1f}, median={np.median(spreads):.0f}")
    
    # When spread is narrow vs wide, what's the volume?
    narrow = [s for s in spreads if s <= 8]
    wide = [s for s in spreads if s > 8]
    print(f"  Narrow (<=8): {len(narrow)} ticks ({100*len(narrow)/len(spreads):.1f}%)")
    print(f"  Wide (>8): {len(wide)} ticks ({100*len(wide)/len(spreads):.1f}%)")
    
    # Volume imbalance persistence/mean-reversion
    vimb = []
    for p in tom:
        b1v = float(p.get('bid1', 0)) if isinstance(p, dict) else 0
        # Already loaded - let me recalculate from raw data
    
    # Trade frequency: how many ticks between trades?
    trade_tss = sorted([tr['ts'] for tr in tom_trades])
    if len(trade_tss) > 1:
        gaps = [trade_tss[i+1] - trade_tss[i] for i in range(len(trade_tss)-1)]
        print(f"  Trade gaps: mean={np.mean(gaps):.0f}ms, median={np.median(gaps):.0f}ms, min={min(gaps)}, max={max(gaps)}")
    print(f"  Total trades: {len(tom_trades)}, total qty: {sum(tr['qty'] for tr in tom_trades)}")

print("\n\n=== TOMATOES: VOLUME IMBALANCE ANALYSIS ===")
for day in [-1, -2]:
    print(f"\nDay {day}:")
    rows = []
    with open(f'data/raw/prices_round_0_day_{day}.csv') as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                rows.append(row)
    
    # Calculate L1 volume imbalance and future mid change
    vimb_series = []
    mid_series = []
    for row in rows:
        bv1 = float(row['bid_volume_1'])
        av1 = float(row['ask_volume_1'])
        vimb = (bv1 - av1) / (bv1 + av1) if (bv1 + av1) > 0 else 0
        mid = float(row['mid_price'])
        vimb_series.append(vimb)
        mid_series.append(mid)
    
    vimb_arr = np.array(vimb_series)
    mid_arr = np.array(mid_series)
    
    # Autocorrelation of volume imbalance
    for lag in [1, 2, 5]:
        ac = np.corrcoef(vimb_arr[:-lag], vimb_arr[lag:])[0, 1]
        print(f"  VImb autocorr lag-{lag}: {ac:.4f}")
    
    # Volume imbalance quintiles → future return
    mid_chg = np.diff(mid_arr)
    for horizon in [1, 5, 10]:
        mid_fwd = mid_arr[horizon:] - mid_arr[:-horizon]
        v = vimb_arr[:len(mid_fwd)]
        # Quintile analysis
        pcts = np.percentile(v, [20, 40, 60, 80])
        bins = np.digitize(v, pcts)
        print(f"  VImb → {horizon}-tick fwd return by quintile:")
        for q in range(5):
            mask = bins == q
            if mask.any():
                avg_ret = np.mean(mid_fwd[mask])
                print(f"    Q{q}: n={mask.sum()}, avg fwd ret = {avg_ret:.4f}")
