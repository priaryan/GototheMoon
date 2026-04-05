#!/usr/bin/env python3
"""
Test targeted improvements to fix the early-dip weakness of the purple version
while keeping its strong late performance.

Variants:
  G: Soft dampening - replace binary threshold with linear ramp
  H: Adaptive IP - higher inventory penalty in low-momentum regime
  I: Combined soft dampening + adaptive IP
  J: Soft dampening + slightly reduced MW (hedge against over-directional)
"""
import os, re, subprocess, json, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")

with open(TRADER) as f:
    ORIGINAL = f.read()

# ── Template: we'll write a complete TomatoesMM for each variant ──────

TOMATOES_TEMPLATE = '''class TomatoesMM:
    """
    TOMATOES: Dual EMA momentum with regime-aware inventory management.
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    FAST_ALPHA = 0.10
    SLOW_ALPHA = 0.02

    MOMENTUM_WEIGHT = {mw}
    TAKE_MARGIN = 0.0

    # Inventory penalty
    INV_PENALTY = {ip}
    INV_PENALTY_HIGH = {ip_high}  # used in low-momentum regime

    # Momentum dampening
    MOMENTUM_THRESHOLD = {thr}
    SOFT_DAMPEN = {soft}  # True=linear ramp, False=binary cutoff
    ADAPTIVE_IP = {adaptive_ip}  # True=use higher IP in low-momentum regime

    WARMUP_TICKS = 5

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        fast_ema,
        slow_ema,
        warmup_ticks: int,
    ) -> tuple:
        raw_buys = depth.buy_orders or {{}}
        raw_sells = depth.sell_orders or {{}}
        if not raw_buys or not raw_sells:
            return [], fast_ema, slow_ema, warmup_ticks

        buy_orders = {{p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}}
        sell_orders = {{p: abs(v) for p, v in sorted(raw_sells.items())}}

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if fast_ema is None:
            fast_ema = wall_mid
            slow_ema = wall_mid
        else:
            fast_ema = self.FAST_ALPHA * wall_mid + (1 - self.FAST_ALPHA) * fast_ema
            slow_ema = self.SLOW_ALPHA * wall_mid + (1 - self.SLOW_ALPHA) * slow_ema

        warmup_ticks += 1
        if warmup_ticks <= self.WARMUP_TICKS:
            return [], fast_ema, slow_ema, warmup_ticks

        raw_momentum = fast_ema - slow_ema

        # Regime-aware momentum scaling
        if self.MOMENTUM_THRESHOLD > 0:
            abs_mom = abs(raw_momentum)
            if self.SOFT_DAMPEN:
                # Linear ramp: proportional signal below threshold, full above
                scale = min(1.0, abs_mom / self.MOMENTUM_THRESHOLD)
                momentum = raw_momentum * scale
            else:
                # Binary cutoff (original)
                momentum = raw_momentum if abs_mom >= self.MOMENTUM_THRESHOLD else 0.0
        else:
            momentum = raw_momentum

        # Regime-aware inventory penalty
        if self.ADAPTIVE_IP and self.MOMENTUM_THRESHOLD > 0:
            abs_mom = abs(raw_momentum)
            if abs_mom < self.MOMENTUM_THRESHOLD:
                inv_pen = self.INV_PENALTY_HIGH
            else:
                inv_pen = self.INV_PENALTY
        else:
            inv_pen = self.INV_PENALTY

        fair_adj = (
            slow_ema
            + self.MOMENTUM_WEIGHT * momentum
            - inv_pen * position
        )

        orders = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        buy_margin = self.TAKE_MARGIN
        sell_margin = self.TAKE_MARGIN
        if pos > 0:
            sell_margin = 0.0
        if pos < 0:
            buy_margin = 0.0

        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp <= fair_adj - buy_margin:
                size = min(sv, max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
                pos += size
            elif sp <= fair_adj and position < 0:
                size = min(sv, abs(position), max_buy)
                if size > 0:
                    orders.append(Order("TOMATOES", sp, size))
                    max_buy -= size
                    pos += size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp >= fair_adj + sell_margin:
                size = min(bv, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
                pos -= size
            elif bp >= fair_adj and position > 0:
                size = min(bv, position, max_sell)
                if size > 0:
                    orders.append(Order("TOMATOES", bp, -size))
                    max_sell -= size
                    pos -= size

        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid:
                bid_price = max(bid_price, overbid)
                break
            elif bp < wall_mid:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > wall_mid:
                ask_price = min(ask_price, underbid)
                break
            elif sp > wall_mid:
                ask_price = min(ask_price, sp)
                break

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders, fast_ema, slow_ema, warmup_ticks'''


def write_variant(mw, ip, ip_high, thr, soft, adaptive_ip):
    """Splice customized TomatoesMM into bestfornow.py."""
    block = TOMATOES_TEMPLATE.format(
        mw=mw, ip=ip, ip_high=ip_high, thr=thr,
        soft=soft, adaptive_ip=adaptive_ip,
    )
    # Replace TomatoesMM class in ORIGINAL
    src = ORIGINAL
    # Find and replace the class
    pattern = r"class TomatoesMM:.*?(?=\nclass Trader:)"
    src = re.sub(pattern, block + "\n\n", src, flags=re.DOTALL)
    with open(TRADER, "w") as f:
        f.write(src)


def run_backtest():
    result = subprocess.run(
        ["bash", os.path.join(ROOT, "run_rust_backtest.sh"), "bestfornow.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    out = result.stdout
    sub_pnl = d1_pnl = d2_pnl = tom_sub = emr_sub = None
    sub_run_dir = None
    for line in out.strip().split("\n"):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "SUB":
            sub_pnl = float(parts[4])
            sub_run_dir = parts[5]
        elif parts[0] == "D-1":
            d1_pnl = float(parts[4])
        elif parts[0] == "D-2":
            d2_pnl = float(parts[4])
        elif parts[0] == "TOM":
            tom_sub = float(parts[3])
        elif parts[0] == "EMR":
            emr_sub = float(parts[3])

    min_tom = 0.0
    if sub_run_dir:
        log_path = os.path.join(RUST_BT, sub_run_dir, "submission.log")
        if os.path.exists(log_path):
            with open(log_path) as f:
                data = json.load(f)
            activities = data.get("activitiesLog", "")
            if isinstance(activities, str):
                for ln in activities.strip().split("\n"):
                    p = ln.split(";")
                    if len(p) < 4 or p[1] == "timestamp":
                        continue
                    if p[2] == "TOMATOES":
                        pnl = float(p[-1])
                        min_tom = min(min_tom, pnl)
    return {
        "sub": sub_pnl, "d1": d1_pnl, "d2": d2_pnl,
        "tom_sub": tom_sub, "emr_sub": emr_sub,
        "min_tom": min_tom,
    }


def fmt(val, w=8):
    return " " * w if val is None else f"{val:>{w}.1f}"


HDR = f"{'Var':<6} {'MW':>5} {'IP':>5} {'IPhi':>5} {'Thr':>5} {'Soft':>5} {'AdIP':>5} | {'SUB':>8} {'TOM':>8} {'MinTOM':>8} {'D1':>10} {'D2':>10}"
SEP = "-" * len(HDR)
all_results = []


def test(label, mw, ip, ip_high, thr, soft, adaptive_ip):
    write_variant(mw, ip, ip_high, thr, soft, adaptive_ip)
    r = run_backtest()
    row = {"label": label, "mw": mw, "ip": ip, "ip_high": ip_high,
           "thr": thr, "soft": soft, "adaptive_ip": adaptive_ip, **r}
    all_results.append(row)
    s = "Y" if soft else "N"
    a = "Y" if adaptive_ip else "N"
    print(f"{label:<6} {mw:>5.2f} {ip:>5.3f} {ip_high:>5.3f} {thr:>5.2f} {s:>5} {a:>5} | "
          f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")
    return r


print(SEP)
print(HDR)
print(SEP)

# ── Baselines ──
print("\n── Baselines ──")
# Green: no threshold, no IP
test("GREEN", 0.5, 0.0, 0.0, 0.0, False, False)
# Purple: binary threshold + IP=0.02
test("PURPL", 0.5, 0.02, 0.02, 0.60, False, False)

# ── Variant G: Soft dampening (linear ramp), same params as purple ──
print("\n── G: Soft dampening (replaces binary threshold) ──")
for thr in [0.4, 0.5, 0.6, 0.75, 1.0, 1.5, 2.0]:
    test("G", 0.5, 0.02, 0.02, thr, True, False)

# ── Variant H: Adaptive IP (higher IP in low-momentum regime) ──
print("\n── H: Adaptive IP (binary threshold, adaptive penalty) ──")
for ip_high in [0.03, 0.05, 0.08, 0.10, 0.15]:
    test("H", 0.5, 0.02, ip_high, 0.60, False, True)

# ── Variant I: Soft dampening + Adaptive IP ──
print("\n── I: Soft dampening + Adaptive IP ──")
for thr in [0.5, 0.75, 1.0, 1.5]:
    for ip_high in [0.03, 0.05, 0.08, 0.10]:
        test("I", 0.5, 0.02, ip_high, thr, True, True)

# ── Variant J: Soft dampening + reduced MW ──
print("\n── J: Soft dampening + reduced MW (extra robustness) ──")
for mw in [0.3, 0.35, 0.4, 0.45]:
    for thr in [0.75, 1.0, 1.5]:
        test("J", mw, 0.02, 0.02, thr, True, False)

# ── Summary ──
print("\n" + "=" * len(HDR))
print("TOP 15 BY SUB PnL:")
print(SEP)
print(HDR)
print(SEP)
top = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)[:15]
for r in top:
    s = "Y" if r["soft"] else "N"
    a = "Y" if r["adaptive_ip"] else "N"
    print(f"{r['label']:<6} {r['mw']:>5.2f} {r['ip']:>5.3f} {r['ip_high']:>5.3f} {r['thr']:>5.2f} {s:>5} {a:>5} | "
          f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")

# Best with soft dampening
best_soft = sorted([r for r in all_results if r.get("soft")],
                   key=lambda r: r["sub"] or -9999, reverse=True)
if best_soft:
    b = best_soft[0]
    print(f"\nBEST SOFT: {b['label']} MW={b['mw']} IP={b['ip']} IPhi={b['ip_high']} "
          f"Thr={b['thr']} Adaptive={b['adaptive_ip']} → SUB={b['sub']} TOM={b['tom_sub']} MinTOM={b['min_tom']}")

with open(os.path.join(ROOT, "sweep_dip_fix_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

with open(TRADER, "w") as f:
    f.write(ORIGINAL)
print("\nOriginal bestfornow.py restored.")
