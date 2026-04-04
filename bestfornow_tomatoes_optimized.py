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
    TOMATOES:
    1. Base market making sleeve uses 17 lots
    2. Small swing sleeve uses 3 lots
    3. Swing sleeve buys after confirmed rebound from a recent local low
    4. Swing sleeve sells after confirmed drop from a recent local high
    """

    LIMIT = POS_LIMITS["TOMATOES"]

    # Base sleeve
    BASE_LIMIT = 17
    EMA_ALPHA = 0.1
    INV_PENALTY = 0.02
    TAKE_MARGIN = 0.25
    FLATTEN_THRESH = 2

    # Swing sleeve
    OVERLAY_LIMIT = LIMIT - BASE_LIMIT
    SWING_WINDOW = 40
    REBOUND_TICKS = 8
    MAX_EXTREMA_AGE = 10
    HOLD_STEPS = 60  # measured in simulator steps of 100 timestamp units

    def _reconcile_overlay_pos(self, actual_position: int, overlay_pos: int) -> int:
        """
        Keep estimated overlay position consistent with actual net position.
        Since overlay orders are aggressive, this works well enough in practice.
        """
        if overlay_pos > 0:
            if actual_position <= 0:
                return 0
            return min(overlay_pos, actual_position)

        if overlay_pos < 0:
            if actual_position >= 0:
                return 0
            return max(overlay_pos, actual_position)

        return 0

    def _generate_base_orders(
        self,
        depth: OrderDepth,
        base_position: int,
        ema_wm,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm, None

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema_wm

        fair_adj = ema_wm - self.INV_PENALTY * base_position

        orders: List[Order] = []
        pos = base_position
        max_buy = self.BASE_LIMIT - pos
        max_sell = self.BASE_LIMIT + pos

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
            elif sp <= fair_adj and base_position < 0:
                size = min(sv, abs(base_position), max_buy)
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
            elif bp >= fair_adj and base_position > 0:
                size = min(bv, base_position, max_sell)
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

        max_buy = self.BASE_LIMIT - pos
        max_sell = self.BASE_LIMIT + pos

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders, ema_wm, wall_mid

    def _update_overlay_signal(
        self,
        wall_mid,
        history,
        overlay_dir,
        overlay_until_ts,
        timestamp,
    ):
        if history is None:
            history = []

        history.append(wall_mid)
        if len(history) > self.SWING_WINDOW + 5:
            history = history[-(self.SWING_WINDOW + 5):]

        # Expire old overlay
        if overlay_dir != 0 and overlay_until_ts is not None and timestamp >= overlay_until_ts:
            overlay_dir = 0
            overlay_until_ts = None

        if len(history) < self.SWING_WINDOW:
            return history, overlay_dir, overlay_until_ts

        window = history[-self.SWING_WINDOW:]
        prev = window[:-1]
        cur = window[-1]

        prev_min = min(prev)
        prev_max = max(prev)

        min_last_idx = max(i for i, v in enumerate(prev) if v == prev_min)
        max_last_idx = max(i for i, v in enumerate(prev) if v == prev_max)

        min_age = len(prev) - 1 - min_last_idx
        max_age = len(prev) - 1 - max_last_idx

        prev_last = prev[-1]

        long_signal = (
            min_age <= self.MAX_EXTREMA_AGE
            and cur >= prev_min + self.REBOUND_TICKS
            and cur > prev_last
        )

        short_signal = (
            max_age <= self.MAX_EXTREMA_AGE
            and cur <= prev_max - self.REBOUND_TICKS
            and cur < prev_last
        )

        if long_signal and not short_signal:
            overlay_dir = 1
            overlay_until_ts = timestamp + self.HOLD_STEPS * 100
        elif short_signal and not long_signal:
            overlay_dir = -1
            overlay_until_ts = timestamp + self.HOLD_STEPS * 100

        return history, overlay_dir, overlay_until_ts

    def _generate_overlay_orders(
        self,
        depth: OrderDepth,
        overlay_pos: int,
        overlay_dir: int,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], overlay_pos

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        orders: List[Order] = []

        target_overlay_pos = overlay_dir * self.OVERLAY_LIMIT

        # Aggressive one level adjustment toward target overlay inventory
        if overlay_pos < target_overlay_pos:
            best_ask = min(sell_orders.keys())
            best_ask_vol = sell_orders[best_ask]
            size = min(target_overlay_pos - overlay_pos, best_ask_vol)
            if size > 0:
                orders.append(Order("TOMATOES", best_ask, size))
                overlay_pos += size

        elif overlay_pos > target_overlay_pos:
            best_bid = max(buy_orders.keys())
            best_bid_vol = buy_orders[best_bid]
            size = min(overlay_pos - target_overlay_pos, best_bid_vol)
            if size > 0:
                orders.append(Order("TOMATOES", best_bid, -size))
                overlay_pos -= size

        return orders, overlay_pos

    def generate_orders(
        self,
        depth: OrderDepth,
        actual_position: int,
        ema_wm,
        history,
        overlay_dir,
        overlay_until_ts,
        overlay_pos,
        timestamp,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm, history, overlay_dir, overlay_until_ts, overlay_pos

        overlay_pos = self._reconcile_overlay_pos(actual_position, overlay_pos)

        # Base sleeve uses position net of overlay sleeve
        base_position = actual_position - overlay_pos

        base_orders, ema_wm, wall_mid = self._generate_base_orders(
            depth,
            base_position,
            ema_wm,
        )

        if wall_mid is None:
            return base_orders, ema_wm, history, overlay_dir, overlay_until_ts, overlay_pos

        history, overlay_dir, overlay_until_ts = self._update_overlay_signal(
            wall_mid,
            history,
            overlay_dir,
            overlay_until_ts,
            timestamp,
        )

        overlay_orders, overlay_pos = self._generate_overlay_orders(
            depth,
            overlay_pos,
            overlay_dir,
        )

        return (
            base_orders + overlay_orders,
            ema_wm,
            history,
            overlay_dir,
            overlay_until_ts,
            overlay_pos,
        )


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


class TomatoesMM:
    """
    TOMATOES:
    1. Base market making sleeve uses 17 lots
    2. Small swing sleeve uses 3 lots
    3. Swing sleeve buys after confirmed rebound from a recent local low
    4. Swing sleeve sells after confirmed drop from a recent local high
    """

    LIMIT = POS_LIMITS["TOMATOES"]

    # Base sleeve
    BASE_LIMIT = 17
    EMA_ALPHA = 0.1
    INV_PENALTY = 0.02
    TAKE_MARGIN = 0.25
    FLATTEN_THRESH = 2

    # Swing sleeve
    OVERLAY_LIMIT = LIMIT - BASE_LIMIT
    SWING_WINDOW = 40
    REBOUND_TICKS = 8
    MAX_EXTREMA_AGE = 10
    HOLD_STEPS = 60  # measured in simulator steps of 100 timestamp units

    def _reconcile_overlay_pos(self, actual_position: int, overlay_pos: int) -> int:
        """
        Keep estimated overlay position consistent with actual net position.
        Since overlay orders are aggressive, this works well enough in practice.
        """
        if overlay_pos > 0:
            if actual_position <= 0:
                return 0
            return min(overlay_pos, actual_position)

        if overlay_pos < 0:
            if actual_position >= 0:
                return 0
            return max(overlay_pos, actual_position)

        return 0

    def _generate_base_orders(
        self,
        depth: OrderDepth,
        base_position: int,
        ema_wm,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm, None

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = self.EMA_ALPHA * wall_mid + (1 - self.EMA_ALPHA) * ema_wm

        fair_adj = ema_wm - self.INV_PENALTY * base_position

        orders: List[Order] = []
        pos = base_position
        max_buy = self.BASE_LIMIT - pos
        max_sell = self.BASE_LIMIT + pos

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
            elif sp <= fair_adj and base_position < 0:
                size = min(sv, abs(base_position), max_buy)
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
            elif bp >= fair_adj and base_position > 0:
                size = min(bv, base_position, max_sell)
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

        max_buy = self.BASE_LIMIT - pos
        max_sell = self.BASE_LIMIT + pos

        if max_buy > 0:
            orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0:
            orders.append(Order("TOMATOES", ask_price, -max_sell))

        return orders, ema_wm, wall_mid

    def _update_overlay_signal(
        self,
        wall_mid,
        history,
        overlay_dir,
        overlay_until_ts,
        timestamp,
    ):
        if history is None:
            history = []

        history.append(wall_mid)
        if len(history) > self.SWING_WINDOW + 5:
            history = history[-(self.SWING_WINDOW + 5):]

        # Expire old overlay
        if overlay_dir != 0 and overlay_until_ts is not None and timestamp >= overlay_until_ts:
            overlay_dir = 0
            overlay_until_ts = None

        if len(history) < self.SWING_WINDOW:
            return history, overlay_dir, overlay_until_ts

        window = history[-self.SWING_WINDOW:]
        prev = window[:-1]
        cur = window[-1]

        prev_min = min(prev)
        prev_max = max(prev)

        min_last_idx = max(i for i, v in enumerate(prev) if v == prev_min)
        max_last_idx = max(i for i, v in enumerate(prev) if v == prev_max)

        min_age = len(prev) - 1 - min_last_idx
        max_age = len(prev) - 1 - max_last_idx

        prev_last = prev[-1]

        long_signal = (
            min_age <= self.MAX_EXTREMA_AGE
            and cur >= prev_min + self.REBOUND_TICKS
            and cur > prev_last
        )

        short_signal = (
            max_age <= self.MAX_EXTREMA_AGE
            and cur <= prev_max - self.REBOUND_TICKS
            and cur < prev_last
        )

        if long_signal and not short_signal:
            overlay_dir = 1
            overlay_until_ts = timestamp + self.HOLD_STEPS * 100
        elif short_signal and not long_signal:
            overlay_dir = -1
            overlay_until_ts = timestamp + self.HOLD_STEPS * 100

        return history, overlay_dir, overlay_until_ts

    def _generate_overlay_orders(
        self,
        depth: OrderDepth,
        overlay_pos: int,
        overlay_dir: int,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], overlay_pos

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        orders: List[Order] = []

        target_overlay_pos = overlay_dir * self.OVERLAY_LIMIT

        # Aggressive one level adjustment toward target overlay inventory
        if overlay_pos < target_overlay_pos:
            best_ask = min(sell_orders.keys())
            best_ask_vol = sell_orders[best_ask]
            size = min(target_overlay_pos - overlay_pos, best_ask_vol)
            if size > 0:
                orders.append(Order("TOMATOES", best_ask, size))
                overlay_pos += size

        elif overlay_pos > target_overlay_pos:
            best_bid = max(buy_orders.keys())
            best_bid_vol = buy_orders[best_bid]
            size = min(overlay_pos - target_overlay_pos, best_bid_vol)
            if size > 0:
                orders.append(Order("TOMATOES", best_bid, -size))
                overlay_pos -= size

        return orders, overlay_pos

    def generate_orders(
        self,
        depth: OrderDepth,
        actual_position: int,
        ema_wm,
        history,
        overlay_dir,
        overlay_until_ts,
        overlay_pos,
        timestamp,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], ema_wm, history, overlay_dir, overlay_until_ts, overlay_pos

        overlay_pos = self._reconcile_overlay_pos(actual_position, overlay_pos)

        # Base sleeve uses position net of overlay sleeve
        base_position = actual_position - overlay_pos

        base_orders, ema_wm, wall_mid = self._generate_base_orders(
            depth,
            base_position,
            ema_wm,
        )

        if wall_mid is None:
            return base_orders, ema_wm, history, overlay_dir, overlay_until_ts, overlay_pos

        history, overlay_dir, overlay_until_ts = self._update_overlay_signal(
            wall_mid,
            history,
            overlay_dir,
            overlay_until_ts,
            timestamp,
        )

        overlay_orders, overlay_pos = self._generate_overlay_orders(
            depth,
            overlay_pos,
            overlay_dir,
        )

        return (
            base_orders + overlay_orders,
            ema_wm,
            history,
            overlay_dir,
            overlay_until_ts,
            overlay_pos,
        )