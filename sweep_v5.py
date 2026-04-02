"""Parameter sweep for v5 TOMATOES strategy."""
import sys, os, importlib.util, csv
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any, Optional

# Datamodel
@dataclass
class Order:
    symbol: str; price: int; quantity: int
@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)
@dataclass
class Trade:
    symbol: str; price: float; quantity: int; buyer: str = ""; seller: str = ""; timestamp: int = 0
@dataclass
class TradingState:
    traderData: str = ""; timestamp: int = 0; listings: Dict[str, Any] = field(default_factory=dict)
    order_depths: Dict[str, OrderDepth] = field(default_factory=dict)
    own_trades: Dict[str, List[Trade]] = field(default_factory=dict)
    market_trades: Dict[str, List[Trade]] = field(default_factory=dict)
    position: Dict[str, int] = field(default_factory=dict); observations: Any = None

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
                    fills.append((order.symbol, ap, fq))
                    pos += fq; rem -= fq
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
                    fills.append((order.symbol, bp, -fq))
                    pos -= fq; rem -= fq
                    depth.buy_orders[bp] -= fq
                    if depth.buy_orders[bp] <= 0: del depth.buy_orders[bp]
    return fills, pos


def tomato_strategy(depth, position, params):
    """Parameterized TOMATOES strategy."""
    raw_buys = depth.buy_orders or {}
    raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells: return []

    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

    best_bid = max(buy_orders); best_ask = min(sell_orders)
    best_bid_vol = buy_orders[best_bid]; best_ask_vol = sell_orders[best_ask]
    spread = best_ask - best_bid
    bid_wall = min(buy_orders); ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2

    total_vol = best_bid_vol + best_ask_vol
    vol_imbalance = (best_bid_vol - best_ask_vol) / total_vol if total_vol > 0 else 0

    orders = []; pos = position; LIMIT = 20
    max_buy = LIMIT - pos; max_sell = LIMIT + pos

    buy_margin = params['base_margin']
    sell_margin = params['base_margin']

    # Vol imbalance
    if vol_imbalance > params['vi_thresh']:
        buy_margin -= params['vi_adj']
    elif vol_imbalance < -params['vi_thresh']:
        sell_margin -= params['vi_adj']

    # Spread
    if spread <= params['spread_tight']:
        buy_margin -= params['spread_adj_tight']
        sell_margin -= params['spread_adj_tight']
    elif spread <= params['spread_med']:
        buy_margin -= params['spread_adj_med']
        sell_margin -= params['spread_adj_med']

    # Position
    if pos > params['pos_thresh_hi']:
        sell_margin -= params['pos_adj_hi']
    elif pos > params['pos_thresh_lo']:
        sell_margin -= params['pos_adj_lo']
    if pos < -params['pos_thresh_hi']:
        buy_margin -= params['pos_adj_hi']
    elif pos < -params['pos_thresh_lo']:
        buy_margin -= params['pos_adj_lo']

    buy_margin = max(buy_margin, params['min_margin'])
    sell_margin = max(sell_margin, params['min_margin'])

    buy_threshold = wall_mid - buy_margin
    sell_threshold = wall_mid + sell_margin

    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp <= buy_threshold:
            size = min(sv, max_buy); orders.append(Order("TOMATOES", sp, size))
            max_buy -= size; pos += size
        elif sp <= wall_mid and pos < 0:
            size = min(sv, abs(pos), max_buy)
            if size > 0:
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size; pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp >= sell_threshold:
            size = min(bv, max_sell); orders.append(Order("TOMATOES", bp, -size))
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
    total_pnl = 0
    results = []
    for pf in day_files:
        rows = load_prices(pf)
        ts_data = defaultdict(dict)
        for r in rows:
            if r.get('product'):
                ts_data[int(r['timestamp'])][r['product']] = r

        pos = {'TOMATOES': 0}
        cash = 0.0
        last_mid = 0.0

        for ts in sorted(ts_data):
            if 'TOMATOES' not in ts_data[ts]: continue
            row = ts_data[ts]['TOMATOES']
            od = build_od(row)
            if row.get('mid_price'): last_mid = float(row['mid_price'])

            orders = tomato_strategy(od, pos['TOMATOES'], params)
            fills, new_pos = match(orders, od, pos['TOMATOES'], 20)
            for sym, price, qty in fills:
                cash -= price * qty
            pos['TOMATOES'] = new_pos

        pnl = cash + pos['TOMATOES'] * last_mid
        results.append(round(pnl, 2))
        total_pnl += pnl

    return round(total_pnl, 2), results


# Day files
day_files = [
    os.path.join(DATA_DIR, 'prices_round_0_day_-1.csv'),
    os.path.join(DATA_DIR, 'prices_round_0_day_-2.csv'),
]

# v4 baseline (wall-mid, margin=1, no signals)
v4_params = {
    'base_margin': 1.0, 'vi_thresh': 999, 'vi_adj': 0, 'spread_tight': 0,
    'spread_adj_tight': 0, 'spread_med': 0, 'spread_adj_med': 0,
    'pos_thresh_hi': 999, 'pos_adj_hi': 0, 'pos_thresh_lo': 999, 'pos_adj_lo': 0,
    'min_margin': 1.0,
}
total, per_day = run_backtest(v4_params, day_files)
print(f"v4 baseline:  D-1={per_day[0]:>8.1f}  D-2={per_day[1]:>8.1f}  Total={total:>8.1f}")

# Sweep key parameters
best_total = -99999
best_params = None
best_label = ""

configs = [
    # (label, overrides)
    ("v4_baseline", {}),
    # Spread only
    ("spread6_adj0.5", {'spread_tight': 6, 'spread_adj_tight': 0.5, 'min_margin': 0}),
    ("spread6_adj1.0", {'spread_tight': 6, 'spread_adj_tight': 1.0, 'min_margin': 0}),
    ("spread7_adj0.5", {'spread_tight': 7, 'spread_adj_tight': 0.5, 'min_margin': 0}),
    ("spread8_adj0.5", {'spread_tight': 8, 'spread_adj_tight': 0.5, 'min_margin': 0}),
    ("spread8_adj0.5_med10", {'spread_tight': 8, 'spread_adj_tight': 0.5, 'spread_med': 10, 'spread_adj_med': 0.25, 'min_margin': 0}),
    # Vol imbalance only
    ("vi0.15_adj0.5", {'vi_thresh': 0.15, 'vi_adj': 0.5, 'min_margin': 0.5}),
    ("vi0.15_adj1.0", {'vi_thresh': 0.15, 'vi_adj': 1.0, 'min_margin': 0}),
    ("vi0.25_adj0.5", {'vi_thresh': 0.25, 'vi_adj': 0.5, 'min_margin': 0.5}),
    ("vi0.10_adj0.5", {'vi_thresh': 0.10, 'vi_adj': 0.5, 'min_margin': 0.5}),
    # Position only
    ("pos5_adj0.5", {'pos_thresh_lo': 5, 'pos_adj_lo': 0.5, 'pos_thresh_hi': 10, 'pos_adj_hi': 1.0, 'min_margin': 0}),
    ("pos3_adj0.5", {'pos_thresh_lo': 3, 'pos_adj_lo': 0.5, 'pos_thresh_hi': 8, 'pos_adj_hi': 1.0, 'min_margin': 0}),
    # Base margin changes
    ("margin0.5", {'base_margin': 0.5, 'min_margin': 0}),
    ("margin0", {'base_margin': 0, 'min_margin': 0}),
    ("margin1.5", {'base_margin': 1.5, 'min_margin': 0}),
    ("margin2", {'base_margin': 2.0, 'min_margin': 0}),
    # Combined best guesses
    ("spread6+vi0.15", {'spread_tight': 6, 'spread_adj_tight': 0.5, 'vi_thresh': 0.15, 'vi_adj': 0.5, 'min_margin': 0}),
    ("spread6+pos5", {'spread_tight': 6, 'spread_adj_tight': 0.5, 'pos_thresh_lo': 5, 'pos_adj_lo': 0.5, 'pos_thresh_hi': 10, 'pos_adj_hi': 1.0, 'min_margin': 0}),
    ("spread6+vi+pos", {'spread_tight': 6, 'spread_adj_tight': 0.5, 'vi_thresh': 0.15, 'vi_adj': 0.5, 'pos_thresh_lo': 5, 'pos_adj_lo': 0.5, 'pos_thresh_hi': 10, 'pos_adj_hi': 1.0, 'min_margin': 0}),
    ("all_signals_conservative", {'spread_tight': 6, 'spread_adj_tight': 0.25, 'vi_thresh': 0.2, 'vi_adj': 0.25, 'pos_thresh_lo': 8, 'pos_adj_lo': 0.25, 'pos_thresh_hi': 15, 'pos_adj_hi': 0.5, 'min_margin': 0.5}),
    ("all_signals_moderate", {'spread_tight': 6, 'spread_adj_tight': 0.5, 'vi_thresh': 0.15, 'vi_adj': 0.5, 'pos_thresh_lo': 5, 'pos_adj_lo': 0.5, 'pos_thresh_hi': 10, 'pos_adj_hi': 1.0, 'min_margin': 0}),
]

print(f"\n{'Config':<30s} {'D-1':>8s} {'D-2':>8s} {'Total':>8s}")
print("-" * 58)

for label, overrides in configs:
    p = dict(v4_params)
    p.update(overrides)
    total, per_day = run_backtest(p, day_files)
    marker = " *" if total > 2343.5 else ""  # beat v4
    print(f"{label:<30s} {per_day[0]:>8.1f} {per_day[1]:>8.1f} {total:>8.1f}{marker}")
    if total > best_total:
        best_total = total
        best_params = p
        best_label = label

print(f"\nBest: {best_label} = {best_total:.1f}")
print(f"Best params: {best_params}")
