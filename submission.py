from datamodel import Order, OrderDepth, TradingState
from dataclasses import dataclass
from typing import Dict, List, Tuple
import json


@dataclass
class EmeraldConfig:
    symbol: str = "EMERALDS"
    fair_value: int = 10000
    position_limit: int = 20

    # Fair value blending
    fixed_fair_weight: float = 0.0
    wall_mid_weight: float = 1.0

    # Inventory and quoting controls
    soft_inventory_limit: int = 12
    base_quote_size: int = 6
    inventory_step: int = 5

    # StaticTrader style thresholds
    take_through_edge: int = 1


class EmeraldMarketMaker:
    """
    EMERALDS market maker with StaticTrader style logic, but cleaner and configurable.

    Main ideas:
    1. Infer fair using a blend of fixed fair and wall mid
    2. Take asks through fair
    3. Take bids through fair
    4. Allow trading at fair only when flattening inventory
    5. Quote using wall structure
    6. Keep controlled quote sizing and inventory skew
    """

    def __init__(self, config: EmeraldConfig | None = None):
        self.config = config or EmeraldConfig()

    def _get_book(
        self, order_depth: OrderDepth
    ) -> Tuple[Dict[int, int], Dict[int, int]]:
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
    ) -> Tuple[int | None, float | None, int | None]:
        """
        Match the repo worldview:
        bid wall = lowest visible buy price
        ask wall = highest visible sell price
        wall mid = average of the two
        """
        bid_wall = min(buy_orders.keys()) if buy_orders else None
        ask_wall = max(sell_orders.keys()) if sell_orders else None

        if bid_wall is None or ask_wall is None:
            return bid_wall, None, ask_wall

        wall_mid = (bid_wall + ask_wall) / 2
        return bid_wall, wall_mid, ask_wall

    def _compute_fair(
        self,
        fixed_fair: int,
        wall_mid: float | None,
        best_bid: int | None,
        best_ask: int | None,
    ) -> float:
        cfg = self.config

        if wall_mid is None:
            if best_bid is not None and best_ask is not None:
                wall_mid = (best_bid + best_ask) / 2
            else:
                wall_mid = float(fixed_fair)

        total_weight = cfg.fixed_fair_weight + cfg.wall_mid_weight
        if total_weight <= 0:
            return float(fixed_fair)

        fair = (
            cfg.fixed_fair_weight * fixed_fair
            + cfg.wall_mid_weight * wall_mid
        ) / total_weight

        return fair

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        cfg = self.config
        current_pos = position

        buy_orders, sell_orders = self._get_book(order_depth)
        best_bid, best_ask = self._get_best_prices(buy_orders, sell_orders)
        bid_wall, wall_mid, ask_wall = self._get_wall_prices(buy_orders, sell_orders)

        fair = self._compute_fair(
            fixed_fair=cfg.fair_value,
            wall_mid=wall_mid,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        fair_floor = int(fair)
        fair_ceil = int(fair) if fair == int(fair) else int(fair) + 1

        ##########################################################
        # 1. TAKING
        ##########################################################

        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]

            if ask_price <= fair - cfg.take_through_edge:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

            elif ask_price <= fair and current_pos < 0:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, abs(current_pos), buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]

            if bid_price >= fair + cfg.take_through_edge:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

            elif bid_price >= fair and current_pos > 0:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, current_pos, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

        ##########################################################
        # 2. MAKING
        ##########################################################

        if bid_wall is None or ask_wall is None:
            return orders

        bid_quote = int(bid_wall + 1)
        ask_quote = int(ask_wall - 1)

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]
            overbid_price = bid_price + 1

            if bid_vol > 1 and overbid_price < fair:
                bid_quote = max(bid_quote, overbid_price)
                break
            elif bid_price < fair:
                bid_quote = max(bid_quote, bid_price)
                break

        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]
            undercut_price = ask_price - 1

            if ask_vol > 1 and undercut_price > fair:
                ask_quote = min(ask_quote, undercut_price)
                break
            elif ask_price > fair:
                ask_quote = min(ask_quote, ask_price)
                break

        skew_steps = int(current_pos / cfg.inventory_step)
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        if bid_quote >= ask_quote:
            bid_quote = fair_floor - 1
            ask_quote = fair_ceil + 1

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


class TomatoTrader:
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
        self,
        order_depth: OrderDepth,
        position: int,
        trader_data: str,
    ) -> Tuple[List[Order], str]:

        orders: List[Order] = []
        cfg = self.config
        current_pos = position

        data = self._load_trader_data(trader_data)
        buy_orders, sell_orders = self._get_book(order_depth)
        best_bid, best_ask = self._get_best_prices(buy_orders, sell_orders)
        bid_wall, ask_wall, wall_mid = self._get_wall_prices(buy_orders, sell_orders)

        if wall_mid is None:
            if best_bid is not None and best_ask is not None:
                wall_mid = (best_bid + best_ask) / 2
            else:
                return [], trader_data

        prev_fair = data.get("tomatoes_fair_ema")
        fair = self._update_ema(prev_fair, wall_mid, cfg.ema_alpha)
        data["tomatoes_fair_ema"] = fair

        fair_int = round(fair)

        ##########################################################
        # 1. TAKING
        ##########################################################

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

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price < fair_int + cfg.take_edge:
                break

            bid_vol = buy_orders[bid_price]
            sell_capacity = min(
                cfg.position_limit + current_pos,
                current_pos + cfg.target_take_position,
            )
            trade_size = min(bid_vol, max(0, sell_capacity))

            if trade_size > 0:
                orders.append(Order(cfg.symbol, bid_price, -trade_size))
                current_pos -= trade_size

        ##########################################################
        # 2. INVENTORY MANAGEMENT
        ##########################################################

        if current_pos > cfg.soft_inventory_limit and best_bid is not None:
            flatten_size = min(
                buy_orders.get(best_bid, 0),
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

        ##########################################################
        # 3. PASSIVE QUOTING
        ##########################################################

        target_bid = fair_int - cfg.quote_edge
        target_ask = fair_int + cfg.quote_edge

        if best_bid is None:
            bid_quote = target_bid
        else:
            bid_quote = min(target_bid, best_bid + 1)

        if best_ask is None:
            ask_quote = target_ask
        else:
            ask_quote = max(target_ask, best_ask - 1)

        ##########################################################
        # 4. INVENTORY SKEW
        ##########################################################

        skew_steps = int(current_pos / cfg.inventory_step)
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        if bid_quote >= ask_quote:
            bid_quote = fair_int - 1
            ask_quote = fair_int + 1

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

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
    IMC Prosperity submission entry point.
    Trades EMERALDS and TOMATOES.

    EMERALDS: Market maker with StaticTrader style logic
    TOMATOES: Market maker with EMA fair value smoothing
    """

    def __init__(self):
        self.emeralds_mm = EmeraldMarketMaker(
            EmeraldConfig(
                symbol="EMERALDS",
                fair_value=10000,
                position_limit=20,
                fixed_fair_weight=0.0,
                wall_mid_weight=1.0,
                soft_inventory_limit=12,
                base_quote_size=6,
                inventory_step=5,
                take_through_edge=1,
            )
        )

        self.tomatoes_trader = TomatoTrader(
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
        conversions = 0
        trader_data = state.traderData if state.traderData else ""

        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]

            emeralds_orders = self.emeralds_mm.generate_orders(
                emeralds_order_depth,
                emeralds_position,
            )

            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders

        if "TOMATOES" in state.order_depths:
            tomatoes_position = state.position.get("TOMATOES", 0)
            tomatoes_order_depth = state.order_depths["TOMATOES"]

            tomatoes_orders, trader_data = self.tomatoes_trader.generate_orders(
                tomatoes_order_depth,
                tomatoes_position,
                trader_data,
            )

            if tomatoes_orders:
                orders["TOMATOES"] = tomatoes_orders

        return orders, conversions, trader_data
