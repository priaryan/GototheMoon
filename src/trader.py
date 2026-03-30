"""
Main trader class compatible with IMC Prosperity 3 backtester.

This trader uses the market maker strategy for products in the data.
"""

from typing import Dict, List, Tuple

try:
    # When running via backtester
    from prosperity3bt.datamodel import Order, TradingState, OrderDepth, Symbol
except ImportError:
    # When running locally
    from datamodel import Order, TradingState, OrderDepth, Symbol

from strategies.market_maker import MarketMaker, MarketMakerConfig


class Trader:
    """
    Main trader class that integrates all strategies.
    Compatible with the prosperity3bt backtester.
    """

    def __init__(self):
        """Initialize strategies for all available products."""
        # Market maker for EMERALDS
        self.emeralds_config = MarketMakerConfig(
            symbol="EMERALDS",
            fair_value=10000,
            position_limit=10,
            soft_inventory_limit=5,
            base_quote_size=3,
            inventory_step=5,
        )
        self.emeralds_mm = MarketMaker(self.emeralds_config)

        # Market maker for TOMATOES
        self.tomatoes_config = MarketMakerConfig(
            symbol="TOMATOES",
            fair_value=5000,
            position_limit=10,
            soft_inventory_limit=5,
            base_quote_size=3,
            inventory_step=5,
        )
        self.tomatoes_mm = MarketMaker(self.tomatoes_config)

    def run(self, state: TradingState) -> Tuple[Dict[Symbol, List[Order]], List, str]:
        """
        Main trading logic called by the backtester at each timestamp.

        Args:
            state: Current trading state with order depths, positions, observations
            
        Returns:
            orders: Dict[Symbol, List[Order]] - Orders grouped by product
            conversions: List - Conversion operations (empty for now)
            trader_data: str - Persistent state data (JSON string)
        """
        orders: Dict[Symbol, List[Order]] = {}
        conversions: List = []
        
        # Trade EMERALDS
        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]
            emeralds_orders = self.emeralds_mm.generate_orders(emeralds_order_depth, emeralds_position)
            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders
        
        # Trade TOMATOES
        if "TOMATOES" in state.order_depths:
            tomatoes_position = state.position.get("TOMATOES", 0)
            tomatoes_order_depth = state.order_depths["TOMATOES"]
            tomatoes_orders = self.tomatoes_mm.generate_orders(tomatoes_order_depth, tomatoes_position)
            if tomatoes_orders:
                orders["TOMATOES"] = tomatoes_orders
        
        # Return orders, conversions, and trader data
        trader_data = ""  # No persistent state needed for now
        
        return orders, conversions, trader_data
