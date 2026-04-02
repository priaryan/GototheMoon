"""Finer sweep + new approaches for TOMATOES."""
import csv, os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Any

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
    with open(path) as f:
        return list(csv.DictReader(f, delimiter=';'))

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
                av = abs(depth.sell_orders[ap])
                fq = min(rem, av)
                if fq > 0:
                    fills.append((order.symbol, ap, fq)); pos += fq; rem -= fq
                    depth.sell_orders[ap] += fq
                    if abs(depth.sell_orders[ap]) < 1: del depth.sell_orders[ap]
        elif order.quantity < 0:
            rem = min(abs(order.quantity), limit + pos)
            if rem <= 0: continue
            for bp in sorted(depth.buy_orders, reverse=True):
                if rem <= 0 or order.price > bp: break
                bv = depth.buy_orders[bp]
                fq = min(rem, bv)
                if fq > 0:
                    fills.append((order.symbol, bp, -fq)); pos -= fq; rem -= fq
                    depth.buy_orders[bp] -= fq
                    if depth.buy_orders[bp] <= 0: del depth.buy_orders[bp]
    return fills, pos


def strategy_v5(depth, position, params):
    raw_buys = depth.buy_orders or {}
    raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells: return []
    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

    best_bid = max(buy_orders); best_ask = min(sell_orders)
    best_bid_vol = buy_orders[best_bid]; best_ask_vol = sell_orders[best_ask]
    spread = best_ask - best_bid

    # Wall prices - configurable level
    wall_level = params.get('wall_level', 'L3')
    if wall_level == 'L2':
        sorted_bids = sorted(buy_orders.keys())
        sorted_asks = sorted(sell_orders.keys(), reverse=True)
        bid_wall = sorted_bids[min(1, len(sorted_bids)-1)]
        ask_wall = sorted_asks[min(1, len(sorted_asks)-1)]
    else:
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2

    total_vol = best_bid_vol + best_ask_vol
    vol_imb = (best_bid_vol - best_ask_vol) / total_vol if total_vol > 0 else 0

    orders = []; pos = position; LIMIT = 20
    max_buy = LIMIT - pos; max_sell = LIMIT + pos

    buy_margin = params['base_margin']
    sell_margin = params['base_margin']

    # Size scaling: reduce size when taking against inventory
    buy_size_mult = 1.0
    sell_size_mult = 1.0

    # Vol imbalance signal
    vi_thresh = params.get('vi_thresh', 999)
    if vol_imb > vi_thresh:
        buy_margin -= params.get('vi_adj', 0)
    elif vol_imb < -vi_thresh:
        sell_margin -= params.get('vi_adj', 0)

    # Spread signal
    if spread <= params.get('spread_tight', 0):
        buy_margin -= params.get('spread_adj', 0)
        sell_margin -= params.get('spread_adj', 0)

    # Position signal (margin + size based)
    pos_mode = params.get('pos_mode', 'margin')  # 'margin', 'size', or 'both'
    pos_thresh = params.get('pos_thresh', 999)
    if abs(pos) > pos_thresh:
        adj = params.get('pos_adj', 0)
        if pos_mode in ('margin', 'both'):
            if pos > 0: sell_margin -= adj
            else: buy_margin -= adj
        if pos_mode in ('size', 'both'):
            if pos > 0: buy_size_mult *= 0.5  # buy less when long
            else: sell_size_mult *= 0.5

    buy_margin = max(buy_margin, params.get('min_margin', 0))
    sell_margin = max(sell_margin, params.get('min_margin', 0))

    buy_threshold = wall_mid - buy_margin
    sell_threshold = wall_mid + sell_margin

    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp <= buy_threshold:
            size = min(sv, max_buy)
            size = max(1, int(size * buy_size_mult))
            size = min(size, max_buy)
            orders.append(Order("TOMATOES", sp, size))
            max_buy -= size; pos += size
        elif sp <= wall_mid and pos < 0:
            size = min(sv, abs(pos), max_buy)
            if size > 0:
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size; pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp >= sell_threshold:
            size = min(bv, max_sell)
            size = max(1, int(size * sell_size_mult))
            size = min(size, max_sell)
            orders.append(Order("TOMATOES", bp, -size))
            max_sell -= size; pos -= size
        elif bp >= wall_mid and pos > 0:
            size = min(bv, pos, max_sell)
            if size > 0:
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size; pos -= size

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


def run_backtest(params, day_files):
    results = []
    for pf in day_files:
        rows = load_prices(pf)
        ts_data = defaultdict(dict)
        for r in rows:
            if r.get('product'): ts_data[int(r['timestamp'])][r['product']] = r
        pos = 0; cash = 0.0; last_mid = 0.0
        for ts in sorted(ts_data):
            if 'TOMATOES' not in ts_data[ts]: continue
            row = ts_data[ts]['TOMATOES']
            od = build_od(row)
            if row.get('mid_price'): last_mid = float(row['mid_price'])
            orders = strategy_v5(od, pos, params)
            fills, pos = match(orders, od, pos, 20)
            for sym, price, qty in fills:
                cash -= price * qty
        results.append(round(cash + pos * last_mid, 2))
    return round(sum(results), 2), results


day_files = [os.path.join(DATA_DIR, f'prices_round_0_day_{d}.csv') for d in ['-1', '-2']]

configs = [
    # Fine-tuned margins
    ("margin=1.0 (v4)", {'base_margin': 1.0}),
    ("margin=0.9", {'base_margin': 0.9}),
    ("margin=0.8", {'base_margin': 0.8}),
    ("margin=0.7", {'base_margin': 0.7}),
    ("margin=0.6", {'base_margin': 0.6}),
    ("margin=0.5", {'base_margin': 0.5}),
    ("margin=0.4", {'base_margin': 0.4}),
    ("margin=0.3", {'base_margin': 0.3}),

    # L2 walls instead of L3
    ("L2_margin1.0", {'base_margin': 1.0, 'wall_level': 'L2'}),
    ("L2_margin0.5", {'base_margin': 0.5, 'wall_level': 'L2'}),
    ("L2_margin0", {'base_margin': 0.0, 'wall_level': 'L2'}),

    # Position management: size-based
    ("margin0.5+pos_size5", {'base_margin': 0.5, 'pos_mode': 'size', 'pos_thresh': 5, 'pos_adj': 0}),
    ("margin0.5+pos_size10", {'base_margin': 0.5, 'pos_mode': 'size', 'pos_thresh': 10, 'pos_adj': 0}),

    # Spread + margin combos
    ("margin0.8+spr6adj0.3", {'base_margin': 0.8, 'spread_tight': 6, 'spread_adj': 0.3}),
    ("margin0.7+spr6adj0.2", {'base_margin': 0.7, 'spread_tight': 6, 'spread_adj': 0.2}),
    ("margin0.5+spr8adj0.5", {'base_margin': 0.5, 'spread_tight': 8, 'spread_adj': 0.5}),

    # Vol imbalance with margin 0.5
    ("margin0.5+vi0.15adj0.5", {'base_margin': 0.5, 'vi_thresh': 0.15, 'vi_adj': 0.5}),
    ("margin0.5+vi0.2adj0.3", {'base_margin': 0.5, 'vi_thresh': 0.2, 'vi_adj': 0.3}),

    # Position margin with margin 0.5
    ("margin0.5+pos_m5adj0.5", {'base_margin': 0.5, 'pos_mode': 'margin', 'pos_thresh': 5, 'pos_adj': 0.5}),
    ("margin0.5+pos_m10adj0.5", {'base_margin': 0.5, 'pos_mode': 'margin', 'pos_thresh': 10, 'pos_adj': 0.5}),

    # Best combos
    ("margin0.5+spr6+vi+pos_m", {'base_margin': 0.5, 'spread_tight': 6, 'spread_adj': 0.3, 'vi_thresh': 0.15, 'vi_adj': 0.3, 'pos_mode': 'margin', 'pos_thresh': 5, 'pos_adj': 0.3}),
    ("margin0.8+spr6+vi+pos_m", {'base_margin': 0.8, 'spread_tight': 6, 'spread_adj': 0.3, 'vi_thresh': 0.15, 'vi_adj': 0.3, 'pos_mode': 'margin', 'pos_thresh': 8, 'pos_adj': 0.5}),
    ("margin0.7+L2", {'base_margin': 0.7, 'wall_level': 'L2'}),
    ("margin0.5+L2+pos_m", {'base_margin': 0.5, 'wall_level': 'L2', 'pos_mode': 'margin', 'pos_thresh': 5, 'pos_adj': 0.5}),
]

print(f"{'Config':<32s} {'D-1':>8s} {'D-2':>8s} {'Total':>8s} {'vs v4':>7s}")
print("-" * 65)

for label, overrides in configs:
    p = {'base_margin': 1.0, 'min_margin': 0}
    p.update(overrides)
    total, per_day = run_backtest(p, day_files)
    diff = total - 2343.5
    marker = " ***" if diff > 50 else (" **" if diff > 20 else (" *" if diff > 0 else ""))
    print(f"{label:<32s} {per_day[0]:>8.1f} {per_day[1]:>8.1f} {total:>8.1f} {diff:>+7.1f}{marker}")
