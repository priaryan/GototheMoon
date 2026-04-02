from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """
    EMERALDS: fair = 10000, extremely stable.
    
    Try wider quotes than v3 but tighter than v2:
    Quote at 9997/10003 (6-tick spread, 3 ticks from fair).
    This should be tighter than wall-mid's 9993/10007 but wide enough to get fills.
    Also take aggressively at/near fair.
    """

    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        buy_orders = depth.buy_orders or {}
        sell_orders = depth.sell_orders or {}
        fair = self.FAIR
        pos = position

        # TAKE — buy any ask < fair, sell any bid > fair
        for ask_price in sorted(sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_vol = abs(sell_orders[ask_price])
            can_buy = self.LIMIT - pos
            size = min(ask_vol, can_buy)
            if size > 0:
                orders.append(Order("EMERALDS", ask_price, size))
                pos += size

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_vol = abs(buy_orders[bid_price])
            can_sell = self.LIMIT + pos
            size = min(bid_vol, can_sell)
            if size > 0:
                orders.append(Order("EMERALDS", bid_price, -size))
                pos -= size

        # FLATTEN at fair
        if pos > 0 and fair in buy_orders:
            size = min(abs(buy_orders[fair]), pos)
            if size > 0:
                orders.append(Order("EMERALDS", fair, -size))
                pos -= size
        elif pos < 0 and fair in sell_orders:
            size = min(abs(sell_orders[fair]), abs(pos))
            if size > 0:
                orders.append(Order("EMERALDS", fair, size))
                pos += size

        # MAKE — quote at fair-3/fair+3 with inventory skew
        bid_quote = fair - 3   # 9997
        ask_quote = fair + 3   # 10003

        skew = pos // 5
        bid_quote -= skew
        ask_quote -= skew

        bid_quote = min(bid_quote, fair - 1)
        ask_quote = max(ask_quote, fair + 1)

        if bid_quote >= ask_quote:
            bid_quote = fair - 1
            ask_quote = fair + 1

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("EMERALDS", bid_quote, max_buy))
        if max_sell > 0:
            orders.append(Order("EMERALDS", ask_quote, -max_sell))

        return orders


class TomatoesMM:
    """
    TOMATOES: Wall-mid strategy — proven best on Rust backtester.
    Identical to bestfornow.py / bestfornow_v2.py.
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
            em_orders = self.emeralds.generate_orders(state.order_depths["EMERALDS"], pos)
            if em_orders:
                orders["EMERALDS"] = em_orders

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders = self.tomatoes.generate_orders(state.order_depths["TOMATOES"], pos)
            if tom_orders:
                orders["TOMATOES"] = tom_orders

        return orders, 0, ""
