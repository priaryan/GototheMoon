"""
bestfornow_v7.py

EMA fair value with inventory aware taking.

Main update for TOMATOES:
detect short lived shock regimes using recent wall mid history,
then switch to a more defensive market making mode.

Sweep-optimised params (Python backtester: 2731 → 3038):
  Base: ema=0.15, inv_pen=0.01, take=0.2, flatten=0, no passive cap
  Shock: move=2.0, vol=0.6, rev=1.5, take_mult=2.0, passive=1, keep both sides
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
    TOMATOES: EMA wall-mid making + inventory-penalised taking
    with a shock regime detector.

    Normal mode:
    1. use EMA wall mid as fair anchor
    2. take moderate dislocations
    3. make around wall mid

    Shock mode:
    1. detect large recent moves / realized volatility / sharp reversals
    2. widen take thresholds
    3. reduce passive size
    4. disable passive quoting on the risky side
    5. flatten inventory earlier
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    EMA_ALPHA = 0.15            # sweep: faster EMA (was 0.10)
    INV_PENALTY = 0.01            # sweep: lighter penalty (was 0.02)

    TAKE_MARGIN = 0.2             # sweep: tighter margin (was 0.3)
    FLATTEN_THRESH = 0            # sweep: always flatten (was 3)

    HISTORY_LEN = 8
    SHOCK_MOVE_THRESH = 2.0       # sweep: calibrated to data (was 4.0)
    SHOCK_VOL_THRESH = 0.6        # sweep: calibrated to data (was 1.75)
    SHOCK_REVERSAL_THRESH = 1.5   # sweep: calibrated to data (was 2.5)

    SHOCK_TAKE_MULTIPLIER = 2.0   # sweep: less extreme (was 4.0)
    SHOCK_PASSIVE_SIZE = 1        # sweep: minimal passive in shock (was 2)
    SHOCK_FLATTEN_THRESH = 0      # same
    SHOCK_DISABLE_RISKY = False   # sweep: keep quoting both sides (was True)

    def _compute_regime(self, mids: List[float]) -> str:
        if len(mids) < 4:
            return "normal"

        last = mids[-1]
        prev = mids[-2]
        short_move = last - prev
        medium_move = last - mids[-4]

        diffs = [mids[i] - mids[i - 1] for i in range(1, len(mids))]
        realized_vol = sum(abs(x) for x in diffs[-5:]) / max(1, len(diffs[-5:]))

        prev_medium = mids[-2] - mids[-5] if len(mids) >= 5 else 0.0
        reversal = (
            abs(short_move) >= self.SHOCK_REVERSAL_THRESH
            and abs(prev_medium) >= self.SHOCK_REVERSAL_THRESH
            and short_move * prev_medium < 0
        )

        large_move = abs(medium_move) >= self.SHOCK_MOVE_THRESH
        high_vol = realized_vol >= self.SHOCK_VOL_THRESH

        if reversal or (large_move and high_vol):
            return "shock"
        return "normal"

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        ema_wm,
        mid_history: List[float],
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm, mid_history, "normal"

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema_wm

        mid_history = (mid_history + [wall_mid])[-self.HISTORY_LEN :]
        regime = self._compute_regime(mid_history)

        fair_adj = ema_wm - self.INV_PENALTY * position

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        buy_margin = self.TAKE_MARGIN
        sell_margin = self.TAKE_MARGIN
        flatten_thresh = self.FLATTEN_THRESH

        if regime == "shock":
            buy_margin *= self.SHOCK_TAKE_MULTIPLIER
            sell_margin *= self.SHOCK_TAKE_MULTIPLIER
            flatten_thresh = self.SHOCK_FLATTEN_THRESH

        if pos > flatten_thresh:
            sell_margin = 0.0 if regime == "normal" else min(sell_margin, 0.25)
        if pos < -flatten_thresh:
            buy_margin = 0.0 if regime == "normal" else min(buy_margin, 0.25)

        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break

            if regime == "shock" and self.SHOCK_DISABLE_RISKY and pos >= flatten_thresh:
                break

            if sp <= fair_adj - buy_margin:
                size = min(sv, max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
                pos += size
            elif sp <= fair_adj and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0:
                    orders.append(Order("TOMATOES", sp, size))
                    max_buy -= size
                    pos += size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break

            if regime == "shock" and self.SHOCK_DISABLE_RISKY and pos <= -flatten_thresh:
                break

            if bp >= fair_adj + sell_margin:
                size = min(bv, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
                pos -= size
            elif bp >= fair_adj and pos > 0:
                size = min(bv, pos, max_sell)
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

        passive_buy_size = max_buy
        passive_sell_size = max_sell

        if regime == "shock":
            passive_buy_size = min(passive_buy_size, self.SHOCK_PASSIVE_SIZE)
            passive_sell_size = min(passive_sell_size, self.SHOCK_PASSIVE_SIZE)

            if self.SHOCK_DISABLE_RISKY:
                if pos > 0:
                    passive_buy_size = 0
                    ask_price = max(best_bid, min(ask_price, best_ask))
                elif pos < 0:
                    passive_sell_size = 0
                    bid_price = min(best_ask, max(bid_price, best_bid))

        if bid_price < ask_price:
            if passive_buy_size > 0:
                orders.append(Order("TOMATOES", bid_price, passive_buy_size))
            if passive_sell_size > 0:
                orders.append(Order("TOMATOES", ask_price, -passive_sell_size))
        else:
            if pos > 0 and passive_sell_size > 0:
                orders.append(Order("TOMATOES", best_ask, -passive_sell_size))
            elif pos < 0 and passive_buy_size > 0:
                orders.append(Order("TOMATOES", best_bid, passive_buy_size))

        return orders, ema_wm, mid_history, regime


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

        ema_wm = td.get("ema_wm")
        tomato_mid_history = td.get("tomato_mid_history", [])
        tomato_regime = td.get("tomato_regime", "normal")

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, ema_wm, tomato_mid_history, tomato_regime = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"],
                pos,
                ema_wm,
                tomato_mid_history,
            )
            orders["TOMATOES"] = tom_orders

        td["ema_wm"] = ema_wm
        td["tomato_mid_history"] = tomato_mid_history
        td["tomato_regime"] = tomato_regime

        return orders, 0, json.dumps(td)