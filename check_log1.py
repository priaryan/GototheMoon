"""Analyze log1.tex to check trade history."""
import json

data = json.load(open('log1.tex'))
print('Keys:', list(data.keys()))

if 'tradeHistory' in data:
    trades = data['tradeHistory']
    print('Total trades:', len(trades))
    
    # Count SUBMISSION trades
    sub_trades = [t for t in trades if t.get('buyer') == 'SUBMISSION' or t.get('seller') == 'SUBMISSION']
    print('SUBMISSION trades:', len(sub_trades))
    
    if sub_trades:
        print('\nFirst SUBMISSION trade:')
        t = sub_trades[0]
        print(f"  Timestamp: {t.get('timestamp')}")
        print(f"  Symbol: {t.get('symbol')}")
        print(f"  Buyer: {t.get('buyer')}")
        print(f"  Seller: {t.get('seller')}")
        print(f"  Price: {t.get('price')}")
        print(f"  Quantity: {t.get('quantity')}")
