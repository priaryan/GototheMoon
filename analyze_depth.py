import csv
import numpy as np

for day in ['-1']:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    for prod_name in ['EMERALDS', 'TOMATOES']:
        levels = {2: 0, 3: 0}
        l2gaps_bid = []
        l2gaps_ask = []
        bv2s = []
        av2s = []
        with open(fname) as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['product'] != prod_name:
                    continue
                b1, b2, b3 = row['bid_price_1'], row['bid_price_2'], row['bid_price_3']
                a1, a2, a3 = row['ask_price_1'], row['ask_price_2'], row['ask_price_3']
                if b3 and a3:
                    levels[3] += 1
                elif b2 and a2:
                    levels[2] += 1
                if b1 and b2 and a1 and a2:
                    l2gaps_bid.append(float(b1) - float(b2))
                    l2gaps_ask.append(float(a2) - float(a1))
                    bv2s.append(int(row['bid_volume_2']))
                    av2s.append(int(row['ask_volume_2']))

        print(f'{prod_name} day{day}: depth levels = {levels}')
        if l2gaps_bid:
            print(f'  L1-L2 bid gap: mean={np.mean(l2gaps_bid):.1f}  L1-L2 ask gap: mean={np.mean(l2gaps_ask):.1f}')
            print(f'  L2 bid depth: mean={np.mean(bv2s):.1f}   L2 ask depth: mean={np.mean(av2s):.1f}')

# Check EMERALDS mid stability - is it truly pinned at 10000?
print()
for day in ['-1', '-2']:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        em_mids = []
        for row in reader:
            if row['product'] == 'EMERALDS' and row['mid_price']:
                em_mids.append(float(row['mid_price']))
        m = np.array(em_mids)
        print(f'EMERALDS day{day}: mid mean={m.mean():.2f} std={m.std():.3f} range=[{m.min():.1f}, {m.max():.1f}]')
        vals, counts = np.unique(m, return_counts=True)
        top5 = np.argsort(-counts)[:5]
        print(f'  Top mids: {[(vals[i], counts[i]) for i in top5]}')
