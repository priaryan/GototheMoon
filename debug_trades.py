"""Debug the visualization - analyze trades vs market data alignment."""
import json

data = json.load(open('log1.tex'))
trades = data.get('tradeHistory', [])
sub_trades = [t for t in trades if t.get('buyer') == 'SUBMISSION' or t.get('seller') == 'SUBMISSION']

print("=== TRADE DATA ANALYSIS ===")
print(f"Total SUBMISSION trades: {len(sub_trades)}\n")

# Group by product
from collections import defaultdict
trades_by_product = defaultdict(list)
for t in sub_trades:
    trades_by_product[t.get('symbol')].append(t)

for product in ['TOMATOES', 'EMERALDS']:
    trades = trades_by_product.get(product, [])
    print(f"\n{product}: {len(trades)} trades")
    if trades:
        print(f"  Time range: {trades[0].get('timestamp')} to {trades[-1].get('timestamp')}")
        print(f"  First 5 trades:")
        for i, t in enumerate(trades[:5]):
            action = 'BUY' if t.get('buyer') == 'SUBMISSION' else 'SELL'
            print(f"    {i+1}. T={t.get('timestamp'):6} {action:4} {int(t.get('price')):5} @ {int(t.get('quantity'))} units")
        
        print(f"  Last 5 trades:")
        for i, t in enumerate(trades[-5:], len(trades)-4):
            action = 'BUY' if t.get('buyer') == 'SUBMISSION' else 'SELL'
            print(f"    {i}. T={t.get('timestamp'):6} {action:4} {int(t.get('price')):5} @ {int(t.get('quantity'))} units")

# Check market data
print("\n=== MARKET DATA ===")
log_csv = data.get('activitiesLog', '').split('\n')
print(f"Total market snapshots: {len(log_csv)-2}")

# Parse first and last
if len(log_csv) > 1:
    parts = log_csv[1].split(';')
    print(f"\nFirst snapshot: {log_csv[1][:80]}...")
    parts = log_csv[-2].split(';')
    print(f"Last snapshot: {log_csv[-2][:80]}...")
