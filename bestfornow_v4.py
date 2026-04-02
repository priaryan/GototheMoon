from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """
    EMERALDS market maker, combining wall-mid's proven wide quotes
    with added taking at fair value.
    
    v2 wall-mid for EMERALDS: D-2=7,140, D-1=7,609 (total 14,749)
    
    Strategy:
    - TAKE anything below 10000 (buy) or above 10000 (sell)
    - MAKE at the same prices wall-mid would (wide quotes)
    """

    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        raw_buys: Dict[int, int] = depth.buy_orders or {}
        raw_sells: Dict[int, int] = depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        fair = self.FAIR
        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # ── TAKE: buy asks < fair, sell bids > fair ──
        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp < fair:
                size = min(sv, max_buy)
                orders.append(Order("EMERALDS", sp, size))
                max_buy -= size
                pos += size
            elif sp == fair and pos < 0:
                # flatten short at fair
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
            elif bp == fair and pos > 0:
                # flatten long at fair
                size = min(bv, pos, max_sell)
                if size > 0:
                    orders.append(Order("EMERALDS", bp, -size))
                    max_sell -= size
                    pos -= size

        # ── MAKE: Use wall-mid style (proven best) ──
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)

        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        # Overbid: improve on the best bid still under fair
        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < fair:
                bid_price = max(bid_price, overbid)
                break
            elif bp < fair:
                bid_price = max(bid_price, bp)
                break

        # Underbid: improve on the best ask still over fair
        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > fair:
                ask_price = min(ask_price, underbid)
                break
            elif sp > fair:
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
    TOMATOES: Wall-mid strategy — proven best on Rust backtester.
    Identical to v2 (which matches bestfornow.py).
    """

    LIMIT = POS_LIMITS["TOMATOES"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        raw_buys: Dict[int, int] = depth.buy_orders or {}
        raw_sells: Dict[int, int] = depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        orders: List[Order] = []
        max_buy = self.LIMIT - position
        max_sell = self.LIMIT + position

        # TAKING
        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp <= wall_mid - 1:
                size = min(sv, max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
            elif sp <= wall_mid and position < 0:
                size = min(sv, abs(position), max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp >= wall_mid + 1:
                size = min(bv, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
            elif bp >= wall_mid and position > 0:
                size = min(bv, position, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size

        # MAKING
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

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            orders["TOMATOES"] = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"], pos
            )

        return orders, 0, ""
