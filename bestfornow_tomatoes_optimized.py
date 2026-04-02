from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


# Position limits per product
POS_LIMITS = {
    "TOMATOES": 20,
}


class MeanRevertingMarketMaker:
    """
    Optimized TOMATOES market maker based on mean reversion diagnostics.
    
    Key insights from diagnostics:
    - Reversion correlation: -0.701 (STRONG mean reversion)
    - Future returns: +0.0258% when buying below wall_mid, -0.0239% when selling above
    - Passive fill rate: 0.2% (nearly zero) — focus on TAKING not MAKING
    - Adverse selection: +6.5 ticks per trade — very profitable to take
    
    Strategy:
    1. AGGRESSIVELY TAKE — buy any asks below wall_mid, sell any bids above wall_mid
    2. INVENTORY MANAGEMENT — use extreme skew to force unwind at wall_mid
    3. PASSIVE QUOTES — only post if inventory forces us to, with aggressive skew
    """

    def __init__(self, symbol: str, position_limit: int):
        self.symbol = symbol
        self.position_limit = position_limit

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        raw_buys: Dict[int, int] = order_depth.buy_orders or {}
        raw_sells: Dict[int, int] = order_depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        # Normalise to positive volumes, sorted for iteration
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        # Wall prices (outermost levels) and their midpoint
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        orders: List[Order] = []
        max_buy = self.position_limit - position
        max_sell = self.position_limit + position

        # ── 1. AGGRESSIVE TAKING (exploit mean reversion) ──────────────────────
        # Buy ANY asks below wall_mid (they will revert up)
        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp < wall_mid:  # Changed: was <= wall_mid - 1
                size = min(sv, max_buy)
                orders.append(Order(self.symbol, sp, size))
                max_buy -= size
                position += size

        # Sell ANY bids above wall_mid (they will revert down)
        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp > wall_mid:  # Changed: was >= wall_mid + 1
                size = min(bv, max_sell)
                orders.append(Order(self.symbol, bp, -size))
                max_sell -= size
                position -= size

        # ── 2. FLATTEN stretched inventory at wall_mid ──────────────────────────
        # Only try to unwind at wall_mid, don't waste on passive quotes elsewhere
        if position > 8 and wall_mid in buy_orders:
            # Sell excess long position at wall_mid
            size = min(abs(buy_orders[wall_mid]), position - 8)
            if size > 0:
                orders.append(Order(self.symbol, int(wall_mid), -size))
                position -= size
                max_sell -= size

        if position < -8 and wall_mid in sell_orders:
            # Buy excess short position at wall_mid
            size = min(abs(sell_orders[wall_mid]), abs(position) - 8)
            if size > 0:
                orders.append(Order(self.symbol, int(wall_mid), size))
                position += size
                max_buy -= size

        # ── 3. AGGRESSIVE QUOTING with strong inventory skew ──────────────────────
        # Only post if we need to reduce inventory
        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())

        # Strong inventory skew: push quotes far away if not needed
        # If long, quote aggressively to sell; if short, quote aggressively to buy
        if position > 5:
            # We're long, make aggressive ask to unwind
            ask_quote = best_ask - 2
            bid_quote = best_bid - 3  # Don't buy more
        elif position < -5:
            # We're short, make aggressive bid to unwind
            bid_quote = best_bid + 2
            ask_quote = best_ask + 3  # Don't sell more
        else:
            # Flat or near-flat, post passively but we expect low fill rate
            bid_quote = best_bid
            ask_quote = best_ask

        # Safety: don't cross the bid-ask
        if bid_quote >= ask_quote:
            bid_quote = int(wall_mid) - 1
            ask_quote = int(wall_mid) + 1

        # Post what's left after taking
        if max_buy > 0 and position < 12:
            orders.append(Order(self.symbol, bid_quote, min(max_buy, 6)))
        if max_sell > 0 and position > -12:
            orders.append(Order(self.symbol, ask_quote, -min(max_sell, 6)))

        return orders


class Trader:
    """
    IMC submission entry point.
    Optimized TOMATOES market maker exploiting mean reversion.
    """

    SYMBOLS = ["TOMATOES"]

    def __init__(self):
        self.makers = {
            sym: MeanRevertingMarketMaker(sym, POS_LIMITS[sym])
            for sym in self.SYMBOLS
        }

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        for symbol, maker in self.makers.items():
            if symbol in state.order_depths:
                pos = state.position.get(symbol, 0)
                depth = state.order_depths[symbol]
                sym_orders = maker.generate_orders(depth, pos)
                if sym_orders:
                    orders[symbol] = sym_orders

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data
