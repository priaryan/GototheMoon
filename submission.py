from datamodel import Order, OrderDepth, TradingState
from dataclasses import dataclass
from typing import Dict, List, Tuple
import json

@dataclass
class EmeraldConfig:
    symbol: str = "EMERALDS"
    fair_value: int = 10000
    position_limit: int = 20

    # Fair value blending
    fixed_fair_weight: float = 0.0
    wall_mid_weight: float = 1.0

    # Inventory and quoting controls
    soft_inventory_limit: int = 12
    base_quote_size: int = 6
    inventory_step: int = 5

    # StaticTrader style thresholds
    take_through_edge: int = 1


class EmeraldMarketMaker:
    """
    EMERALDS market maker with StaticTrader style logic, but cleaner and configurable.

    Main ideas:
    1. Infer fair using a blend of fixed fair and wall mid
    2. Take asks through fair
    3. Take bids through fair
    4. Allow trading at fair only when flattening inventory
    5. Quote using wall structure
    6. Keep controlled quote sizing and inventory skew
    """

    def __init__(self, config: EmeraldConfig | None = None):
        self.config = config or EmeraldConfig()

    def _get_book(
        self, order_depth: OrderDepth
    ) -> Tuple[Dict[int, int], Dict[int, int]]:
        buy_orders = order_depth.buy_orders or {}
        sell_orders = order_depth.sell_orders or {}
        return buy_orders, sell_orders

    def _get_best_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, int | None]:
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        return best_bid, best_ask

    def _get_wall_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, float | None, int | None]:
        """
        Match the repo worldview:
        bid wall = lowest visible buy price
        ask wall = highest visible sell price
        wall mid = average of the two
        """
        bid_wall = min(buy_orders.keys()) if buy_orders else None
        ask_wall = max(sell_orders.keys()) if sell_orders else None

        if bid_wall is None or ask_wall is None:
            return bid_wall, None, ask_wall

        wall_mid = (bid_wall + ask_wall) / 2
        return bid_wall, wall_mid, ask_wall

    def _compute_fair(
        self,
        fixed_fair: int,
        wall_mid: float | None,
        best_bid: int | None,
        best_ask: int | None,
    ) -> float:
        cfg = self.config

        # Fallback if wall mid is unavailable
        if wall_mid is None:
            if best_bid is not None and best_ask is not None:
                wall_mid = (best_bid + best_ask) / 2
            else:
                wall_mid = float(fixed_fair)

        total_weight = cfg.fixed_fair_weight + cfg.wall_mid_weight
        if total_weight <= 0:
            return float(fixed_fair)

        fair = (
            cfg.fixed_fair_weight * fixed_fair
            + cfg.wall_mid_weight * wall_mid
        ) / total_weight

        return fair

    def generate_orders(self, order_depth: OrderDepth, position: int) -> List[Order]:
        orders: List[Order] = []
        cfg = self.config
        current_pos = position

        buy_orders, sell_orders = self._get_book(order_depth)
        best_bid, best_ask = self._get_best_prices(buy_orders, sell_orders)
        bid_wall, wall_mid, ask_wall = self._get_wall_prices(buy_orders, sell_orders)

        fair = self._compute_fair(
            fixed_fair=cfg.fair_value,
            wall_mid=wall_mid,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        # For StaticTrader style comparisons, use integer fair thresholding
        fair_floor = int(fair)
        fair_ceil = int(fair) if fair == int(fair) else int(fair) + 1

        ##########################################################
        # 1. TAKING
        ##########################################################

        # Buy asks clearly below fair
        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]

            if ask_price <= fair - cfg.take_through_edge:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

            # Buy at fair only to reduce short inventory
            elif ask_price <= fair and current_pos < 0:
                buy_capacity = cfg.position_limit - current_pos
                trade_size = min(ask_vol, abs(current_pos), buy_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

        # Sell bids clearly above fair
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]

            if bid_price >= fair + cfg.take_through_edge:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

            # Sell at fair only to reduce long inventory
            elif bid_price >= fair and current_pos > 0:
                sell_capacity = cfg.position_limit + current_pos
                trade_size = min(bid_vol, current_pos, sell_capacity)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

        ##########################################################
        # 2. MAKING
        ##########################################################

        # Need usable walls to emulate StaticTrader style quoting
        if bid_wall is None or ask_wall is None:
            return orders

        # Base case from wall structure
        bid_quote = int(bid_wall + 1)
        ask_quote = int(ask_wall - 1)

        # OVERBID best meaningful bid still below fair
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = buy_orders[bid_price]
            overbid_price = bid_price + 1

            if bid_vol > 1 and overbid_price < fair:
                bid_quote = max(bid_quote, overbid_price)
                break
            elif bid_price < fair:
                bid_quote = max(bid_quote, bid_price)
                break

        # UNDERCUT best meaningful ask still above fair
        for ask_price in sorted(sell_orders.keys()):
            ask_vol = -sell_orders[ask_price]
            undercut_price = ask_price - 1

            if ask_vol > 1 and undercut_price > fair:
                ask_quote = min(ask_quote, undercut_price)
                break
            elif ask_price > fair:
                ask_quote = min(ask_quote, ask_price)
                break

        # Inventory skew from your cleaner implementation
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety fallback
        if bid_quote >= ask_quote:
            bid_quote = fair_floor - 1
            ask_quote = fair_ceil + 1

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        # Keep your controlled sizing rather than posting full remaining size
        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))

        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        return orders


@dataclass
class TomatoConfig:
    symbol: str = "TOMATOES"
    position_limit: int = 50

    # Passive quoting
    base_quote_size: int = 8
    inventory_step: int = 10
    aggressive_inventory_target: int = 30

    # Pressure signal
    book_imbalance_weight: float = 0.65
    trade_imbalance_weight: float = 0.35

    # Triggering
    aggression_threshold: float = 0.22
    persistence_ticks: int = 2

    # Inventory aware passive taking at benchmark
    flatten_only_at_wall_mid: bool = True

    # Optional cooldown after an aggressive action
    cooldown_ticks: int = 1


class TomatoTrader:
    """
    Dynamic TOMATOES trader inspired by the repo DynamicTrader structure,
    but without any informed trader identity signal.

    Core idea:
    1. Use wall mid as the benchmark
    2. Estimate short term pressure from:
       a. order book imbalance
       b. recent trade flow imbalance
    3. If pressure is strong and persistent, take liquidity directionally
    4. Otherwise make markets around wall structure
    5. Skew quoting by inventory
    """

    def __init__(self, config: TomatoConfig | None = None):
        self.config = config or TomatoConfig()

    def _get_book(
        self, order_depth: OrderDepth
    ) -> Tuple[Dict[int, int], Dict[int, int]]:
        buy_orders = order_depth.buy_orders or {}
        sell_orders = order_depth.sell_orders or {}
        return buy_orders, sell_orders

    def _get_best_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, int | None]:
        best_bid = max(buy_orders.keys()) if buy_orders else None
        best_ask = min(sell_orders.keys()) if sell_orders else None
        return best_bid, best_ask

    def _get_wall_prices(
        self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]
    ) -> Tuple[int | None, float | None, int | None]:
        bid_wall = min(buy_orders.keys()) if buy_orders else None
        ask_wall = max(sell_orders.keys()) if sell_orders else None

        if bid_wall is None or ask_wall is None:
            return bid_wall, None, ask_wall

        wall_mid = (bid_wall + ask_wall) / 2
        return bid_wall, wall_mid, ask_wall

    def _load_trader_data(self, trader_data: str) -> dict:
        if not trader_data:
            return {}
        try:
            return json.loads(trader_data)
        except Exception:
            return {}

    def _dump_trader_data(self, data: dict) -> str:
        try:
            return json.dumps(data)
        except Exception:
            return ""

    def _top_level_volume(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
        levels: int = 3,
    ) -> Tuple[int, int]:
        top_bids = sorted(buy_orders.items(), reverse=True)[:levels]
        top_asks = sorted(sell_orders.items())[:levels]

        bid_vol = sum(v for _, v in top_bids)
        ask_vol = sum(abs(v) for _, v in top_asks)
        return bid_vol, ask_vol

    def _book_imbalance(
        self,
        buy_orders: Dict[int, int],
        sell_orders: Dict[int, int],
        levels: int = 3,
    ) -> float:
        bid_vol, ask_vol = self._top_level_volume(buy_orders, sell_orders, levels=levels)
        total = bid_vol + ask_vol
        if total <= 0:
            return 0.0
        return (bid_vol - ask_vol) / total

    def _trade_flow_imbalance(self, state: TradingState) -> float:
        trades = []
        trades.extend(state.market_trades.get(self.config.symbol, []))
        trades.extend(state.own_trades.get(self.config.symbol, []))

        if not trades:
            return 0.0

        buy_flow = 0
        sell_flow = 0

        for trade in trades:
            qty = abs(trade.quantity)

            # Approximation:
            # buyer only -> bullish pressure
            # seller only -> bearish pressure
            # if both unknown, ignore
            if getattr(trade, "buyer", None) and not getattr(trade, "seller", None):
                buy_flow += qty
            elif getattr(trade, "seller", None) and not getattr(trade, "buyer", None):
                sell_flow += qty
            else:
                # fallback heuristic:
                # if both exist, keep directional neutrality
                # this keeps the signal conservative
                pass

        total = buy_flow + sell_flow
        if total <= 0:
            return 0.0

        return (buy_flow - sell_flow) / total

    def _combined_signal(
        self,
        book_imbalance: float,
        trade_imbalance: float,
    ) -> float:
        cfg = self.config
        return (
            cfg.book_imbalance_weight * book_imbalance
            + cfg.trade_imbalance_weight * trade_imbalance
        )

    def _update_signal_state(self, state: TradingState, raw_signal: float) -> Tuple[int, dict]:
        cfg = self.config
        data = self._load_trader_data(state.traderData)

        tomato_data = data.get(cfg.symbol, {})
        last_direction = tomato_data.get("last_direction", 0)
        persistence = tomato_data.get("persistence", 0)
        cooldown_until = tomato_data.get("cooldown_until", -1)

        direction = 0
        if raw_signal > cfg.aggression_threshold:
            direction = 1
        elif raw_signal < -cfg.aggression_threshold:
            direction = -1

        if direction != 0 and direction == last_direction:
            persistence += 1
        elif direction != 0:
            persistence = 1
        else:
            persistence = 0

        tomato_data["last_direction"] = direction
        tomato_data["persistence"] = persistence
        tomato_data["cooldown_until"] = cooldown_until
        tomato_data["last_signal"] = raw_signal

        data[cfg.symbol] = tomato_data
        return direction, data

    def _can_be_aggressive(self, state: TradingState, data: dict) -> bool:
        cfg = self.config
        tomato_data = data.get(cfg.symbol, {})
        persistence = tomato_data.get("persistence", 0)
        cooldown_until = tomato_data.get("cooldown_until", -1)

        return (
            persistence >= cfg.persistence_ticks
            and state.timestamp > cooldown_until
        )

    def _set_cooldown(self, state: TradingState, data: dict) -> dict:
        cfg = self.config
        tomato_data = data.get(cfg.symbol, {})
        tomato_data["cooldown_until"] = state.timestamp + cfg.cooldown_ticks
        data[cfg.symbol] = tomato_data
        return data

    def generate_orders(
        self,
        state: TradingState,
        order_depth: OrderDepth,
        position: int,
    ) -> Tuple[List[Order], str]:
        orders: List[Order] = []
        cfg = self.config
        current_pos = position

        buy_orders, sell_orders = self._get_book(order_depth)
        best_bid, best_ask = self._get_best_prices(buy_orders, sell_orders)
        bid_wall, wall_mid, ask_wall = self._get_wall_prices(buy_orders, sell_orders)

        if wall_mid is None:
            return orders, state.traderData or ""

        ##########################################################
        # 1. BUILD PRESSURE SIGNAL
        ##########################################################

        book_imb = self._book_imbalance(buy_orders, sell_orders, levels=3)
        trade_imb = self._trade_flow_imbalance(state)
        signal = self._combined_signal(book_imb, trade_imb)

        direction, trader_data_obj = self._update_signal_state(state, signal)
        can_be_aggressive = self._can_be_aggressive(state, trader_data_obj)

        ##########################################################
        # 2. AGGRESSIVE LAYER
        ##########################################################

        aggressive_done = False

        if can_be_aggressive:
            if direction > 0 and best_ask is not None:
                target_pos = cfg.aggressive_inventory_target
                buy_capacity = cfg.position_limit - current_pos
                desired = max(0, target_pos - current_pos)
                trade_size = min(desired, buy_capacity)

                if trade_size > 0:
                    available = abs(sell_orders.get(best_ask, 0))
                    trade_size = min(trade_size, available)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, best_ask, trade_size))
                    current_pos += trade_size
                    aggressive_done = True

            elif direction < 0 and best_bid is not None:
                target_pos = -cfg.aggressive_inventory_target
                sell_capacity = cfg.position_limit + current_pos
                desired = max(0, current_pos - target_pos)
                trade_size = min(desired, sell_capacity)

                if trade_size > 0:
                    available = abs(buy_orders.get(best_bid, 0))
                    trade_size = min(trade_size, available)

                if trade_size > 0:
                    orders.append(Order(cfg.symbol, best_bid, -trade_size))
                    current_pos -= trade_size
                    aggressive_done = True

        if aggressive_done:
            trader_data_obj = self._set_cooldown(state, trader_data_obj)
            return orders, self._dump_trader_data(trader_data_obj)

        ##########################################################
        # 3. PASSIVE TAKING AROUND WALL MID
        ##########################################################

        # Buy below benchmark
        for ask_price in sorted(sell_orders.keys()):
            ask_vol = abs(sell_orders[ask_price])
            buy_capacity = cfg.position_limit - current_pos

            if buy_capacity <= 0:
                break

            if ask_price < wall_mid:
                trade_size = min(ask_vol, buy_capacity)
                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

            elif cfg.flatten_only_at_wall_mid and ask_price <= wall_mid and current_pos < 0:
                trade_size = min(ask_vol, abs(current_pos), buy_capacity)
                if trade_size > 0:
                    orders.append(Order(cfg.symbol, ask_price, trade_size))
                    current_pos += trade_size

        # Sell above benchmark
        for bid_price in sorted(buy_orders.keys(), reverse=True):
            bid_vol = abs(buy_orders[bid_price])
            sell_capacity = cfg.position_limit + current_pos

            if sell_capacity <= 0:
                break

            if bid_price > wall_mid:
                trade_size = min(bid_vol, sell_capacity)
                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

            elif cfg.flatten_only_at_wall_mid and bid_price >= wall_mid and current_pos > 0:
                trade_size = min(bid_vol, current_pos, sell_capacity)
                if trade_size > 0:
                    orders.append(Order(cfg.symbol, bid_price, -trade_size))
                    current_pos -= trade_size

        ##########################################################
        # 4. PASSIVE MAKING
        ##########################################################

        if bid_wall is None or ask_wall is None:
            return orders, self._dump_trader_data(trader_data_obj)

        bid_quote = int(bid_wall + 1)
        ask_quote = int(ask_wall - 1)

        # Slight directional shading even when not aggressive
        if signal > 0:
            ask_quote = max(ask_quote, int(ask_wall))
        elif signal < 0:
            bid_quote = min(bid_quote, int(bid_wall))

        # Inventory skew
        skew_steps = current_pos // cfg.inventory_step
        bid_quote -= skew_steps
        ask_quote -= skew_steps

        # Safety
        if bid_quote >= ask_quote:
            benchmark_floor = int(wall_mid)
            benchmark_ceil = benchmark_floor if wall_mid == benchmark_floor else benchmark_floor + 1
            bid_quote = benchmark_floor - 1
            ask_quote = benchmark_ceil + 1

        max_buy = cfg.position_limit - current_pos
        max_sell = cfg.position_limit + current_pos

        bid_size = min(cfg.base_quote_size, max(0, max_buy))
        ask_size = min(cfg.base_quote_size, max(0, max_sell))

        if bid_size > 0:
            orders.append(Order(cfg.symbol, bid_quote, bid_size))

        if ask_size > 0:
            orders.append(Order(cfg.symbol, ask_quote, -ask_size))

        return orders, self._dump_trader_data(trader_data_obj)

class Trader:
    """
    IMC submission entry point.
    Trades EMERALDS and TOMATOES.
    """

    def __init__(self):
        self.emeralds_mm = EmeraldMarketMaker(
            EmeraldConfig(
                symbol="EMERALDS",
                fair_value=10000,
                position_limit=20,
                fixed_fair_weight=0.2,
                wall_mid_weight=0.8,
                soft_inventory_limit=12,
                base_quote_size=6,
                inventory_step=5,
                take_through_edge=1,
            )
        )

        self.tomato_trader = TomatoTrader(
            TomatoConfig(
                symbol="TOMATOES",
                position_limit=50,
                base_quote_size=8,
                inventory_step=10,
                aggressive_inventory_target=30,
                book_imbalance_weight=0.65,
                trade_imbalance_weight=0.35,
                aggression_threshold=0.22,
                persistence_ticks=2,
                flatten_only_at_wall_mid=True,
                cooldown_ticks=1,
            )
        )

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        orders: Dict[str, List[Order]] = {}
        trader_data = state.traderData or ""

        if "EMERALDS" in state.order_depths:
            emeralds_position = state.position.get("EMERALDS", 0)
            emeralds_order_depth = state.order_depths["EMERALDS"]

            emeralds_orders = self.emeralds_mm.generate_orders(
                emeralds_order_depth,
                emeralds_position,
            )

            if emeralds_orders:
                orders["EMERALDS"] = emeralds_orders

        if "TOMATOES" in state.order_depths:
            tomatoes_position = state.position.get("TOMATOES", 0)
            tomatoes_order_depth = state.order_depths["TOMATOES"]

            tomatoes_orders, trader_data = self.tomato_trader.generate_orders(
                state,
                tomatoes_order_depth,
                tomatoes_position,
            )

            if tomatoes_orders:
                orders["TOMATOES"] = tomatoes_orders

        conversions = 0
        return orders, conversions, trader_data