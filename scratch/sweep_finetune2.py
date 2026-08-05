#!/usr/bin/env python3
"""
Fine-tune around the two best dip-fix configurations:
  H: Binary threshold + adaptive IP (best PnL: 2531.5)
  I: Soft dampening + adaptive IP (best balanced: 2530.5, MinTOM=-177)

Focus on finding the right balance of robustness + PnL.
"""
import os, re, subprocess, json

ROOT = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(ROOT, "bestfornow.py")
RUST_BT = os.path.join(ROOT, "..", "prosperity_rust_backtester")

with open(TRADER) as f:
    ORIGINAL = f.read()

TOMATOES_TEMPLATE = '''class TomatoesMM:
    """
    TOMATOES: Dual EMA momentum with regime-aware inventory management.
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    FAST_ALPHA = 0.10
    SLOW_ALPHA = 0.02

    MOMENTUM_WEIGHT = {mw}
    TAKE_MARGIN = 0.0

    INV_PENALTY = {ip}
    INV_PENALTY_HIGH = {ip_high}

    MOMENTUM_THRESHOLD = {thr}
    SOFT_DAMPEN = {soft}
    ADAPTIVE_IP = {adaptive_ip}

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

        if self.MOMENTUM_THRESHOLD > 0:
            abs_mom = abs(raw_momentum)
            if self.SOFT_DAMPEN:
                scale = min(1.0, abs_mom / self.MOMENTUM_THRESHOLD)
                momentum = raw_momentum * scale
            else:
                momentum = raw_momentum if abs_mom >= self.MOMENTUM_THRESHOLD else 0.0
        else:
            momentum = raw_momentum

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
    block = TOMATOES_TEMPLATE.format(
        mw=mw, ip=ip, ip_high=ip_high, thr=thr,
        soft=soft, adaptive_ip=adaptive_ip,
    )
    src = ORIGINAL
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

# ── Fine-tune H: Binary threshold + adaptive IP ──
# Best was: IP_high=0.03, SUB=2531.5
print("\n── H fine: IP_high grid (binary Thr=0.60, IP=0.02) ──")
for ip_high in [0.025, 0.03, 0.035, 0.04, 0.045]:
    test("H", 0.5, 0.02, ip_high, 0.60, False, True)

# Fine-tune threshold for H with best IP_high
print("\n── H fine: Thr grid (IP_high=0.03) ──")
for thr in [0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
    test("H", 0.5, 0.02, 0.03, thr, False, True)

# Fine-tune base IP for H
print("\n── H fine: base IP grid (IP_high=0.03, Thr=0.60) ──")
for ip in [0.01, 0.015, 0.02, 0.025, 0.03]:
    test("H", 0.5, ip, 0.03, 0.60, False, True)

# ── Fine-tune I: Soft dampening + adaptive IP ──
# Best was: IP_high=0.08, Thr=0.75, SUB=2530.5
print("\n── I fine: IP_high grid (soft Thr=0.75, IP=0.02) ──")
for ip_high in [0.06, 0.07, 0.08, 0.09, 0.10]:
    test("I", 0.5, 0.02, ip_high, 0.75, True, True)

print("\n── I fine: Thr grid (IP_high=0.08) ──")
for thr in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    test("I", 0.5, 0.02, 0.08, thr, True, True)

# ── Summary ──
print("\n" + "=" * len(HDR))
print("TOP 10:")
print(SEP)
print(HDR)
print(SEP)
top = sorted(all_results, key=lambda r: r["sub"] or -9999, reverse=True)[:10]
for r in top:
    s = "Y" if r["soft"] else "N"
    a = "Y" if r["adaptive_ip"] else "N"
    print(f"{r['label']:<6} {r['mw']:>5.2f} {r['ip']:>5.3f} {r['ip_high']:>5.3f} {r['thr']:>5.2f} {s:>5} {a:>5} | "
          f"{fmt(r['sub'])} {fmt(r['tom_sub'])} {fmt(r['min_tom'])} {fmt(r['d1'], 10)} {fmt(r['d2'], 10)}")

# Best balanced: good PnL + good drawdown
balanced = [r for r in all_results if (r["min_tom"] or -999) > -185]
if balanced:
    best_bal = max(balanced, key=lambda r: r["sub"] or -9999)
    s = "Y" if best_bal["soft"] else "N"
    a = "Y" if best_bal["adaptive_ip"] else "N"
    print(f"\nBEST BALANCED (MinTOM > -185):")
    print(f"  {best_bal['label']} MW={best_bal['mw']} IP={best_bal['ip']} IPhi={best_bal['ip_high']} "
          f"Thr={best_bal['thr']} Soft={s} Adaptive={a} → SUB={best_bal['sub']} TOM={best_bal['tom_sub']} MinTOM={best_bal['min_tom']}")

with open(os.path.join(ROOT, "sweep_finetune2_results.json"), "w") as f:
    json.dump(all_results, f, indent=2)

with open(TRADER, "w") as f:
    f.write(ORIGINAL)
print("Original bestfornow.py restored.")
