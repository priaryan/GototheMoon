import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


FILES = [
    "data/raw/prices_round_0_day_-2.csv",
    "data/raw/prices_round_0_day_-1.csv",
]

PRODUCT = "TOMATOES"

# horizons to test
RETURN_HORIZONS = [1, 5, 10, 20]
FILL_HORIZON = 5
ROLLING_WINDOW = 200


def load_data(files):
    dfs = []
    for file in files:
        if not os.path.exists(file):
            raise FileNotFoundError(f"Could not find file: {file}")
        df = pd.read_csv(file, sep=";")
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def pick_wall_price(row, side):
    prices = [row.get(f"{side}_price_1"), row.get(f"{side}_price_2"), row.get(f"{side}_price_3")]
    volumes = [row.get(f"{side}_volume_1"), row.get(f"{side}_volume_2"), row.get(f"{side}_volume_3")]

    candidates = []
    for p, v in zip(prices, volumes):
        if pd.notna(p) and pd.notna(v):
            candidates.append((p, abs(v)))

    if not candidates:
        return np.nan

    wall_price, _ = max(candidates, key=lambda x: x[1])
    return wall_price


def build_frame(data):
    df = data[data["product"] == PRODUCT].copy()
    df = df.sort_values(["day", "timestamp"]).reset_index(drop=True)

    day_order = {day: i for i, day in enumerate(sorted(df["day"].unique()))}
    max_ts = df["timestamp"].max()
    df["time_index"] = df["day"].map(day_order) * (max_ts + 100) + df["timestamp"]

    df["best_bid"] = df["bid_price_1"]
    df["best_ask"] = df["ask_price_1"]
    df["spread"] = df["best_ask"] - df["best_bid"]
    df["mid_price_calc"] = (df["best_bid"] + df["best_ask"]) / 2.0

    if "mid_price" not in df.columns:
        df["mid_price"] = df["mid_price_calc"]

    df["bid_wall"] = df.apply(lambda row: pick_wall_price(row, "bid"), axis=1)
    df["ask_wall"] = df.apply(lambda row: pick_wall_price(row, "ask"), axis=1)
    df["wall_mid"] = (df["bid_wall"] + df["ask_wall"]) / 2.0

    df["mid_vs_wall_norm"] = (df["mid_price"] - df["wall_mid"]) / df["wall_mid"]
    df["mid_vs_wall_roll_mean"] = df["mid_vs_wall_norm"].rolling(ROLLING_WINDOW).mean()

    return df


def check_reversion(df):
    dev = df["mid_vs_wall_norm"]
    future_change = dev.shift(-1) - dev

    valid = pd.DataFrame({
        "dev": dev,
        "future_change": future_change
    }).dropna()

    corr = valid["dev"].corr(valid["future_change"])

    print("\n" + "=" * 80)
    print("1. REVERSION CHECK")
    print("=" * 80)
    print(f"Reversion correlation: {corr:.6f}")

    if corr < -0.2:
        print("Conclusion: strong mean reversion")
    elif corr < -0.05:
        print("Conclusion: weak to moderate mean reversion")
    elif corr < 0.05:
        print("Conclusion: little to no reversion edge")
    else:
        print("Conclusion: more momentum like than mean reverting")

    return corr


def bucket_future_returns(df, horizons=RETURN_HORIZONS, n_buckets=10):
    print("\n" + "=" * 80)
    print("2. FUTURE RETURNS BY DEVIATION BUCKET")
    print("=" * 80)

    work = df[["mid_price", "mid_vs_wall_norm"]].copy().dropna()

    try:
        work["bucket"] = pd.qcut(work["mid_vs_wall_norm"], q=n_buckets, duplicates="drop")
    except ValueError:
        print("Not enough unique values for qcut")
        return

    for h in horizons:
        work[f"future_mid_{h}"] = work["mid_price"].shift(-h)
        work[f"future_return_{h}"] = (work[f"future_mid_{h}"] - work["mid_price"]) / work["mid_price"]

        grouped = work.groupby("bucket", observed=False)[f"future_return_{h}"].mean()

        print(f"\nHorizon = {h}")
        print(grouped)

        plt.figure(figsize=(10, 5))
        grouped.plot(kind="bar")
        plt.title(f"TOMATOES Future Return by Deviation Bucket, horizon={h}")
        plt.xlabel("Deviation bucket")
        plt.ylabel("Average future return")
        plt.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        plt.show()


def wall_stability(df):
    work = df.copy()
    work["bid_wall_change"] = work["bid_wall"].diff().abs()
    work["ask_wall_change"] = work["ask_wall"].diff().abs()

    bid_change_pct = (work["bid_wall_change"] > 0).mean()
    ask_change_pct = (work["ask_wall_change"] > 0).mean()

    print("\n" + "=" * 80)
    print("3. WALL STABILITY")
    print("=" * 80)
    print(f"Average bid wall change: {work['bid_wall_change'].mean():.6f}")
    print(f"Average ask wall change: {work['ask_wall_change'].mean():.6f}")
    print(f"Bid wall changes on {100 * bid_change_pct:.2f}% of timesteps")
    print(f"Ask wall changes on {100 * ask_change_pct:.2f}% of timesteps")

    plt.figure(figsize=(12, 5))
    plt.plot(work["time_index"], work["bid_wall"], label="Bid wall", linewidth=0.8)
    plt.plot(work["time_index"], work["ask_wall"], label="Ask wall", linewidth=0.8)
    plt.title("TOMATOES Wall Prices Over Time")
    plt.xlabel("Time")
    plt.ylabel("Price")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def fill_probability(df, horizon=FILL_HORIZON):
    work = df.copy()

    future_min_ask = work["best_ask"].shift(-1).rolling(horizon).min()
    future_max_bid = work["best_bid"].shift(-1).rolling(horizon).max()

    work["would_bid_fill_at_best_bid"] = work["best_bid"] >= future_min_ask
    work["would_ask_fill_at_best_ask"] = work["best_ask"] <= future_max_bid

    bid_fill_rate = work["would_bid_fill_at_best_bid"].mean()
    ask_fill_rate = work["would_ask_fill_at_best_ask"].mean()

    print("\n" + "=" * 80)
    print("4. PASSIVE FILL PROXY")
    print("=" * 80)
    print(f"Fill horizon: {horizon}")
    print(f"Bid fill rate at current best bid: {bid_fill_rate:.6f}")
    print(f"Ask fill rate at current best ask: {ask_fill_rate:.6f}")

    return bid_fill_rate, ask_fill_rate


def adverse_selection(df, horizon=FILL_HORIZON):
    work = df.copy()
    work["future_mid"] = work["mid_price"].shift(-horizon)

    work["buy_pnl_from_best_bid_fill"] = work["future_mid"] - work["best_bid"]
    work["sell_pnl_from_best_ask_fill"] = work["best_ask"] - work["future_mid"]

    print("\n" + "=" * 80)
    print("5. ADVERSE SELECTION CHECK")
    print("=" * 80)
    print(f"Horizon: {horizon}")
    print(f"Average buy side PnL after fill proxy: {work['buy_pnl_from_best_bid_fill'].mean():.6f}")
    print(f"Average sell side PnL after fill proxy: {work['sell_pnl_from_best_ask_fill'].mean():.6f}")

    plt.figure(figsize=(10, 5))
    plt.hist(work["buy_pnl_from_best_bid_fill"].dropna(), bins=60, alpha=0.6, label="Buy side PnL")
    plt.hist(work["sell_pnl_from_best_ask_fill"].dropna(), bins=60, alpha=0.6, label="Sell side PnL")
    plt.title("TOMATOES Passive Fill Proxy PnL Distribution")
    plt.xlabel("PnL versus future mid")
    plt.ylabel("Frequency")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def basic_market_summary(df):
    print("\n" + "=" * 80)
    print("MARKET SUMMARY")
    print("=" * 80)
    print(f"Rows: {len(df)}")
    print(f"Days: {sorted(df['day'].unique().tolist())}")

    print("\nSpread distribution:")
    print(df["spread"].value_counts().sort_index())

    print("\nNormalized deviation stats:")
    print(df["mid_vs_wall_norm"].describe())

    print("\nMean absolute normalized deviation:")
    print(df["mid_vs_wall_norm"].abs().mean())

    print("\nMid price versus wall mid correlation:")
    valid = df[["mid_price", "wall_mid"]].dropna()
    print(valid["mid_price"].corr(valid["wall_mid"]))


def plot_deviation(df):
    plot_df = df.iloc[::10].copy()

    plt.figure(figsize=(14, 6))
    plt.plot(
        plot_df["time_index"],
        plot_df["mid_vs_wall_norm"],
        linewidth=0.6,
        alpha=0.35,
        label="Normalized deviation"
    )
    plt.plot(
        df["time_index"],
        df["mid_vs_wall_roll_mean"],
        linewidth=2.0,
        label=f"Rolling mean {ROLLING_WINDOW}"
    )
    plt.axhline(0.0, linewidth=1.0, linestyle="--")
    plt.title("TOMATOES Normalized Deviation from Wall Mid")
    plt.xlabel("Time")
    plt.ylabel("(Mid Price - Wall Mid) / Wall Mid")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def plot_spread(df):
    spread_counts = df["spread"].value_counts().sort_index()

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    axes[0].step(df.iloc[::10]["time_index"], df.iloc[::10]["spread"], where="mid", linewidth=0.8)
    axes[0].set_title("TOMATOES Spread Over Time")
    axes[0].set_xlabel("Time")
    axes[0].set_ylabel("Spread")
    axes[0].grid(True, alpha=0.3)

    axes[1].bar(spread_counts.index.astype(str), spread_counts.values)
    axes[1].set_title("TOMATOES Spread Distribution")
    axes[1].set_xlabel("Spread")
    axes[1].set_ylabel("Count")
    axes[1].grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.show()


def main():
    data = load_data(FILES)
    df = build_frame(data)

    basic_market_summary(df)
    plot_spread(df)
    plot_deviation(df)

    check_reversion(df)
    bucket_future_returns(df)
    wall_stability(df)
    fill_probability(df)
    adverse_selection(df)

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print("Send me the printed outputs, especially these:")
    print("1. Reversion correlation")
    print("2. Future return by bucket tables")
    print("3. Wall stability numbers")
    print("4. Fill rates")
    print("5. Adverse selection averages")


if __name__ == "__main__":
    main()