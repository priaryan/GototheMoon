from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple
import json


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """
    EMERALDS market maker with hardcoded fair value of 10000.
    EMERALDS is extremely stable (std ~0.25, range 9996-10004).
    Book is always 9992/10008 with walls at 9990/10010.
    Profit comes from passive fills by other participants.
    """

    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        buy_orders = depth.buy_orders or {}
        sell_orders = depth.sell_orders or {}
        fair = self.FAIR
        pos = position

        # 1. TAKE — buy asks below fair, sell bids above fair
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

        # 2. CLOSE — flatten when stretched, even at fair
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

        # 3. MAKE — aggressive quotes close to fair
        best_bid = max(buy_orders.keys()) if buy_orders else fair - 2
        best_ask = min(sell_orders.keys()) if sell_orders else fair + 2

        bid_quote = min(best_bid + 1, fair - 1)
        ask_quote = max(best_ask - 1, fair + 1)

        # Inventory skew
        skew = pos // 5
        bid_quote -= skew
        ask_quote -= skew

        # Never trade through fair
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
    TOMATOES market maker with slow EMA fair value tracking.
    TOMATOES trends over time (range ~65 ticks/day) with tick-to-tick
    mean-reversion (autocorr ~ -0.41).
    Uses a slow EMA to avoid chasing noise, then aggressively takes
    and quotes around it.
    """

    LIMIT = POS_LIMITS["TOMATOES"]

    def __init__(self):
        self.ema = None

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        buy_orders = depth.buy_orders or {}
        sell_orders = depth.sell_orders or {}

        if not buy_orders or not sell_orders:
            return []

        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        # Slow EMA for fair value — alpha=0.05 tracks trend without noise
        if self.ema is None:
            self.ema = mid
        else:
            self.ema = 0.05 * mid + 0.95 * self.ema

        fair = round(self.ema)
        pos = position

        # 1. TAKE — buy asks below fair, sell bids above fair
        for ask_price in sorted(sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_vol = abs(sell_orders[ask_price])
            can_buy = self.LIMIT - pos
            size = min(ask_vol, can_buy)
            if size > 0:
                orders.append(Order("TOMATOES", ask_price, size))
                pos += size

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_vol = abs(buy_orders[bid_price])
            can_sell = self.LIMIT + pos
            size = min(bid_vol, can_sell)
            if size > 0:
                orders.append(Order("TOMATOES", bid_price, -size))
                pos -= size

        # 2. CLOSE — flatten stretched inventory at fair
        if pos > 10 and fair in buy_orders:
            size = min(abs(buy_orders[fair]), pos - 10)
            if size > 0:
                orders.append(Order("TOMATOES", fair, -size))
                pos -= size
        elif pos < -10 and fair in sell_orders:
            size = min(abs(sell_orders[fair]), abs(pos) - 10)
            if size > 0:
                orders.append(Order("TOMATOES", fair, size))
                pos += size

        # 3. MAKE — passive quotes with inventory skew
        bid_quote = min(best_bid + 1, fair - 1)
        ask_quote = max(best_ask - 1, fair + 1)

        skew = pos // 4
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
            orders.append(Order("TOMATOES", bid_quote, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_quote, -max_sell))

        return orders

    def get_state(self) -> dict:
        return {"ema": self.ema}

    def load_state(self, data: dict):
        if data and "ema" in data:
            self.ema = data["ema"]


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
                self.tomatoes.load_state(saved.get("TOMATOES", {}))
            except (json.JSONDecodeError, AttributeError):
                pass

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

        trader_data = json.dumps({"TOMATOES": self.tomatoes.get_state()})
        return orders, 0, trader_data
