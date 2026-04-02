from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    """
    EMERALDS: Hardcoded fair = 10000, extremely stable.
    
    Problem with wall-mid: quotes at 9993/10007 (14-tick spread).
    Fix: quote at 9999/10001 (2-tick spread around known fair).
    Each fill earns ~1 tick instead of ~7, but fill rate should be MUCH higher.
    
    With inventory skew to avoid buildup.
    """

    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        buy_orders = depth.buy_orders or {}
        sell_orders = depth.sell_orders or {}
        fair = self.FAIR
        pos = position

        # 1. TAKE — buy any ask < fair, sell any bid > fair
        for ask_price in sorted(sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_vol = abs(sell_orders[ask_price])
            can_buy = self.LIMIT - pos
            size = min(ask_vol, can_buy)
            if size > 0:
                orders.append(Order("EMERALDS", ask_price, size))
                pos += size

        for bid_price in sorted(buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_vol = abs(buy_orders[bid_price])
            can_sell = self.LIMIT + pos
            size = min(bid_vol, can_sell)
            if size > 0:
                orders.append(Order("EMERALDS", bid_price, -size))
                pos -= size

        # 2. FLATTEN at fair if inventory extreme
        if pos > 0 and fair in buy_orders:
            size = min(abs(buy_orders[fair]), pos)
            if size > 0:
                orders.append(Order("EMERALDS", fair, -size))
                pos -= size
        elif pos < 0 and fair in sell_orders:
            size = min(abs(sell_orders[fair]), abs(pos))
            if size > 0:
                orders.append(Order("EMERALDS", fair, size))
                pos += size

        # 3. MAKE — tight quotes around fair with inventory skew
        # Base: 9999 bid, 10001 ask (1 tick from fair)
        bid_quote = fair - 1
        ask_quote = fair + 1

        # Inventory skew: shift quotes to discourage building more position
        # Every 4 units of position shifts quotes by 1 tick
        skew = pos // 4
        bid_quote -= skew
        ask_quote -= skew

        # Hard limits: never cross fair
        bid_quote = min(bid_quote, fair - 1)
        ask_quote = max(ask_quote, fair + 1)

        if bid_quote >= ask_quote:
            bid_quote = fair - 1
            ask_quote = fair + 1

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("EMERALDS", bid_quote, max_buy))
        if max_sell > 0:
            orders.append(Order("EMERALDS", ask_quote, -max_sell))

        return orders


class TomatoesMM:
    """
    TOMATOES: Trending product with mean-reverting ticks.
    
    Strategy: use wall-mid as fair (proven best by Rust backtester),
    but tighten the quote spread and be more aggressive on taking.
    
    Changes from v2:
    - TAKE at wall_mid (not just wall_mid-1) to get more fills
    - Tighter passive quotes: bid_wall+2 / ask_wall-2
    - Stronger inventory-based position unwinding
    - Full remaining size on quotes (not capped)
    """

    LIMIT = POS_LIMITS["TOMATOES"]

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        raw_buys: Dict[int, int] = depth.buy_orders or {}
        raw_sells: Dict[int, int] = depth.sell_orders or {}

        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())

        orders: List[Order] = []
        max_buy = self.LIMIT - position
        max_sell = self.LIMIT + position

        # ── 1. AGGRESSIVE TAKING ──────────────────────────────────
        # Buy asks at wall_mid or below (was wall_mid - 1)
        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp < wall_mid:
                size = min(sv, max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
            elif sp == int(wall_mid) and position < 0:
                # Unwind short at fair
                size = min(sv, abs(position), max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size

        # Sell bids at wall_mid or above (was wall_mid + 1)
        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp > wall_mid:
                size = min(bv, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
            elif bp == int(wall_mid) and position > 0:
                # Unwind long at fair
                size = min(bv, position, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size

        # ── 2. TIGHTER MAKING ──────────────────────────────────────
        # Tighter quotes: 2 ticks inside wall instead of using overbid logic
        bid_price = max(int(bid_wall + 2), best_bid + 1)
        ask_price = min(int(ask_wall - 2), best_ask - 1)

        # Clamp to stay on our side of wall_mid
        bid_price = min(bid_price, int(wall_mid) - 1)
        ask_price = max(ask_price, int(wall_mid) + 1)

        # Inventory skew: shift towards unwinding
        skew = position // 4
        bid_price -= skew
        ask_price -= skew

        # Re-clamp after skew
        bid_price = min(bid_price, int(wall_mid) - 1)
        ask_price = max(ask_price, int(wall_mid) + 1)

        if bid_price >= ask_price:
            bid_price = int(wall_mid) - 1
            ask_price = int(wall_mid) + 1

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders


class Trader:
    SYMBOLS = ["EMERALDS", "TOMATOES"]

    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            em_orders = self.emeralds.generate_orders(state.order_depths["EMERALDS"], pos)
            if em_orders:
                orders["EMERALDS"] = em_orders

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders = self.tomatoes.generate_orders(state.order_depths["TOMATOES"], pos)
            if tom_orders:
                orders["TOMATOES"] = tom_orders

        return orders, 0, ""
