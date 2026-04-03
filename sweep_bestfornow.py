#!/usr/bin/env python3
"""
Sweep bestfornow.py TOMATOES parameters:
  1. Shock regime thresholds and reactions
  2. Base params (take margin, flatten, EMA, penalty)
  3. Passive size cap
  4. Riskier variants: tighter takes, asymmetric aggression, momentum
"""
import csv, json, os, time, itertools
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


HISTORY_LEN = 8

def compute_regime(mids, move_thresh, vol_thresh, reversal_thresh):
    if len(mids) < 4:
        return "normal"
    last = mids[-1]
    prev = mids[-2]
    short_move = last - prev
    medium_move = last - mids[-4]
    diffs = [mids[i] - mids[i-1] for i in range(1, len(mids))]
    realized_vol = sum(abs(x) for x in diffs[-5:]) / max(1, len(diffs[-5:]))
    prev_medium = mids[-2] - mids[-5] if len(mids) >= 5 else 0.0
    reversal = (abs(short_move) >= reversal_thresh
                and abs(prev_medium) >= reversal_thresh
                and short_move * prev_medium < 0)
    large_move = abs(medium_move) >= move_thresh
    high_vol = realized_vol >= vol_thresh
    if reversal or (large_move and high_vol):
        return "shock"
    return "normal"


def sim_tomatoes(all_days, p):
    """Full sim with shock regime support."""
    ema_alpha = p["ema_alpha"]
    inv_pen = p["inv_pen"]
    take_margin = p["take_margin"]
    flatten_thresh = p["flatten_thresh"]
    passive_size = p["passive_size"]  # normal passive cap (0 = unlimited)

    # Shock detection thresholds
    shock_move = p.get("shock_move", 99)
    shock_vol = p.get("shock_vol", 99)
    shock_reversal = p.get("shock_reversal", 99)
    # Shock reaction params
    shock_take_mult = p.get("shock_take_mult", 4.0)
    shock_passive = p.get("shock_passive", 2)
    shock_flatten = p.get("shock_flatten", 0)
    shock_disable_risky = p.get("shock_disable_risky", True)

    # Riskier features
    momentum_alpha = p.get("momentum_alpha", 0.0)  # momentum signal blending
    take_scale_with_edge = p.get("take_scale_with_edge", False)  # scale size by edge/margin

    total_pnl = 0.0

    for day, timestamps, ts_products in all_days:
        pos = 0
        ema_wm = None
        mid_history = []
        cash_flow = 0.0
        last_mid = 0.0
        prev_wm = None

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

            # Track history for shock detection
            mid_history = (mid_history + [td.wall_mid])[-HISTORY_LEN:]
            regime = compute_regime(mid_history, shock_move, shock_vol, shock_reversal)

            # Momentum signal
            momentum = 0.0
            if momentum_alpha > 0 and prev_wm is not None:
                momentum = (td.wall_mid - prev_wm) * momentum_alpha
            prev_wm = td.wall_mid

            fair_adj = ema_wm - inv_pen * pos + momentum

            # Margins
            buy_margin = take_margin
            sell_margin = take_margin
            ft = flatten_thresh

            if regime == "shock":
                buy_margin *= shock_take_mult
                sell_margin *= shock_take_mult
                ft = shock_flatten

            if pos > ft:
                sell_margin = 0.0 if regime == "normal" else min(sell_margin, 0.25)
            if pos < -ft:
                buy_margin = 0.0 if regime == "normal" else min(buy_margin, 0.25)

            cur_pos = pos
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            # TAKE sells
            for sp, sv in td.sell_levels:
                if max_buy <= 0:
                    break
                if regime == "shock" and shock_disable_risky and cur_pos >= ft:
                    break
                if sp <= fair_adj - buy_margin:
                    size = min(sv, max_buy)
                    if take_scale_with_edge and buy_margin > 0:
                        edge = (fair_adj - buy_margin - sp) / buy_margin
                        size = max(1, min(size, int(size * min(edge + 0.5, 1.0))))
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
                if regime == "shock" and shock_disable_risky and cur_pos <= -ft:
                    break
                if bp >= fair_adj + sell_margin:
                    size = min(bv, max_sell)
                    if take_scale_with_edge and sell_margin > 0:
                        edge = (bp - fair_adj - sell_margin) / sell_margin
                        size = max(1, min(size, int(size * min(edge + 0.5, 1.0))))
                    cash_flow += bp * size
                    cur_pos -= size
                    max_sell -= size
                elif bp >= fair_adj and pos > 0:
                    size = min(bv, pos, max_sell)
                    if size > 0:
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

            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos

            passive_buy_size = max_buy
            passive_sell_size = max_sell

            if regime == "shock":
                passive_buy_size = min(passive_buy_size, shock_passive)
                passive_sell_size = min(passive_sell_size, shock_passive)
                if shock_disable_risky:
                    if cur_pos > 0:
                        passive_buy_size = 0
                        ask_price = max(td.best_bid, min(ask_price, td.best_ask))
                    elif cur_pos < 0:
                        passive_sell_size = 0
                        bid_price = min(td.best_ask, max(bid_price, td.best_bid))
            else:
                if passive_size > 0:
                    passive_buy_size = min(passive_buy_size, passive_size)
                    passive_sell_size = min(passive_sell_size, passive_size)

            # Match make orders (only if bid < ask)
            if bid_price < ask_price:
                if passive_buy_size > 0:
                    remaining = passive_buy_size
                    for sp, sv in td.sell_levels:
                        if remaining <= 0 or bid_price < sp:
                            break
                        fill = min(remaining, sv)
                        cash_flow -= sp * fill
                        cur_pos += fill
                        remaining -= fill

                if passive_sell_size > 0:
                    remaining = passive_sell_size
                    for bp, bv in td.buy_levels:
                        if remaining <= 0 or ask_price > bp:
                            break
                        fill = min(remaining, bv)
                        cash_flow += bp * fill
                        cur_pos -= fill
                        remaining -= fill
            else:
                # Price crossed: flatten only
                if cur_pos > 0 and passive_sell_size > 0:
                    remaining = passive_sell_size
                    for bp, bv in td.buy_levels:
                        if remaining <= 0:
                            break
                        if td.best_ask <= bp:
                            fill = min(remaining, bv)
                            cash_flow += bp * fill
                            cur_pos -= fill
                            remaining -= fill
                elif cur_pos < 0 and passive_buy_size > 0:
                    remaining = passive_buy_size
                    for sp, sv in td.sell_levels:
                        if remaining <= 0:
                            break
                        if td.best_bid >= sp:
                            fill = min(remaining, sv)
                            cash_flow -= sp * fill
                            cur_pos += fill
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

    # ── Current bestfornow.py baseline (shock never fires, so effectively normal-mode only) ──
    baseline = {
        "ema_alpha": 0.10, "inv_pen": 0.02, "take_margin": 0.3,
        "flatten_thresh": 3, "passive_size": 8,
        "shock_move": 99, "shock_vol": 99, "shock_reversal": 99,
        "shock_take_mult": 4.0, "shock_passive": 2, "shock_flatten": 0,
        "shock_disable_risky": True,
    }
    baseline_pnl = sim_tomatoes(all_days, baseline)
    print(f"Baseline (bestfornow.py): {baseline_pnl}")

    # v6 optimal (no shock, no passive cap)
    v6_opt = dict(baseline, take_margin=0.25, flatten_thresh=2, passive_size=0,
                  shock_move=99, shock_vol=99, shock_reversal=99)
    v6_pnl = sim_tomatoes(all_days, v6_opt)
    print(f"v6 optimal (no shock/cap): {v6_pnl}")

    results = []

    # ══════════════════════════════════════════════════════════
    # PHASE 1: Optimize base params WITHOUT shock regime
    # ══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("PHASE 1: Base parameter sweep (no shock)")
    print("="*60)

    best_base = (baseline_pnl, baseline)
    count = 0
    for ema in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
        for ip in [0.0, 0.01, 0.02, 0.03, 0.05]:
            for tm in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30]:
                for ft in [0, 1, 2, 3, 4]:
                    for ps in [0, 4, 8, 12, 20]:
                        p = dict(baseline,
                                 ema_alpha=ema, inv_pen=ip, take_margin=tm,
                                 flatten_thresh=ft, passive_size=ps,
                                 shock_move=99, shock_vol=99, shock_reversal=99)
                        pnl = sim_tomatoes(all_days, p)
                        count += 1
                        if pnl > best_base[0]:
                            best_base = (pnl, dict(p))
                            print(f"  NEW BEST: {pnl:>8.2f}  ema={ema} ip={ip} tm={tm} ft={ft} ps={ps}")

    print(f"\nPhase 1: {count} combos tested in {time.time()-t0:.0f}s")
    print(f"Best base: {best_base[0]} with params:")
    for k,v in best_base[1].items():
        if k not in ("shock_move","shock_vol","shock_reversal","shock_take_mult",
                      "shock_passive","shock_flatten","shock_disable_risky"):
            print(f"  {k}: {v}")

    # ══════════════════════════════════════════════════════════
    # PHASE 2: With best base params, sweep shock thresholds
    # ══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("PHASE 2: Shock regime sweep (on top of best base)")
    print("="*60)

    base_p = dict(best_base[1])
    base_no_shock_pnl = best_base[0]

    best_shock = (base_no_shock_pnl, base_p)
    shock_count = 0
    # Only test realistic thresholds for this data (max move=2, max vol=1.4)
    for sm in [2.0, 2.5, 3.0]:
        for sv in [0.6, 0.8, 1.0]:
            for sr in [1.5, 2.0, 2.5]:
                for stm in [2.0, 3.0, 4.0]:
                    for sp in [1, 2, 4]:
                        for sft in [0, 1]:
                            for sdr in [True, False]:
                                p = dict(base_p,
                                         shock_move=sm, shock_vol=sv, shock_reversal=sr,
                                         shock_take_mult=stm, shock_passive=sp,
                                         shock_flatten=sft, shock_disable_risky=sdr)
                                pnl = sim_tomatoes(all_days, p)
                                shock_count += 1
                                if pnl > best_shock[0]:
                                    best_shock = (pnl, dict(p))
                                    print(f"  SHOCK IMPROVED: {pnl:>8.2f}  sm={sm} sv={sv} sr={sr} stm={stm} sp={sp} sft={sft} sdr={sdr}")

    print(f"\nPhase 2: {shock_count} combos tested in {time.time()-t0:.0f}s")
    print(f"Best with shock: {best_shock[0]} (base was {base_no_shock_pnl}, delta={best_shock[0]-base_no_shock_pnl:+.2f})")
    if best_shock[0] > base_no_shock_pnl:
        print("Shock regime HELPS! Params:")
        for k, v in best_shock[1].items():
            print(f"  {k}: {v}")
    else:
        print("Shock regime does NOT help on this data.")

    # ══════════════════════════════════════════════════════════
    # PHASE 3: Riskier strategies (on top of best base)
    # ══════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("PHASE 3: Riskier strategies")
    print("="*60)

    # 3a: Lower take margin (more aggressive taking)
    print("\n-- 3a: Aggressive take margins --")
    for tm in [0.0, 0.05, 0.10, 0.15]:
        p = dict(base_p, take_margin=tm)
        pnl = sim_tomatoes(all_days, p)
        delta = pnl - base_no_shock_pnl
        print(f"  take_margin={tm:.2f}: {pnl:>8.2f} ({delta:+.2f})")

    # 3b: Momentum blending (trend-following tilt)
    print("\n-- 3b: Momentum signal --")
    for ma in [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 2.0]:
        p = dict(base_p, momentum_alpha=ma)
        pnl = sim_tomatoes(all_days, p)
        delta = pnl - base_no_shock_pnl
        print(f"  momentum_alpha={ma:.1f}: {pnl:>8.2f} ({delta:+.2f})")

    # 3c: Zero flatten threshold (always lean to unwind)
    print("\n-- 3c: Zero flatten threshold --")
    p = dict(base_p, flatten_thresh=0)
    pnl = sim_tomatoes(all_days, p)
    print(f"  flatten_thresh=0: {pnl:>8.2f} ({pnl-base_no_shock_pnl:+.2f})")

    # 3d: Larger inventory penalty
    print("\n-- 3d: Higher inv penalty --")
    for ip in [0.03, 0.05, 0.08, 0.10]:
        p = dict(base_p, inv_pen=ip)
        pnl = sim_tomatoes(all_days, p)
        print(f"  inv_pen={ip:.2f}: {pnl:>8.2f} ({pnl-base_no_shock_pnl:+.2f})")

    # 3e: Unlimited passive (remove cap)
    print("\n-- 3e: Passive size cap removal --")
    for ps in [0, 5, 8, 12, 20]:
        p = dict(base_p, passive_size=ps)
        pnl = sim_tomatoes(all_days, p)
        print(f"  passive_size={ps}: {pnl:>8.2f} ({pnl-base_no_shock_pnl:+.2f})")

    # 3f: Edge-scaled taking
    print("\n-- 3f: Edge-scaled taking --")
    p = dict(base_p, take_scale_with_edge=True)
    pnl = sim_tomatoes(all_days, p)
    print(f"  edge_scaled: {pnl:>8.2f} ({pnl-base_no_shock_pnl:+.2f})")

    # 3g: Combine best risky features on top of best base
    # (Will manually combine after seeing individual results)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"Total sweep time: {elapsed:.0f}s")

    # Save results
    summary = {
        "baseline_pnl": baseline_pnl,
        "v6_optimal_pnl": v6_pnl,
        "best_base": {"pnl": best_base[0], "params": best_base[1]},
        "best_shock": {"pnl": best_shock[0], "params": best_shock[1]},
    }
    with open("sweep_bestfornow_results.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nResults saved to sweep_bestfornow_results.json")


if __name__ == "__main__":
    main()
