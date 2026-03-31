#!/usr/bin/env python3
"""
IMC Prosperity 4 – Python Backtester
=====================================
Replicates the core logic of the Rust backtester at:
  https://github.com/GeyzsoN/prosperity_rust_backtester

Features replicated:
  - Reads prices_*.csv and trades_*.csv from data/raw/ (auto-pairs by day)
  - Simulates the order-book each tick and calls trader.run(state)
  - Matches trader orders against the book (price-priority, FIFO within level)
  - Tracks position per product, enforces position limits
  - Computes PnL mark-to-market using mid price
  - Supports multi-day runs, carry mode, and per-product PnL breakdown
  - Outputs a compact summary table matching the Rust CLI format
  - Writes metrics.json and activity.csv under runs/<backtest-id>/

Usage:
  python3 backtester.py                          # auto-detect trader & data
  python3 backtester.py --trader bestfornow.py   # specific trader file
  python3 backtester.py --day -1                  # single day
  python3 backtester.py --carry                   # carry state across days
  python3 backtester.py --persist                 # write full artifact set
"""

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ─── Datamodel (standalone, mirrors IMC Prosperity) ─────────────────

@dataclass
class Order:
    symbol: str
    price: int
    quantity: int  # positive = buy, negative = sell


@dataclass
class OrderDepth:
    buy_orders: Dict[int, int] = field(default_factory=dict)   # price → +qty
    sell_orders: Dict[int, int] = field(default_factory=dict)  # price → -qty


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


# ─── Position limits (default Prosperity 4 tutorial) ─────────────────

DEFAULT_POS_LIMITS: Dict[str, int] = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}

# ─── CSV loaders ──────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")
RUNS_DIR = os.path.join(ROOT, "runs")


def discover_days(data_dir: str) -> List[Tuple[str, str, Optional[str]]]:
    """Return sorted list of (day, prices_path, trades_path|None)."""
    import glob
    price_files = sorted(glob.glob(os.path.join(data_dir, "prices_round_*_day_*.csv")))
    result = []
    for pf in price_files:
        base = os.path.basename(pf)
        day = base.replace(".csv", "").split("_")[-1]
        tf = pf.replace("prices_", "trades_")
        result.append((day, pf, tf if os.path.exists(tf) else None))
    return result


def load_prices_csv(path: str) -> List[dict]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows


def load_trades_csv(path: str) -> List[dict]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows.append(r)
    return rows


# ─── Build order book from a prices row ───────────────────────────────

def build_order_depth(row: dict) -> OrderDepth:
    """Convert a single CSV row into an OrderDepth."""
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
            od.sell_orders[price] = od.sell_orders.get(price, 0) - vol  # negative
    return od


# ─── Order matching engine ─────────────────────────────────────────────

def match_orders(
    orders: List[Order],
    depth: OrderDepth,
    position: int,
    pos_limit: int,
) -> Tuple[List[Trade], int]:
    """
    Match trader orders against the order book.
    Returns (fills, new_position).
    Replicates the Rust backtester's sequential matching:
      - Buy orders matched against asks (ascending price)
      - Sell orders matched against bids (descending price)
    """
    fills: List[Trade] = []
    pos = position

    for order in orders:
        if order.quantity > 0:
            # BUY: match against sell_orders (asks)
            remaining = order.quantity
            available_room = pos_limit - pos
            if available_room <= 0:
                continue
            remaining = min(remaining, available_room)

            for ask_price in sorted(depth.sell_orders.keys()):
                if remaining <= 0:
                    break
                if order.price < ask_price:
                    break  # our bid too low
                ask_vol = abs(depth.sell_orders[ask_price])
                fill_qty = min(remaining, ask_vol)
                if fill_qty > 0:
                    fills.append(Trade(
                        symbol=order.symbol,
                        price=ask_price,
                        quantity=fill_qty,
                    ))
                    pos += fill_qty
                    remaining -= fill_qty
                    # Update book
                    depth.sell_orders[ask_price] += fill_qty  # less negative
                    if abs(depth.sell_orders[ask_price]) < 1:
                        del depth.sell_orders[ask_price]

        elif order.quantity < 0:
            # SELL: match against buy_orders (bids)
            remaining = abs(order.quantity)
            available_room = pos_limit + pos
            if available_room <= 0:
                continue
            remaining = min(remaining, available_room)

            for bid_price in sorted(depth.buy_orders.keys(), reverse=True):
                if remaining <= 0:
                    break
                if order.price > bid_price:
                    break  # our ask too high
                bid_vol = depth.buy_orders[bid_price]
                fill_qty = min(remaining, bid_vol)
                if fill_qty > 0:
                    fills.append(Trade(
                        symbol=order.symbol,
                        price=bid_price,
                        quantity=-fill_qty,
                    ))
                    pos -= fill_qty
                    remaining -= fill_qty
                    depth.buy_orders[bid_price] -= fill_qty
                    if depth.buy_orders[bid_price] <= 0:
                        del depth.buy_orders[bid_price]

    return fills, pos


# ─── Trader loader ──────────────────────────────────────────────────────

def load_trader(path: str):
    """Dynamically load a trader module and return a Trader instance."""
    # Inject our datamodel into sys.modules so "from datamodel import ..." works
    dm_module = type(sys)("datamodel")
    dm_module.Order = Order
    dm_module.OrderDepth = OrderDepth
    dm_module.TradingState = TradingState
    dm_module.Trade = Trade
    sys.modules["datamodel"] = dm_module

    spec = importlib.util.spec_from_file_location("trader_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "Trader"):
        raise RuntimeError(f"No 'Trader' class found in {path}")
    return mod.Trader()


def auto_find_trader() -> str:
    """Find the best candidate trader file in the repo."""
    candidates = [
        "submission_edit.py",
        "bestfornow.py",
        "submission.py",
    ]
    for c in candidates:
        p = os.path.join(ROOT, c)
        if os.path.isfile(p):
            return p
    # Fallback: any .py with 'class Trader'
    import glob
    for f in glob.glob(os.path.join(ROOT, "*.py")):
        try:
            with open(f) as fh:
                if "class Trader" in fh.read():
                    return f
        except Exception:
            pass
    raise FileNotFoundError("No trader file found")


# ─── Single-day backtest ────────────────────────────────────────────────

@dataclass
class DayResult:
    day: str
    ticks: int
    own_trades: int
    final_pnl: float
    pnl_by_product: Dict[str, float]
    activity: List[dict]


def run_day(
    trader,
    day: str,
    prices_rows: List[dict],
    market_trades_rows: List[dict],
    pos_limits: Dict[str, int],
    initial_position: Optional[Dict[str, int]] = None,
    initial_trader_data: str = "",
    prior_own_trades: Optional[Dict[str, List[Trade]]] = None,
    prior_market_trades: Optional[Dict[str, List[Trade]]] = None,
) -> Tuple[DayResult, Dict[str, int], str, Dict[str, List[Trade]], Dict[str, List[Trade]]]:
    """
    Run one day of backtesting.
    Returns (result, final_positions, trader_data, own_trades, market_trades).
    """
    # Group price rows by timestamp
    ts_data: Dict[int, Dict[str, dict]] = defaultdict(dict)
    for row in prices_rows:
        if row.get("product"):
            ts = int(row["timestamp"])
            ts_data[ts][row["product"]] = row

    # Group market trades by timestamp
    ts_market_trades: Dict[int, List[dict]] = defaultdict(list)
    for row in market_trades_rows:
        if row.get("symbol"):
            ts = int(row["timestamp"])
            ts_market_trades[ts].append(row)

    timestamps = sorted(ts_data.keys())
    position = dict(initial_position) if initial_position else {}
    trader_data = initial_trader_data
    own_trades_accum: Dict[str, List[Trade]] = defaultdict(list)
    if prior_own_trades:
        for k, v in prior_own_trades.items():
            own_trades_accum[k] = list(v)
    market_trades_accum: Dict[str, List[Trade]] = defaultdict(list)
    if prior_market_trades:
        for k, v in prior_market_trades.items():
            market_trades_accum[k] = list(v)

    all_fills: List[Trade] = []
    pnl_by_product: Dict[str, float] = defaultdict(float)
    activity: List[dict] = []

    # Track cash flow per product for PnL computation
    cash_flow: Dict[str, float] = defaultdict(float)

    last_mid: Dict[str, float] = {}

    for ts in timestamps:
        products_at_ts = ts_data[ts]

        # Build order depths
        order_depths: Dict[str, OrderDepth] = {}
        for product, row in products_at_ts.items():
            order_depths[product] = build_order_depth(row)
            if row.get("mid_price") and row["mid_price"] != "":
                last_mid[product] = float(row["mid_price"])

        # Collect market trades for this tick
        tick_market_trades: Dict[str, List[Trade]] = defaultdict(list)
        for tr_row in ts_market_trades.get(ts, []):
            t = Trade(
                symbol=tr_row["symbol"],
                price=float(tr_row["price"]),
                quantity=int(tr_row["quantity"]),
                buyer=tr_row.get("buyer", ""),
                seller=tr_row.get("seller", ""),
                timestamp=ts,
            )
            tick_market_trades[t.symbol].append(t)
            market_trades_accum[t.symbol].append(t)

        # Build TradingState
        # own_trades: only trades from the previous tick
        prev_own_trades: Dict[str, List[Trade]] = defaultdict(list)
        for fill in all_fills:
            if fill.timestamp == ts - 100:  # previous tick
                prev_own_trades[fill.symbol].append(fill)

        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings={},
            order_depths=order_depths,
            own_trades=dict(prev_own_trades),
            market_trades=dict(tick_market_trades),
            position=dict(position),
            observations=None,
        )

        # Call trader
        try:
            result = trader.run(state)
            if len(result) == 3:
                orders_dict, conversions, trader_data = result
            else:
                orders_dict = result[0]
                trader_data = ""
        except Exception as e:
            print(f"  [WARN] Trader error at ts={ts}: {e}")
            orders_dict = {}
            trader_data = ""

        # Match orders for each product
        tick_fills: List[Trade] = []
        for product, order_list in orders_dict.items():
            if product not in order_depths:
                continue
            limit = pos_limits.get(product, 20)
            pos = position.get(product, 0)
            fills, new_pos = match_orders(order_list, order_depths[product], pos, limit)
            for f in fills:
                f.timestamp = ts
            tick_fills.extend(fills)
            position[product] = new_pos
            own_trades_accum[product].extend(fills)

        all_fills.extend(tick_fills)

        # Update cash flow
        for f in tick_fills:
            # Buy: we pay price * qty (negative cash), Sell: we receive
            cash_flow[f.symbol] -= f.price * f.quantity  # qty negative for sells → double neg = positive

        # Compute mark-to-market PnL
        for product in set(list(cash_flow.keys()) + list(position.keys())):
            mid = last_mid.get(product, 0)
            pos_val = position.get(product, 0) * mid
            pnl_by_product[product] = cash_flow.get(product, 0) + pos_val

        # Record activity
        activity.append({
            "timestamp": ts,
            "positions": dict(position),
            "pnl": dict(pnl_by_product),
            "fills": len(tick_fills),
        })

    final_pnl = sum(pnl_by_product.values())
    result = DayResult(
        day=day,
        ticks=len(timestamps),
        own_trades=len(all_fills),
        final_pnl=round(final_pnl, 2),
        pnl_by_product={k: round(v, 2) for k, v in pnl_by_product.items()},
        activity=activity,
    )
    return result, position, trader_data, dict(own_trades_accum), dict(market_trades_accum)


# ─── Output formatting ─────────────────────────────────────────────────

def print_summary(trader_name: str, dataset_name: str, results: List[DayResult], carry: bool):
    print()
    print(f"trader:   {trader_name}")
    print(f"dataset:  {dataset_name}")
    print(f"mode:     fast")
    if carry:
        print(f"carry:    on")
    print()

    header = f"{'SET':<12} {'DAY':>6} {'TICKS':>7} {'OWN_TRADES':>11} {'FINAL_PNL':>12}"
    print(header)
    print("-" * len(header))

    for r in results:
        label = f"D{r.day}"
        print(f"{label:<12} {r.day:>6} {r.ticks:>7} {r.own_trades:>11} {r.final_pnl:>12.2f}")

    # Product breakdown
    all_products = set()
    for r in results:
        all_products.update(r.pnl_by_product.keys())
    all_products = sorted(all_products)

    if all_products:
        print()
        col_w = 12
        header_parts = [f"{'PRODUCT':<16}"]
        for r in results:
            header_parts.append(f"{'D'+r.day:>{col_w}}")
        print("".join(header_parts))
        print("-" * (16 + col_w * len(results)))

        for prod in all_products:
            parts = [f"{prod:<16}"]
            for r in results:
                val = r.pnl_by_product.get(prod, 0)
                parts.append(f"{val:>{col_w}.2f}")
            print("".join(parts))

    print()


def write_artifacts(backtest_id: str, results: List[DayResult], persist: bool):
    run_dir = os.path.join(RUNS_DIR, backtest_id)
    os.makedirs(run_dir, exist_ok=True)

    # Always write metrics.json
    metrics = {
        "backtest_id": backtest_id,
        "days": [],
    }
    for r in results:
        metrics["days"].append({
            "day": r.day,
            "ticks": r.ticks,
            "own_trades": r.own_trades,
            "final_pnl": r.final_pnl,
            "pnl_by_product": r.pnl_by_product,
        })
    with open(os.path.join(run_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    if persist:
        # Write activity.csv
        all_activity = []
        for r in results:
            for a in r.activity:
                row = {"day": r.day, "timestamp": a["timestamp"], "fills": a["fills"]}
                for prod, pos in a["positions"].items():
                    row[f"pos_{prod}"] = pos
                for prod, pnl in a["pnl"].items():
                    row[f"pnl_{prod}"] = pnl
                all_activity.append(row)

        if all_activity:
            fieldnames = sorted(all_activity[0].keys())
            with open(os.path.join(run_dir, "activity.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in all_activity:
                    writer.writerow(row)

        # Write pnl_by_product.csv
        all_products = set()
        for r in results:
            all_products.update(r.pnl_by_product.keys())
        all_products = sorted(all_products)
        with open(os.path.join(run_dir, "pnl_by_product.csv"), "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["day"] + all_products)
            for r in results:
                row = [r.day] + [r.pnl_by_product.get(p, 0) for p in all_products]
                writer.writerow(row)

    print(f"Artifacts written to: {run_dir}")


# ─── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="IMC Prosperity 4 Python Backtester")
    parser.add_argument("--trader", type=str, default=None,
                        help="Path to trader .py file (auto-detected if omitted)")
    parser.add_argument("--data-dir", type=str, default=DATA_DIR,
                        help="Directory containing prices/trades CSVs")
    parser.add_argument("--day", type=str, default=None,
                        help="Run only this day (e.g. -1)")
    parser.add_argument("--carry", action="store_true",
                        help="Carry positions & state across days")
    parser.add_argument("--persist", action="store_true",
                        help="Write full artifact set (activity.csv, pnl_by_product.csv)")
    args = parser.parse_args()

    # Find trader
    if args.trader:
        trader_path = os.path.abspath(args.trader)
    else:
        trader_path = auto_find_trader()
    trader_name = os.path.basename(trader_path)

    print(f"Loading trader: {trader_name}")
    trader = load_trader(trader_path)

    # Discover data
    days = discover_days(args.data_dir)
    if not days:
        print(f"ERROR: No price CSV files found in {args.data_dir}")
        sys.exit(1)

    if args.day:
        days = [(d, p, t) for d, p, t in days if d == args.day]
        if not days:
            print(f"ERROR: Day {args.day} not found")
            sys.exit(1)

    # Detect products and their limits from first file
    first_prices = load_prices_csv(days[0][1])
    products = set()
    for row in first_prices:
        if row.get("product"):
            products.add(row["product"])
    pos_limits = {}
    for p in products:
        pos_limits[p] = DEFAULT_POS_LIMITS.get(p, 20)

    # Run backtest
    t0 = time.time()
    results: List[DayResult] = []
    position = None
    trader_data = ""
    own_trades = None
    market_trades = None

    for day, prices_path, trades_path in days:
        prices_rows = load_prices_csv(prices_path)
        market_trades_rows = load_trades_csv(trades_path) if trades_path else []

        # Filter to this day
        day_prices = [r for r in prices_rows if r.get("day") == day]
        if not day_prices:
            day_prices = prices_rows  # file may not have day column consistently

        day_market_trades = [r for r in market_trades_rows]

        init_pos = position if (args.carry and position) else None
        init_td = trader_data if args.carry else ""
        init_own = own_trades if (args.carry and own_trades) else None
        init_mkt = market_trades if (args.carry and market_trades) else None

        result, position, trader_data, own_trades, market_trades = run_day(
            trader, day, day_prices, day_market_trades, pos_limits,
            initial_position=init_pos,
            initial_trader_data=init_td,
            prior_own_trades=init_own,
            prior_market_trades=init_mkt,
        )
        results.append(result)

    elapsed = time.time() - t0

    # Output
    dataset_name = os.path.basename(args.data_dir) if args.data_dir != DATA_DIR else "tutorial"
    print_summary(trader_name, dataset_name, results, args.carry)
    print(f"Elapsed: {elapsed:.2f}s")

    # Write artifacts
    backtest_id = f"backtest-{uuid.uuid4().hex[:8]}"
    write_artifacts(backtest_id, results, args.persist)


if __name__ == "__main__":
    main()
