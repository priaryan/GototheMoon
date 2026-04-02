"""Final fine-tuning around the best TOMATOES parameters."""
import csv, os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class Order:
    symbol: str; price: int; quantity: int
@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")

def load_prices(path):
    with open(path) as f: return list(csv.DictReader(f, delimiter=';'))

def build_od(row):
    od = OrderDepth()
    for lvl in range(1, 4):
        bp, bv = row.get(f'bid_price_{lvl}',''), row.get(f'bid_volume_{lvl}','')
        ap, av = row.get(f'ask_price_{lvl}',''), row.get(f'ask_volume_{lvl}','')
        if bp: od.buy_orders[int(float(bp))] = od.buy_orders.get(int(float(bp)),0) + int(float(bv))
        if ap: od.sell_orders[int(float(ap))] = od.sell_orders.get(int(float(ap)),0) - int(float(av))
    return od

def match(orders, depth, pos, limit=20):
    fills = []
    for order in orders:
        if order.quantity > 0:
            rem = min(order.quantity, limit - pos)
            if rem <= 0: continue
            for ap in sorted(depth.sell_orders):
                if rem <= 0 or order.price < ap: break
                av = abs(depth.sell_orders[ap]); fq = min(rem, av)
                if fq > 0:
                    fills.append((ap, fq)); pos += fq; rem -= fq
                    depth.sell_orders[ap] += fq
                    if abs(depth.sell_orders[ap]) < 1: del depth.sell_orders[ap]
        elif order.quantity < 0:
            rem = min(abs(order.quantity), limit + pos)
            if rem <= 0: continue
            for bp in sorted(depth.buy_orders, reverse=True):
                if rem <= 0 or order.price > bp: break
                bv = depth.buy_orders[bp]; fq = min(rem, bv)
                if fq > 0:
                    fills.append((bp, -fq)); pos -= fq; rem -= fq
                    depth.buy_orders[bp] -= fq
                    if depth.buy_orders[bp] <= 0: del depth.buy_orders[bp]
    return fills, pos

def strategy(depth, pos, base_m, pos_t1, pos_a1, pos_t2=999, pos_a2=0, min_m=0):
    raw_buys = depth.buy_orders or {}; raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells: return []
    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
    bid_wall = min(buy_orders); ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2

    orders = []; LIMIT = 20
    max_buy = LIMIT - pos; max_sell = LIMIT + pos

    buy_margin = base_m; sell_margin = base_m

    # Two-tier position management
    if pos > pos_t2: sell_margin -= pos_a2
    elif pos > pos_t1: sell_margin -= pos_a1
    if pos < -pos_t2: buy_margin -= pos_a2
    elif pos < -pos_t1: buy_margin -= pos_a1

    buy_margin = max(buy_margin, min_m)
    sell_margin = max(sell_margin, min_m)

    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp <= wall_mid - buy_margin:
            size = min(sv, max_buy); orders.append(Order("TOMATOES", sp, size))
            max_buy -= size; pos += size
        elif sp <= wall_mid and pos < 0:
            size = min(sv, abs(pos), max_buy)
            if size > 0: orders.append(Order("TOMATOES", sp, size)); max_buy -= size; pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp >= wall_mid + sell_margin:
            size = min(bv, max_sell); orders.append(Order("TOMATOES", bp, -size))
            max_sell -= size; pos -= size
        elif bp >= wall_mid and pos > 0:
            size = min(bv, pos, max_sell)
            if size > 0: orders.append(Order("TOMATOES", bp, -size)); max_sell -= size; pos -= size

    bid_price = int(bid_wall + 1); ask_price = int(ask_wall - 1)
    for bp, bv in buy_orders.items():
        ob = bp + 1
        if bv > 1 and ob < wall_mid: bid_price = max(bid_price, ob); break
        elif bp < wall_mid: bid_price = max(bid_price, bp); break
    for sp, sv in sell_orders.items():
        ub = sp - 1
        if sv > 1 and ub > wall_mid: ask_price = min(ask_price, ub); break
        elif sp > wall_mid: ask_price = min(ask_price, sp); break

    max_buy = LIMIT - pos; max_sell = LIMIT + pos
    if max_buy > 0: orders.append(Order("TOMATOES", bid_price, max_buy))
    if max_sell > 0: orders.append(Order("TOMATOES", ask_price, -max_sell))
    return orders

def run_bt(base_m, pos_t1, pos_a1, pos_t2=999, pos_a2=0, min_m=0):
    results = []
    for d in ['-1', '-2']:
        rows = load_prices(os.path.join(DATA_DIR, f'prices_round_0_day_{d}.csv'))
        ts_data = defaultdict(dict)
        for r in rows:
            if r.get('product'): ts_data[int(r['timestamp'])][r['product']] = r
        pos = 0; cash = 0.0; last_mid = 0.0
        for ts in sorted(ts_data):
            if 'TOMATOES' not in ts_data[ts]: continue
            row = ts_data[ts]['TOMATOES']; od = build_od(row)
            if row.get('mid_price'): last_mid = float(row['mid_price'])
            orders = strategy(od, pos, base_m, pos_t1, pos_a1, pos_t2, pos_a2, min_m)
            fills, pos = match(orders, od, pos, 20)
            for price, qty in fills: cash -= price * qty
        results.append(round(cash + pos * last_mid, 2))
    return round(sum(results), 2), results

print(f"{'Config':<45s} {'D-1':>8s} {'D-2':>8s} {'Total':>8s} {'vs v4':>7s}")
print("-" * 75)

# Baseline
total, pd = run_bt(1.0, 999, 0)
print(f"{'v4 baseline (margin=1.0, no pos)':<45s} {pd[0]:>8.1f} {pd[1]:>8.1f} {total:>8.1f} {total-2343.5:>+7.1f}")

configs = []
# Single tier sweep
for bm in [0.3, 0.5, 0.7, 1.0]:
    for pt in [3, 5, 7, 10, 12]:
        for pa in [0.3, 0.5, 0.7, 1.0]:
            configs.append((f"m{bm}+p{pt}a{pa}", bm, pt, pa, 999, 0, 0))

# Two-tier sweep (best single + second tier)
for bm in [0.5]:
    for pt1 in [3, 5]:
        for pa1 in [0.3, 0.5]:
            for pt2 in [10, 12, 15]:
                for pa2 in [0.5, 1.0]:
                    configs.append((f"m{bm}+p{pt1}a{pa1}+p{pt2}a{pa2}", bm, pt1, pa1, pt2, pa2, 0))

best_total = 2343.5
best_label = "v4"

for label, bm, pt1, pa1, pt2, pa2, mm in configs:
    total, pd = run_bt(bm, pt1, pa1, pt2, pa2, mm)
    diff = total - 2343.5
    if total > best_total:
        best_total = total
        best_label = label
        marker = " <-- BEST" if diff > 100 else " *"
        print(f"{label:<45s} {pd[0]:>8.1f} {pd[1]:>8.1f} {total:>8.1f} {diff:>+7.1f}{marker}")

print(f"\nBest: {best_label} = {best_total:.1f} (vs v4: {best_total-2343.5:+.1f})")
