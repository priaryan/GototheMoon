from typing import Dict, List, Tuple

try:
    # When running via backtester
    from prosperity3bt.datamodel import Order, TradingState, Symbol
except ImportError:
    # When running locally
    from datamodel import Order, TradingState, Symbol

from strategies.market_maker import MarketMaker, MarketMakerConfig


class Trader:
    """
    Main trader class compatible with the prosperity3bt backtester.
    Currently trades EMERALDS only.
    """

    def __init__(self):
        self.emeralds_config = MarketMakerConfig(
            symbol="EMERALDS",
            fair_value=10000,
            position_limit=20,
            soft_inventory_limit=12,
            base_quote_size=6,
            inventory_step=5,
        )
        self.emeralds_mm = MarketMaker(self.emeralds_config)

    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], List, str]:
        orders: Dict[Symbol, List[Order]] = {}
        conversions: List = []

        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]
            emeralds_orders = self.emeralds_mm.generate_orders(
                emeralds_order_depth,
                emeralds_position,
            )
            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders

        trader_data = ""
        return orders, conversions, trader_data