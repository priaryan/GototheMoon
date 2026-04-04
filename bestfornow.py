import json
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
}


class EmeraldsMM:
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    INV_PENALTY = 0.05

    def generate_orders(self, depth: OrderDepth, position: int) -> List[Order]:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return []

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        fair = self.FAIR - self.INV_PENALTY * position

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp < fair:
                size = min(sv, max_buy)
                orders.append(Order("EMERALDS", sp, size))
                max_buy -= size
                pos += size
            elif sp <= fair and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0:
                    orders.append(Order("EMERALDS", sp, size))
                    max_buy -= size
                    pos += size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp > fair:
                size = min(bv, max_sell)
                orders.append(Order("EMERALDS", bp, -size))
                max_sell -= size
                pos -= size
            elif bp >= fair and pos > 0:
                size = min(bv, pos, max_sell)
                if size > 0:
                    orders.append(Order("EMERALDS", bp, -size))
                    max_sell -= size
                    pos -= size

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        for bp, bv in buy_orders.items():
            overbid = bp + 1
            if bv > 1 and overbid < self.FAIR:
                bid_price = max(bid_price, overbid)
                break
            elif bp < self.FAIR:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in sell_orders.items():
            underbid = sp - 1
            if sv > 1 and underbid > self.FAIR:
                ask_price = min(ask_price, underbid)
                break
            elif sp > self.FAIR:
                ask_price = min(ask_price, sp)
                break

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("EMERALDS", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("EMERALDS", ask_price, -max_sell))

        return orders


class TomatoesExtremaFollower:
    """
    TOMATOES as a Squid Ink style product.

    Core idea:
    detect informative trades at running extrema and follow them.

    signal =  1 -> long bias
    signal = -1 -> short bias
    signal =  0 -> no bias

    We do not passively market make here.
    We only take liquidity to move toward a target position.
    """
    LIMIT = POS_LIMITS["TOMATOES"]

    SIGNAL_QTY = 15
    EXTREMA_EPS = 0
    TARGET_POS = 12
    CONFIRM_TRADE_COUNT = 1

    def _best_bid_ask(self, depth: OrderDepth):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return None, None, None, None

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        best_bid = max(buy_orders.keys())
        best_ask = min(sell_orders.keys())
        return buy_orders, sell_orders, best_bid, best_ask

    def _extract_trade_qty(self, trade):
        q = getattr(trade, "quantity", 0)
        return abs(q)

    def _update_signal_from_trades(
        self,
        trades,
        running_low,
        running_high,
        best_bid,
        best_ask,
        current_signal,
    ):
        """
        Heuristic:
        if a SIGNAL_QTY trade prints at the running low, treat as bullish
        if a SIGNAL_QTY trade prints at the running high, treat as bearish

        We also invalidate old signals if new opposite extremes appear.
        """
        if not trades:
            return current_signal, running_low, running_high

        mids = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None

        low_hits = 0
        high_hits = 0

        for tr in trades:
            px = getattr(tr, "price", None)
            if px is None:
                continue

            qty = self._extract_trade_qty(tr)

            if running_low is None or px < running_low:
                running_low = px
            if running_high is None or px > running_high:
                running_high = px

            if qty != self.SIGNAL_QTY:
                continue

            if running_low is not None and px <= running_low + self.EXTREMA_EPS:
                if mids is None or px <= mids:
                    low_hits += 1

            if running_high is not None and px >= running_high - self.EXTREMA_EPS:
                if mids is None or px >= mids:
                    high_hits += 1

        new_signal = current_signal

        if low_hits >= self.CONFIRM_TRADE_COUNT and high_hits == 0:
            new_signal = 1
        elif high_hits >= self.CONFIRM_TRADE_COUNT and low_hits == 0:
            new_signal = -1
        elif low_hits >= self.CONFIRM_TRADE_COUNT and high_hits >= self.CONFIRM_TRADE_COUNT:
            new_signal = 0

        return new_signal, running_low, running_high

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        market_trades,
        running_low,
        running_high,
        signal,
    ):
        buy_orders, sell_orders, best_bid, best_ask = self._best_bid_ask(depth)
        if buy_orders is None or sell_orders is None:
            return [], running_low, running_high, signal

        wall_mid = (best_bid + best_ask) / 2

        if running_low is None:
            running_low = wall_mid
        if running_high is None:
            running_high = wall_mid

        signal, running_low, running_high = self._update_signal_from_trades(
            market_trades,
            running_low,
            running_high,
            best_bid,
            best_ask,
            signal,
        )

        orders: List[Order] = []

        # Decide target position from signal
        if signal == 1:
            target_pos = self.TARGET_POS
        elif signal == -1:
            target_pos = -self.TARGET_POS
        else:
            target_pos = 0

        pos = position

        # Buy up toward target
        if pos < target_pos:
            need = target_pos - pos
            for ask_px in sorted(sell_orders.keys()):
                ask_vol = sell_orders[ask_px]
                if need <= 0:
                    break
                size = min(ask_vol, need, self.LIMIT - pos)
                if size > 0:
                    orders.append(Order("TOMATOES", ask_px, size))
                    pos += size
                    need -= size

        # Sell down toward target
        elif pos > target_pos:
            need = pos - target_pos
            for bid_px in sorted(buy_orders.keys(), reverse=True):
                bid_vol = buy_orders[bid_px]
                if need <= 0:
                    break
                size = min(bid_vol, need, self.LIMIT + pos)
                if size > 0:
                    orders.append(Order("TOMATOES", bid_px, -size))
                    pos -= size
                    need -= size

        return orders, running_low, running_high, signal


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesExtremaFollower()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                pass

        tomatoes_low = td.get("tomatoes_low")
        tomatoes_high = td.get("tomatoes_high")
        tomatoes_signal = td.get("tomatoes_signal", 0)

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            market_trades = state.market_trades.get("TOMATOES", [])
            tom_orders, tomatoes_low, tomatoes_high, tomatoes_signal = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"],
                pos,
                market_trades,
                tomatoes_low,
                tomatoes_high,
                tomatoes_signal,
            )
            orders["TOMATOES"] = tom_orders

        td["tomatoes_low"] = tomatoes_low
        td["tomatoes_high"] = tomatoes_high
        td["tomatoes_signal"] = tomatoes_signal

        return orders, 0, json.dumps(td)