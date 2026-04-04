#!/usr/bin/env python3
"""
Sweep bestfornow_v7.py Kelp+Ink hybrid parameters for TOMATOES.

Tests dual-EMA momentum signal with:
  - MOMENTUM_WEIGHT: how much momentum tilts fair value
  - FAST_ALPHA, SLOW_ALPHA: EMA speeds
  - KELP_THRESH, INK_THRESH: mode thresholds
  - INK_MARGIN_REDUCTION: Ink taking aggression
  - TAKE_MARGIN, INV_PENALTY: base taking params
"""
import csv, json, os, time
from collections import defaultdict
from dataclasses import dataclass
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
                buys, sells = [], []
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
    fast_alpha = p["fast_alpha"]
    slow_alpha = p["slow_alpha"]
    take_margin = p["take_margin"]
    inv_pen = p["inv_pen"]
    momentum_weight = p["momentum_weight"]
    kelp_thresh = p["kelp_thresh"]
    ink_thresh = p["ink_thresh"]
    ink_margin_red = p["ink_margin_red"]

    total_pnl = 0.0

    for day, timestamps, ts_products in all_days:
        pos = 0
        fast_ema = None
        slow_ema = None
        cash_flow = 0.0
        last_mid = 0.0

        for ts in timestamps:
            if "TOMATOES" not in ts_products[ts]:
                continue
            td = ts_products[ts]["TOMATOES"]
            last_mid = td.mid_price if td.mid_price else last_mid

            # Update dual EMAs
            if fast_ema is None:
                fast_ema = td.wall_mid
                slow_ema = td.wall_mid
            else:
                fast_ema = fast_alpha * td.wall_mid + (1 - fast_alpha) * fast_ema
                slow_ema = slow_alpha * td.wall_mid + (1 - slow_alpha) * slow_ema

            # Momentum signal
            momentum = fast_ema - slow_ema

            # Direction + mode
            if abs(momentum) >= ink_thresh:
                mode = "ink"
                direction = 1 if momentum > 0 else -1
            elif abs(momentum) >= kelp_thresh:
                mode = "kelp"
                direction = 1 if momentum > 0 else -1
            else:
                mode = "neutral"
                direction = 0

            # Momentum-tilted fair value
            fair_adj = slow_ema + momentum_weight * momentum - inv_pen * pos

            # Taking margins
            bm = take_margin
            sm = take_margin

            if mode == "ink":
                if direction == 1:
                    bm = max(0, take_margin - ink_margin_red)
                else:
                    sm = max(0, take_margin - ink_margin_red)

            # Always flatten
            if pos > 0:
                sm = 0.0
            if pos < 0:
                bm = 0.0

            cur_pos = pos
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            # TAKE sells
            for sp, sv in td.sell_levels:
                if max_buy <= 0:
                    break
                if sp <= fair_adj - bm:
                    size = min(sv, max_buy)
                    cash_flow -= sp * size
                    cur_pos += size
                    max_buy -= size
                elif sp <= fair_adj and pos < 0:
                    size = min(sv, abs(pos), max_buy)
                    if size > 0:
                        cash_flow -= sp * size
                        cur_pos += size
                        max_buy -= size

            # TAKE buys
            for bp, bv in td.buy_levels:
                if max_sell <= 0:
                    break
                if bp >= fair_adj + sm:
                    size = min(bv, max_sell)
                    cash_flow += bp * size
                    cur_pos -= size
                    max_sell -= size
                elif bp >= fair_adj and pos > 0:
                    size = min(bv, pos, max_sell)
                    if size > 0:
                        cash_flow += bp * size
                        cur_pos -= size
                        max_sell -= size

            # MAKE (standard wall-mid, match against book)
            wm = td.wall_mid
            bid_price = td.bid_wall + 1
            ask_price = td.ask_wall - 1

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

            # Kelp-style: widen adverse side
            if abs(momentum) >= kelp_thresh:
                if momentum > 0:
                    if ask_price - wm < 1:
                        ask_price = td.ask_wall
                else:
                    if wm - bid_price < 1:
                        bid_price = td.bid_wall

            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            # Match make orders
            if max_buy > 0:
                remaining = max_buy
                for sp, sv in td.sell_levels:
                    if remaining <= 0 or bid_price < sp:
                        break
                    fill = min(remaining, sv)
                    cash_flow -= sp * fill
                    cur_pos += fill
                    remaining -= fill

            if max_sell > 0:
                remaining = max_sell
                for bp, bv in td.buy_levels:
                    if remaining <= 0 or ask_price > bp:
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

    # v6 baseline (single EMA, no momentum)
    v6_baseline = {
        "fast_alpha": 0.15, "slow_alpha": 0.15,
        "take_margin": 0.2, "inv_pen": 0.01,
        "momentum_weight": 0.0,
        "kelp_thresh": 99, "ink_thresh": 99,
        "ink_margin_red": 0.0,
    }
    v6_pnl = sim_tomatoes(all_days, v6_baseline)
    print(f"v6 baseline (single EMA 0.15, no momentum): {v6_pnl}")

    # v7 defaults
    v7_defaults = {
        "fast_alpha": 0.25, "slow_alpha": 0.05,
        "take_margin": 0.2, "inv_pen": 0.01,
        "momentum_weight": 0.3,
        "kelp_thresh": 0.5, "ink_thresh": 1.5,
        "ink_margin_red": 0.15,
    }
    v7_pnl = sim_tomatoes(all_days, v7_defaults)
    print(f"v7 defaults (hybrid): {v7_pnl}")

    print()

    # ═══════════════════════════════════════════
    # PHASE 1: Sweep dual EMA + momentum weight
    # ═══════════════════════════════════════════
    print("=" * 60)
    print("PHASE 1: EMA speeds + momentum weight (no modes)")
    print("=" * 60)

    best_p1 = (v6_pnl, v6_baseline)
    count = 0
    for fa in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
        for sa in [0.02, 0.03, 0.05, 0.08, 0.10, 0.15]:
            if sa > fa:
                continue
            for mw in [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]:
                for tm in [0.0, 0.10, 0.15, 0.20, 0.25]:
                    for ip in [0.0, 0.01, 0.02, 0.03]:
                        p = dict(v6_baseline,
                                 fast_alpha=fa, slow_alpha=sa,
                                 momentum_weight=mw,
                                 take_margin=tm, inv_pen=ip,
                                 kelp_thresh=99, ink_thresh=99)
                        pnl = sim_tomatoes(all_days, p)
                        count += 1
                        if pnl > best_p1[0]:
                            best_p1 = (pnl, dict(p))
                            print(f"  NEW: {pnl:>8.2f}  fa={fa} sa={sa} mw={mw} tm={tm} ip={ip}")

    print(f"\nPhase 1: {count} combos in {time.time()-t0:.0f}s")
    print(f"Best: {best_p1[0]}")
    for k, v in best_p1[1].items():
        if k not in ("kelp_thresh", "ink_thresh", "ink_margin_red"):
            print(f"  {k}: {v}")

    # ═══════════════════════════════════════════
    # PHASE 2: Kelp + Ink mode thresholds
    # ═══════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PHASE 2: Kelp + Ink mode thresholds (on top of best P1)")
    print("=" * 60)

    base_p = dict(best_p1[1])
    base_pnl = best_p1[0]
    best_p2 = (base_pnl, base_p)
    count2 = 0

    for kt in [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 99]:
        for it in [0.5, 0.7, 1.0, 1.5, 2.0, 99]:
            if it <= kt and it != 99:
                continue
            for imr in [0.0, 0.05, 0.10, 0.15, 0.20]:
                p = dict(base_p,
                         kelp_thresh=kt, ink_thresh=it,
                         ink_margin_red=imr)
                pnl = sim_tomatoes(all_days, p)
                count2 += 1
                if pnl > best_p2[0]:
                    best_p2 = (pnl, dict(p))
                    print(f"  NEW: {pnl:>8.2f}  kt={kt} it={it} imr={imr}")

    print(f"\nPhase 2: {count2} combos in {time.time()-t0:.0f}s")
    print(f"Best with modes: {best_p2[0]} (delta={best_p2[0]-base_pnl:+.2f})")
    for k, v in best_p2[1].items():
        print(f"  {k}: {v}")

    # ═══════════════════════════════════════════
    # PHASE 3: Quick check alternative strategies
    # ═══════════════════════════════════════════
    print("\n" + "=" * 60)
    print("PHASE 3: Strategy variants")
    print("=" * 60)

    optimal = best_p2[1]

    # 3a: Momentum weight sensitivity
    print("\n-- Momentum weight sensitivity --")
    for mw in [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]:
        p = dict(optimal, momentum_weight=mw)
        pnl = sim_tomatoes(all_days, p)
        delta = pnl - best_p2[0]
        tag = " ***" if pnl > best_p2[0] else ""
        print(f"  mw={mw:.1f}: {pnl:>8.2f} ({delta:+.2f}){tag}")

    # 3b: Single EMA reference (like v6)
    print("\n-- Single EMA reference (like v6) --")
    for alpha in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]:
        p = dict(optimal, fast_alpha=alpha, slow_alpha=alpha, momentum_weight=0.0,
                 kelp_thresh=99, ink_thresh=99)
        pnl = sim_tomatoes(all_days, p)
        delta = pnl - best_p2[0]
        print(f"  ema={alpha:.2f}: {pnl:>8.2f} ({delta:+.2f})")

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"Total: {elapsed:.0f}s")

    summary = {
        "v6_pnl": v6_pnl,
        "v7_default_pnl": v7_pnl,
        "best_ema_momentum": {"pnl": best_p1[0], "params": best_p1[1]},
        "best_with_modes": {"pnl": best_p2[0], "params": best_p2[1]},
    }
    with open("sweep_v7_results.json", "w") as f:
        json.dump(summary, f, indent=2)
    print("Results saved to sweep_v7_results.json")


if __name__ == "__main__":
    main()
