#!/usr/bin/env python3
"""Sweep v6 parameters: INV_PENALTY, buy/sell margins, flatten threshold, EMA alpha."""
import csv
import importlib.util
import json
import os
import sys
import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─── Minimal datamodel ──────────────────────────────────────────────
@dataclass
class Order:
    symbol: str
    price: int
    quantity: int

@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)
    sell_orders: Dict[int, int] = field(default_factory=dict)

@dataclass
class Trade:
    symbol: str
    price: float
    quantity: int
    buyer: str = ""
    seller: str = ""
    timestamp: int = 0

@dataclass
class TradingState:
    traderData: str = ""
    timestamp: int = 0
    listings: Dict[str, Any] = field(default_factory=dict)
    order_depths: Dict[str, OrderDepth] = field(default_factory=dict)
    own_trades: Dict[str, List[Trade]] = field(default_factory=dict)
    market_trades: Dict[str, List[Trade]] = field(default_factory=dict)
    position: Dict[str, int] = field(default_factory=dict)
    observations: Any = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")
POS_LIMIT = 20

def load_prices(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            rows.append(r)
    return rows

def build_order_depth(row):
    od = OrderDepth()
    for lvl in range(1, 4):
        bp_key = f"bid_price_{lvl}"
        bv_key = f"bid_volume_{lvl}"
        if row.get(bp_key) and row[bp_key] != "":
            price = int(float(row[bp_key]))
            vol = int(float(row[bv_key]))
            od.buy_orders[price] = od.buy_orders.get(price, 0) + vol
        ap_key = f"ask_price_{lvl}"
        av_key = f"ask_volume_{lvl}"
        if row.get(ap_key) and row[ap_key] != "":
            price = int(float(row[ap_key]))
            vol = int(float(row[av_key]))
            od.sell_orders[price] = od.sell_orders.get(price, 0) - vol
    return od

def match_orders(orders, depth, position, pos_limit):
    fills = []
    pos = position
    for order in orders:
        if order.quantity > 0:
            remaining = order.quantity
            available_room = pos_limit - pos
            if available_room <= 0: continue
            remaining = min(remaining, available_room)
            for ask_price in sorted(depth.sell_orders.keys()):
                if remaining <= 0: break
                if order.price < ask_price: break
                ask_vol = abs(depth.sell_orders[ask_price])
                fill_qty = min(remaining, ask_vol)
                if fill_qty > 0:
                    fills.append(Trade(symbol=order.symbol, price=ask_price, quantity=fill_qty))
                    pos += fill_qty
                    remaining -= fill_qty
                    depth.sell_orders[ask_price] += fill_qty
                    if abs(depth.sell_orders[ask_price]) < 1:
                        del depth.sell_orders[ask_price]
        elif order.quantity < 0:
            remaining = abs(order.quantity)
            available_room = pos_limit + pos
            if available_room <= 0: continue
            remaining = min(remaining, available_room)
            for bid_price in sorted(depth.buy_orders.keys(), reverse=True):
                if remaining <= 0: break
                if order.price > bid_price: break
                bid_vol = depth.buy_orders[bid_price]
                fill_qty = min(remaining, bid_vol)
                if fill_qty > 0:
                    fills.append(Trade(symbol=order.symbol, price=bid_price, quantity=-fill_qty))
                    pos -= fill_qty
                    remaining -= fill_qty
                    depth.buy_orders[bid_price] -= fill_qty
                    if depth.buy_orders[bid_price] <= 0:
                        del depth.buy_orders[bid_price]
    return fills, pos


# ─── Strategy function with tuneable params ──────────────────────────

def generate_tomato_orders(depth, position, ema_wm, params):
    """Generate TOMATO orders with given params dict."""
    raw_buys = depth.buy_orders or {}
    raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells:
        return [], ema_wm

    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

    bid_wall = min(buy_orders)
    ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2

    # EMA update
    ema_alpha = params["ema_alpha"]
    if ema_wm is None:
        ema_wm = wall_mid
    else:
        ema_wm = ema_alpha * wall_mid + (1 - ema_alpha) * ema_wm

    inv_penalty = params["inv_penalty"]
    fair_adj = ema_wm - inv_penalty * position

    orders = []
    pos = position
    max_buy = POS_LIMIT - pos
    max_sell = POS_LIMIT + pos

    buy_margin = params["take_margin"]
    sell_margin = params["take_margin"]
    flatten_thresh = params["flatten_thresh"]

    if pos > flatten_thresh:
        sell_margin = 0.0
    if pos < -flatten_thresh:
        buy_margin = 0.0

    # TAKE
    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp <= fair_adj - buy_margin:
            size = min(sv, max_buy)
            orders.append(Order("TOMATOES", sp, size))
            max_buy -= size
            pos += size
        elif sp <= fair_adj and position < 0:
            size = min(sv, abs(position), max_buy)
            if size > 0:
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
                pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp >= fair_adj + sell_margin:
            size = min(bv, max_sell)
            orders.append(Order("TOMATOES", bp, -size))
            max_sell -= size
            pos -= size
        elif bp >= fair_adj and position > 0:
            size = min(bv, position, max_sell)
            if size > 0:
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
                pos -= size

    # MAKE: wall-mid style
    bid_price = int(bid_wall + 1)
    ask_price = int(ask_wall - 1)
    for bp, bv in buy_orders.items():
        ob = bp + 1
        if bv > 1 and ob < wall_mid:
            bid_price = max(bid_price, ob)
            break
        elif bp < wall_mid:
            bid_price = max(bid_price, bp)
            break
    for sp, sv in sell_orders.items():
        ub = sp - 1
        if sv > 1 and ub > wall_mid:
            ask_price = min(ask_price, ub)
            break
        elif sp > wall_mid:
            ask_price = min(ask_price, sp)
            break

    # Optional: skew making quotes based on position
    make_skew = params.get("make_skew", 0.0)
    if make_skew > 0:
        skew_thresh = params.get("make_skew_thresh", 8)
        if pos > skew_thresh:
            ask_price = max(int(wall_mid) + 1, ask_price - 1)
        if pos < -skew_thresh:
            bid_price = min(int(wall_mid) - 1, bid_price + 1)

    max_buy = POS_LIMIT - pos
    max_sell = POS_LIMIT + pos
    if max_buy > 0:
        orders.append(Order("TOMATOES", bid_price, max_buy))
    if max_sell > 0:
        orders.append(Order("TOMATOES", ask_price, -max_sell))

    return orders, ema_wm


def generate_emerald_orders(depth, position, params):
    """Generate EMERALD orders with given params."""
    raw_buys = depth.buy_orders or {}
    raw_sells = depth.sell_orders or {}
    if not raw_buys or not raw_sells:
        return []

    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

    emr_inv_pen = params.get("emr_inv_penalty", 0.0)
    fair = 10000 - emr_inv_pen * position

    orders = []
    pos = position
    max_buy = POS_LIMIT - pos
    max_sell = POS_LIMIT + pos

    for sp, sv in sell_orders.items():
        if max_buy <= 0: break
        if sp < fair:
            size = min(sv, max_buy)
            orders.append(Order("EMERALDS", sp, size))
            max_buy -= size
            pos += size
        elif sp <= fair and pos < 0:
            size = min(sv, abs(pos), max_buy)
            if size > 0:
                orders.append(Order("EMERALDS", sp, size))
                max_buy -= size
                pos += size

    for bp, bv in buy_orders.items():
        if max_sell <= 0: break
        if bp > fair:
            size = min(bv, max_sell)
            orders.append(Order("EMERALDS", bp, -size))
            max_sell -= size
            pos -= size
        elif bp >= fair and pos > 0:
            size = min(bv, pos, max_sell)
            if size > 0:
                orders.append(Order("EMERALDS", bp, -size))
                max_sell -= size
                pos -= size

    bid_wall = min(buy_orders)
    ask_wall = max(sell_orders)
    bid_price = int(bid_wall + 1)
    ask_price = int(ask_wall - 1)
    for bp, bv in buy_orders.items():
        ob = bp + 1
        if bv > 1 and ob < 10000:
            bid_price = max(bid_price, ob)
            break
        elif bp < 10000:
            bid_price = max(bid_price, bp)
            break
    for sp, sv in sell_orders.items():
        ub = sp - 1
        if sv > 1 and ub > 10000:
            ask_price = min(ask_price, ub)
            break
        elif sp > 10000:
            ask_price = min(ask_price, sp)
            break

    max_buy = POS_LIMIT - pos
    max_sell = POS_LIMIT + pos
    if max_buy > 0:
        orders.append(Order("EMERALDS", bid_price, max_buy))
    if max_sell > 0:
        orders.append(Order("EMERALDS", ask_price, -max_sell))
    return orders


# ─── Run backtest for one param set ──────────────────────────────────

def run_backtest(all_day_data, params):
    """Run full backtest with given params. Returns total PnL."""
    total_pnl = 0.0

    for day_label, prices_rows in all_day_data:
        ts_data = defaultdict(dict)
        for row in prices_rows:
            if row.get("product"):
                ts = int(row["timestamp"])
                ts_data[ts][row["product"]] = row

        timestamps = sorted(ts_data.keys())
        position = {}
        ema_wm = None
        cash_flow = defaultdict(float)
        last_mid = {}

        for ts in timestamps:
            products_at_ts = ts_data[ts]
            order_depths = {}
            for product, row in products_at_ts.items():
                order_depths[product] = build_order_depth(row)
                if row.get("mid_price") and row["mid_price"] != "":
                    last_mid[product] = float(row["mid_price"])

            all_orders = {}

            if "EMERALDS" in order_depths:
                epos = position.get("EMERALDS", 0)
                all_orders["EMERALDS"] = generate_emerald_orders(
                    order_depths["EMERALDS"], epos, params
                )

            if "TOMATOES" in order_depths:
                tpos = position.get("TOMATOES", 0)
                tom_orders, ema_wm = generate_tomato_orders(
                    order_depths["TOMATOES"], tpos, ema_wm, params
                )
                all_orders["TOMATOES"] = tom_orders

            for product, order_list in all_orders.items():
                if product not in order_depths: continue
                pos = position.get(product, 0)
                fills, new_pos = match_orders(order_list, order_depths[product], pos, POS_LIMIT)
                position[product] = new_pos
                for f in fills:
                    cash_flow[f.symbol] -= f.price * f.quantity

        # Final PnL
        pnl = 0.0
        for product in set(list(cash_flow.keys()) + list(position.keys())):
            mid = last_mid.get(product, 0)
            pos_val = position.get(product, 0) * mid
            pnl += cash_flow.get(product, 0) + pos_val
        total_pnl += pnl

    return round(total_pnl, 2)


# ─── Load data once ──────────────────────────────────────────────────

def load_all_data():
    import glob
    price_files = sorted(glob.glob(os.path.join(DATA_DIR, "prices_round_*_day_*.csv")))
    all_day_data = []
    for pf in price_files:
        base = os.path.basename(pf)
        day = base.replace(".csv", "").split("_")[-1]
        rows = load_prices(pf)
        all_day_data.append((day, rows))
    return all_day_data


# ─── Main sweep ──────────────────────────────────────────────────────

def main():
    print("Loading data...")
    all_day_data = load_all_data()
    print(f"Loaded {len(all_day_data)} days")

    # Define parameter grid
    inv_penalties = [0.0, 0.02, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30]
    take_margins = [0.0, 0.25, 0.5, 0.75, 1.0]
    flatten_thresholds = [3, 5, 7, 10, 15, 20]
    ema_alphas = [0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
    emr_inv_penalties = [0.0, 0.05, 0.1, 0.2]
    make_skew_options = [0.0, 1.0]  # 0=off, 1=on
    make_skew_thresholds = [5, 8, 12]

    # Phase 1: Coarse sweep of main params (no skew first)
    print("\n=== Phase 1: Coarse sweep (no make_skew) ===")
    results = []
    total_combos = len(inv_penalties) * len(take_margins) * len(flatten_thresholds) * len(ema_alphas) * len(emr_inv_penalties)
    print(f"Total combinations: {total_combos}")

    count = 0
    for inv_pen in inv_penalties:
        for tm in take_margins:
            for ft in flatten_thresholds:
                for ea in ema_alphas:
                    for eip in emr_inv_penalties:
                        params = {
                            "inv_penalty": inv_pen,
                            "take_margin": tm,
                            "flatten_thresh": ft,
                            "ema_alpha": ea,
                            "emr_inv_penalty": eip,
                            "make_skew": 0.0,
                        }
                        pnl = run_backtest(all_day_data, params)
                        results.append((pnl, params))
                        count += 1
                        if count % 500 == 0:
                            print(f"  {count}/{total_combos} done...")

    results.sort(key=lambda x: -x[0])
    print(f"\nTop 20 parameter sets:")
    print(f"{'Rank':>4} {'PnL':>10} {'inv_pen':>8} {'margin':>7} {'flatten':>8} {'ema_a':>6} {'emr_ip':>7}")
    for i, (pnl, p) in enumerate(results[:20]):
        print(f"{i+1:>4} {pnl:>10.2f} {p['inv_penalty']:>8.2f} {p['take_margin']:>7.2f} {p['flatten_thresh']:>8} {p['ema_alpha']:>6.2f} {p['emr_inv_penalty']:>7.2f}")

    # Phase 2: Fine-tune around top params + test make_skew
    best_p = results[0][1]
    print(f"\n=== Phase 2: Fine-tune around best ===")
    print(f"Best base: inv_pen={best_p['inv_penalty']}, margin={best_p['take_margin']}, flatten={best_p['flatten_thresh']}, ema={best_p['ema_alpha']}, emr_ip={best_p['emr_inv_penalty']}")

    # Fine sweep around best inv_penalty
    fine_inv = [best_p['inv_penalty'] + d for d in [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]]
    fine_inv = [max(0.0, x) for x in fine_inv]
    fine_margin = [best_p['take_margin'] + d for d in [-0.15, -0.1, -0.05, 0.0, 0.05, 0.1, 0.15]]
    fine_margin = [max(0.0, x) for x in fine_margin]
    fine_flatten = [best_p['flatten_thresh'] + d for d in [-2, -1, 0, 1, 2]]
    fine_flatten = [max(1, x) for x in fine_flatten]
    fine_ema = [best_p['ema_alpha'] + d for d in [-0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.05]]
    fine_ema = [max(0.01, min(1.0, x)) for x in fine_ema]

    fine_results = []
    fine_combos = len(fine_inv) * len(fine_margin) * len(fine_flatten) * len(fine_ema) * len(make_skew_options)
    print(f"Fine-tune combinations: {fine_combos}")

    for inv_pen in fine_inv:
        for tm in fine_margin:
            for ft in fine_flatten:
                for ea in fine_ema:
                    for ms in make_skew_options:
                        params = {
                            "inv_penalty": round(inv_pen, 4),
                            "take_margin": round(tm, 4),
                            "flatten_thresh": ft,
                            "ema_alpha": round(ea, 4),
                            "emr_inv_penalty": best_p['emr_inv_penalty'],
                            "make_skew": ms,
                            "make_skew_thresh": 8,
                        }
                        pnl = run_backtest(all_day_data, params)
                        fine_results.append((pnl, params))

    fine_results.sort(key=lambda x: -x[0])
    print(f"\nTop 20 fine-tuned parameter sets:")
    print(f"{'Rank':>4} {'PnL':>10} {'inv_pen':>8} {'margin':>7} {'flatten':>8} {'ema_a':>6} {'emr_ip':>7} {'skew':>5}")
    for i, (pnl, p) in enumerate(fine_results[:20]):
        print(f"{i+1:>4} {pnl:>10.2f} {p['inv_penalty']:>8.3f} {p['take_margin']:>7.3f} {p['flatten_thresh']:>8} {p['ema_alpha']:>6.3f} {p['emr_inv_penalty']:>7.2f} {p['make_skew']:>5.0f}")

    # Overall best
    all_results = results + fine_results
    all_results.sort(key=lambda x: -x[0])
    best_pnl, best_params = all_results[0]
    print(f"\n{'='*60}")
    print(f"BEST OVERALL: PnL={best_pnl}")
    print(f"Parameters: {json.dumps(best_params, indent=2)}")

    # Save results
    with open(os.path.join(ROOT, "sweep_v6_results.json"), "w") as f:
        json.dump({
            "best_pnl": best_pnl,
            "best_params": best_params,
            "top_20": [(pnl, p) for pnl, p in all_results[:20]],
        }, f, indent=2)
    print(f"\nResults saved to sweep_v6_results.json")


if __name__ == "__main__":
    main()
