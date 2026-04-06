"""
bestfornow_full.py

Active strategies:
  EMERALDS: wall mid making with inventory penalised taking.
  TOMATOES: Dual EMA momentum with soft dampening + adaptive IP.

Skeleton strategies (rename products when round is revealed):
  PRODUCT_X: Informed-trader-following market maker (Kelp-style)
  PRODUCT_Y: Pure informed-direction follower (Ink-style)
  BASKET_A / COMP_A1, COMP_A2, COMP_A3: ETF basket spread trading
  OPTION_UNDERLYING / OPTION_VOUCHER_*: BS options + IV scalping
  PRODUCT_Z: Commodity conversion arbitrage
"""

import json
import math
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple
from statistics import NormalDist

_N = NormalDist()

# ══════════════════════════════════════════════════════════════════
#  PRODUCT CONFIG — rename these when the round products are known
# ══════════════════════════════════════════════════════════════════

POS_LIMITS = {
    "EMERALDS": 20,
    "TOMATOES": 20,
    "PRODUCT_X": 50,
    "PRODUCT_Y": 50,
    "BASKET_A": 60,
    "COMP_A1": 250,
    "COMP_A2": 350,
    "COMP_A3": 60,
    "OPTION_UNDERLYING": 400,
    "OPTION_VOUCHER_9500": 200,
    "OPTION_VOUCHER_9750": 200,
    "OPTION_VOUCHER_10000": 200,
    "OPTION_VOUCHER_10250": 200,
    "OPTION_VOUCHER_10500": 200,
    "PRODUCT_Z": 75,
}

INFORMED_TRADER_ID = "Olivia"
LONG, NEUTRAL, SHORT = 1, 0, -1

BASKET_CONSTITUENTS = ["COMP_A1", "COMP_A2", "COMP_A3"]
BASKET_FACTORS = [6, 3, 1]  # BASKET_A = 6*COMP_A1 + 3*COMP_A2 + 1*COMP_A3

OPTION_SYMBOLS = [
    "OPTION_VOUCHER_9500",
    "OPTION_VOUCHER_9750",
    "OPTION_VOUCHER_10000",
    "OPTION_VOUCHER_10250",
    "OPTION_VOUCHER_10500",
]

CONVERSION_LIMIT = 10


# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def parse_book(depth: OrderDepth):
    """Return (buy_orders desc, sell_orders asc) with positive volumes."""
    raw_buys = depth.buy_orders or {}
    raw_sells = depth.sell_orders or {}
    buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
    sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
    return buy_orders, sell_orders


def get_walls(buy_orders, sell_orders):
    """Return (bid_wall, wall_mid, ask_wall)."""
    bid_wall = min(buy_orders)
    ask_wall = max(sell_orders)
    wall_mid = (bid_wall + ask_wall) / 2
    return bid_wall, wall_mid, ask_wall


def detect_informed(state: TradingState, symbol: str, prev_bought_ts, prev_sold_ts):
    """
    Scan market_trades + own_trades for the informed trader (Olivia).
    Returns (direction, bought_ts, sold_ts).
    """
    bought_ts = prev_bought_ts
    sold_ts = prev_sold_ts

    trades = state.market_trades.get(symbol, []) + state.own_trades.get(symbol, [])
    for trade in trades:
        if trade.buyer == INFORMED_TRADER_ID:
            bought_ts = trade.timestamp
        if trade.seller == INFORMED_TRADER_ID:
            sold_ts = trade.timestamp

    if bought_ts is None and sold_ts is None:
        direction = NEUTRAL
    elif bought_ts is not None and sold_ts is None:
        direction = LONG
    elif bought_ts is None and sold_ts is not None:
        direction = SHORT
    elif bought_ts > sold_ts:
        direction = LONG
    elif sold_ts > bought_ts:
        direction = SHORT
    else:
        direction = NEUTRAL

    return direction, bought_ts, sold_ts


# ══════════════════════════════════════════════════════════════════
#  EMERALDS — wall mid making (unchanged)
# ══════════════════════════════════════════════════════════════════

class EmeraldsMM:
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    INV_PENALTY = 0.0

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


# ══════════════════════════════════════════════════════════════════
#  TOMATOES — dual EMA momentum + soft dampening + adaptive IP
# ══════════════════════════════════════════════════════════════════

class TomatoesMM:
    LIMIT = POS_LIMITS["TOMATOES"]

    FAST_ALPHA = 0.10
    SLOW_ALPHA = 0.02

    MOMENTUM_WEIGHT = 0.5

    TAKE_MARGIN = 0.0
    INV_PENALTY = 0.02
    INV_PENALTY_HIGH = 0.08
    MOMENTUM_THRESHOLD = 0.75

    WARMUP_TICKS = 5

    def generate_orders(
        self,
        depth: OrderDepth,
        position: int,
        fast_ema,
        slow_ema,
        warmup_ticks: int,
    ) -> tuple:
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells:
            return [], fast_ema, slow_ema, warmup_ticks

        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}

        best_bid = max(buy_orders)
        best_ask = min(sell_orders)
        bid_wall = min(buy_orders)
        ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2

        if fast_ema is None:
            fast_ema = wall_mid
            slow_ema = wall_mid
        else:
            fast_ema = self.FAST_ALPHA * wall_mid + (1 - self.FAST_ALPHA) * fast_ema
            slow_ema = self.SLOW_ALPHA * wall_mid + (1 - self.SLOW_ALPHA) * slow_ema

        warmup_ticks += 1
        if warmup_ticks <= self.WARMUP_TICKS:
            return [], fast_ema, slow_ema, warmup_ticks

        raw_momentum = fast_ema - slow_ema
        abs_mom = abs(raw_momentum)
        scale = min(1.0, abs_mom / self.MOMENTUM_THRESHOLD)
        momentum = raw_momentum * scale

        if abs_mom < self.MOMENTUM_THRESHOLD:
            inv_pen = self.INV_PENALTY_HIGH
        else:
            inv_pen = self.INV_PENALTY

        fair_adj = (
            slow_ema
            + self.MOMENTUM_WEIGHT * momentum
            - inv_pen * position
        )

        orders: List[Order] = []
        pos = position
        max_buy = self.LIMIT - pos
        max_sell = self.LIMIT + pos

        buy_margin = self.TAKE_MARGIN
        sell_margin = self.TAKE_MARGIN
        if pos > 0:
            sell_margin = 0.0
        if pos < 0:
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

        return orders, fast_ema, slow_ema, warmup_ticks


# ══════════════════════════════════════════════════════════════════
#  PRODUCT_X — Informed-trader-following market maker (Kelp-style)
#
#  Wall-mid MM that reacts to Olivia's trades:
#    - If Olivia bought recently, aggressively lift asks
#    - If Olivia sold recently, aggressively hit bids
#    - Otherwise widen quotes away from informed direction
# ══════════════════════════════════════════════════════════════════

class ProductXMM:
    SYMBOL = "PRODUCT_X"
    LIMIT = POS_LIMITS[SYMBOL]
    INFORMED_WINDOW = 500  # ms to react after informed trade
    SAFE_POS = 40          # don't chase beyond this position

    def generate_orders(
        self,
        state: TradingState,
        depth: OrderDepth,
        position: int,
        prev_bought_ts,
        prev_sold_ts,
    ) -> tuple:
        buy_orders, sell_orders = parse_book(depth)
        if not buy_orders or not sell_orders:
            return [], prev_bought_ts, prev_sold_ts

        bid_wall, wall_mid, ask_wall = get_walls(buy_orders, sell_orders)
        direction, bought_ts, sold_ts = detect_informed(
            state, self.SYMBOL, prev_bought_ts, prev_sold_ts
        )

        orders: List[Order] = []
        max_buy = self.LIMIT - position
        max_sell = self.LIMIT + position

        # ── Bid side ──
        bid_price = int(bid_wall + 1)
        bid_volume = max_buy

        # Olivia bought recently → aggressively lift asks to follow
        if bought_ts is not None and bought_ts + self.INFORMED_WINDOW >= state.timestamp:
            if position < self.SAFE_POS:
                bid_price = int(ask_wall)
                bid_volume = self.SAFE_POS - position
        else:
            # Olivia is short → widen bid (don't buy cheaply into informed selling)
            if wall_mid - bid_price < 1 and direction == SHORT and position > -self.SAFE_POS:
                bid_price = int(bid_wall)

        if bid_volume > 0 and max_buy > 0:
            orders.append(Order(self.SYMBOL, bid_price, min(bid_volume, max_buy)))

        # ── Ask side ──
        ask_price = int(ask_wall - 1)
        ask_volume = max_sell

        # Olivia sold recently → aggressively hit bids to follow
        if sold_ts is not None and sold_ts + self.INFORMED_WINDOW >= state.timestamp:
            if position > -self.SAFE_POS:
                ask_price = int(bid_wall)
                ask_volume = self.SAFE_POS + position
        else:
            # Olivia is long → widen ask
            if ask_price - wall_mid < 1 and direction == LONG and position < self.SAFE_POS:
                ask_price = int(ask_wall)

        if ask_volume > 0 and max_sell > 0:
            orders.append(Order(self.SYMBOL, ask_price, -min(ask_volume, max_sell)))

        return orders, bought_ts, sold_ts


# ══════════════════════════════════════════════════════════════════
#  PRODUCT_Y — Pure informed-direction follower (Ink-style)
#
#  Simpler than X: just max-out position in Olivia's direction.
#  Best for products where informed signal is very strong.
# ══════════════════════════════════════════════════════════════════

class ProductYFollower:
    SYMBOL = "PRODUCT_Y"
    LIMIT = POS_LIMITS[SYMBOL]

    def generate_orders(
        self,
        state: TradingState,
        depth: OrderDepth,
        position: int,
        prev_bought_ts,
        prev_sold_ts,
    ) -> tuple:
        buy_orders, sell_orders = parse_book(depth)
        if not buy_orders or not sell_orders:
            return [], prev_bought_ts, prev_sold_ts

        bid_wall, wall_mid, ask_wall = get_walls(buy_orders, sell_orders)
        direction, bought_ts, sold_ts = detect_informed(
            state, self.SYMBOL, prev_bought_ts, prev_sold_ts
        )

        orders: List[Order] = []

        # Target position: max long if Olivia long, max short if short, flat if neutral
        target = 0
        if direction == LONG:
            target = self.LIMIT
        elif direction == SHORT:
            target = -self.LIMIT

        remaining = target - position

        if remaining > 0:
            orders.append(Order(self.SYMBOL, int(ask_wall), remaining))
        elif remaining < 0:
            orders.append(Order(self.SYMBOL, int(bid_wall), remaining))

        return orders, bought_ts, sold_ts


# ══════════════════════════════════════════════════════════════════
#  BASKET_A — ETF basket spread trading
#
#  Computes spread = basket_mid - (f1*comp1 + f2*comp2 + f3*comp3)
#  Adjusts for a running mean premium.
#  Trades basket when spread exceeds threshold; hedges with constituents.
# ══════════════════════════════════════════════════════════════════

class BasketSpreadTrader:
    BASKET_SYMBOL = "BASKET_A"
    BASKET_LIMIT = POS_LIMITS[BASKET_SYMBOL]

    SPREAD_THRESHOLD = 80      # open when |spread - premium| > this
    INITIAL_PREMIUM = 5.0      # starting estimate of basket premium
    INITIAL_N = 60000          # weight of initial premium estimate
    CLOSE_AT_ZERO = True       # close position when spread crosses zero
    HEDGE_FACTOR = 0.5         # fraction of basket position to delta-hedge

    def generate_orders(
        self,
        state: TradingState,
        basket_pos: int,
        comp_positions: Dict[str, int],
        premium_state: list,  # [mean_premium, n]
    ) -> tuple:
        """Returns (all_orders_dict, updated_premium_state)."""
        all_orders: Dict[str, List[Order]] = {self.BASKET_SYMBOL: []}
        for sym in BASKET_CONSTITUENTS:
            all_orders[sym] = []

        # Parse basket book
        if self.BASKET_SYMBOL not in state.order_depths:
            return all_orders, premium_state
        basket_buys, basket_sells = parse_book(state.order_depths[self.BASKET_SYMBOL])
        if not basket_buys or not basket_sells:
            return all_orders, premium_state

        basket_bid_wall, basket_mid, basket_ask_wall = get_walls(basket_buys, basket_sells)

        # Parse constituent books, compute index price
        comp_mids = {}
        for sym in BASKET_CONSTITUENTS:
            if sym not in state.order_depths:
                return all_orders, premium_state
            cb, cs = parse_book(state.order_depths[sym])
            if not cb or not cs:
                return all_orders, premium_state
            _, mid, _ = get_walls(cb, cs)
            comp_mids[sym] = mid

        index_price = sum(
            comp_mids[sym] * f for sym, f in zip(BASKET_CONSTITUENTS, BASKET_FACTORS)
        )

        # Update running premium estimate
        raw_spread = basket_mid - index_price
        mean_premium, n = premium_state
        n += 1
        mean_premium += (raw_spread - mean_premium) / n
        premium_state = [mean_premium, n]

        spread = raw_spread - mean_premium

        # ── Basket orders ──
        max_buy = self.BASKET_LIMIT - basket_pos
        max_sell = self.BASKET_LIMIT + basket_pos
        expected_pos = basket_pos

        if spread > self.SPREAD_THRESHOLD and max_sell > 0:
            all_orders[self.BASKET_SYMBOL].append(
                Order(self.BASKET_SYMBOL, int(basket_bid_wall), -max_sell)
            )
            fill_est = min(sum(basket_buys.values()), max_sell)
            expected_pos -= fill_est

        elif spread < -self.SPREAD_THRESHOLD and max_buy > 0:
            all_orders[self.BASKET_SYMBOL].append(
                Order(self.BASKET_SYMBOL, int(basket_ask_wall), max_buy)
            )
            fill_est = min(sum(basket_sells.values()), max_buy)
            expected_pos += fill_est

        elif self.CLOSE_AT_ZERO:
            if spread > 0 and basket_pos > 0:
                all_orders[self.BASKET_SYMBOL].append(
                    Order(self.BASKET_SYMBOL, int(basket_bid_wall), -basket_pos)
                )
                expected_pos -= min(sum(basket_buys.values()), basket_pos)
            elif spread < 0 and basket_pos < 0:
                all_orders[self.BASKET_SYMBOL].append(
                    Order(self.BASKET_SYMBOL, int(basket_ask_wall), -basket_pos)
                )
                expected_pos += min(sum(basket_sells.values()), -basket_pos)

        # ── Constituent hedge orders ──
        for i, sym in enumerate(BASKET_CONSTITUENTS):
            factor = BASKET_FACTORS[i]
            target_hedge = round(-expected_pos * factor * self.HEDGE_FACTOR)
            remaining = target_hedge - comp_positions.get(sym, 0)

            if sym not in state.order_depths:
                continue
            cb, cs = parse_book(state.order_depths[sym])
            if not cb or not cs:
                continue
            c_bid_wall, _, c_ask_wall = get_walls(cb, cs)

            limit = POS_LIMITS[sym]
            cpos = comp_positions.get(sym, 0)
            if remaining > 0:
                remaining = min(remaining, limit - cpos)
                if remaining > 0:
                    all_orders[sym].append(Order(sym, int(c_ask_wall), remaining))
            elif remaining < 0:
                remaining = max(remaining, -(limit + cpos))
                if remaining < 0:
                    all_orders[sym].append(Order(sym, int(c_bid_wall), remaining))

        return all_orders, premium_state


# ══════════════════════════════════════════════════════════════════
#  OPTIONS — Black-Scholes IV scalping + mean reversion
#
#  For each voucher:
#    1. Compute theo via BS with fitted vol smile
#    2. Track EMA of (market - theo) deviation
#    3. Trade when deviation exceeds threshold
#  Underlying: mean-reversion on EMA deviation
# ══════════════════════════════════════════════════════════════════

class OptionsMM:
    UNDERLYING_SYMBOL = "OPTION_UNDERLYING"
    UNDERLYING_LIMIT = POS_LIMITS[UNDERLYING_SYMBOL]

    DAY = 5                          # current competition day
    DAYS_PER_YEAR = 365

    # Vol smile coefficients: iv = c[0]*m^2 + c[1]*m + c[2]
    # where m = log(K/S) / sqrt(TTE)
    VOL_SMILE_COEFFS = [0.27362531, 0.01007566, 0.14876677]

    THEO_EMA_WINDOW = 20             # EMA window for theo diff normalisation
    IV_SCALP_THR_OPEN = 0.5          # open position threshold
    IV_SCALP_THR_CLOSE = 0.0         # close position threshold

    UNDERLYING_MR_WINDOW = 10        # EMA window for underlying mean reversion
    UNDERLYING_MR_THR = 15           # deviation threshold to trade underlying

    WARMUP_TICKS = 30                # don't trade until this many ticks

    @staticmethod
    def bs_call(S, K, TTE, sigma):
        d1 = (math.log(S / K) + 0.5 * sigma ** 2 * TTE) / (sigma * TTE ** 0.5)
        d2 = d1 - sigma * TTE ** 0.5
        price = S * _N.cdf(d1) - K * _N.cdf(d2)
        delta = _N.cdf(d1)
        vega = S * _N.pdf(d1) * TTE ** 0.5
        return price, delta, vega

    def get_iv(self, S, K, TTE):
        m = math.log(K / S) / TTE ** 0.5
        c = self.VOL_SMILE_COEFFS
        return c[0] * m * m + c[1] * m + c[2]

    def generate_orders(
        self,
        state: TradingState,
        underlying_pos: int,
        option_positions: Dict[str, int],
        ema_state: dict,  # {key: value} for all EMA states
    ) -> tuple:
        """Returns (all_orders_dict, updated_ema_state)."""
        all_orders: Dict[str, List[Order]] = {self.UNDERLYING_SYMBOL: []}
        for sym in OPTION_SYMBOLS:
            all_orders[sym] = []

        # Parse underlying book
        if self.UNDERLYING_SYMBOL not in state.order_depths:
            return all_orders, ema_state
        u_buys, u_sells = parse_book(state.order_depths[self.UNDERLYING_SYMBOL])
        if not u_buys or not u_sells:
            return all_orders, ema_state
        _, u_mid, _ = get_walls(u_buys, u_sells)
        best_u_bid = max(u_buys)
        best_u_ask = min(u_sells)
        underlying_price = (best_u_bid + best_u_ask) / 2

        # TTE calculation
        tick_fraction = state.timestamp / 100 / 10_000
        tte = 1 - (self.DAYS_PER_YEAR - 8 + self.DAY + tick_fraction) / self.DAYS_PER_YEAR
        if tte <= 0:
            return all_orders, ema_state

        # EMA helper
        def update_ema(key, value, window):
            alpha = 2 / (window + 1)
            old = ema_state.get(key, 0.0)
            new = alpha * value + (1 - alpha) * old
            ema_state[key] = new
            return new

        # Underlying mean-reversion EMA
        u_ema = update_ema("u_ema", u_mid, self.UNDERLYING_MR_WINDOW)
        u_dev = u_mid - u_ema

        # Skip warmup
        tick_num = state.timestamp / 100
        if tick_num < self.WARMUP_TICKS:
            return all_orders, ema_state

        # ── Option orders (IV scalping) ──
        for sym in OPTION_SYMBOLS:
            if sym not in state.order_depths:
                continue
            o_buys, o_sells = parse_book(state.order_depths[sym])
            if not o_buys or not o_sells:
                continue

            o_bid_wall, o_mid, o_ask_wall = get_walls(o_buys, o_sells)
            best_o_bid = max(o_buys)
            best_o_ask = min(o_sells)

            strike = int(sym.split("_")[-1])
            iv = self.get_iv(underlying_price, strike, tte)
            theo, delta, vega = self.bs_call(underlying_price, strike, tte, iv)

            theo_diff = o_mid - theo
            mean_diff = update_ema(f"{sym}_td", theo_diff, self.THEO_EMA_WINDOW)
            norm_diff = theo_diff - mean_diff

            pos = option_positions.get(sym, 0)
            limit = POS_LIMITS[sym]
            max_buy = limit - pos
            max_sell = limit + pos

            # Overpriced → sell
            if norm_diff >= self.IV_SCALP_THR_OPEN and max_sell > 0:
                all_orders[sym].append(Order(sym, best_o_bid, -max_sell))
            elif norm_diff >= self.IV_SCALP_THR_CLOSE and pos > 0:
                all_orders[sym].append(Order(sym, best_o_bid, -pos))
            # Underpriced → buy
            elif norm_diff <= -self.IV_SCALP_THR_OPEN and max_buy > 0:
                all_orders[sym].append(Order(sym, best_o_ask, max_buy))
            elif norm_diff <= -self.IV_SCALP_THR_CLOSE and pos < 0:
                all_orders[sym].append(Order(sym, best_o_ask, -pos))

        # ── Underlying mean-reversion ──
        u_max_buy = self.UNDERLYING_LIMIT - underlying_pos
        u_max_sell = self.UNDERLYING_LIMIT + underlying_pos
        u_bid_wall, _, u_ask_wall = get_walls(u_buys, u_sells)

        if u_dev > self.UNDERLYING_MR_THR and u_max_sell > 0:
            all_orders[self.UNDERLYING_SYMBOL].append(
                Order(self.UNDERLYING_SYMBOL, int(u_bid_wall + 1), -u_max_sell)
            )
        elif u_dev < -self.UNDERLYING_MR_THR and u_max_buy > 0:
            all_orders[self.UNDERLYING_SYMBOL].append(
                Order(self.UNDERLYING_SYMBOL, int(u_ask_wall - 1), u_max_buy)
            )

        return all_orders, ema_state


# ══════════════════════════════════════════════════════════════════
#  PRODUCT_Z — Commodity conversion arbitrage
#
#  Compares local market price vs external (conversion) price.
#  If local sell > external buy cost → sell locally, convert to replenish.
#  If local buy < external sell revenue → buy locally, convert to sell.
#  Position is always flattened via conversion each tick.
# ══════════════════════════════════════════════════════════════════

class ProductZArb:
    SYMBOL = "PRODUCT_Z"
    LIMIT = POS_LIMITS[SYMBOL]

    def generate_orders(
        self,
        state: TradingState,
        depth: OrderDepth,
        position: int,
    ) -> tuple:
        """Returns (orders, conversions)."""
        orders: List[Order] = []
        conversions = 0

        conv_obs = state.observations.conversionObservations.get(self.SYMBOL)
        if conv_obs is None:
            return orders, conversions

        buy_orders, sell_orders = parse_book(depth)
        if not buy_orders or not sell_orders:
            return orders, conversions

        ex_bid = conv_obs.bidPrice
        ex_ask = conv_obs.askPrice
        transport = conv_obs.transportFees
        export_tariff = conv_obs.exportTariff
        import_tariff = conv_obs.importTariff

        # Effective prices including fees
        # Buy from external (import): cost = ex_ask + import_tariff + transport
        # Sell to external (export): revenue = ex_bid - export_tariff - transport
        cost_to_import = ex_ask + import_tariff + transport
        revenue_to_export = ex_bid - export_tariff - transport

        # Strategy: sell locally at prices above import cost (short arb)
        local_sell_price = math.floor(ex_bid + 0.5)
        local_buy_price = math.ceil(ex_ask - 0.5)

        short_arb = local_sell_price - cost_to_import
        long_arb = revenue_to_export - local_buy_price

        remaining = CONVERSION_LIMIT

        if short_arb > long_arb and short_arb >= 0:
            # Sell locally → will import via conversion to cover
            for bp, bv in buy_orders.items():
                if remaining <= 0:
                    break
                if bp >= local_sell_price:
                    v = min(remaining, bv)
                    orders.append(Order(self.SYMBOL, bp, -v))
                    remaining -= v
            if remaining > 0:
                orders.append(Order(self.SYMBOL, local_sell_price, -remaining))

        elif long_arb >= 0:
            # Buy locally → will export via conversion to sell
            for sp, sv in sell_orders.items():
                if remaining <= 0:
                    break
                if sp <= local_buy_price:
                    v = min(remaining, sv)
                    orders.append(Order(self.SYMBOL, sp, v))
                    remaining -= v
            if remaining > 0:
                orders.append(Order(self.SYMBOL, local_buy_price, remaining))

        # Flatten position via conversion (convert all inventory)
        conversions = max(min(-position, CONVERSION_LIMIT), -CONVERSION_LIMIT)

        return orders, conversions


# ══════════════════════════════════════════════════════════════════
#  TRADER — main entry point
# ══════════════════════════════════════════════════════════════════

class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()
        self.product_x = ProductXMM()
        self.product_y = ProductYFollower()
        self.basket = BasketSpreadTrader()
        self.options = OptionsMM()
        self.product_z = ProductZArb()

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}
        conversions = 0

        td = {}
        if state.traderData:
            try:
                td = json.loads(state.traderData)
            except Exception:
                pass

        # ── EMERALDS ──
        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(
                state.order_depths["EMERALDS"], pos
            )

        # ── TOMATOES ──
        fast_ema = td.get("fast_ema")
        slow_ema = td.get("slow_ema")
        tomato_warmup_ticks = td.get("tomato_warmup_ticks", 0)

        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, fast_ema, slow_ema, tomato_warmup_ticks = self.tomatoes.generate_orders(
                state.order_depths["TOMATOES"], pos, fast_ema, slow_ema, tomato_warmup_ticks,
            )
            orders["TOMATOES"] = tom_orders

        td["fast_ema"] = fast_ema
        td["slow_ema"] = slow_ema
        td["tomato_warmup_ticks"] = tomato_warmup_ticks

        # ── PRODUCT_X (informed MM) ──
        x_bought = td.get("x_bought_ts")
        x_sold = td.get("x_sold_ts")

        if "PRODUCT_X" in state.order_depths:
            pos = state.position.get("PRODUCT_X", 0)
            x_orders, x_bought, x_sold = self.product_x.generate_orders(
                state, state.order_depths["PRODUCT_X"], pos, x_bought, x_sold,
            )
            orders["PRODUCT_X"] = x_orders

        td["x_bought_ts"] = x_bought
        td["x_sold_ts"] = x_sold

        # ── PRODUCT_Y (informed follower) ──
        y_bought = td.get("y_bought_ts")
        y_sold = td.get("y_sold_ts")

        if "PRODUCT_Y" in state.order_depths:
            pos = state.position.get("PRODUCT_Y", 0)
            y_orders, y_bought, y_sold = self.product_y.generate_orders(
                state, state.order_depths["PRODUCT_Y"], pos, y_bought, y_sold,
            )
            orders["PRODUCT_Y"] = y_orders

        td["y_bought_ts"] = y_bought
        td["y_sold_ts"] = y_sold

        # ── BASKET_A + constituents ──
        premium_state = td.get("basket_premium", [self.basket.INITIAL_PREMIUM, self.basket.INITIAL_N])

        if "BASKET_A" in state.order_depths:
            basket_pos = state.position.get("BASKET_A", 0)
            comp_positions = {sym: state.position.get(sym, 0) for sym in BASKET_CONSTITUENTS}
            basket_orders, premium_state = self.basket.generate_orders(
                state, basket_pos, comp_positions, premium_state,
            )
            orders.update(basket_orders)

        td["basket_premium"] = premium_state

        # ── OPTIONS ──
        option_ema = td.get("option_ema", {})

        if "OPTION_UNDERLYING" in state.order_depths:
            u_pos = state.position.get("OPTION_UNDERLYING", 0)
            o_positions = {sym: state.position.get(sym, 0) for sym in OPTION_SYMBOLS}
            option_orders, option_ema = self.options.generate_orders(
                state, u_pos, o_positions, option_ema,
            )
            orders.update(option_orders)

        td["option_ema"] = option_ema

        # ── PRODUCT_Z (conversion arb) ──
        if "PRODUCT_Z" in state.order_depths:
            pos = state.position.get("PRODUCT_Z", 0)
            z_orders, conversions = self.product_z.generate_orders(
                state, state.order_depths["PRODUCT_Z"], pos,
            )
            orders["PRODUCT_Z"] = z_orders

        return orders, conversions, json.dumps(td)
