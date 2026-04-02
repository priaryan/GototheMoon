#!/usr/bin/env python3
"""
plot_trades.py — Visualise backtest trades on top of order book data.

Usage:
  python3 plot_trades.py <run_dir>
  python3 plot_trades.py runs/backtest-XXXXXXXX

Generates one HTML file per product per day with:
  - Order-book levels (bid/ask shaded bands)
  - Wall mid (outer bid/ask midpoint)
  - Our trades (buy = green triangles, sell = red triangles)
  - Position subplot
  - Cumulative PnL subplot
"""

import csv
import os
import sys
from collections import defaultdict

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("Installing plotly...")
    os.system(f"{sys.executable} -m pip install plotly")
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")


def load_prices(day):
    path = os.path.join(DATA_DIR, f"prices_round_0_day_{day}.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            rows.append(r)
    return rows


def load_trades_csv(run_dir):
    path = os.path.join(run_dir, "trades.csv")
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def load_activity_csv(run_dir):
    path = os.path.join(run_dir, "activity.csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def plot_product_day(product, day, price_rows, our_trades, activity_rows, run_dir):
    """Create a multi-panel plot for one product on one day."""

    # Parse book data
    timestamps = []
    best_bids = []
    best_asks = []
    bid_walls = []
    ask_walls = []
    wall_mids = []
    mid_prices = []
    bid2s = []
    ask2s = []
    bid3s = []
    ask3s = []

    for r in price_rows:
        if r.get("product") != product:
            continue
        ts = int(r["timestamp"])
        timestamps.append(ts)

        b1 = float(r.get("bid_price_1", 0) or 0)
        a1 = float(r.get("ask_price_1", 0) or 0)
        b2 = float(r.get("bid_price_2", 0) or 0)
        a2 = float(r.get("ask_price_2", 0) or 0)
        b3 = float(r.get("bid_price_3", 0) or 0)
        a3 = float(r.get("ask_price_3", 0) or 0)

        best_bids.append(b1)
        best_asks.append(a1)
        bid2s.append(b2 if b2 else b1)
        ask2s.append(a2 if a2 else a1)
        bid3s.append(b3 if b3 else (b2 if b2 else b1))
        ask3s.append(a3 if a3 else (a2 if a2 else a1))

        # Wall = outermost level
        all_bids = [x for x in [b1, b2, b3] if x > 0]
        all_asks = [x for x in [a1, a2, a3] if x > 0]
        bw = min(all_bids) if all_bids else b1
        aw = max(all_asks) if all_asks else a1
        bid_walls.append(bw)
        ask_walls.append(aw)
        wall_mids.append((bw + aw) / 2 if bw and aw else 0)

        mp = float(r.get("mid_price", 0) or 0)
        mid_prices.append(mp if mp else (b1 + a1) / 2)

    if not timestamps:
        return

    # Parse our trades for this product & day
    buy_ts = []
    buy_px = []
    buy_sz = []
    sell_ts = []
    sell_px = []
    sell_sz = []

    for t in our_trades:
        if t["symbol"] != product or t["day"] != day:
            continue
        ts = int(t["timestamp"])
        px = float(t["price"])
        qty = int(t["quantity"])
        if qty > 0:
            buy_ts.append(ts)
            buy_px.append(px)
            buy_sz.append(abs(qty))
        else:
            sell_ts.append(ts)
            sell_px.append(px)
            sell_sz.append(abs(qty))

    # Parse activity for position & PnL
    act_ts = []
    act_pos = []
    act_pnl = []
    pnl_key = f"pnl_{product}"
    pos_key = f"pos_{product}"
    for a in activity_rows:
        if a.get("day") != day:
            continue
        ts = int(a["timestamp"])
        act_ts.append(ts)
        act_pos.append(int(float(a.get(pos_key, 0) or 0)))
        act_pnl.append(float(a.get(pnl_key, 0) or 0))

    # Build figure with 3 subplots
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.55, 0.2, 0.25],
        subplot_titles=[
            f"{product} Day {day} — Order Book & Trades",
            "Position",
            "Cumulative PnL",
        ],
    )

    # ── Subplot 1: Order book + trades ──

    # L3 band (lightest)
    fig.add_trace(go.Scatter(
        x=timestamps, y=ask3s, mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=timestamps, y=bid3s, mode="lines",
        line=dict(width=0), fill="tonexty",
        fillcolor="rgba(200,200,200,0.15)", name="L3 Spread",
        hoverinfo="skip",
    ), row=1, col=1)

    # L2 band
    fig.add_trace(go.Scatter(
        x=timestamps, y=ask2s, mode="lines",
        line=dict(width=0), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=timestamps, y=bid2s, mode="lines",
        line=dict(width=0), fill="tonexty",
        fillcolor="rgba(180,180,220,0.2)", name="L2 Spread",
        hoverinfo="skip",
    ), row=1, col=1)

    # Best bid/ask
    fig.add_trace(go.Scatter(
        x=timestamps, y=best_asks, mode="lines",
        line=dict(color="rgba(220,60,60,0.6)", width=1),
        name="Best Ask",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=timestamps, y=best_bids, mode="lines",
        line=dict(color="rgba(60,60,220,0.6)", width=1),
        name="Best Bid",
    ), row=1, col=1)

    # Wall mid
    fig.add_trace(go.Scatter(
        x=timestamps, y=wall_mids, mode="lines",
        line=dict(color="orange", width=1.5, dash="dot"),
        name="Wall Mid",
    ), row=1, col=1)

    # Our BUY trades
    if buy_ts:
        fig.add_trace(go.Scatter(
            x=buy_ts, y=buy_px, mode="markers",
            marker=dict(
                symbol="triangle-up", size=[6 + s * 2 for s in buy_sz],
                color="limegreen", line=dict(width=1, color="darkgreen"),
            ),
            name=f"BUY ({sum(buy_sz)} units)",
            text=[f"BUY {s}@{p}" for s, p in zip(buy_sz, buy_px)],
            hoverinfo="text+x",
        ), row=1, col=1)

    # Our SELL trades
    if sell_ts:
        fig.add_trace(go.Scatter(
            x=sell_ts, y=sell_px, mode="markers",
            marker=dict(
                symbol="triangle-down", size=[6 + s * 2 for s in sell_sz],
                color="red", line=dict(width=1, color="darkred"),
            ),
            name=f"SELL ({sum(sell_sz)} units)",
            text=[f"SELL {s}@{p}" for s, p in zip(sell_sz, sell_px)],
            hoverinfo="text+x",
        ), row=1, col=1)

    # ── Subplot 2: Position ──
    if act_ts:
        colors = ["green" if p > 0 else ("red" if p < 0 else "gray") for p in act_pos]
        fig.add_trace(go.Bar(
            x=act_ts, y=act_pos,
            marker_color=colors,
            name="Position",
            showlegend=False,
        ), row=2, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="gray", row=2, col=1)

    # ── Subplot 3: PnL ──
    if act_ts:
        pnl_colors = ["green" if p >= 0 else "red" for p in act_pnl]
        fig.add_trace(go.Scatter(
            x=act_ts, y=act_pnl, mode="lines",
            line=dict(color="blue", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(0,100,255,0.1)",
            name="PnL",
            showlegend=False,
        ), row=3, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1)

    # Layout
    fig.update_layout(
        height=900,
        width=1400,
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        title_text=f"Backtest: {product} Day {day}",
    )
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Pos", row=2, col=1)
    fig.update_yaxes(title_text="PnL", row=3, col=1)

    # Save
    out_path = os.path.join(run_dir, f"plot_{product}_day{day}.html")
    fig.write_html(out_path)
    print(f"  Saved: {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 plot_trades.py <run_dir>")
        print("  e.g.: python3 plot_trades.py runs/backtest-843dba11")
        sys.exit(1)

    run_dir = sys.argv[1]
    if not os.path.isabs(run_dir):
        run_dir = os.path.join(ROOT, run_dir)

    # Check required files exist
    trades_path = os.path.join(run_dir, "trades.csv")
    if not os.path.exists(trades_path):
        print(f"ERROR: {trades_path} not found.")
        print("Re-run backtester with --persist to generate trade data:")
        print(f"  python3 backtester.py --trader bestfornow_v6.py --persist")
        sys.exit(1)

    our_trades = load_trades_csv(run_dir)
    activity_rows = load_activity_csv(run_dir)

    # Discover days and products from trades
    days = sorted(set(t["day"] for t in our_trades))
    products = sorted(set(t["symbol"] for t in our_trades))

    if not days:
        print("No trades found in trades.csv")
        sys.exit(1)

    print(f"Plotting {len(products)} products × {len(days)} days...")

    for day in days:
        price_rows = load_prices(day)
        for product in products:
            print(f"  {product} day {day}...")
            plot_product_day(product, day, price_rows, our_trades, activity_rows, run_dir)

    print("\nDone! Open the HTML files in a browser.")


if __name__ == "__main__":
    main()
