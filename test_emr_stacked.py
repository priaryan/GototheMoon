"""Test EMERALDS with multiple quote levels (stacked quotes)."""
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple

POS_LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

class EmeraldsMM:
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    INV_PENALTY = 0.05
    
    def generate_orders(self, depth, position):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return []
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        fair = self.FAIR - self.INV_PENALTY * position
        orders = []; pos = position
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        # TAKE
        for sp, sv in sell_orders.items():
            if max_buy <= 0: break
            if sp < fair:
                size = min(sv, max_buy); orders.append(Order("EMERALDS", sp, size)); max_buy -= size; pos += size
            elif sp <= fair and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0: orders.append(Order("EMERALDS", sp, size)); max_buy -= size; pos += size
        for bp, bv in buy_orders.items():
            if max_sell <= 0: break
            if bp > fair:
                size = min(bv, max_sell); orders.append(Order("EMERALDS", bp, -size)); max_sell -= size; pos -= size
            elif bp >= fair and pos > 0:
                size = min(bv, pos, max_sell)
                if size > 0: orders.append(Order("EMERALDS", bp, -size)); max_sell -= size; pos -= size
        
        # MAKE: stacked quotes at 9993 AND 9995 / 10007 AND 10005
        # This tests if quoting at TWO levels captures more flow
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        
        # Primary quotes (wall-mid overbid/underbid)
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        bid_price = int(bid_wall + 1); ask_price = int(ask_wall - 1)
        for bp, bv in buy_orders.items():
            ob = bp + 1
            if bv > 1 and ob < self.FAIR: bid_price = max(bid_price, ob); break
            elif bp < self.FAIR: bid_price = max(bid_price, bp); break
        for sp, sv in sell_orders.items():
            ub = sp - 1
            if sv > 1 and ub > self.FAIR: ask_price = min(ask_price, ub); break
            elif sp > self.FAIR: ask_price = min(ask_price, sp); break
        
        # Split order across two levels
        # E.g., 15 at primary (9993/10007), 5 at secondary (9995/10005)
        primary_size_buy = min(max_buy, 15)
        secondary_size_buy = min(max_buy - primary_size_buy, 5)
        
        primary_size_sell = min(max_sell, 15)
        secondary_size_sell = min(max_sell - primary_size_sell, 5)
        
        if primary_size_buy > 0:
            orders.append(Order("EMERALDS", bid_price, primary_size_buy))
        if secondary_size_buy > 0 and bid_price + 2 < self.FAIR:
            orders.append(Order("EMERALDS", bid_price + 2, secondary_size_buy))
        
        if primary_size_sell > 0:
            orders.append(Order("EMERALDS", ask_price, -primary_size_sell))
        if secondary_size_sell > 0 and ask_price - 2 > self.FAIR:
            orders.append(Order("EMERALDS", ask_price - 2, -secondary_size_sell))
        
        return orders

class TomatoesMM:
    LIMIT = POS_LIMITS["TOMATOES"]
    INV_PENALTY = 0.05
    def generate_orders(self, depth, position):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return []
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2
        fair_adj = wall_mid - self.INV_PENALTY * position
        orders = []; pos = position
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        buy_margin = 0.5; sell_margin = 0.5
        if pos > 5: sell_margin = 0.0
        if pos < -5: buy_margin = 0.0
        for sp, sv in sell_orders.items():
            if max_buy <= 0: break
            if sp <= fair_adj - buy_margin:
                size = min(sv, max_buy); orders.append(Order("TOMATOES", sp, size)); max_buy -= size; pos += size
            elif sp <= fair_adj and position < 0:
                size = min(sv, abs(position), max_buy)
                if size > 0: orders.append(Order("TOMATOES", sp, size)); max_buy -= size; pos += size
        for bp, bv in buy_orders.items():
            if max_sell <= 0: break
            if bp >= fair_adj + sell_margin:
                size = min(bv, max_sell); orders.append(Order("TOMATOES", bp, -size)); max_sell -= size; pos -= size
            elif bp >= fair_adj and position > 0:
                size = min(bv, position, max_sell)
                if size > 0: orders.append(Order("TOMATOES", bp, -size)); max_sell -= size; pos -= size
        bid_price = int(bid_wall + 1); ask_price = int(ask_wall - 1)
        for bp, bv in buy_orders.items():
            ob = bp + 1
            if bv > 1 and ob < wall_mid: bid_price = max(bid_price, ob); break
            elif bp < wall_mid: bid_price = max(bid_price, bp); break
        for sp, sv in sell_orders.items():
            ub = sp - 1
            if sv > 1 and ub > wall_mid: ask_price = min(ask_price, ub); break
            elif sp > wall_mid: ask_price = min(ask_price, sp); break
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
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
