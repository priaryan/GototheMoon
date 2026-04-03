#!/usr/bin/env python3
"""Fast sweep for v7 TOMATOES parameters — quadratic penalty, skew, spread-adaptive margin."""
import csv, json, os, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")
POS_LIMIT = 20

@dataclass
class TickData:
    buy_levels: list
    sell_levels: list
    bid_wall: int
    ask_wall: int
    wall_mid: float
    mid_price: float
    best_bid: int
    best_ask: int
    spread: int


def load_and_precompute():
    import glob
    price_files = sorted(glob.glob(os.path.join(DATA_DIR, "prices_round_*_day_*.csv")))
    all_days = []
    for pf in price_files:
        day = os.path.basename(pf).replace(".csv", "").split("_")[-1]
        ts_products = defaultdict(dict)
        with open(pf, newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if not row.get("product"):
                    continue
                ts = int(row["timestamp"])
                product = row["product"]
                buys = []
                sells = []
                for lvl in range(1, 4):
                    bp = row.get(f"bid_price_{lvl}", "")
                    bv = row.get(f"bid_volume_{lvl}", "")
                    if bp and bp != "":
                        buys.append((int(float(bp)), abs(int(float(bv)))))
                    ap = row.get(f"ask_price_{lvl}", "")
                    av = row.get(f"ask_volume_{lvl}", "")
                    if ap and ap != "":
                        sells.append((int(float(ap)), abs(int(float(av)))))
                if not buys or not sells:
                    continue
                buys.sort(key=lambda x: -x[0])
                sells.sort(key=lambda x: x[0])
                bid_wall = buys[-1][0]
                ask_wall = sells[-1][0]
                wall_mid = (bid_wall + ask_wall) / 2.0
                mid = float(row.get("mid_price", 0) or 0)
                best_bid = buys[0][0]
                best_ask = sells[0][0]
                spread = best_ask - best_bid
                td = TickData(buys, sells, bid_wall, ask_wall, wall_mid, mid, best_bid, best_ask, spread)
                ts_products[ts][product] = td
        timestamps = sorted(ts_products.keys())
        all_days.append((day, timestamps, ts_products))
    return all_days


def sim_tomatoes(all_days, p):
    """Simulate with params dict p. Returns total PnL."""
    linear_pen = p["linear_pen"]
    quad_pen = p["quad_pen"]
    ema_alpha = p["ema_alpha"]
    base_margin = p["base_margin"]
    flatten_thresh = p["flatten_thresh"]
    spread_neutral = p["spread_neutral"]
    spread_scale = p["spread_scale"]
    skew_div = p["skew_div"]
    make_cap_thresh = p["make_cap_thresh"]
    make_cap_size = p["make_cap_size"]

    total_pnl = 0.0

    for day, timestamps, ts_products in all_days:
        pos = 0
        ema_wm = None
        cash_flow = 0.0
        last_mid = 0.0

        for ts in timestamps:
            if "TOMATOES" not in ts_products[ts]:
                continue
            td = ts_products[ts]["TOMATOES"]
            last_mid = td.mid_price if td.mid_price else last_mid

            # EMA
            if ema_wm is None:
                ema_wm = td.wall_mid
            else:
                ema_wm = ema_alpha * td.wall_mid + (1 - ema_alpha) * ema_wm

            # Quadratic fair
            fair_adj = ema_wm - linear_pen * pos - quad_pen * pos * abs(pos)

            # Spread-adaptive margin
            extra = max(0, (td.spread - spread_neutral)) * spread_scale
            bm = base_margin + extra
            sm = base_margin + extra
            if pos > flatten_thresh:
                sm = 0.0
            if pos < -flatten_thresh:
                bm = 0.0

            cur_pos = pos
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            # TAKE sells
            for sp, sv in td.sell_levels:
                if max_buy <= 0:
                    break
                take = False
                size = 0
                if sp <= fair_adj - bm:
                    size = min(sv, max_buy)
                    take = True
                elif sp <= fair_adj and pos < 0:
                    size = min(sv, abs(pos), max_buy)
                    take = size > 0
                if take and size > 0:
                    cash_flow -= sp * size
                    cur_pos += size
                    max_buy -= size

            # TAKE buys
            for bp, bv in td.buy_levels:
                if max_sell <= 0:
                    break
                take = False
                size = 0
                if bp >= fair_adj + sm:
                    size = min(bv, max_sell)
                    take = True
                elif bp >= fair_adj and pos > 0:
                    size = min(bv, pos, max_sell)
                    take = size > 0
                if take and size > 0:
                    cash_flow += bp * size
                    cur_pos -= size
                    max_sell -= size

            # MAKE
            bid_price = td.bid_wall + 1
            ask_price = td.ask_wall - 1
            wm = td.wall_mid

            for bp, bv in td.buy_levels:
                ob = bp + 1
                if bv > 1 and ob < wm:
                    bid_price = max(bid_price, ob)
                    break
                elif bp < wm:
                    bid_price = max(bid_price, bp)
                    break

            for sp, sv in td.sell_levels:
                ub = sp - 1
                if sv > 1 and ub > wm:
                    ask_price = min(ask_price, ub)
                    break
                elif sp > wm:
                    ask_price = min(ask_price, sp)
                    break

            # Skew
            if skew_div > 0:
                skew = round(cur_pos / skew_div)
                bid_price -= skew
                ask_price -= skew
                bid_price = min(bid_price, int(wm) - 1)
                ask_price = max(ask_price, int(wm) + 1)

            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            # Cap making size
            make_buy = max_buy
            make_sell = max_sell
            if make_cap_thresh > 0:
                if cur_pos > make_cap_thresh:
                    make_buy = min(make_buy, make_cap_size)
                if cur_pos < -make_cap_thresh:
                    make_sell = min(make_sell, make_cap_size)

            # Match make orders
            if make_buy > 0:
                remaining = make_buy
                for sp, sv in td.sell_levels:
                    if remaining <= 0:
                        break
                    if bid_price < sp:
                        break
                    fill = min(remaining, sv)
                    cash_flow -= sp * fill
                    cur_pos += fill
                    remaining -= fill

            if make_sell > 0:
                remaining = make_sell
                for bp, bv in td.buy_levels:
                    if remaining <= 0:
                        break
                    if ask_price > bp:
                        break
                    fill = min(remaining, bv)
                    cash_flow += bp * fill
                    cur_pos -= fill
                    remaining -= fill

            pos = cur_pos

        pnl = cash_flow + pos * last_mid
        total_pnl += pnl

    return round(total_pnl, 2)


def main():
    t0 = time.time()
    print("Loading data...")
    all_days = load_and_precompute()
    print(f"Loaded {len(all_days)} days in {time.time()-t0:.1f}s")

    # v6 baseline params (no quad, no skew, no spread-adapt, no cap)
    v6_params = {
        "linear_pen": 0.02, "quad_pen": 0.0, "ema_alpha": 0.1,
        "base_margin": 0.25, "flatten_thresh": 2,
        "spread_neutral": 99, "spread_scale": 0.0,  # effectively off
        "skew_div": 0, "make_cap_thresh": 0, "make_cap_size": 99,
    }
    v6_pnl = sim_tomatoes(all_days, v6_params)
    print(f"v6 baseline: {v6_pnl}")

    # Phase 1: Sweep each new feature independently to see impact
    print("\n=== Feature isolation tests ===")

    # Test #1: Quadratic penalty alone
    print("\n-- Quadratic penalty (linear_pen, quad_pen) --")
    best_quad = (-99999, {})
    for lp in [0.0, 0.01, 0.02, 0.03, 0.05]:
        for qp in [0.0, 0.001, 0.002, 0.003, 0.005, 0.008, 0.01]:
            p = dict(v6_params)
            p["linear_pen"] = lp
            p["quad_pen"] = qp
            pnl = sim_tomatoes(all_days, p)
            if pnl > best_quad[0]:
                best_quad = (pnl, {"linear_pen": lp, "quad_pen": qp})
            if pnl > v6_pnl:
                print(f"  lp={lp:.3f} qp={qp:.3f} -> {pnl:>8.2f}  (+{pnl-v6_pnl:.2f})")
    print(f"  BEST quad: {best_quad}")

    # Test #2: Skew alone
    print("\n-- Make skew (skew_div) --")
    best_skew = (-99999, {})
    for sd in [0, 5, 7, 8, 10, 12, 15, 20]:
        p = dict(v6_params)
        p["skew_div"] = sd
        pnl = sim_tomatoes(all_days, p)
        tag = " ***" if pnl > v6_pnl else ""
        print(f"  skew_div={sd:>3} -> {pnl:>8.2f}{tag}")
        if pnl > best_skew[0]:
            best_skew = (pnl, {"skew_div": sd})
    print(f"  BEST skew: {best_skew}")

    # Test #3: Spread-adaptive margin alone
    print("\n-- Spread-adaptive margin (spread_neutral, spread_scale) --")
    best_spread = (-99999, {})
    for sn in [4, 6, 8, 10, 12]:
        for ss in [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]:
            p = dict(v6_params)
            p["spread_neutral"] = sn
            p["spread_scale"] = ss
            pnl = sim_tomatoes(all_days, p)
            if pnl > best_spread[0]:
                best_spread = (pnl, {"spread_neutral": sn, "spread_scale": ss})
    print(f"  BEST spread-adapt: {best_spread}")

    # Test #4: Make cap alone
    print("\n-- Make cap (make_cap_thresh, make_cap_size) --")
    best_cap = (-99999, {})
    for mct in [0, 8, 10, 12, 15]:
        for mcs in [3, 5, 8, 99]:
            p = dict(v6_params)
            p["make_cap_thresh"] = mct
            p["make_cap_size"] = mcs
            pnl = sim_tomatoes(all_days, p)
            if pnl > best_cap[0]:
                best_cap = (pnl, {"make_cap_thresh": mct, "make_cap_size": mcs})
    print(f"  BEST cap: {best_cap}")

    # Phase 2: Combine the best of each
    print("\n=== Phase 2: Combined sweep ===")
    # Take best values from isolation and vary around them
    quad_lps = [best_quad[1]["linear_pen"] + d for d in [-0.01, 0, 0.01]]
    quad_qps = [best_quad[1]["quad_pen"] + d for d in [-0.001, 0, 0.001, 0.002]]
    quad_lps = [max(0, x) for x in quad_lps]
    quad_qps = [max(0, x) for x in quad_qps]
    skew_divs = [0, best_skew[1]["skew_div"]]
    if best_skew[1]["skew_div"] > 0:
        skew_divs += [best_skew[1]["skew_div"] - 2, best_skew[1]["skew_div"] + 2]
    skew_divs = sorted(set(max(0, x) for x in skew_divs))
    spread_sns = [best_spread[1]["spread_neutral"]]
    spread_sss = [0.0, best_spread[1]["spread_scale"]]
    cap_mcts = [0, best_cap[1]["make_cap_thresh"]]
    cap_mcss = [best_cap[1]["make_cap_size"]]
    ema_alphas = [0.05, 0.1, 0.15, 0.2]
    base_margins = [0.0, 0.15, 0.25, 0.35, 0.5]
    flatten_threshs = [1, 2, 3, 5]

    total = (len(quad_lps) * len(quad_qps) * len(skew_divs) * len(spread_sss) *
             len(cap_mcts) * len(ema_alphas) * len(base_margins) * len(flatten_threshs))
    print(f"Combinations: {total}")

    results = []
    count = 0
    for lp in quad_lps:
        for qp in quad_qps:
            for sd in skew_divs:
                for ss in spread_sss:
                    for mct in cap_mcts:
                        for ea in ema_alphas:
                            for bm in base_margins:
                                for ft in flatten_threshs:
                                    p = {
                                        "linear_pen": lp, "quad_pen": qp,
                                        "ema_alpha": ea, "base_margin": bm,
                                        "flatten_thresh": ft,
                                        "spread_neutral": spread_sns[0],
                                        "spread_scale": ss,
                                        "skew_div": sd,
                                        "make_cap_thresh": mct,
                                        "make_cap_size": cap_mcss[0],
                                    }
                                    pnl = sim_tomatoes(all_days, p)
                                    results.append((pnl, dict(p)))
                                    count += 1
                                    if count % 2000 == 0:
                                        print(f"  {count}/{total}...")

    results.sort(key=lambda x: -x[0])
    print(f"\nTop 20 combined:")
    print(f"{'Rank':>4} {'PnL':>10} {'lp':>6} {'qp':>6} {'ema':>5} {'margin':>7} {'flat':>5} {'skew':>5} {'sprS':>5} {'capT':>5}")
    for i, (pnl, p) in enumerate(results[:20]):
        print(f"{i+1:>4} {pnl:>10.2f} {p['linear_pen']:>6.3f} {p['quad_pen']:>6.4f} {p['ema_alpha']:>5.2f} {p['base_margin']:>7.2f} {p['flatten_thresh']:>5} {p['skew_div']:>5} {p['spread_scale']:>5.2f} {p['make_cap_thresh']:>5}")

    best_pnl, best_p = results[0]
    print(f"\n{'='*60}")
    print(f"BEST: PnL={best_pnl} (v6 was {v6_pnl}, delta={best_pnl-v6_pnl:+.2f})")
    print(f"Params: {json.dumps(best_p, indent=2)}")
    print(f"Elapsed: {time.time()-t0:.1f}s")

    with open(os.path.join(ROOT, "sweep_v7_results.json"), "w") as f:
        json.dump({"best_pnl": best_pnl, "best_params": best_p, "v6_pnl": v6_pnl,
                    "top_20": [(pnl, p) for pnl, p in results[:20]]}, f, indent=2)
    print("Saved to sweep_v7_results.json")


if __name__ == "__main__":
    main()
