# IMC Prosperity 3 Backtester Setup

## Installation

The backtester is already cloned in `backtests/imc-prosperity-3-backtester/`.

If you need to reinstall or update the backtester, run:

```bash
cd backtests/imc-prosperity-3-backtester
pip install -e .
```

Or install the latest version globally:

```bash
pip install -U prosperity3bt
```

## Running Backtest

From the project root directory (GototheMoon/), run:

```bash
# Backtest on all days from round 0
prosperity3bt algorithm.py 0

# Backtest on specific day
prosperity3bt algorithm.py 0-0

# Backtest on round 1
prosperity3bt algorithm.py 1

# With visualization (if log format matches visualizer)
prosperity3bt algorithm.py 0 --vis

# With custom output file
prosperity3bt algorithm.py 0 --out results.log

# Merge PnL across days
prosperity3bt algorithm.py 0 --merge-pnl
```

## Algorithm Structure

The algorithm is organized as follows:

- **algorithm.py** - Entry point for backtester (imports Trader from src/)
- **src/trader.py** - Main `Trader` class with `run()` method
- **src/strategies/emerald_market_maker.py** - EmeraldMarketMaker strategy logic
- **src/models/**, **src/execution/** - Helper modules

The `Trader.run(state)` method must return:
- `orders: Dict[Symbol, List[Order]]` - Orders grouped by product
- `conversions: List` - Any conversion operations
- `trader_data: str` - Persistent state between calls

## Key Changes Made for Backtester Compatibility

1. ✅ Added `Trader` class with `run(state: TradingState)` method
2. ✅ Orders now returned as `Dict[Symbol, List[Order]]`
3. ✅ Flexible imports supporting both local `datamodel` and backtester's `prosperity3bt.datamodel`
4. ✅ Uses `TradingState` object for getting position and order depths

## Adding More Strategies

To add a new product strategy:

1. Create strategy class in `src/strategies/`
2. Implement logic matching the `EmeraldMarketMaker` interface
3. In `Trader.run()`, instantiate and call the strategy
4. Add orders to the `orders` dict: `orders["PRODUCT"] = strategy_orders`

Example:

```python
def run(self, state: TradingState):
    orders = {}
    
    # Your existing EMERALDS logic
    emerald_orders = self.emerald_mm.generate_orders(
        state.order_depths["EMERALDS"],
        state.position.get("EMERALDS", 0)
    )
    if emerald_orders:
        orders["EMERALDS"] = emerald_orders
    
    # Add new product
    starfruit_orders = self.starfruit_strategy.generate_orders(
        state.order_depths["STARFRUIT"],
        state.position.get("STARFRUIT", 0)
    )
    if starfruit_orders:
        orders["STARFRUIT"] = starfruit_orders
    
    return orders, [], ""
```

