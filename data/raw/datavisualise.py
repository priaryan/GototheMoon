import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


FILES = [
    "data/raw/prices_round_0_day_-2.csv",
    "data/raw/prices_round_0_day_-1.csv",
]

PRODUCT = "TOMATOES"
ROLLING_WINDOW = 200
DOWNSAMPLE = 10


def load_data(files):
    dfs = []
    for file in files:
        df = pd.read_csv(file, sep=";")
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def pick_wall_price(row, side):
    prices = [row.get(f"{side}_price_1"), row.get(f"{side}_price_2"), row.get(f"{side}_price_3")]
    volumes = [row.get(f"{side}_volume_1"), row.get(f"{side}_volume_2"), row.get(f"{side}_volume_3")]

    candidates = []
    for p, v in zip(prices, volumes):
        if pd.notna(p) and pd.notna(v):
            candidates.append((p, v))

    if not candidates:
        return np.nan

    wall_price, _ = max(candidates, key=lambda x: abs(x[1]))
    return wall_price


def build_tomatoes_frame(data):
    df = data[data["product"] == PRODUCT].copy()
    df = df.sort_values(["day", "timestamp"]).reset_index(drop=True)

    day_order = {day: i for i, day in enumerate(sorted(df["day"].unique()))}
    max_ts = df["timestamp"].max()
    df["time_index"] = df["day"].map(day_order) * (max_ts + 100) + df["timestamp"]

    df["best_bid"] = df["bid_price_1"]
    df["best_ask"] = df["ask_price_1"]
    df["spread"] = df["best_ask"] - df["best_bid"]

    df["bid_wall"] = df.apply(lambda row: pick_wall_price(row, "bid"), axis=1)
    df["ask_wall"] = df.apply(lambda row: pick_wall_price(row, "ask"), axis=1)
    df["wall_mid"] = (df["bid_wall"] + df["ask_wall"]) / 2.0

    df["mid_vs_wall_norm"] = (df["mid_price"] - df["wall_mid"]) / df["wall_mid"]
    df["mid_vs_wall_roll"] = df["mid_vs_wall_norm"].rolling(ROLLING_WINDOW).mean()

    return df


def plot_clear_spread(df):
    plot_df = df.iloc[::DOWNSAMPLE].copy()

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    axes[0].step(plot_df["time_index"], plot_df["spread"], where="mid", linewidth=0.8)
    axes[0].set_title(f"TOMATOES Spread Over Time, every {DOWNSAMPLE}th point")
    axes[0].set_xlabel("Time")
    axes[0].set_ylabel("Spread")
    axes[0].grid(True, alpha=0.3)

    spread_counts = df["spread"].value_counts().sort_index()
    axes[1].bar(spread_counts.index.astype(str), spread_counts.values)
    axes[1].set_title("TOMATOES Spread Distribution")
    axes[1].set_xlabel("Spread")
    axes[1].set_ylabel("Count")
    axes[1].grid(True, axis="y", alpha=0.3)

    plt.tight_layout()
    plt.show()


def plot_clear_normalized_deviation(df):
    plot_df = df.iloc[::DOWNSAMPLE].copy()

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    axes[0].plot(
        plot_df["time_index"],
        plot_df["mid_vs_wall_norm"],
        linewidth=0.6,
        alpha=0.35,
        label="Normalized deviation"
    )
    axes[0].plot(
        df["time_index"],
        df["mid_vs_wall_roll"],
        linewidth=2.0,
        label=f"Rolling mean {ROLLING_WINDOW}"
    )
    axes[0].axhline(0.0, linewidth=1.0, linestyle="--")
    axes[0].set_title("TOMATOES Normalized Deviation from Wall Mid")
    axes[0].set_xlabel("Time")
    axes[0].set_ylabel("(Mid Price   Wall Mid) / Wall Mid")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].hist(df["mid_vs_wall_norm"].dropna(), bins=80)
    axes[1].axvline(0.0, linewidth=1.0, linestyle="--")
    axes[1].set_title("Distribution of Normalized Deviation")
    axes[1].set_xlabel("Normalized deviation")
    axes[1].set_ylabel("Frequency")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


def print_summary(df):
    print("\n===== TOMATOES SUMMARY =====")
    print(df["spread"].describe())
    print("\nNormalized deviation stats:")
    print(df["mid_vs_wall_norm"].describe())

    print("\nSpread value counts:")
    print(df["spread"].value_counts().sort_index())

    print("\nMean absolute normalized deviation:")
    print(df["mid_vs_wall_norm"].abs().mean())


def main():
    data = load_data(FILES)
    tomatoes = build_tomatoes_frame(data)

    print_summary(tomatoes)
    plot_clear_spread(tomatoes)
    plot_clear_normalized_deviation(tomatoes)


if __name__ == "__main__":
    main()