import csv

for day in [-2, -1]:
    products = {}
    fname = f'/Users/rishit_gadre/IMCProsperity4/GototheMoon/data/raw/prices_round_0_day_{day}.csv'
    with open(fname) as f:
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

    print(f'=== DAY {day} ===')
    for p, d in products.items():
        prices = d['mid_prices']
        spreads = d['spreads']
        print(f"  {p}: mid=[{min(prices):.1f}, {max(prices):.1f}], mean={sum(prices)/len(prices):.2f}, spread_mean={sum(spreads)/len(spreads):.2f}")
    print()

# TOMATOES trend analysis
print("=== TOMATOES TREND (day -1, first/last 20 mid prices) ===")
with open('/Users/rishit_gadre/IMCProsperity4/GototheMoon/data/raw/prices_round_0_day_-1.csv') as f:
    reader = csv.DictReader(f, delimiter=';')
    tom_prices = []
    for row in reader:
        if row['product'] == 'TOMATOES':
            tom_prices.append((int(row['timestamp']), float(row['mid_price'])))

print("First 10:", [(t, p) for t, p in tom_prices[:10]])
print("Last 10:", [(t, p) for t, p in tom_prices[-10:]])

# Check if TOMATOES has a strong mean-reverting or trending behavior
prices_only = [p for _, p in tom_prices]
mean_price = sum(prices_only) / len(prices_only)
print(f"\nTOMATOES mean: {mean_price:.2f}")
print(f"TOMATOES range: {max(prices_only) - min(prices_only):.1f}")
print(f"TOMATOES std: {(sum((p - mean_price)**2 for p in prices_only) / len(prices_only))**0.5:.4f}")

# Autocorrelation estimate
returns = [prices_only[i] - prices_only[i-1] for i in range(1, len(prices_only))]
mean_ret = sum(returns) / len(returns)
var_ret = sum((r - mean_ret)**2 for r in returns) / len(returns)
if var_ret > 0:
    cov_ret = sum((returns[i] - mean_ret) * (returns[i-1] - mean_ret) for i in range(1, len(returns))) / (len(returns) - 1)
    autocorr = cov_ret / var_ret
    print(f"TOMATOES return autocorrelation(1): {autocorr:.4f}")
