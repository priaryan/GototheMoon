import csv
import numpy as np

for day in ['-1', '-2']:
    fname = f'data/raw/prices_round_0_day_{day}.csv'
    with open(fname) as f:
        reader = csv.DictReader(f, delimiter=';')
        stats = {}
        for row in reader:
            prod = row['product']
            if prod not in stats:
                stats[prod] = {'spreads':[], 'bd1':[], 'ad1':[], 'mids':[], 'wallspr':[]}
            b1 = row.get('bid_price_1','')
            a1 = row.get('ask_price_1','')
            b2 = row.get('bid_price_2','')
            a2 = row.get('ask_price_2','')
            b3 = row.get('bid_price_3','')
            a3 = row.get('ask_price_3','')
            bv1 = row.get('bid_volume_1','')
            av1 = row.get('ask_volume_1','')
            mid = row.get('mid_price','')
            if b1 and a1:
                stats[prod]['spreads'].append(float(a1)-float(b1))
                stats[prod]['bd1'].append(int(bv1))
                stats[prod]['ad1'].append(int(av1))
            if mid:
                stats[prod]['mids'].append(float(mid))
            bwall = float(b3 or b2 or b1) if b1 else None
            awall = float(a3 or a2 or a1) if a1 else None
            if bwall and awall:
                stats[prod]['wallspr'].append(awall - bwall)

        print(f'=== Day {day} ===')
        for prod, s in stats.items():
            spr = np.array(s['spreads'])
            ws = np.array(s['wallspr'])
            bd = np.array(s['bd1'])
            ad = np.array(s['ad1'])
            mids = np.array(s['mids'])
            print(f'{prod}:')
            print(f'  L1 spread: mean={spr.mean():.1f} med={np.median(spr):.0f} p25={np.percentile(spr,25):.0f} p75={np.percentile(spr,75):.0f}')
            print(f'  Wall spread: mean={ws.mean():.1f} med={np.median(ws):.0f}')
            print(f'  L1 bid depth: mean={bd.mean():.1f}  L1 ask depth: mean={ad.mean():.1f}')
            print(f'  Mid: min={mids.min():.1f} max={mids.max():.1f} std={mids.std():.2f}')
