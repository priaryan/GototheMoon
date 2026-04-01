import csv

# Check what prices are actually available for EMERALDS
fname = '/Users/rishit_gadre/IMCProsperity4/GototheMoon/data/raw/prices_round_0_day_-1.csv'
take_opportunities = {"EMERALDS": {"buy_below_fair": 0, "sell_above_fair": 0}, "TOMATOES": {"buy_below_fair": 0, "sell_above_fair": 0}}

with open(fname) as f:
    reader = csv.DictReader(f, delimiter=';')
    emerald_book = []
    for row in reader:
        if row['product'] == 'EMERALDS':
            bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
            ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
            bid2 = int(float(row['bid_price_2'])) if row['bid_price_2'] else None
            ask2 = int(float(row['ask_price_2'])) if row['ask_price_2'] else None
            bv1 = int(float(row['bid_volume_1'])) if row['bid_volume_1'] else 0
            av1 = int(float(row['ask_volume_1'])) if row['ask_volume_1'] else 0
            bv2 = int(float(row['bid_volume_2'])) if row['bid_volume_2'] else 0
            av2 = int(float(row['ask_volume_2'])) if row['ask_volume_2'] else 0
            
            emerald_book.append({
                'bid1': bid1, 'bv1': bv1, 'bid2': bid2, 'bv2': bv2,
                'ask1': ask1, 'av1': av1, 'ask2': ask2, 'av2': av2,
            })
            
            # Count take opportunities vs fair=10000
            if ask1 and ask1 < 10000:
                take_opportunities["EMERALDS"]["buy_below_fair"] += 1
            if bid1 and bid1 > 10000:
                take_opportunities["EMERALDS"]["sell_above_fair"] += 1

print("=== EMERALDS order book sample (first 20) ===")
for i, b in enumerate(emerald_book[:20]):
    print(f"  t={i}: bid={b['bid1']}x{b['bv1']}, {b['bid2']}x{b['bv2']} | ask={b['ask1']}x{b['av1']}, {b['ask2']}x{b['av2']}")

print(f"\nEMERALDS take opportunities (vs fair=10000): {take_opportunities['EMERALDS']}")

# Check unique bid/ask prices for EMERALDS
bids = set()
asks = set()
for b in emerald_book:
    if b['bid1']: bids.add(b['bid1'])
    if b['bid2']: bids.add(b['bid2'])
    if b['ask1']: asks.add(b['ask1'])
    if b['ask2']: asks.add(b['ask2'])
print(f"EMERALDS unique bid prices: {sorted(bids)}")
print(f"EMERALDS unique ask prices: {sorted(asks)}")

# Check TOMATOES same
with open(fname) as f:
    reader = csv.DictReader(f, delimiter=';')
    tom_bids = set()
    tom_asks = set()
    for row in reader:
        if row['product'] == 'TOMATOES':
            bid1 = int(float(row['bid_price_1'])) if row['bid_price_1'] else None
            ask1 = int(float(row['ask_price_1'])) if row['ask_price_1'] else None
            bid2 = int(float(row['bid_price_2'])) if row['bid_price_2'] else None
            ask2 = int(float(row['ask_price_2'])) if row['ask_price_2'] else None
            if bid1: tom_bids.add(bid1)
            if bid2: tom_bids.add(bid2)
            if ask1: tom_asks.add(ask1)
            if ask2: tom_asks.add(ask2)

print(f"\nTOMATOES unique bid prices: {sorted(tom_bids)}")
print(f"TOMATOES unique ask prices: {sorted(tom_asks)}")
