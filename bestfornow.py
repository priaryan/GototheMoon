import json
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple


POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
    # "PRODUCT_X": 50,  # add later when the real symbol and limit are known
}


class EmeraldsMM:
    """
    EMERALDS: wall mid making + inventory penalised taking.
    fair_adj = 10000 - 0.05 * position
    """
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

        # TAKE
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

        # MAKE
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


class TomatoesMM:
    """
    TOMATOES: EMA wall mid making + inventory penalised taking.
    ema_wm = 0.1 * wall_mid + 0.9 * ema_wm
    fair_adj = ema_wm - 0.02 * position
    take_margin = 0.25, flatten when |pos| > 2
    """
    LIMIT = POS_LIMITS["TOMATOES"]
    EMA_ALPHA = 0.1
    INV_PENALTY = 0.02
    TAKE_MARGIN = 0.25
    FLATTEN_THRESH = 2

    def generate_orders(self, depth: OrderDepth, position: int, ema_wm) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema_wm

        fair_adj = ema_wm - self.INV_PENALTY * position

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        # TAKE
        buy_margin = self.TAKE_MARGIN
        sell_margin = self.TAKE_MARGIN

        if pos > self.FLATTEN_THRESH:
            sell_margin = 0.0
        if pos < -self.FLATTEN_THRESH:
            buy_margin = 0.0

        for sp, sv in sell_orders.items():
            if max_buy <= 0:
                break
            if sp <= fair_adj - buy_margin:
                size = min(sv, max_buy)
                orders.append(Order("TOMATOES", sp, size))
                max_buy -= size
                pos += size
            elif sp <= fair_adj and position < 0:
                size = min(sv, abs(position), max_buy)
                if size > 0:
                    orders.append(Order("TOMATOES", sp, size))
                    max_buy -= size
                    pos += size

        for bp, bv in buy_orders.items():
            if max_sell <= 0:
                break
            if bp >= fair_adj + sell_margin:
                size = min(bv, max_sell)
                orders.append(Order("TOMATOES", bp, -size))
                max_sell -= size
                pos -= size
            elif bp >= fair_adj and position > 0:
                size = min(bv, position, max_sell)
                if size > 0:
                    orders.append(Order("TOMATOES", bp, -size))
                    max_sell -= size
                    pos -= size

        # MAKE
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

        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders, ema_wm


class ProductXTrader:
    """
    PRODUCT_X: Squid Ink style extrema follower.

    Idea:
    track running low and high
    detect characteristic trade size at an extreme
    go long after low prints
    go short after high prints
    flatten when neutral

    This class is intentionally directional and does not market make.
    """

    SYMBOL = "PRODUCT_X"
    SIGNAL_QTY = 15
    EXTREMA_EPS = 0
    TARGET_POS = 40

    def __init__(self, position_limit: int = 50):
        self.LIMIT = position_limit

    def _extract_trade_info(self, trade):
        px = getattr(trade, "price", None)
        qty = abs(getattr(trade, "quantity", 0))
        ts = getattr(trade, "timestamp", None)
        return px, qty, ts

    def _update_signal(
        self,
        trades,
        running_low,
        running_high,
        current_signal,
        last_signal_ts,
        wall_mid,
    ):
        if running_low is None:
            running_low = wall_mid
        if running_high is None:
            running_high = wall_mid

        low_hits = 0
        high_hits = 0
        newest_low_ts = None
        newest_high_ts = None

        for trade in trades:
            px, qty, ts = self._extract_trade_info(trade)
            if px is None:
                continue

            if running_low is None or px < running_low:
                running_low = px
            if running_high is None or px > running_high:
                running_high = px

            if qty != self.SIGNAL_QTY:
                continue

            if px <= running_low + self.EXTREMA_EPS:
                low_hits += 1
                newest_low_ts = ts

            if px >= running_high - self.EXTREMA_EPS:
                high_hits += 1
                newest_high_ts = ts

        signal = current_signal
        signal_ts = last_signal_ts

        if low_hits > 0 and high_hits == 0:
            signal = 1
            signal_ts = newest_low_ts
        elif high_hits > 0 and low_hits == 0:
            signal = -1
            signal_ts = newest_high_ts
        elif high_hits > 0 and low_hits > 0:
            if newest_low_ts is not None and newest_high_ts is not None:
                if newest_low_ts > newest_high_ts:
                    signal = 1
                    signal_ts = newest_low_ts
                elif newest_high_ts > newest_low_ts:
                    signal = -1
                    signal_ts = newest_high_ts
                else:
                    signal = 0

        return signal, signal_ts, running_low, running_high

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        market_trades,
        running_low,
        running_high,
        signal,
        last_signal_ts,
    ):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], running_low, running_high, signal, last_signal_ts

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        signal, last_signal_ts, running_low, running_high = self._update_signal(
            market_trades,
            running_low,
            running_high,
            signal,
            last_signal_ts,
            wall_mid,
        )

        if signal == 1:
            target_pos = self.TARGET_POS
        elif signal == -1:
            target_pos = -self.TARGET_POS
        else:
            target_pos = 0

        orders: List[Order] = []
        pos = position

        # Move toward target by taking liquidity
        if pos < target_pos:
            need = target_pos - pos
            max_buy = self.LIMIT - pos
            for ap, av in sell_orders.items():
                if need <= 0 or max_buy <= 0:
                    break
                size = min(av, need, max_buy)
                if size > 0:
                    orders.append(Order(self.SYMBOL, ap, size))
                    pos += size
                    need -= size
                    max_buy -= size

        elif pos > target_pos:
            need = pos - target_pos
            max_sell = self.LIMIT + pos
            for bp, bv in buy_orders.items():
                if need <= 0 or max_sell <= 0:
                    break
                size = min(bv, need, max_sell)
                if size > 0:
                    orders.append(Order(self.SYMBOL, bp, -size))
                    pos -= size
                    need -= size
                    max_sell -= size

        return orders, running_low, running_high, signal, last_signal_ts


class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()
        self.product_x = ProductXTrader(position_limit=50)

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                pass

        ema_wm = td.get("ema_wm")

        x_low = td.get("x_low")
        x_high = td.get("x_high")
        x_signal = td.get("x_signal", 0)
        x_last_signal_ts = td.get("x_last_signal_ts")

        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, ema_wm = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"], pos, ema_wm
            )
            orders["TOMATOES"] = tom_orders

        # PRODUCT_X intentionally not enabled yet
        # When needed, uncomment this block and add PRODUCT_X to POS_LIMITS
        #
        # if "PRODUCT_X" in state.order_depths:
        #     pos = state.position.get("PRODUCT_X", 0)
        #     x_orders, x_low, x_high, x_signal, x_last_signal_ts = self.product_x.generate_orders(
        #         state.order_depths["PRODUCT_X"],
        #         pos,
        #         state.market_trades.get("PRODUCT_X", []),
        #         x_low,
        #         x_high,
        #         x_signal,
        #         x_last_signal_ts,
        #     )
        #     orders["PRODUCT_X"] = x_orders

        td["ema_wm"] = ema_wm
        td["x_low"] = x_low
        td["x_high"] = x_high
        td["x_signal"] = x_signal
        td["x_last_signal_ts"] = x_last_signal_ts

        return orders, 0, json.dumps(td)