"""Exhaustive fine sweep around the best parameters."""
import csv, os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict

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

def strategy(depth, pos, bm, pt, pa, flatten_always=False):
    raw_buys = depth.buy_orders or {}; raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells: return []
    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
    bid_wall = min(buy_orders); ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2

    orders = []; LIMIT = 20
    max_buy = LIMIT - pos; max_sell = LIMIT + pos

    buy_margin = bm; sell_margin = bm
    if pos > pt: sell_margin -= pa
    if pos < -pt: buy_margin -= pa
    buy_margin = max(buy_margin, 0); sell_margin = max(sell_margin, 0)

    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp <= wall_mid - buy_margin:
            size = min(sv, max_buy); orders.append(Order("TOMATOES", sp, size))
            max_buy -= size; pos += size
        elif sp <= wall_mid and pos < 0:
            size = min(sv, abs(pos), max_buy)
            if size > 0: orders.append(Order("TOMATOES", sp, size)); max_buy -= size; pos += size
        elif flatten_always and sp <= wall_mid and pos < -pt:
            # Extra-aggressive flatten when deeply positioned
            size = min(sv, max_buy)
            if size > 0: orders.append(Order("TOMATOES", sp, size)); max_buy -= size; pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp >= wall_mid + sell_margin:
            size = min(bv, max_sell); orders.append(Order("TOMATOES", bp, -size))
            max_sell -= size; pos -= size
        elif bp >= wall_mid and pos > 0:
            size = min(bv, pos, max_sell)
            if size > 0: orders.append(Order("TOMATOES", bp, -size)); max_sell -= size; pos -= size
        elif flatten_always and bp >= wall_mid and pos > pt:
            size = min(bv, max_sell)
            if size > 0: orders.append(Order("TOMATOES", bp, -size)); max_sell -= size; pos -= size

    # Making
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

def run_bt(bm, pt, pa, flatten_always=False):
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
            orders = strategy(od, pos, bm, pt, pa, flatten_always)
            fills, pos = match(orders, od, pos, 20)
            for price, qty in fills: cash -= price * qty
        results.append(round(cash + pos * last_mid, 2))
    return round(sum(results), 2), results

print(f"{'Config':<40s} {'D-1':>8s} {'D-2':>8s} {'Total':>8s}")
print("-" * 62)

best_t = 0; best_l = ""
# Exhaustive fine sweep
for bm_x10 in range(0, 15):  # 0.0 to 1.4
    bm = bm_x10 / 10.0
    for pt in [3, 4, 5, 6, 7, 8, 10, 12, 15]:
        for pa_x10 in range(1, 15):  # 0.1 to 1.4
            pa = pa_x10 / 10.0
            for fa in [False, True]:
                total, pd = run_bt(bm, pt, pa, fa)
                if total > best_t:
                    best_t = total
                    fa_str = "+fa" if fa else ""
                    best_l = f"m{bm}+p{pt}a{pa}{fa_str}"
                    print(f"{best_l:<40s} {pd[0]:>8.1f} {pd[1]:>8.1f} {total:>8.1f}")

print(f"\nBEST: {best_l} = {best_t:.1f} (vs v4: {best_t-2343.5:+.1f})")
