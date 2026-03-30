from datamodel import Order, OrderDepth, TradingState
from dataclasses import dataclass
from typing import Dict, List, Tuple


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

        # Fallback if wall mid is unavailable
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

        # For StaticTrader style comparisons, use integer fair thresholding
        fair_floor = int(fair)
        fair_ceil = int(fair) if fair == int(fair) else int(fair) + 1

        ##########################################################
        # 1. TAKING
        ##########################################################

        # Buy asks clearly below fair
        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]

            if ask_price <= fair - cfg.take_through_edge:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

            # Buy at fair only to reduce short inventory
            elif ask_price <= fair and current_pos < 0:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, abs(current_pos), buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

        # Sell bids clearly above fair
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]

            if bid_price >= fair + cfg.take_through_edge:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

            # Sell at fair only to reduce long inventory
            elif bid_price >= fair and current_pos > 0:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, current_pos, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

        ##########################################################
        # 2. MAKING
        ##########################################################

        # Need usable walls to emulate StaticTrader style quoting
        if bid_wall is None or ask_wall is None:
            return orders

        # Base case from wall structure
        bid_quote = int(bid_wall + 1)
        ask_quote = int(ask_wall - 1)

        # OVERBID best meaningful bid still below fair
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]
            overbid_price = bid_price + 1

            if bid_vol > 1 and overbid_price < fair:
                bid_quote = max(bid_quote, overbid_price)
                break
            elif bid_price < fair:
                bid_quote = max(bid_quote, bid_price)
                break

        # UNDERCUT best meaningful ask still above fair
        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]
            undercut_price = ask_price - 1

            if ask_vol > 1 and undercut_price > fair:
                ask_quote = min(ask_quote, undercut_price)
                break
            elif ask_price > fair:
                ask_quote = min(ask_quote, ask_price)
                break

        # Inventory skew from your cleaner implementation
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety fallback
        if bid_quote >= ask_quote:
            bid_quote = fair_floor - 1
            ask_quote = fair_ceil + 1

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        # Keep your controlled sizing rather than posting full remaining size
        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))

        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        return orders


class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS only.

    Default test configuration:
    100 percent wall mid
    0 percent fixed fair
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

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]

            emeralds_orders = self.emeralds_mm.generate_orders(
                emeralds_order_depth,
                emeralds_position,
            )

            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data