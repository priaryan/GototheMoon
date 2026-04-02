"""Quick test: wider EMERALDS quotes on Rust backtester."""
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple

POS_LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

class EmeraldsMM:
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    def generate_orders(self, depth, position):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return []
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        fair = self.FAIR
        orders = []; pos = position
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        for sp, sv in sell_orders.items():
            if max_buy <= 0: break
            if sp < fair:
                size = min(sv, max_buy); orders.append(Order("EMERALDS", sp, size))
                max_buy -= size; pos += size
            elif sp == fair and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0: orders.append(Order("EMERALDS", sp, size)); max_buy -= size; pos += size
        for bp, bv in buy_orders.items():
            if max_sell <= 0: break
            if bp > fair:
                size = min(bv, max_sell); orders.append(Order("EMERALDS", bp, -size))
                max_sell -= size; pos -= size
            elif bp == fair and pos > 0:
                size = min(bv, pos, max_sell)
                if size > 0: orders.append(Order("EMERALDS", bp, -size)); max_sell -= size; pos -= size
        # MAKE: bid at the wall itself (widest possible that still gets fills)
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        bid_price = bid_wall  # AT the wall (wider than wall+1)
        ask_price = ask_wall  # AT the wall
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        if max_buy > 0: orders.append(Order("EMERALDS", bid_price, max_buy))
        if max_sell > 0: orders.append(Order("EMERALDS", ask_price, -max_sell))
        return orders

class TomatoesMM:
    LIMIT = POS_LIMITS["TOMATOES"]
    def generate_orders(self, depth, position):
        raw_buys = depth.buy_orders or {}; raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return []
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2
        orders = []; max_buy = self.LIMIT - position; max_sell = self.LIMIT + position
        for sp, sv in sell_orders.items():
            if max_buy <= 0: break
            if sp <= wall_mid - 1:
                size = min(sv, max_buy); orders.append(Order("TOMATOES", sp, size)); max_buy -= size
            elif sp <= wall_mid and position < 0:
                size = min(sv, abs(position), max_buy)
                orders.append(Order("TOMATOES", sp, size)); max_buy -= size
        for bp, bv in buy_orders.items():
            if max_sell <= 0: break
            if bp >= wall_mid + 1:
                size = min(bv, max_sell); orders.append(Order("TOMATOES", bp, -size)); max_sell -= size
            elif bp >= wall_mid and position > 0:
                size = min(bv, position, max_sell)
                orders.append(Order("TOMATOES", bp, -size)); max_sell -= size
        bid_price = int(bid_wall + 1); ask_price = int(ask_wall - 1)
        for bp, bv in buy_orders.items():
            ob = bp + 1
            if bv > 1 and ob < wall_mid: bid_price = max(bid_price, ob); break
            elif bp < wall_mid: bid_price = max(bid_price, bp); break
        for sp, sv in sell_orders.items():
            ub = sp - 1
            if sv > 1 and ub > wall_mid: ask_price = min(ask_price, ub); break
            elif sp > wall_mid: ask_price = min(ask_price, sp); break
        max_buy = self.LIMIT - position; max_sell = self.LIMIT + position
        if max_buy > 0: orders.append(Order("TOMATOES", bid_price, max_buy))
        if max_sell > 0: orders.append(Order("TOMATOES", ask_price, -max_sell))
        return orders

class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()
    def run(self, state):
        orders = {}
        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(state.order_depths["EMERALDS"], pos)
        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            orders["TOMATOES"] = self.tomatoes.generate_orders(state.order_depths["TOMATOES"], pos)
        return orders, 0, ""
