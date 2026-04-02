"""Deep analysis for v5 strategy design."""
import csv
from collections import Counter

for day_file in ['data/raw/prices_round_0_day_-1.csv', 'data/raw/prices_round_0_day_-2.csv']:
    print(f'\n=== {day_file} ===')
    rows = []
    with open(day_file) as f:
        reader = csv.DictReader(f, delimiter=';')
        for row in reader:
            if row['product'] == 'TOMATOES':
                rows.append(row)

    mids = [float(r['mid_price']) for r in rows]
    bids = [float(r['bid_price_1']) for r in rows]
    asks = [float(r['ask_price_1']) for r in rows]
    bid_vols = [int(r['bid_volume_1']) for r in rows]
    ask_vols = [int(r['ask_volume_1']) for r in rows]

    # Volume imbalance
    imbalances = [(bv - av) / (bv + av) for bv, av in zip(bid_vols, ask_vols)]

    future_changes_1 = [mids[i+1] - mids[i] for i in range(len(mids)-1)]
    future_changes_5 = [mids[min(i+5, len(mids)-1)] - mids[i] for i in range(len(mids)-1)]

    n = len(future_changes_1)
    mean_imb = sum(imbalances[:n]) / n
    mean_fc1 = sum(future_changes_1) / n
    mean_fc5 = sum(future_changes_5) / n
    var_imb = sum((x - mean_imb)**2 for x in imbalances[:n]) / n
    var_fc1 = sum((x - mean_fc1)**2 for x in future_changes_1) / n
    var_fc5 = sum((x - mean_fc5)**2 for x in future_changes_5) / n

    if var_imb > 0 and var_fc1 > 0:
        cov1 = sum((imbalances[i] - mean_imb) * (future_changes_1[i] - mean_fc1) for i in range(n)) / n
        corr1 = cov1 / (var_imb**0.5 * var_fc1**0.5)
        print(f'Volume imbalance -> next mid change corr: {corr1:.4f}')

    if var_imb > 0 and var_fc5 > 0:
        cov5 = sum((imbalances[i] - mean_imb) * (future_changes_5[i] - mean_fc5) for i in range(n)) / n
        corr5 = cov5 / (var_imb**0.5 * var_fc5**0.5)
        print(f'Volume imbalance -> 5-tick mid change corr: {corr5:.4f}')

    # Spread distribution
    spreads = [a - b for a, b in zip(asks, bids)]
    spread_counter = Counter(int(s) for s in spreads)
    print(f'Spread distribution: {spread_counter.most_common(10)}')

    # Microprice
    microprices = [(bv * a + av * b) / (bv + av) for b, a, bv, av in zip(bids, asks, bid_vols, ask_vols)]
    micro_bias = [mp - m for mp, m in zip(microprices, mids)]

    n2 = min(len(micro_bias)-1, len(future_changes_1))
    mean_mb = sum(micro_bias[:n2]) / n2
    var_mb = sum((x - mean_mb)**2 for x in micro_bias[:n2]) / n2

    if var_mb > 0 and var_fc1 > 0:
        cov_mb1 = sum((micro_bias[i] - mean_mb) * (future_changes_1[i] - mean_fc1) for i in range(n2)) / n2
        corr_mb1 = cov_mb1 / (var_mb**0.5 * var_fc1**0.5)
        print(f'Microprice bias -> next mid change corr: {corr_mb1:.4f}')

    if var_mb > 0 and var_fc5 > 0:
        cov_mb5 = sum((micro_bias[i] - mean_mb) * (future_changes_5[i] - mean_fc5) for i in range(n2)) / n2
        corr_mb5 = cov_mb5 / (var_mb**0.5 * var_fc5**0.5)
        print(f'Microprice bias -> 5-tick mid change corr: {corr_mb5:.4f}')

    # Bucket analysis
    pos_imb = [future_changes_5[i] for i in range(n) if imbalances[i] > 0.2]
    neg_imb = [future_changes_5[i] for i in range(n) if imbalances[i] < -0.2]
    mid_imb = [future_changes_5[i] for i in range(n) if -0.2 <= imbalances[i] <= 0.2]

    if pos_imb:
        print(f'Pos vol imbalance (>0.2): avg 5-tick change = {sum(pos_imb)/len(pos_imb):.3f}, n={len(pos_imb)}')
    if neg_imb:
        print(f'Neg vol imbalance (<-0.2): avg 5-tick change = {sum(neg_imb)/len(neg_imb):.3f}, n={len(neg_imb)}')
    if mid_imb:
        print(f'Neutral vol imbalance:     avg 5-tick change = {sum(mid_imb)/len(mid_imb):.3f}, n={len(mid_imb)}')

    # Prediction accuracy comparison
    wm_errors = [(mids[i] - mids[i+1])**2 for i in range(len(mids)-1)]
    mp_errors = [(microprices[i] - mids[i+1])**2 for i in range(len(microprices)-1)]
    n3 = min(len(wm_errors), len(mp_errors))
    print(f'Mid MSE (predicting next mid): {sum(wm_errors[:n3])/n3:.3f}')
    print(f'Microprice MSE (predicting next mid): {sum(mp_errors[:n3])/n3:.3f}')

    # Trade intensity analysis: when do market trades happen?
    print()

    # Deeper: L2/L3 depth analysis
    bid2_vols = [int(r['bid_volume_2']) for r in rows if r.get('bid_volume_2')]
    ask2_vols = [int(r['ask_volume_2']) for r in rows if r.get('ask_volume_2')]
    print(f'L2 bid vol: avg={sum(bid2_vols)/len(bid2_vols):.1f}' if bid2_vols else 'No L2 bid')
    print(f'L2 ask vol: avg={sum(ask2_vols)/len(ask2_vols):.1f}' if ask2_vols else 'No L2 ask')

    # How often does the bid/ask wall change?
    wall_changes_bid = sum(1 for i in range(1, len(bids)) if bids[i] != bids[i-1])
    wall_changes_ask = sum(1 for i in range(1, len(asks)) if asks[i] != asks[i-1])
    print(f'Bid wall changes: {wall_changes_bid}/{len(bids)-1} = {wall_changes_bid/(len(bids)-1)*100:.1f}%')
    print(f'Ask wall changes: {wall_changes_ask}/{len(asks)-1} = {wall_changes_ask/(len(asks)-1)*100:.1f}%')

    # Position drift simulation: if we always buy 1 when imbalance>0, sell 1 when imbalance<0
    # what's the final position after all ticks?
    sim_pos = 0
    sim_pnl = 0
    for i in range(n):
        if imbalances[i] > 0.3 and sim_pos < 20:
            sim_pos += 1
            sim_pnl -= mids[i]  # buy at mid
        elif imbalances[i] < -0.3 and sim_pos > -20:
            sim_pos -= 1
            sim_pnl += mids[i]  # sell at mid
    # Mark to market
    sim_pnl += sim_pos * mids[-1]
    print(f'Simple vol-imbalance signal PnL (at mid): {sim_pnl:.1f}, final pos: {sim_pos}')
