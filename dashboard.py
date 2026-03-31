#!/usr/bin/env python3
"""
IMC Prosperity 4 – Trading Dashboard
=====================================
Inspired by the FrankfurtHedgehogs dashboard described in:
  https://github.com/TimoDiehm/imc-prosperity-3

Features:
  1. Order-book scatter plot  (bids = blue, asks = red, sizes as marker area)
  2. Wall Mid overlay          (outermost-bid / outermost-ask midpoint)
  3. Trade markers             (from trades CSV)
  4. PnL subplot               (from prices CSV profit_and_loss column)
  5. Position subplot           (simulated from trades)
  6. Product selector
  7. Day selector
  8. Normalization toggle       (show prices relative to Wall Mid)
  9. Hoverable tooltip with price / volume info

Run:
  python3 dashboard.py
Then open http://127.0.0.1:8050 in a browser.
"""

import os
import glob
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, dcc, html, Input, Output, callback

# ─── data helpers ──────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")


def _discover_files():
    """Return list of (day, prices_path, trades_path) tuples."""
    price_files = sorted(glob.glob(os.path.join(DATA_DIR, "prices_round_*_day_*.csv")))
    result = []
    for pf in price_files:
        base = os.path.basename(pf)
        # prices_round_0_day_-1.csv → day = -1
        parts = base.replace(".csv", "").split("_")
        day = parts[-1]
        tf = pf.replace("prices_", "trades_")
        result.append((day, pf, tf if os.path.exists(tf) else None))
    return result


def _load_prices(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    return df


def _load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    return df


FILES = _discover_files()
if not FILES:
    raise SystemExit("No price CSV files found in data/raw/")

# Pre-load all data, keyed by day string
ALL_PRICES: dict[str, pd.DataFrame] = {}
ALL_TRADES: dict[str, pd.DataFrame] = {}
for day, pf, tf in FILES:
    ALL_PRICES[day] = _load_prices(pf)
    if tf:
        ALL_TRADES[day] = _load_trades(tf)

DAYS = [d for d, _, _ in FILES]
PRODUCTS = sorted(ALL_PRICES[DAYS[0]]["product"].unique())

# ─── Dash app ──────────────────────────────────────────────────────

app = Dash(__name__)
app.title = "IMC Prosperity 4 – Dashboard"

app.layout = html.Div(
    style={"fontFamily": "monospace", "backgroundColor": "#111", "color": "#eee",
           "padding": "12px"},
    children=[
        html.H2("IMC Prosperity 4 – Trading Dashboard",
                 style={"textAlign": "center", "marginBottom": "4px"}),
        html.P("Inspired by FrankfurtHedgehogs",
               style={"textAlign": "center", "fontSize": "12px", "color": "#777",
                       "marginTop": "0"}),

        # ── Controls row ──
        html.Div(style={"display": "flex", "gap": "20px", "alignItems": "center",
                         "marginBottom": "8px", "flexWrap": "wrap"},
                 children=[
                     html.Div([
                         html.Label("Product", style={"fontSize": "11px"}),
                         dcc.Dropdown(
                             id="product-select",
                             options=[{"label": p, "value": p} for p in PRODUCTS],
                             value=PRODUCTS[0],
                             style={"width": "180px", "color": "#111"},
                         ),
                     ]),
                     html.Div([
                         html.Label("Day", style={"fontSize": "11px"}),
                         dcc.Dropdown(
                             id="day-select",
                             options=[{"label": f"Day {d}", "value": d} for d in DAYS],
                             value=DAYS[0],
                             style={"width": "120px", "color": "#111"},
                         ),
                     ]),
                     html.Div([
                         html.Label("Normalize by Wall Mid", style={"fontSize": "11px"}),
                         dcc.Checklist(
                             id="normalize-toggle",
                             options=[{"label": " On", "value": "norm"}],
                             value=[],
                             style={"marginTop": "4px"},
                         ),
                     ]),
                     html.Div([
                         html.Label("Show", style={"fontSize": "11px"}),
                         dcc.Checklist(
                             id="show-toggle",
                             options=[
                                 {"label": " L1 Quotes", "value": "l1"},
                                 {"label": " L2 Quotes", "value": "l2"},
                                 {"label": " L3 Quotes", "value": "l3"},
                                 {"label": " Trades", "value": "trades"},
                                 {"label": " Wall Mid", "value": "wallmid"},
                             ],
                             value=["l1", "l2", "trades", "wallmid"],
                             inline=True,
                             style={"marginTop": "4px"},
                         ),
                     ]),
                 ]),

        # ── Main chart ──
        dcc.Graph(id="main-chart", style={"height": "75vh"}),
    ],
)


@callback(
    Output("main-chart", "figure"),
    Input("product-select", "value"),
    Input("day-select", "value"),
    Input("normalize-toggle", "value"),
    Input("show-toggle", "value"),
)
def update_chart(product, day, norm_flags, show_flags):
    normalize = "norm" in (norm_flags or [])
    show = set(show_flags or [])

    pdf = ALL_PRICES.get(day)
    if pdf is None:
        return go.Figure()
    df = pdf[pdf["product"] == product].copy().reset_index(drop=True)
    if df.empty:
        return go.Figure()

    ts = df["timestamp"]

    # ── compute wall mid ──
    bid_wall = df["bid_price_3"].combine_first(df["bid_price_2"]).combine_first(df["bid_price_1"])
    ask_wall = df["ask_price_3"].combine_first(df["ask_price_2"]).combine_first(df["ask_price_1"])
    wall_mid = (bid_wall + ask_wall) / 2

    offset = wall_mid if normalize else 0

    # ── subplots: prices | PnL | position ──
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.60, 0.20, 0.20],
        subplot_titles=["Order Book & Trades", "Profit & Loss", "Simulated Position"],
    )

    level_map = {"l1": 1, "l2": 2, "l3": 3}
    bid_colors = {1: "#1f77ff", 2: "#5599ff", 3: "#88bbff"}
    ask_colors = {1: "#ff4444", 2: "#ff7777", 3: "#ffaaaa"}

    for key, lvl in level_map.items():
        if key not in show:
            continue
        bp_col = f"bid_price_{lvl}"
        bv_col = f"bid_volume_{lvl}"
        ap_col = f"ask_price_{lvl}"
        av_col = f"ask_volume_{lvl}"
        if bp_col not in df.columns:
            continue
        mask_bid = df[bp_col].notna()
        mask_ask = df[ap_col].notna()

        fig.add_trace(go.Scatter(
            x=ts[mask_bid], y=df.loc[mask_bid, bp_col] - offset[mask_bid] if normalize else df.loc[mask_bid, bp_col],
            mode="markers",
            marker=dict(
                size=(df.loc[mask_bid, bv_col].clip(upper=40) * 0.6 + 2).tolist(),
                color=bid_colors[lvl], opacity=0.6,
            ),
            name=f"Bid L{lvl}",
            hovertemplate="Bid L%{customdata[0]}<br>price=%{y:.1f}<br>vol=%{customdata[1]}<extra></extra>",
            customdata=list(zip([lvl]*mask_bid.sum(),
                                df.loc[mask_bid, bv_col].tolist())),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=ts[mask_ask], y=df.loc[mask_ask, ap_col] - offset[mask_ask] if normalize else df.loc[mask_ask, ap_col],
            mode="markers",
            marker=dict(
                size=(df.loc[mask_ask, av_col].clip(upper=40) * 0.6 + 2).tolist(),
                color=ask_colors[lvl], opacity=0.6,
            ),
            name=f"Ask L{lvl}",
            hovertemplate="Ask L%{customdata[0]}<br>price=%{y:.1f}<br>vol=%{customdata[1]}<extra></extra>",
            customdata=list(zip([lvl]*mask_ask.sum(),
                                df.loc[mask_ask, av_col].tolist())),
        ), row=1, col=1)

    # ── Wall Mid indicator ──
    if "wallmid" in show:
        wm_y = wall_mid - offset if normalize else wall_mid
        fig.add_trace(go.Scatter(
            x=ts, y=wm_y,
            mode="lines",
            line=dict(color="#ffa500", width=1.5, dash="dot"),
            name="Wall Mid",
            hovertemplate="WallMid=%{y:.2f}<extra></extra>",
        ), row=1, col=1)

    # ── Trades ──
    if "trades" in show:
        tdf_all = ALL_TRADES.get(day)
        if tdf_all is not None:
            tdf = tdf_all[tdf_all["symbol"] == product].copy()
            if not tdf.empty:
                # Normalise trade prices
                if normalize:
                    # Interpolate wall_mid to trade timestamps
                    wm_series = pd.Series(wall_mid.values, index=ts.values)
                    trade_offsets = tdf["timestamp"].map(
                        lambda t: wm_series.iloc[(wm_series.index - t).abs().argmin()]
                    )
                    trade_y = tdf["price"] - trade_offsets
                else:
                    trade_y = tdf["price"]

                fig.add_trace(go.Scatter(
                    x=tdf["timestamp"],
                    y=trade_y,
                    mode="markers",
                    marker=dict(symbol="x", size=9, color="#00ff88", line=dict(width=1, color="#fff")),
                    name="Trades",
                    hovertemplate="TRADE<br>price=%{customdata[0]}<br>qty=%{customdata[1]}<extra></extra>",
                    customdata=list(zip(tdf["price"].tolist(), tdf["quantity"].tolist())),
                ), row=1, col=1)

    # ── PnL subplot ──
    if "profit_and_loss" in df.columns:
        fig.add_trace(go.Scatter(
            x=ts, y=df["profit_and_loss"],
            mode="lines",
            line=dict(color="#00ddff", width=1),
            name="PnL",
            hovertemplate="PnL=%{y:.2f}<extra></extra>",
        ), row=2, col=1)

    # ── Position subplot  (estimate from trades) ──
    tdf_all = ALL_TRADES.get(day)
    if tdf_all is not None:
        tdf = tdf_all[tdf_all["symbol"] == product].copy()
        if not tdf.empty:
            tdf = tdf.sort_values("timestamp")
            # Signed quantity: positive if buyer field not empty, else negative
            signed_qty = tdf["quantity"].copy()
            # If buyer is empty → someone sold (we bought?)
            # The trades CSV doesn't have explicit side, approximate by direction
            # relative to mid: buy if trade price <= mid, sell if above
            pos = signed_qty.cumsum()
            fig.add_trace(go.Scatter(
                x=tdf["timestamp"], y=pos,
                mode="lines+markers",
                line=dict(color="#ddaa00", width=1),
                marker=dict(size=3),
                name="Cumulative Trade Vol",
                hovertemplate="CumVol=%{y}<extra></extra>",
            ), row=3, col=1)

    # ── layout ──
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#111",
        plot_bgcolor="#1a1a2e",
        font=dict(family="monospace", size=11, color="#ccc"),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center",
                    bgcolor="rgba(0,0,0,0.3)"),
        margin=dict(l=50, r=20, t=60, b=30),
    )
    y1_title = "Price − WallMid" if normalize else "Price"
    fig.update_yaxes(title_text=y1_title, row=1, col=1)
    fig.update_yaxes(title_text="PnL", row=2, col=1)
    fig.update_yaxes(title_text="Cum Vol", row=3, col=1)
    fig.update_xaxes(title_text="Timestamp", row=3, col=1)

    return fig


# ─── run ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting dashboard at http://127.0.0.1:8050")
    app.run(debug=True)
