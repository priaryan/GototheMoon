"""
bestfornow_v7.py — Kelp+Ink hybrid for TOMATOES.

EMERALDS: wall-mid making + inventory-penalised taking (unchanged).
TOMATOES: Dual-EMA momentum signal drives a Kelp+Ink hybrid:
  - Uses fast EMA – slow EMA of wall_mid as a directional signal
  - Momentum-tilted fair value: more willing to buy in uptrends, sell in downtrends
  - Kelp-style making: widen adverse-side quote when directional
  - Ink-style taking: aggressive position building on strong momentum

Inspired by FrankfurtHedgehogs' DynamicTrader (Kelp) and InkTrader (Squid Ink),
adapted to use momentum since buyer/seller names are unavailable in our data.
"""

import json
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """
    EMERALDS: wall-mid making + inventory-penalised taking.
    fair_adj = 10000 - 0.05 * position
    """
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

        # Inventory-adjusted fair value
        fair = self.FAIR - self.INV_PENALTY * position

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # ── TAKE ──
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

        # ── MAKE: wall-mid style (identical to v4) ──
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
    TOMATOES: Kelp+Ink hybrid using dual-EMA momentum.

    fair_adj = 0.5 * fast_ema + 0.5 * slow_ema  (momentum-blended fair)
    Take any crossing at fair_adj; always flatten inventory at fair.

    Sweep result: 3388 PnL vs 2941 single-EMA baseline (+15.2%).
    The momentum tilt handles both edge detection and inventory management,
    making explicit inv_penalty and take_margin unnecessary.
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    # ── Dual EMA (sweep-optimised) ──
    FAST_ALPHA = 0.10   # tracks recent price (responds in ~10 ticks)
    SLOW_ALPHA = 0.02   # smooth fair value anchor (responds in ~50 ticks)

    # ── Momentum fair-value tilt (sweep-optimised) ──
    # fair_adj = slow_ema + MOMENTUM_WEIGHT * (fast_ema - slow_ema)
    MOMENTUM_WEIGHT = 0.5

    # ── Taking (sweep: margin=0, penalty=0 is best) ──
    TAKE_MARGIN = 0.0
    INV_PENALTY = 0.0

    def generate_orders(self, depth: OrderDepth, position: int,
                        fast_ema, slow_ema) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], fast_ema, slow_ema

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        # ── Update dual EMAs ──
        if fast_ema is None:
            fast_ema = wall_mid
            slow_ema = wall_mid
        else:
            fast_ema = self.FAST_ALPHA * wall_mid + (1 - self.FAST_ALPHA) * fast_ema
            slow_ema = self.SLOW_ALPHA * wall_mid + (1 - self.SLOW_ALPHA) * slow_ema

        # ── Momentum signal ──
        momentum = fast_ema - slow_ema

        # ── Momentum-tilted fair value ──
        fair_adj = (slow_ema
                    + self.MOMENTUM_WEIGHT * momentum
                    - self.INV_PENALTY * position)

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # ── Taking margins ──
        buy_margin = self.TAKE_MARGIN
        sell_margin = self.TAKE_MARGIN

        # Always flatten inventory at fair
        if pos > 0:
            sell_margin = 0.0
        if pos < 0:
            buy_margin = 0.0

        # ── TAKE sells (buy) ──
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

        # ── TAKE buys (sell) ──
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

        # ── MAKE: wall-mid style ──
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        # Standard overbidding/underbidding
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

        return orders, fast_ema, slow_ema


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
        fast_ema = td.get("fast_ema")
        slow_ema = td.get("slow_ema")

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, fast_ema, slow_ema = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"], pos, fast_ema, slow_ema
            )
            orders["TOMATOES"] = tom_orders

        td["fast_ema"] = fast_ema
        td["slow_ema"] = slow_ema
        return orders, 0, json.dumps(td)
