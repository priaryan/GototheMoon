"""
bestfornow_v7.py — v6 + quadratic penalty, make-skew, spread-adaptive margin.

Changes from v6:
  1. Quadratic inventory penalty: fair_adj = ema - a*pos - b*pos*|pos|
     Steepens sharply near limits to prevent hitting ±20.
  2. Skew making quotes: shift bid/ask by -round(pos/K) ticks
     Uses the making side to actively flatten inventory.
  3. Spread-adaptive take margin: widen margin when spread is large.
  4. Cap making size on the position-increasing side near limits.
  5. Faster EMA for taking fair value (dual EMA not needed yet — just
     tune alpha; can split later if sweep shows benefit).

EMERALDS unchanged from v6 (no edge on this data).
"""

import json
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """EMERALDS: identical to v6."""
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    INV_PENALTY = 0.05

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        fair = self.FAIR - self.INV_PENALTY * position

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp < fair:
                size = min(sv, max_buy)
                orders.append(Order("EMERALDS", sp, size))
                max_buy -= size
                pos += size
            elif sp <= fair and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0:
                    orders.append(Order("EMERALDS", sp, size))
                    max_buy -= size
                    pos += size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp > fair:
                size = min(bv, max_sell)
                orders.append(Order("EMERALDS", bp, -size))
                max_sell -= size
                pos -= size
            elif bp >= fair and pos > 0:
                size = min(bv, pos, max_sell)
                if size > 0:
                    orders.append(Order("EMERALDS", bp, -size))
                    max_sell -= size
                    pos -= size

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < self.FAIR:
                bid_price = max(bid_price, overbid)
                break
            elif bp < self.FAIR:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > self.FAIR:
                ask_price = min(ask_price, underbid)
                break
            elif sp > self.FAIR:
                ask_price = min(ask_price, sp)
                break

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("EMERALDS", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("EMERALDS", ask_price, -max_sell))

        return orders


class TomatoesMM:
    """
    TOMATOES v7: quadratic penalty + make-skew + spread-adaptive margin.

    fair_adj = ema_wm - LINEAR_PEN * pos - QUAD_PEN * pos * |pos|
    make skew = -round(pos / SKEW_DIV)
    take_margin = base + max(0, spread - SPREAD_NEUTRAL) * SPREAD_SCALE
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    # EMA
    EMA_ALPHA = 0.1

    # Inventory penalty (quadratic)
    LINEAR_PEN = 0.02       # from v6
    QUAD_PEN = 0.003        # new: steepens near limits

    # Taking
    BASE_MARGIN = 0.25      # from v6
    FLATTEN_THRESH = 2      # from v6
    SPREAD_NEUTRAL = 8      # spread at which margin starts growing
    SPREAD_SCALE = 0.1      # extra margin per tick of spread above neutral

    # Making
    SKEW_DIV = 10           # skew = round(pos / SKEW_DIV) ticks
    MAKE_CAP_THRESH = 12    # above this |pos|, cap making on increasing side
    MAKE_CAP_SIZE = 5       # max making size on increasing side when capped

    def generate_orders(self, depth: OrderDepth, position: int, ema_wm) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        spread = best_ask - best_bid

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        # ── EMA ──
        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema_wm

        # ── FIX #1: Quadratic inventory penalty ──
        fair_adj = ema_wm - self.LINEAR_PEN * position - self.QUAD_PEN * position * abs(position)

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # ── FIX #5: Spread-adaptive take margin ──
        extra_margin = max(0, (spread - self.SPREAD_NEUTRAL)) * self.SPREAD_SCALE
        buy_margin = self.BASE_MARGIN + extra_margin
        sell_margin = self.BASE_MARGIN + extra_margin

        # Flatten override (from v6)
        if pos > self.FLATTEN_THRESH:
            sell_margin = 0.0
        if pos < -self.FLATTEN_THRESH:
            buy_margin = 0.0

        # ── TAKE ──
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

        # ── MAKE: wall-mid style + FIX #2 skew + FIX #3 cap ──
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

        # FIX #2: Skew making quotes to flatten inventory
        skew = round(pos / self.SKEW_DIV)
        bid_price -= skew
        ask_price -= skew

        # Clamp: don't cross wall_mid (bid shouldn't be above mid, ask shouldn't be below)
        bid_price = min(bid_price, int(wall_mid) - 1)
        ask_price = max(ask_price, int(wall_mid) + 1)

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # FIX #3: Cap making size on position-increasing side near limits
        make_buy = max_buy
        make_sell = max_sell
        if pos > self.MAKE_CAP_THRESH:
            make_buy = min(make_buy, self.MAKE_CAP_SIZE)
        if pos < -self.MAKE_CAP_THRESH:
            make_sell = min(make_sell, self.MAKE_CAP_SIZE)

        if make_buy > 0:
            orders.append(Order("TOMATOES", bid_price, make_buy))
        if make_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -make_sell))

        return orders, ema_wm


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        # Restore persistent state
        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                pass
        ema_wm = td.get("ema_wm")

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, ema_wm = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"], pos, ema_wm
            )
            orders["TOMATOES"] = tom_orders

        td["ema_wm"] = ema_wm
        return orders, 0, json.dumps(td)
