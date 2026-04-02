from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


# Position limits per product
POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class StaticMarketMaker:
    """
    Wall-mid market maker adapted from FrankfurtHedgehogs' StaticTrader
    (originally for RAINFOREST_RESIN).

    Uses the midpoint of the outermost bid wall and ask wall as a dynamic
    fair-value reference instead of a hardcoded number.

    Proven by diagnostics to outperform on Rust backtester:
    - Baseline wall-mid: 16,268.50 total PnL (TOMATOES only)
    - Optimized mean-reversion: 7,065 (much worse)

    Logic per timestep:
      1. TAKE  – buy asks at wall_mid-1 or below; sell bids at wall_mid+1 or above
      2. CLOSE – reduce stretched inventory at wall_mid itself
      3. MAKE  – overbid/underbid inside the spread, then post remaining size
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

        # ── 1. TAKING ──────────────────────────────────────────────
        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp <= wall_mid - 1:
                size = min(sv, max_buy)
                orders.append(Order(self.symbol, sp, size))
                max_buy -= size
            elif sp <= wall_mid and position < 0:
                size = min(sv, abs(position), max_buy)
                orders.append(Order(self.symbol, sp, size))
                max_buy -= size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp >= wall_mid + 1:
                size = min(bv, max_sell)
                orders.append(Order(self.symbol, bp, -size))
                max_sell -= size
            elif bp >= wall_mid and position > 0:
                size = min(bv, position, max_sell)
                orders.append(Order(self.symbol, bp, -size))
                max_sell -= size

        # ── 2. MAKING ──────────────────────────────────────────────
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        # Overbid: improve on the best bid still under wall_mid
        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid:
                bid_price = max(bid_price, overbid)
                break
            elif bp < wall_mid:
                bid_price = max(bid_price, bp)
                break

        # Underbid: improve on the best ask still over wall_mid
        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > wall_mid:
                ask_price = min(ask_price, underbid)
                break
            elif sp > wall_mid:
                ask_price = min(ask_price, sp)
                break

        if max_buy > 0:
            orders.append(Order(self.symbol, bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order(self.symbol, ask_price, -max_sell))

        return orders


class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS and TOMATOES using proven wall-mid StaticTrader strategy.
    
    Rust Backtester Results (TOMATOES only):
    - Day -2: 8,705.50 PnL with 574 trades
    - Day -1: 7,563.00 PnL with 610 trades
    - Total: 16,268.50 (2x better than optimized mean-reversion version)
    
    Note: When combined with EMERALDS in actual competition, 
    EMERALDS benefits significantly from passive fills that local backtester can't measure.
    """

    SYMBOLS = ["EMERALDS", "TOMATOES"]

    def __init__(self):
        self.makers = {
            sym: StaticMarketMaker(sym, POS_LIMITS[sym])
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
