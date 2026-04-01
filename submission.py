from datamodel import Order, OrderDepth, TradingState
from dataclasses import dataclass
from typing import Dict, List, Tuple
import json


@dataclass
class ProductConfig:
    symbol: str
    position_limit: int = 20

    # Fair value
    use_volume_wall: bool = True
    top_mid_weight: float = 0.35
    wall_mid_weight: float = 0.65

    # Taking
    take_edge: float = 1.0

    # Passive quoting
    base_quote_edge: int = 1
    passive_order_size: int = 6

    # Inventory control
    skew_per_unit: float = 0.08
    flatten_at_fair: bool = True


PRODUCT_CONFIGS: Dict[str, ProductConfig] = {
    "EMERALDS": ProductConfig(
        symbol="EMERALDS",
        position_limit=20,
        use_volume_wall=True,
        top_mid_weight=0.30,
        wall_mid_weight=0.70,
        take_edge=1.0,
        base_quote_edge=1,
        passive_order_size=6,
        skew_per_unit=0.10,
        flatten_at_fair=True,
    ),
    "TOMATOES": ProductConfig(
        symbol="TOMATOES",
        position_limit=20,
        use_volume_wall=True,
        top_mid_weight=0.3,
        wall_mid_weight=0.7,
        take_edge=1.0,
        base_quote_edge=1,
        passive_order_size=5,
        skew_per_unit=0.07,
        flatten_at_fair=True,
    ),
}


class StaticMarketMaker:
    """
    Refined static style market maker.

    Main ideas
    1. Estimate fair from top mid and size wall mid
    2. Take clear mispricings through fair
    3. Flatten inventory at fair when possible
    4. Quote passively around inventory adjusted fair
    5. Cap passive size to reduce noisy inventory swings
    """

    def __init__(self, config: ProductConfig):
        self.config = config

    def _load_trader_data(self, trader_data: str) -> Dict:
        if not trader_data:
            return {}
        try:
            return json.loads(trader_data)
        except Exception:
            return {}

    def _get_top_mid(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
    ) -> float:
        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        return (best_bid + best_ask) / 2.0

    def _get_wall_mid(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
    ) -> float:
        bid_wall = max(buy_orders.items(), key=lambda x: (x[1], x[0]))[0]
        ask_wall = min(sell_orders.items(), key=lambda x: (-x[1], x[0]))[0]
        return (bid_wall + ask_wall) / 2.0

    def _get_fair_value(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
    ) -> float:
        top_mid = self._get_top_mid(buy_orders, sell_orders)

        if not self.config.use_volume_wall:
            return top_mid

        wall_mid = self._get_wall_mid(buy_orders, sell_orders)
        fair = (
            self.config.top_mid_weight * top_mid
            + self.config.wall_mid_weight * wall_mid
        )
        return fair

    def _get_passive_prices(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
        adjusted_fair: float,
    ) -> Tuple[int, int]:
        best_bid = max(buy_orders)
        best_ask = min(sell_orders)

        bid_price = int(adjusted_fair - self.config.base_quote_edge)
        ask_price = int(adjusted_fair + self.config.base_quote_edge)

        bid_price = min(bid_price, best_ask - 1)
        ask_price = max(ask_price, best_bid + 1)

        if bid_price >= ask_price:
            bid_price = best_bid
            ask_price = best_ask

        return bid_price, ask_price

    def generate_orders(
        self,
        order_depth: OrderDepth,
        position: int,
    ) -> List[Order]:
        raw_buys: Dict[int, int] = order_depth.buy_orders or {}
        raw_sells: Dict[int, int] = order_depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        fair = self._get_fair_value(buy_orders, sell_orders)

        inventory_skew = position * self.config.skew_per_unit
        adjusted_fair = fair - inventory_skew

        orders: List[Order] = []

        max_buy = self.config.position_limit - position
        max_sell = self.config.position_limit + position

        # 1. Take asks that are clearly cheap
        for ask_price, ask_volume in sell_orders.items():
            if max_buy <= 0:
                break

            if ask_price < adjusted_fair - self.config.take_edge:
                size = min(ask_volume, max_buy)
                if size > 0:
                    orders.append(Order(self.config.symbol, ask_price, size))
                    max_buy -= size

            elif (
                self.config.flatten_at_fair
                and position < 0
                and ask_price <= fair
            ):
                size = min(ask_volume, abs(position), max_buy)
                if size > 0:
                    orders.append(Order(self.config.symbol, ask_price, size))
                    max_buy -= size

        # 2. Take bids that are clearly rich
        for bid_price, bid_volume in buy_orders.items():
            if max_sell <= 0:
                break

            if bid_price > adjusted_fair + self.config.take_edge:
                size = min(bid_volume, max_sell)
                if size > 0:
                    orders.append(Order(self.config.symbol, bid_price, -size))
                    max_sell -= size

            elif (
                self.config.flatten_at_fair
                and position > 0
                and bid_price >= fair
            ):
                size = min(bid_volume, position, max_sell)
                if size > 0:
                    orders.append(Order(self.config.symbol, bid_price, -size))
                    max_sell -= size

        # 3. Passive quoting with capped size
        bid_price, ask_price = self._get_passive_prices(
            buy_orders,
            sell_orders,
            adjusted_fair,
        )

        passive_buy_size = min(self.config.passive_order_size, max_buy)
        passive_sell_size = min(self.config.passive_order_size, max_sell)

        if passive_buy_size > 0:
            orders.append(Order(self.config.symbol, bid_price, passive_buy_size))

        if passive_sell_size > 0:
            orders.append(Order(self.config.symbol, ask_price, -passive_sell_size))

        return orders


class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS and TOMATOES with a refined static style market maker.
    """

    SYMBOLS = ["EMERALDS", "TOMATOES"]

    def __init__(self):
        self.makers = {
            symbol: StaticMarketMaker(PRODUCT_CONFIGS[symbol])
            for symbol in self.SYMBOLS
        }

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        for symbol in self.SYMBOLS:
            if symbol not in state.order_depths:
                continue

            maker = self.makers[symbol]
            position = state.position.get(symbol, 0)
            order_depth = state.order_depths[symbol]

            orders = maker.generate_orders(order_depth, position)
            if orders:
                result[symbol] = orders

        conversions = 0
        trader_data = ""

        return result, conversions, trader_data