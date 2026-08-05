from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


# Position limits per product
POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,  # adjust if your competition rules differ
}

EMERALDS_FAIR = 10000  # pinned at 10000 for 97%+ of ticks


class StableMaker:
    """
    Optimised market maker for EMERALDS (known, stable fair value).

    Key improvements over base StaticTrader:
      - Quotes at fair±1 (9999/10001) instead of overbid/underbid (~9993/10007).
        This is ~7× tighter → dramatically more fills per tick.
      - Takes EVERY ask below fair and EVERY bid above fair.
      - Closes inventory at fair itself (breakeven, eliminates risk).
      - Posts full remaining capacity at tight quotes.
    """

    def __init__(self, symbol: str, position_limit: int, fair_value: int):
        self.symbol = symbol
        self.position_limit = position_limit
        self.fair = fair_value

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        buys: Dict[int, int] = order_depth.buy_orders or {}
        sells: Dict[int, int] = order_depth.sell_orders or {}

        if not buys and not sells:
            return []

        orders: List[Order] = []
        max_buy = self.position_limit - position
        max_sell = self.position_limit + position
        fair = self.fair

        # ── 1. TAKE: sweep everything on the profitable side of fair ──
        for ask_p in sorted(sells.keys()):
            if max_buy <= 0:
                break
            vol = abs(sells[ask_p])
            if ask_p < fair:
                size = min(vol, max_buy)
                orders.append(Order(self.symbol, ask_p, size))
                max_buy -= size
            elif ask_p == fair and position < 0:
                # Close short inventory at fair (breakeven)
                size = min(vol, abs(position), max_buy)
                orders.append(Order(self.symbol, ask_p, size))
                max_buy -= size

        for bid_p in sorted(buys.keys(), reverse=True):
            if max_sell <= 0:
                break
            vol = abs(buys[bid_p])
            if bid_p > fair:
                size = min(vol, max_sell)
                orders.append(Order(self.symbol, bid_p, -size))
                max_sell -= size
            elif bid_p == fair and position > 0:
                # Close long inventory at fair (breakeven)
                size = min(vol, position, max_sell)
                orders.append(Order(self.symbol, bid_p, -size))
                max_sell -= size

        # ── 2. MAKE: quote at fair±1 with ALL remaining capacity ─────
        # Every fill captures at least 1 tick of edge vs true value.
        if max_buy > 0:
            orders.append(Order(self.symbol, fair - 1, max_buy))
        if max_sell > 0:
            orders.append(Order(self.symbol, fair + 1, -max_sell))

        return orders


class DynamicMaker:
    """
    Optimised market maker for TOMATOES (drifting fair value).

    Key improvements over base StaticTrader:
      - Same wall-mid taking logic (proven safe for unknown fair).
      - Overbid/underbid making to penny-jump inside the NPC spread.
      - Inventory skew: shifts both quotes toward reducing position,
        reducing adverse holding costs from price drift.
      - Posts full remaining capacity.
    """

    INVENTORY_SKEW_FACTOR = 0.15   # ticks of skew per unit of position
    # At max position (±20): skew = ±3 ticks

    def __init__(self, symbol: str, position_limit: int):
        self.symbol = symbol
        self.position_limit = position_limit

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        raw_buys: Dict[int, int] = order_depth.buy_orders or {}
        raw_sells: Dict[int, int] = order_depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        orders: List[Order] = []
        max_buy = self.position_limit - position
        max_sell = self.position_limit + position

        # ── 1. TAKE: sweep clear mispricings ─────────────────────
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

        # ── 2. MAKE: overbid/underbid inside spread ──────────────
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid:
                bid_price = max(bid_price, overbid)
                break
            elif bp < wall_mid:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > wall_mid:
                ask_price = min(ask_price, underbid)
                break
            elif sp > wall_mid:
                ask_price = min(ask_price, sp)
                break

        # Inventory skew: shift quotes toward reducing position
        # Long → lower both quotes (sell more aggressively)
        # Short → raise both quotes (buy more aggressively)
        skew = int(position * self.INVENTORY_SKEW_FACTOR)
        bid_price -= skew
        ask_price -= skew

        # Safety: never cross quotes
        if bid_price >= ask_price:
            bid_price = int(wall_mid) - 1
            ask_price = int(wall_mid) + 1

        if max_buy > 0:
            orders.append(Order(self.symbol, bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order(self.symbol, ask_price, -max_sell))

        return orders


class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS (stable fair value) and TOMATOES (dynamic fair value).
    """

    def __init__(self):
        self.emeralds_mm = StableMaker("EMERALDS", POS_LIMITS["EMERALDS"], EMERALDS_FAIR)
        self.tomatoes_mm = DynamicMaker("TOMATOES", POS_LIMITS["TOMATOES"])

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        for symbol, maker in [("EMERALDS", self.emeralds_mm), ("TOMATOES", self.tomatoes_mm)]:
            if symbol in state.order_depths:
                pos = state.position.get(symbol, 0)
                depth = state.order_depths[symbol]
                sym_orders = maker.generate_orders(depth, pos)
                if sym_orders:
                    orders[symbol] = sym_orders

        conversions = 0
        trader_data = ""

        return orders, conversions, trader_data