#!/usr/bin/env python3
"""Fast v6 parameter sweep - precompute book data, sweep TOMATOES only."""
import csv, json, os, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data", "raw")
POS_LIMIT = 20

# ─── Precomputed tick data ──────────────────────

@dataclass
class TickData:
    """Pre-parsed book for one product at one timestamp."""
    buy_levels: list    # [(price, abs_vol)] sorted desc
    sell_levels: list   # [(price, abs_vol)] sorted asc
    bid_wall: int
    ask_wall: int
    wall_mid: float
    mid_price: float


def load_and_precompute():
    """Load all days, precompute tick data per product."""
    import glob
    price_files = sorted(glob.glob(os.path.join(DATA_DIR, "prices_round_*_day_*.csv")))
    all_days = []
    for pf in price_files:
        day = os.path.basename(pf).replace(".csv", "").split("_")[-1]
        ts_products = defaultdict(dict)
        with open(pf, newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                if not row.get("product"): continue
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
                
                if not buys or not sells: continue
                buys.sort(key=lambda x: -x[0])
                sells.sort(key=lambda x: x[0])
                
                bid_wall = buys[-1][0]
                ask_wall = sells[-1][0]
                wall_mid = (bid_wall + ask_wall) / 2.0
                mid = float(row.get("mid_price", 0) or 0)
                
                td = TickData(buys, sells, bid_wall, ask_wall, wall_mid, mid)
                ts_products[ts][product] = td
        
        timestamps = sorted(ts_products.keys())
        all_days.append((day, timestamps, ts_products))
    return all_days


def sim_tomatoes(all_days, inv_pen, take_margin, flatten_thresh, ema_alpha):
    """Simulate TOMATOES strategy, return total PnL."""
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
            
            # EMA update
            if ema_wm is None:
                ema_wm = td.wall_mid
            else:
                ema_wm = ema_alpha * td.wall_mid + (1 - ema_alpha) * ema_wm
            
            fair_adj = ema_wm - inv_pen * pos
            
            bm = take_margin
            sm = take_margin
            if pos > flatten_thresh: sm = 0.0
            if pos < -flatten_thresh: bm = 0.0
            
            # Generate + match orders inline for speed
            cur_pos = pos
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos
            
            # TAKE sells (buy from asks)
            for sp, sv in td.sell_levels:
                if max_buy <= 0: break
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
            
            # TAKE buys (sell to bids)
            for bp, bv in td.buy_levels:
                if max_sell <= 0: break
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
            
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos
            
            # Match make orders against book
            if max_buy > 0:
                remaining = max_buy
                for sp, sv in td.sell_levels:
                    if remaining <= 0: break
                    if bid_price < sp: break
                    fill = min(remaining, sv)
                    cash_flow -= sp * fill
                    cur_pos += fill
                    remaining -= fill
            
            if max_sell > 0:
                remaining = max_sell
                for bp, bv in td.buy_levels:
                    if remaining <= 0: break
                    if ask_price > bp: break
                    fill = min(remaining, bv)
                    cash_flow += bp * fill
                    cur_pos -= fill
                    remaining -= fill
            
            pos = cur_pos
        
        pnl = cash_flow + pos * last_mid
        total_pnl += pnl
    
    return round(total_pnl, 2)


def sim_emeralds(all_days, emr_inv_pen):
    """Simulate EMERALDS strategy, return total PnL."""
    total_pnl = 0.0
    
    for day, timestamps, ts_products in all_days:
        pos = 0
        cash_flow = 0.0
        last_mid = 0.0
        
        for ts in timestamps:
            if "EMERALDS" not in ts_products[ts]:
                continue
            td = ts_products[ts]["EMERALDS"]
            last_mid = td.mid_price if td.mid_price else last_mid
            
            fair = 10000 - emr_inv_pen * pos
            cur_pos = pos
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos
            
            # TAKE sells
            for sp, sv in td.sell_levels:
                if max_buy <= 0: break
                if sp < fair:
                    size = min(sv, max_buy)
                    cash_flow -= sp * size
                    cur_pos += size
                    max_buy -= size
                elif sp <= fair and pos < 0:
                    size = min(sv, abs(pos), max_buy)
                    if size > 0:
                        cash_flow -= sp * size
                        cur_pos += size
                        max_buy -= size
            
            # TAKE buys
            for bp, bv in td.buy_levels:
                if max_sell <= 0: break
                if bp > fair:
                    size = min(bv, max_sell)
                    cash_flow += bp * size
                    cur_pos -= size
                    max_sell -= size
                elif bp >= fair and pos > 0:
                    size = min(bv, pos, max_sell)
                    if size > 0:
                        cash_flow += bp * size
                        cur_pos -= size
                        max_sell -= size
            
            # MAKE
            bid_price = td.bid_wall + 1
            ask_price = td.ask_wall - 1
            for bp, bv in td.buy_levels:
                ob = bp + 1
                if bv > 1 and ob < 10000:
                    bid_price = max(bid_price, ob)
                    break
                elif bp < 10000:
                    bid_price = max(bid_price, bp)
                    break
            for sp, sv in td.sell_levels:
                ub = sp - 1
                if sv > 1 and ub > 10000:
                    ask_price = min(ask_price, ub)
                    break
                elif sp > 10000:
                    ask_price = min(ask_price, sp)
                    break
            
            max_buy = POS_LIMIT - cur_pos
            max_sell = POS_LIMIT + cur_pos
            
            if max_buy > 0:
                remaining = max_buy
                for sp, sv in td.sell_levels:
                    if remaining <= 0: break
                    if bid_price < sp: break
                    fill = min(remaining, sv)
                    cash_flow -= sp * fill
                    cur_pos += fill
                    remaining -= fill
            
            if max_sell > 0:
                remaining = max_sell
                for bp, bv in td.buy_levels:
                    if remaining <= 0: break
                    if ask_price > bp: break
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
    print("Loading and precomputing data...")
    all_days = load_and_precompute()
    print(f"Loaded {len(all_days)} days in {time.time()-t0:.1f}s")
    
    # First, find best EMERALDS params
    print("\n=== EMERALDS sweep ===")
    emr_pens = [0.0, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50]
    best_emr = (-999999, 0.0)
    for ep in emr_pens:
        pnl = sim_emeralds(all_days, ep)
        print(f"  emr_inv_pen={ep:.2f} → PnL={pnl:>10.2f}")
        if pnl > best_emr[0]:
            best_emr = (pnl, ep)
    print(f"Best EMR: inv_pen={best_emr[1]:.2f}, PnL={best_emr[0]:.2f}")
    
    # TOMATOES: coarse sweep
    print("\n=== TOMATOES coarse sweep ===")
    inv_penalties = [0.0, 0.02, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50]
    take_margins = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
    flatten_thresholds = [2, 3, 5, 7, 10, 15, 20]
    ema_alphas = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
    
    total = len(inv_penalties) * len(take_margins) * len(flatten_thresholds) * len(ema_alphas)
    print(f"Combinations: {total}")
    
    results = []
    count = 0
    for ip in inv_penalties:
        for tm in take_margins:
            for ft in flatten_thresholds:
                for ea in ema_alphas:
                    pnl = sim_tomatoes(all_days, ip, tm, ft, ea)
                    results.append((pnl, ip, tm, ft, ea))
                    count += 1
    
    results.sort(key=lambda x: -x[0])
    print(f"\nDone in {time.time()-t0:.1f}s")
    print(f"\nTop 30:")
    print(f"{'Rank':>4} {'PnL':>10} {'inv_pen':>8} {'margin':>7} {'flatten':>8} {'ema_a':>6}")
    for i, (pnl, ip, tm, ft, ea) in enumerate(results[:30]):
        print(f"{i+1:>4} {pnl:>10.2f} {ip:>8.2f} {tm:>7.2f} {ft:>8} {ea:>6.2f}")
    
    # Phase 2: Fine-tune around top 5 distinct param sets
    print("\n=== Fine-tune phase ===")
    best = results[0]
    bip, btm, bft, bea = best[1], best[2], best[3], best[4]
    
    fine_inv = sorted(set([max(0, bip + d) for d in [-0.04, -0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03, 0.04]]))
    fine_margin = sorted(set([max(0, btm + d) for d in [-0.2, -0.15, -0.1, -0.05, 0, 0.05, 0.1, 0.15, 0.2]]))
    fine_flatten = sorted(set([max(1, bft + d) for d in [-3, -2, -1, 0, 1, 2, 3]]))
    fine_ema = sorted(set([max(0.005, min(1.0, bea + d)) for d in [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03]]))
    
    ftotal = len(fine_inv) * len(fine_margin) * len(fine_flatten) * len(fine_ema)
    print(f"Fine combos: {ftotal}")
    
    fine_results = []
    for ip in fine_inv:
        for tm in fine_margin:
            for ft in fine_flatten:
                for ea in fine_ema:
                    pnl = sim_tomatoes(all_days, ip, tm, ft, ea)
                    fine_results.append((pnl, ip, tm, ft, ea))
    
    fine_results.sort(key=lambda x: -x[0])
    print(f"\nTop 20 fine-tuned:")
    print(f"{'Rank':>4} {'PnL':>10} {'inv_pen':>8} {'margin':>7} {'flatten':>8} {'ema_a':>6}")
    for i, (pnl, ip, tm, ft, ea) in enumerate(fine_results[:20]):
        print(f"{i+1:>4} {pnl:>10.2f} {ip:>8.3f} {tm:>7.3f} {ft:>8} {ea:>6.3f}")
    
    # Overall best
    all_r = results + fine_results
    all_r.sort(key=lambda x: -x[0])
    best_pnl, best_ip, best_tm, best_ft, best_ea = all_r[0]
    
    total_pnl = best_pnl + best_emr[0]
    print(f"\n{'='*60}")
    print(f"BEST TOMATOES: PnL={best_pnl:.2f}")
    print(f"  inv_penalty={best_ip}")
    print(f"  take_margin={best_tm}")
    print(f"  flatten_thresh={best_ft}")
    print(f"  ema_alpha={best_ea}")
    print(f"BEST EMERALDS: PnL={best_emr[0]:.2f}, inv_pen={best_emr[1]}")
    print(f"TOTAL: {total_pnl:.2f}")
    print(f"\nElapsed: {time.time()-t0:.1f}s")
    
    # Save
    result_data = {
        "best_tomatoes_pnl": best_pnl,
        "best_tomatoes_params": {
            "inv_penalty": best_ip,
            "take_margin": best_tm,
            "flatten_thresh": best_ft,
            "ema_alpha": best_ea,
        },
        "best_emeralds_pnl": best_emr[0],
        "best_emeralds_params": {"inv_penalty": best_emr[1]},
        "total_pnl": total_pnl,
    }
    with open(os.path.join(ROOT, "sweep_v6_results.json"), "w") as f:
        json.dump(result_data, f, indent=2)
    print("Saved to sweep_v6_results.json")

if __name__ == "__main__":
    main()
