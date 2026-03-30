"""
Main trader class compatible with IMC Prosperity 3 backtester.

This trader uses the EmeraldMarketMaker strategy for EMERALDS.
"""

import json
from typing import Any, Dict, List, Tuple

try:
    # When running via backtester
    from prosperity3bt.datamodel import Order, TradingState, OrderDepth, Symbol
except ImportError:
    # When running locally
    from datamodel import Order, TradingState, OrderDepth, Symbol

from strategies.emerald_market_maker import EmeraldMarketMaker, EmeraldConfig


class Trader:
    """
    Main trader class that integrates all strategies.
    Compatible with the prosperity3bt backtester.
    """

    def __init__(self):
        """Initialize all strategies."""
        # Initialize emerald market maker
        self.emerald_config = EmeraldConfig(
            symbol="EMERALDS",
            fair_value=10000,
            position_limit=20,
            soft_inventory_limit=12,
            base_quote_size=6,
            inventory_step=5,
        )
        self.emerald_mm = EmeraldMarketMaker(self.emerald_config)

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
        
        # Get current position for EMERALDS
        emerald_position = state.position.get("EMERALDS", 0)
        
        # Get order depth for EMERALDS
        emerald_order_depth = state.order_depths.get("EMERALDS", OrderDepth())
        
        # Generate orders using emerald market maker
        emerald_orders = self.emerald_mm.generate_orders(emerald_order_depth, emerald_position)
        
        # Group orders by symbol (they should all be EMERALDS)
        if emerald_orders:
            orders["EMERALDS"] = emerald_orders
        
        # Return orders, conversions, and trader data
        trader_data = ""  # No persistent state needed for now
        
        return orders, conversions, trader_data
