# Parameter Optimization & Backtesting Guide

This toolkit helps you iterate on strategy parameters and visualize backtest results.

## Tools Overview

### 1. **parameter_sweep.py** — Generate Parameter Combinations
Creates all parameter combinations as JSON configs for Rust backtesting.

**Parameters iterated:**
- **EMERALDS**
  - `INV_PENALTY`: [0.02, 0.04, 0.05, 0.08, 0.10]
  
- **TOMATOES**
  - `EMA_ALPHA`: [0.05, 0.10, 0.15, 0.20]
  - `INV_PENALTY`: [0.01, 0.02, 0.05, 0.08]
  - `TAKE_MARGIN`: [0.10, 0.25, 0.50, 1.00]
  - `FLATTEN_THRESH`: [1, 2, 3, 5]

**Total combinations:** 5 × (4 × 4 × 4 × 4) = **5 × 256 = 1,280 configurations**

**Usage:**
```bash
python parameter_sweep.py
```

**Output:**
- Creates `parameter_configs/` directory
- Individual JSON files: `config_0000.json` through `config_1279.json`
- Summary file: `parameter_configs/sweep_summary.json`

**Example config file:**
```json
{
  "id": 0,
  "emeralds": {
    "FAIR": 10000,
    "INV_PENALTY": 0.02
  },
  "tomatoes": {
    "EMA_ALPHA": 0.05,
    "INV_PENALTY": 0.01,
    "TAKE_MARGIN": 0.10,
    "FLATTEN_THRESH": 1
  }
}
```

---

### 2. **backtest_harness.py** — Run All Backtests
Orchestrates running all parameter configurations through your Rust backtester.

**Usage:**
```bash
# Basic usage (looks for compiled binary at ./target/release/imc_backtester)
python backtest_harness.py

# Specify custom paths
python backtest_harness.py ./path/to/backtester ./path/to/configs
```

**What it does:**
1. Finds all `config_*.json` files
2. Calls your Rust backtester for each one
3. Captures P&L and other metrics
4. Exports results to CSV
5. Shows summary and rankings

**Output files:**
- `backtest_results.csv` — All results with metrics
- `results/backtest_XXXX.log` — Individual backtest logs (one per config)

**Example backtest_results.csv:**
```
config_id,status,final_pnl,max_drawdown,sharpe_ratio
0,success,15234,2100,0.85
1,success,14890,2300,0.82
...
```

---

### 3. **log_visualizer.py** — Analyze & Visualize Results
Parses backtest logs and creates interactive visualizations.

**Supported input formats:**
- CSV logs (from IMC backtester)
- JSON logs (custom format)

**Usage:**
```bash
# Show summary statistics
python log_visualizer.py backtest_sample.log summary

# Export trades to CSV
python log_visualizer.py backtest_sample.log timeline

# Generate matplotlib charts (position, P&L, trades)
python log_visualizer.py backtest_sample.log chart

# Create interactive HTML dashboard
python log_visualizer.py backtest_sample.log interactive

# Generate everything
python log_visualizer.py backtest_sample.log all
```

**Outputs:**

#### Summary (`summary`)
```json
{
  "total_trades": 234,
  "by_product": {
    "EMERALDS": {
      "count": 120,
      "buys": 60,
      "sells": 60,
      "total_volume": 890
    },
    "TOMATOES": {
      "count": 114,
      "buys": 57,
      "sells": 57,
      "total_volume": 645
    }
  },
  "by_action": {
    "BUY": 117,
    "SELL": 117
  }
}
```

#### Timeline (`timeline`)
Creates `trade_timeline.csv` with:
```
timestamp,product,action,price,quantity,position_before,position_after,pnl,market_mid,reason
2024-01-15T10:30:45,EMERALDS,BUY,9995,5,0,5,250,9993.5,wall_mid_below_fair
2024-01-15T10:31:00,TOMATOES,SELL,490,3,-2,-5,450,489.2,inventory_flatten
...
```

#### Charts (`chart`)
Generates PNG files (e.g., `emeralds_chart.png`):
- **Subplot 1:** Position over time with trade markers (△ = buy, ▽ = sell)
- **Subplot 2:** P&L over time with area fill
- **Subplot 3:** Trade volume bars (green = buys, red = sells)

#### Interactive Dashboard (`interactive`)
Creates `trading_dashboard.html` with:
- Hoverable charts (position, P&L, trades)
- Per-product filtering
- Trade annotations
- Open in any browser

---

## Workflow Example

### Step 1: Generate Parameter Configs
```bash
python parameter_sweep.py
# Output: 1,280 configs in parameter_configs/
```

### Step 2: Run All Backtests
```bash
# First, compile your Rust backtester:
# cd $RUST_BACKTESTER && cargo build --release

python backtest_harness.py ./backtester/target/release/imc_backtester
# This may take 10-30 minutes depending on your Rust implementation
```

### Step 3: Analyze Results
```bash
# Find best config
grep "success" backtest_results.csv | sort -t, -k3 -rn | head -5

# Examine the top config's backtest log
python log_visualizer.py results/backtest_0015.log all
```

### Step 4: Iterate
If needed, manually edit parameter ranges in `parameter_sweep.py`:
```python
# Make ranges tighter around the best values
TOMATOES_EMA_ALPHA = [0.09, 0.10, 0.11, 0.12]  # Instead of [0.05, 0.10, 0.15, 0.20]
```

Then repeat steps 1-3.

---

## Rust Integration

Your Rust backtester should:

1. **Accept command-line arguments:**
   ```
   imc_backtester --config parameter_configs/config_0001.json \
                  --data ./data/raw \
                  --log results/backtest_0001.log
   ```

2. **Load config JSON:**
   ```rust
   let config: ParameterConfig = serde_json::from_str(&config_json)?;
   let emeralds_penalty = config.emeralds.inv_penalty;
   let tomato_ema = config.tomatoes.ema_alpha;
   // ... apply to strategy
   ```

3. **Output final P&L clearly:**
   The harness looks for lines containing "final_pnl", "pnl:", or similar.

---

## Performance Tips

1. **Reduce initial sweep range** if you have tight time constraints:
   - Start with fewer samples per parameter
   - Expand once you identify promising regions

2. **Run in parallel** (if Rust backtester is fast):
   - Modify `backtest_harness.py` to use `concurrent.futures.ThreadPoolExecutor`
   - Warning: Ensure no file conflicts if multiple backtests log to same file

3. **Focus on key parameters:**
   - Remove less-sensitive parameters from sweep
   - Fix secondary parameters to known-good values

---

## Dependencies

**Python packages:**
```bash
pip install matplotlib plotly pandas numpy
```

**Rust dependencies** (for backtester):
```toml
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
```

---

## Example: Interpreting Results

### Dashboard Shows:
- **Position spikes upward** → Taking long
- **Spikes rightward at zero** → Flattening position
- **P&L rises steeply** → Profitable entrance + exit
- **Gaps between trades** → Market making in progress

### What to Look For:
✅ **Good signals:**
- Consistent captures of small edges (0.5-1pt)
- Fast flattening under drawdown
- Low maximum positions (inventory control works)

❌ **Bad signals:**
- Large positions held through adverse moves
- Wide spreads between buy/sell prices ("legging" risk)
- Rare trades (strategy too conservative)

---

## Troubleshooting

**Backtest fails with "config not found":**
- Ensure `parameter_sweep.py` has been run
- Check paths match your file structure

**Log visualizer shows "No data for product":**
- Log format may not match expected CSV/JSON schema
- Check first few lines of your log file
- Adjust log parsing in `log_visualizer.py` if needed

**Too many configurations to backtest:**
- Reduce parameter ranges in `parameter_sweep.py`
- Use mathematical optimization (e.g., Bayesian optimization) for finer tuning later

---

## Next Steps

1. Customize parameter ranges based on your domain knowledge
2. Run parameter sweep → backtest → analyze loop
3. Once optimal parameters found, update `bestfornow_v7.py` with winners
4. Add more granular parameters around best region
5. Consider multi-objective optimization (Sharpe ratio vs. max drawdown, etc.)
