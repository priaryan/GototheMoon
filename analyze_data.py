import csv

products = {}
with open('data/raw/prices_round_0_day_-1.csv') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        p = row['product']
        if p not in products:
            products[p] = {'count': 0, 'mid_prices': [], 'spreads': []}
        products[p]['count'] += 1
        products[p]['mid_prices'].append(float(row['mid_price']))
        bid1 = float(row['bid_price_1']) if row['bid_price_1'] else None
        ask1 = float(row['ask_price_1']) if row['ask_price_1'] else None
        if bid1 and ask1:
            products[p]['spreads'].append(ask1 - bid1)

for p, d in products.items():
    prices = d['mid_prices']
    spreads = d['spreads']
    print(f"{p}: {d['count']} rows")
    print(f"  mid_price: range=[{min(prices):.1f}, {max(prices):.1f}], mean={sum(prices)/len(prices):.2f}")
    print(f"  spread: min={min(spreads):.0f}, max={max(spreads):.0f}, mean={sum(spreads)/len(spreads):.2f}")
    # Price volatility
    diffs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    if diffs:
        print(f"  tick-to-tick volatility: mean={sum(diffs)/len(diffs):.4f}")
    print()

# Trades analysis
print("=== TRADES ===")
with open('data/raw/trades_round_0_day_-1.csv') as f:
    reader = csv.DictReader(f, delimiter=';')
    trades = {}
    for row in reader:
        p = row['symbol']
        if p not in trades:
            trades[p] = {'count': 0, 'volumes': [], 'prices': []}
        trades[p]['count'] += 1
        trades[p]['volumes'].append(int(row['quantity']))
        trades[p]['prices'].append(float(row['price']))

for p, d in trades.items():
    vols = d['volumes']
    prices = d['prices']
    print(f"{p}: {d['count']} trades, total_vol={sum(vols)}, avg_price={sum(prices)/len(prices):.2f}")
