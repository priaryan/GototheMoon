"""Sweep EMA alpha and inventory penalty for TOMATOES."""
import json, sys
from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Tuple

POS_LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

# Parameters to sweep
EMA_ALPHA = 1.0
INV_PENALTY = 0.07

class EmeraldsMM:
    FAIR = 10000
    LIMIT = POS_LIMITS["EMERALDS"]
    def generate_orders(self, depth, position):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return []
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        fair = self.FAIR; orders = []; pos = position
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        for sp, sv in sell_orders.items():
            if max_buy <= 0: break
            if sp < fair:
                size = min(sv, max_buy); orders.append(Order("EMERALDS", sp, size)); max_buy -= size; pos += size
            elif sp == fair and pos < 0:
                size = min(sv, abs(pos), max_buy)
                if size > 0: orders.append(Order("EMERALDS", sp, size)); max_buy -= size; pos += size
        for bp, bv in buy_orders.items():
            if max_sell <= 0: break
            if bp > fair:
                size = min(bv, max_sell); orders.append(Order("EMERALDS", bp, -size)); max_sell -= size; pos -= size
            elif bp == fair and pos > 0:
                size = min(bv, pos, max_sell)
                if size > 0: orders.append(Order("EMERALDS", bp, -size)); max_sell -= size; pos -= size
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        bid_price = int(bid_wall + 1); ask_price = int(ask_wall - 1)
        for bp, bv in buy_orders.items():
            ob = bp + 1
            if bv > 1 and ob < fair: bid_price = max(bid_price, ob); break
            elif bp < fair: bid_price = max(bid_price, bp); break
        for sp, sv in sell_orders.items():
            ub = sp - 1
            if sv > 1 and ub > fair: ask_price = min(ask_price, ub); break
            elif sp > fair: ask_price = min(ask_price, sp); break
        max_buy = self.LIMIT - pos; max_sell = self.LIMIT + pos
        if max_buy > 0: orders.append(Order("EMERALDS", bid_price, max_buy))
        if max_sell > 0: orders.append(Order("EMERALDS", ask_price, -max_sell))
        return orders

class TomatoesMM:
    LIMIT = POS_LIMITS["TOMATOES"]
    
    def generate_orders(self, depth, position, ema_wm):
        raw_buys = depth.buy_orders or {}
        raw_sells = depth.sell_orders or {}
        if not raw_buys or not raw_sells: return [], ema_wm
        buy_orders = {p: abs(v) for p, v in sorted(raw_buys.items(), reverse=True)}
        sell_orders = {p: abs(v) for p, v in sorted(raw_sells.items())}
        bid_wall = min(buy_orders); ask_wall = max(sell_orders)
        wall_mid = (bid_wall + ask_wall) / 2
        
        if ema_wm is None:
            ema_wm = wall_mid
        else:
            ema_wm = EMA_ALPHA * wall_mid + (1 - EMA_ALPHA) * ema_wm
        
        fair_adj = ema_wm - INV_PENALTY * position

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
        return orders, ema_wm

class Trader:
    def __init__(self):
        self.emeralds = EmeraldsMM()
        self.tomatoes = TomatoesMM()
    def run(self, state):
        orders = {}; td = {}
        if state.traderData:
            try: td = json.loads(state.traderData)
            except: pass
        ema_wm = td.get("ema_wm")
        if "EMERALDS" in state.order_depths:
            pos = state.position.get("EMERALDS", 0)
            orders["EMERALDS"] = self.emeralds.generate_orders(state.order_depths["EMERALDS"], pos)
        if "TOMATOES" in state.order_depths:
            pos = state.position.get("TOMATOES", 0)
            tom_orders, ema_wm = self.tomatoes.generate_orders(state.order_depths["TOMATOES"], pos, ema_wm)
            orders["TOMATOES"] = tom_orders
        td["ema_wm"] = ema_wm
        return orders, 0, json.dumps(td)
