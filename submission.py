from datamodel import Order, OrderDepth, TradingState
from dataclasses import dataclass
from typing import Dict, List, Tuple
import json


@dataclass
class EmeraldConfig:
    symbol: str = "EMERALDS"
    fair_value: int = 10000
    position_limit: int = 20
    soft_inventory_limit: int = 12
    base_quote_size: int = 6
    inventory_step: int = 5


class EmeraldMarketMaker:
    """
    EMERALDS market maker strategy.

    Logic per timestep:
    1. Buy asks below fair
    2. Sell bids above fair
    3. Flatten stretched inventory at fair
    4. Quote passively inside the spread
    5. Skew quotes based on inventory
    """

    def __init__(self, config: EmeraldConfig | None = None):
        self.config = config or EmeraldConfig()

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        cfg = self.config
        fair = cfg.fair_value
        current_pos = position

        buy_orders: Dict[int, int] = order_depth.buy_orders or {}
        sell_orders: Dict[int, int] = order_depth.sell_orders or {}

        # 1. Take favorable asks
        for ask_price in sorted(sell_orders.keys()):
            if ask_price >= fair:
                break

            ask_vol = -sell_orders[ask_price]
            buy_capacity = cfg.position_limit - current_pos
            trade_size = min(ask_vol, buy_capacity)

            if trade_size > 0:
                orders.append(Order(cfg.symbol, ask_price, trade_size))
                current_pos += trade_size

        # 2. Take favorable bids
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break

            bid_vol = buy_orders[bid_price]
            sell_capacity = cfg.position_limit + current_pos
            trade_size = min(bid_vol, sell_capacity)

            if trade_size > 0:
                orders.append(Order(cfg.symbol, bid_price, -trade_size))
                current_pos -= trade_size

        # 3. Flatten inventory at fair if stretched
        if current_pos > cfg.soft_inventory_limit and fair in buy_orders:
            trade_size = min(buy_orders[fair], current_pos - cfg.soft_inventory_limit)
            if trade_size > 0:
                orders.append(Order(cfg.symbol, fair, -trade_size))
                current_pos -= trade_size

        if current_pos < -cfg.soft_inventory_limit and fair in sell_orders:
            trade_size = min(-sell_orders[fair], -cfg.soft_inventory_limit - current_pos)
            if trade_size > 0:
                orders.append(Order(cfg.symbol, fair, trade_size))
                current_pos += trade_size

        # 4. Passive quoting inside spread
        best_bid = max(buy_orders.keys()) if buy_orders else fair - 1
        best_ask = min(sell_orders.keys()) if sell_orders else fair + 1

        bid_quote = min(best_bid + 1, fair - 1)
        ask_quote = max(best_ask - 1, fair + 1)

        # 5. Inventory skew
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety fallback
        if bid_quote >= ask_quote:
            bid_quote = fair - 1
            ask_quote = fair + 1

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))

        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        return orders


@dataclass
class TomatoesConfig:
    symbol: str = "TOMATOES"
    position_limit: int = 20

    # Inventory controls
    soft_inventory_limit: int = 12
    base_quote_size: int = 5
    inventory_step: int = 5

    # Fair value controls
    ema_alpha: float = 0.25

    # Trading thresholds
    take_edge: int = 2
    quote_edge: int = 3

    # Max inventory we are willing to accumulate when taking
    target_take_position: int = 16


class TomatoesWallMidMarketMaker:
    """
    TOMATOES strategy inspired by the repo's KELP style, but adapted to a
    stronger market making framework.

    Core ideas:
    1. Estimate fair value from wall mid
    2. Smooth fair value using traderData EMA
    3. Aggressively take obvious dislocations from fair
    4. Passively quote around fair
    5. Skew quotes to control inventory
    """

    def __init__(self, config: TomatoesConfig | None = None):
        self.config = config or TomatoesConfig()

    def _load_trader_data(self, trader_data: str) -> Dict:
        if not trader_data:
            return {}
        try:
            return json.loads(trader_data)
        except Exception:
            return {}

    def _get_book(self, order_depth: OrderDepth) -> Tuple[Dict[int, int], Dict[int, int]]:
        buy_orders = order_depth.buy_orders or {}
        sell_orders = order_depth.sell_orders or {}
        return buy_orders, sell_orders

    def _get_best_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, int | None]:
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        return best_bid, best_ask

    def _get_wall_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, int | None, float | None]:
        """
        Repo style wall estimator:
        bid wall = lowest visible buy price
        ask wall = highest visible sell price
        wall mid = average of those two

        This follows the logic you preferred from the repo worldview.
        """
        bid_wall = min(buy_orders.keys()) if buy_orders else None
        ask_wall = max(sell_orders.keys()) if sell_orders else None

        if bid_wall is None or ask_wall is None:
            return bid_wall, ask_wall, None

        return bid_wall, ask_wall, (bid_wall + ask_wall) / 2

    def _update_ema(self, previous: float | None, value: float, alpha: float) -> float:
        if previous is None:
            return value
        return alpha * value + (1 - alpha) * previous

    def generate_orders(
        self, order_depth: OrderDepth, position: int, trader_data: str
    ) -> Tuple[List[Order], str]:
        orders: List[Order] = []
        cfg = self.config
        current_pos = position

        data = self._load_trader_data(trader_data)
        buy_orders, sell_orders = self._get_book(order_depth)
        best_bid, best_ask = self._get_best_prices(buy_orders, sell_orders)
        bid_wall, ask_wall, wall_mid = self._get_wall_prices(buy_orders, sell_orders)

        if wall_mid is None:
            # Fallback to top of book midpoint if available
            if best_bid is not None and best_ask is not None:
                wall_mid = (best_bid + best_ask) / 2
            else:
                return [], trader_data

        prev_fair = data.get("tomatoes_fair_ema")
        fair = self._update_ema(prev_fair, wall_mid, cfg.ema_alpha)
        data["tomatoes_fair_ema"] = fair

        fair_int = round(fair)

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        # 1. Take favorable asks below fair by enough margin
        for ask_price in sorted(sell_orders.keys()):
            if ask_price > fair_int - cfg.take_edge:
                break

            ask_vol = -sell_orders[ask_price]
            buy_capacity = min(
                cfg.position_limit - current_pos,
                cfg.target_take_position - current_pos,
            )
            trade_size = min(ask_vol, max(0, buy_capacity))

            if trade_size > 0:
                orders.append(Order(cfg.symbol, ask_price, trade_size))
                current_pos += trade_size

        # 2. Take favorable bids above fair by enough margin
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price < fair_int + cfg.take_edge:
                break

            bid_vol = buy_orders[bid_price]
            sell_capacity = min(
                cfg.position_limit + current_pos,
                cfg.target_take_position + current_pos,
            )
            trade_size = min(bid_vol, max(0, sell_capacity))

            if trade_size > 0:
                orders.append(Order(cfg.symbol, bid_price, -trade_size))
                current_pos -= trade_size

        # Refresh capacities after taking
        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        # 3. Inventory flattening around fair when stretched
        if current_pos > cfg.soft_inventory_limit and best_bid is not None:
            flatten_size = min(
                best_bid and buy_orders.get(best_bid, 0),
                current_pos - cfg.soft_inventory_limit,
            )
            if flatten_size > 0 and best_bid >= fair_int:
                orders.append(Order(cfg.symbol, best_bid, -flatten_size))
                current_pos -= flatten_size

        if current_pos < -cfg.soft_inventory_limit and best_ask is not None:
            flatten_size = min(
                -sell_orders.get(best_ask, 0),
                -cfg.soft_inventory_limit - current_pos,
            )
            if flatten_size > 0 and best_ask <= fair_int:
                orders.append(Order(cfg.symbol, best_ask, flatten_size))
                current_pos += flatten_size

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        # 4. Passive quoting around fair
        if best_bid is None:
            best_bid = fair_int - cfg.quote_edge
        if best_ask is None:
            best_ask = fair_int + cfg.quote_edge

        bid_quote = min(best_bid + 1, fair_int - cfg.quote_edge)
        ask_quote = max(best_ask - 1, fair_int + cfg.quote_edge)

        # 5. Inventory skew
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety: maintain a valid spread
        if bid_quote >= ask_quote:
            bid_quote = fair_int - 1
            ask_quote = fair_int + 1

        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))

        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        new_trader_data = json.dumps(data)
        return orders, new_trader_data


class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS and TOMATOES.
    """

    def __init__(self):
        self.emeralds_mm = EmeraldMarketMaker(
            EmeraldConfig(
                symbol="EMERALDS",
                fair_value=10000,
                position_limit=20,
                soft_inventory_limit=12,
                base_quote_size=6,
                inventory_step=5,
            )
        )

        self.tomatoes_mm = TomatoesWallMidMarketMaker(
            TomatoesConfig(
                symbol="TOMATOES",
                position_limit=20,
                soft_inventory_limit=12,
                base_quote_size=5,
                inventory_step=5,
                ema_alpha=0.25,
                take_edge=2,
                quote_edge=3,
                target_take_position=16,
            )
        )

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}
        trader_data_out = {}

        # Load previous traderData once so strategies can extend it
        try:
            existing_data = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            existing_data = {}

        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]

            emeralds_orders = self.emeralds_mm.generate_orders(
                emeralds_order_depth,
                emeralds_position,
            )

            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders

        trader_data_out.update(existing_data)

        if "TOMATOES" in state.order_depths:
            tomatoes_position = state.position.get("TOMATOES", 0)
            tomatoes_order_depth = state.order_depths["TOMATOES"]

            tomatoes_orders, tomatoes_data = self.tomatoes_mm.generate_orders(
                tomatoes_order_depth,
                tomatoes_position,
                json.dumps(trader_data_out),
            )

            try:
                trader_data_out.update(json.loads(tomatoes_data))
            except Exception:
                pass

            if tomatoes_orders:
                orders["TOMATOES"] = tomatoes_orders

        conversions = 0
        trader_data = json.dumps(trader_data_out)

        return orders, conversions, trader_data