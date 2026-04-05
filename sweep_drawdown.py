#!/usr/bin/env python3
"""
Sweep to minimize early drawdown in bestfornow.py TOMATOES strategy.

Problem: Bot accumulates max long position (20) into falling prices
because INV_PENALTY=0.0 and WARMUP_TICKS=5 (too short for EMA convergence).

Tracks both final PnL and max drawdown per day to find the best tradeoff.
"""
import csv, os, time
from collections import defaultdict
from dataclasses import dataclass
from typing import List

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
    warmup_ticks = p["warmup_ticks"]
    # Optional: position ramp during early ticks
    early_pos_limit = p.get("early_pos_limit", POS_LIMIT)
    early_ticks = p.get("early_ticks", 0)

    total_pnl = 0.0
    worst_drawdown = 0.0   # most negative min-PnL across days
    day_results = []

    for day, timestamps, ts_products in all_days:
        pos = 0
        fast_ema = None
        slow_ema = None
        cash_flow = 0.0
        last_mid = 0.0
        tick_count = 0
        min_pnl = 0.0  # track worst unrealized PnL

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

            tick_count += 1

            if tick_count <= warmup_ticks:
                continue

            # Effective position limit (may be reduced during early ticks)
            if early_ticks > 0 and tick_count <= warmup_ticks + early_ticks:
                eff_limit = early_pos_limit
            else:
                eff_limit = POS_LIMIT

            # Momentum signal
            momentum = fast_ema - slow_ema

            fair_adj = slow_ema + momentum_weight * momentum - inv_pen * pos

            # Taking margins
            bm = take_margin
            sm = take_margin
            if pos > 0:
                sm = 0.0
            if pos < 0:
                bm = 0.0

            cur_pos = pos
            max_buy = eff_limit - cur_pos
            max_sell = eff_limit + cur_pos

            # TAKE sells (buy from asks)
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

            # TAKE buys (sell to bids)
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

            # MAKE (passive orders matched against book)
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

            max_buy = eff_limit - cur_pos
            max_sell = eff_limit + cur_pos

            # Match make orders against existing book
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

            # Track unrealized PnL at this tick
            unrealized = cash_flow + pos * td.wall_mid
            min_pnl = min(min_pnl, unrealized)

        pnl = cash_flow + pos * last_mid
        total_pnl += pnl
        worst_drawdown = min(worst_drawdown, min_pnl)
        day_results.append((day, round(pnl, 2), round(min_pnl, 2)))

    return round(total_pnl, 2), round(worst_drawdown, 2), day_results


def main():
    t0 = time.time()
    print("Loading data...")
    all_days = load_and_precompute()
    print(f"Loaded {len(all_days)} days in {time.time()-t0:.1f}s\n")

    # Current best (v7 params)
    baseline = {
        "fast_alpha": 0.10, "slow_alpha": 0.02,
        "take_margin": 0.0, "inv_pen": 0.0,
        "momentum_weight": 0.5,
        "warmup_ticks": 5,
    }
    pnl, dd, days = sim_tomatoes(all_days, baseline)
    print(f"BASELINE: PnL={pnl:>8.2f}  MaxDD={dd:>8.2f}")
    for d, p, m in days:
        print(f"  Day {d}: PnL={p:>8.2f}  MinPnL={m:>8.2f}")
    print()

    # ═══════════════════════════════════════════
    # PHASE 1: INV_PENALTY sweep (most impactful)
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("PHASE 1: INV_PENALTY sweep")
    print("=" * 70)
    best_p1 = (pnl, dd, dict(baseline))
    for ip in [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50]:
        p = dict(baseline, inv_pen=ip)
        r_pnl, r_dd, r_days = sim_tomatoes(all_days, p)
        dd_improve = r_dd - dd
        pnl_change = r_pnl - pnl
        marker = " ***" if r_pnl > best_p1[0] or (r_pnl >= pnl * 0.98 and r_dd > dd + 50) else ""
        print(f"  ip={ip:<5.2f}  PnL={r_pnl:>8.2f} ({pnl_change:>+7.2f})  DD={r_dd:>8.2f} ({dd_improve:>+7.2f}){marker}")
        if r_pnl > best_p1[0]:
            best_p1 = (r_pnl, r_dd, dict(p))

    print(f"\nBest P1: PnL={best_p1[0]}  DD={best_p1[1]}  ip={best_p1[2]['inv_pen']}")
    print()

    # ═══════════════════════════════════════════
    # PHASE 2: WARMUP_TICKS sweep
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("PHASE 2: WARMUP_TICKS sweep (using best inv_pen)")
    print("=" * 70)
    best_p2 = best_p1
    for wt in [0, 3, 5, 10, 15, 20, 30, 50, 75, 100]:
        p = dict(best_p1[2], warmup_ticks=wt)
        r_pnl, r_dd, r_days = sim_tomatoes(all_days, p)
        marker = " ***" if r_pnl > best_p2[0] else ""
        print(f"  wt={wt:<4}  PnL={r_pnl:>8.2f}  DD={r_dd:>8.2f}{marker}")
        if r_pnl > best_p2[0]:
            best_p2 = (r_pnl, r_dd, dict(p))

    print(f"\nBest P2: PnL={best_p2[0]}  DD={best_p2[1]}  wt={best_p2[2]['warmup_ticks']}")
    print()

    # ═══════════════════════════════════════════
    # PHASE 3: TAKE_MARGIN + MOMENTUM_WEIGHT
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("PHASE 3: TAKE_MARGIN + MOMENTUM_WEIGHT fine-tune")
    print("=" * 70)
    best_p3 = best_p2
    for tm in [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        for mw in [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]:
            p = dict(best_p2[2], take_margin=tm, momentum_weight=mw)
            r_pnl, r_dd, _ = sim_tomatoes(all_days, p)
            if r_pnl > best_p3[0]:
                best_p3 = (r_pnl, r_dd, dict(p))
                print(f"  NEW: PnL={r_pnl:>8.2f}  DD={r_dd:>8.2f}  tm={tm} mw={mw}")

    print(f"\nBest P3: PnL={best_p3[0]}  DD={best_p3[1]}")
    print()

    # ═══════════════════════════════════════════
    # PHASE 4: EMA speeds (fine-tune around best)
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("PHASE 4: EMA alpha fine-tune")
    print("=" * 70)
    best_p4 = best_p3
    for fa in [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]:
        for sa in [0.01, 0.015, 0.02, 0.03, 0.04, 0.05]:
            if sa > fa:
                continue
            p = dict(best_p3[2], fast_alpha=fa, slow_alpha=sa)
            r_pnl, r_dd, _ = sim_tomatoes(all_days, p)
            if r_pnl > best_p4[0]:
                best_p4 = (r_pnl, r_dd, dict(p))
                print(f"  NEW: PnL={r_pnl:>8.2f}  DD={r_dd:>8.2f}  fa={fa} sa={sa}")

    print(f"\nBest P4: PnL={best_p4[0]}  DD={best_p4[1]}")
    print()

    # ═══════════════════════════════════════════
    # PHASE 5: Early position limit ramp
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("PHASE 5: Early position limit ramp")
    print("=" * 70)
    best_p5 = best_p4
    for epl in [5, 8, 10, 12, 15]:
        for et in [10, 20, 30, 50, 100, 200]:
            p = dict(best_p4[2], early_pos_limit=epl, early_ticks=et)
            r_pnl, r_dd, _ = sim_tomatoes(all_days, p)
            if r_pnl > best_p5[0]:
                best_p5 = (r_pnl, r_dd, dict(p))
                print(f"  NEW: PnL={r_pnl:>8.2f}  DD={r_dd:>8.2f}  epl={epl} et={et}")

    print(f"\nBest P5: PnL={best_p5[0]}  DD={best_p5[1]}")
    print()

    # ═══════════════════════════════════════════
    # FINAL: Combined best with fine grid
    # ═══════════════════════════════════════════
    print("=" * 70)
    print("FINAL: Fine grid around best params")
    print("=" * 70)
    bp = best_p5[2]
    best_final = best_p5
    # Fine-tune inv_pen around best
    best_ip = bp["inv_pen"]
    for ip_delta in [-0.02, -0.01, -0.005, 0, 0.005, 0.01, 0.02]:
        ip = max(0, best_ip + ip_delta)
        for mw_delta in [-0.1, 0, 0.1]:
            mw = max(0, bp["momentum_weight"] + mw_delta)
            for tm_delta in [-0.05, 0, 0.05]:
                tm = max(0, bp["take_margin"] + tm_delta)
                p = dict(bp, inv_pen=ip, momentum_weight=mw, take_margin=tm)
                r_pnl, r_dd, _ = sim_tomatoes(all_days, p)
                if r_pnl > best_final[0]:
                    best_final = (r_pnl, r_dd, dict(p))
                    print(f"  NEW: PnL={r_pnl:>8.2f}  DD={r_dd:>8.2f}  ip={ip:.3f} mw={mw:.1f} tm={tm:.2f}")

    print(f"\nFINAL BEST: PnL={best_final[0]}  DD={best_final[1]}")
    pnl_f, dd_f, days_f = sim_tomatoes(all_days, best_final[2])
    for d, p, m in days_f:
        print(f"  Day {d}: PnL={p:>8.2f}  MinPnL={m:>8.2f}")
    print(f"\nParameters:")
    for k, v in sorted(best_final[2].items()):
        print(f"  {k}: {v}")

    print(f"\nTotal time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
