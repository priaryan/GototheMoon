# src/strategies/emerald_market_maker.py
from dataclasses import dataclass
from typing import List, Dict

from datamodel import Order, OrderDepth


@dataclass
class EmeraldConfig:
    symbol: str = "EMERALDS"
    fair_value: int = 10000
    position_limit: int = 20
    soft_inventory_limit: int = 12  # optional flatten threshold
    base_quote_size: int = 6        # default passive quote size
    inventory_step: int = 5         # for inventory-based skew


class EmeraldMarketMaker:
    """
    EMERALDS market maker strategy (Rainforest Resin clone).
    
    Logic per timestep:
    1. Take any favorable trades (buy below fair, sell above fair)
    2. Flatten inventory at fair when stretched
    3. Post passive quotes just inside the spread
    4. Adjust quotes slightly based on inventory (optional)
    """

    def __init__(self, config: EmeraldConfig = None):
        self.config = config or EmeraldConfig()

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        cfg = self.config
        fair = cfg.fair_value
        current_pos = position

        buy_orders: Dict[int, int] = order_depth.buy_orders or {}
        sell_orders: Dict[int, int] = order_depth.sell_orders or {}

        # -----------------------------
        # 1. Take favorable sells (buy below fair)
        # -----------------------------
        for ask_price in sorted(sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_vol = -sell_orders[ask_price]  # negative in IMC
            buy_capacity = cfg.position_limit - current_pos
            trade_size = min(ask_vol, buy_capacity)
            if trade_size > 0:
                orders.append(Order(cfg.symbol, ask_price, trade_size))
                current_pos += trade_size

        # -----------------------------
        # 2. Take favorable bids (sell above fair)
        # -----------------------------
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_vol = buy_orders[bid_price]
            sell_capacity = cfg.position_limit + current_pos
            trade_size = min(bid_vol, sell_capacity)
            if trade_size > 0:
                orders.append(Order(cfg.symbol, bid_price, -trade_size))
                current_pos -= trade_size

        # -----------------------------
        # 3. Flatten inventory at fair if stretched
        # -----------------------------
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

        # -----------------------------
        # 4. Passive quoting inside spread
        # -----------------------------
        best_bid = max(buy_orders.keys()) if buy_orders else fair - 1
        best_ask = min(sell_orders.keys()) if sell_orders else fair + 1

        # Default passive quotes
        bid_quote = min(best_bid + 1, fair - 1)
        ask_quote = max(best_ask - 1, fair + 1)

        # Optional inventory skew
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety for spread
        if bid_quote >= ask_quote:
            bid_quote = fair - 1
            ask_quote = fair + 1

        # Sizes
        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))
        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        return orders