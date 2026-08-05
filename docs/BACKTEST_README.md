# Backtester Setup & Usage

## One-Time Setup

Run this **once** to configure the backtester permanently:

```bash
python setup_backtester.py
```

This will:
- ✅ Copy your CSV data files to the backtester
- ✅ Install the backtester in editable mode
- ✅ Verify everything works

## Running Backtest

After setup, run backtest with:

```bash
# Test all days in round 0
python -m prosperity3bt algorithm.py 0

# Test specific day
python -m prosperity3bt algorithm.py 0-0
python -m prosperity3bt algorithm.py 0--1

# Merge profit across days
python -m prosperity3bt algorithm.py 0 --merge-pnl

# Custom output file
python -m prosperity3bt algorithm.py 0 --out results.log

# Skip saving log file
python -m prosperity3bt algorithm.py 0 --no-out
```

## Current Performance

From last backtest:
- **Round 0 Day -2:** 8,383 profit (EMERALDS: 3,215 + TOMATOES: 5,168)
- **Round 0 Day -1:** 8,462 profit (EMERALDS: 3,419 + TOMATOES: 5,043)
- **Total:** 16,845 profit

## Strategy

- **EMERALDS:** Market maker with fair value ~10,000, position limit 10
- **TOMATOES:** Market maker with fair value ~5,000, position limit 10

Both strategies:
1. Take favorable trades (buy below fair, sell above fair)
2. Flatten inventory when stretched
3. Post passive quotes inside the spread
4. Adjust based on inventory skew

## File Structure

```
GototheMoon/
├── algorithm.py                    # Entry point for backtester
├── setup_backtester.py             # One-time setup script
├── src/
│   ├── trader.py                   # Main Trader class
│   └── strategies/
│       ├── market_maker.py         # Generic market maker logic
│       └── emerald_market_maker.py # Original EMERALDS strategy
├── data/
│   └── raw/                        # Your CSV data files
└── backtests/
    └── imc-prosperity-3-backtester/
        └── prosperity3bt/resources/round0/
            ├── prices_round_0_day_*.csv
            └── trades_round_0_day_*.csv
```

## Troubleshooting

**"No module named prosperity3bt"**
- Run `python setup_backtester.py` again

**"No data found for round X"**
- Check CSV files are in `data/raw/`
- Re-run `python setup_backtester.py`

**Want to add more data?**
- Place new CSV files in `data/raw/`
- Update the round number in backtester calls (e.g., `algorithm.py 1`)
- Re-run setup script (it's safe to run multiple times)
