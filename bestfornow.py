"""
bestfornow_v7.py

EMERALDS: wall mid making with inventory penalised taking.
TOMATOES: Dual EMA momentum signal with a startup warmup phase.

Warmup behavior for TOMATOES:
  - Update fast and slow EMAs
  - Do not trade for the first few observations
  - After warmup, resume the original strategy unchanged
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
    EMERALDS: wall mid making + inventory penalised taking.
    fair_adj = 10000 - 0.05 * position
    """
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    INV_PENALTY = 0.0

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
    TOMATOES: Dual EMA momentum with regime-aware inventory management.

    fair_adj = slow_ema + MOMENTUM_WEIGHT * scaled_momentum - inv_pen * position

    Soft dampening: scales momentum linearly below MOMENTUM_THRESHOLD
      instead of a binary cutoff, avoiding signal discontinuities.
    Adaptive IP: uses higher inventory penalty (INV_PENALTY_HIGH) in
      low-momentum regimes where chop risk dominates.

    Warmup: update EMA state only, no orders for first WARMUP_TICKS ticks.
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    FAST_ALPHA = 0.10
    SLOW_ALPHA = 0.02

    MOMENTUM_WEIGHT = 0.5

    TAKE_MARGIN = 0.0
    INV_PENALTY = 0.02       # used when momentum is strong (trending)
    INV_PENALTY_HIGH = 0.08  # used when momentum is weak (choppy)
    MOMENTUM_THRESHOLD = 0.75

    WARMUP_TICKS = 5

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        fast_ema,
        slow_ema,
        warmup_ticks: int,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], fast_ema, slow_ema, warmup_ticks

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

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
        abs_mom = abs(raw_momentum)

        # Soft dampening: linear ramp from 0 to full at threshold
        scale = min(1.0, abs_mom / self.MOMENTUM_THRESHOLD)
        momentum = raw_momentum * scale

        # Adaptive inventory penalty: stronger in low-momentum (choppy) regime
        if abs_mom < self.MOMENTUM_THRESHOLD:
            inv_pen = self.INV_PENALTY_HIGH
        else:
            inv_pen = self.INV_PENALTY

        fair_adj = (
            slow_ema
            + self.MOMENTUM_WEIGHT * momentum
            - inv_pen * position
        )

        orders: List[Order] = []
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

        return orders, fast_ema, slow_ema, warmup_ticks


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                pass

        fast_ema = td.get("fast_ema")
        slow_ema = td.get("slow_ema")
        tomato_warmup_ticks = td.get("tomato_warmup_ticks", 0)

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, fast_ema, slow_ema, tomato_warmup_ticks = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"],
                pos,
                fast_ema,
                slow_ema,
                tomato_warmup_ticks,
            )
            orders["TOMATOES"] = tom_orders

        td["fast_ema"] = fast_ema
        td["slow_ema"] = slow_ema
        td["tomato_warmup_ticks"] = tomato_warmup_ticks

        return orders, 0, json.dumps(td)