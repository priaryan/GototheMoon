# IMC Prosperity 4 — Go to the Moon

Market-making algorithms and a backtesting toolkit written for
[IMC Prosperity 4](https://prosperity.imc.com/), a two-week algorithmic trading
competition in which teams submit a Python `Trader` class that is run against a
simulated exchange tick by tick.

This repository covers the **tutorial round**, traded on two products:

| Product | Behaviour | Approach |
|---|---|---|
| `EMERALDS` | Mean-reverting around a stable fair value (~10 000) | Symmetric quoting, tight edge |
| `TOMATOES` | Drifting fair value, noisier book | EMA-tracked fair, inventory skew |

Position limit is ±20 units per product.

---

## The strategy

The submitted trader (`submission.py`) is a static market maker built around a
volume-weighted estimate of fair value. Each tick, per product:

**1. Estimate fair value.** Two mid prices are blended — the *top mid* from the
best bid/ask, and the *wall mid* taken from the largest resting order on each
side. Size-weighted levels move less than the touch, so weighting the wall
higher (0.65–0.70) gives a fair value that is less easily dragged around by a
one-lot quote:

```
fair = 0.30 · top_mid + 0.70 · wall_mid
```

**2. Skew for inventory.** The quoting centre is shifted against the current
position, so a long book quotes lower and naturally sheds risk:

```
adjusted_fair = fair − position · skew_per_unit
```

**3. Take clear mispricings.** Any ask below `adjusted_fair − take_edge`, or bid
above `adjusted_fair + take_edge`, is lifted or hit up to the position limit.

**4. Flatten at fair.** When holding a position, orders at or through the
*unskewed* fair are used to reduce it, even if they are not profitable against
the skewed centre. This keeps inventory from accumulating across a slow drift.

**5. Quote passively.** Remaining capacity rests one tick either side of the
adjusted fair, clamped inside the current spread, capped at `passive_order_size`
(5–6 lots) to limit noisy inventory swings.

All tunables live in the `ProductConfig` dataclass at the top of `submission.py`.

## Results

From the local backtester over both tutorial days (10 000 ticks each), best
configuration found by the parameter sweep:

| Metric | Value |
|---|---:|
| Submission score | 2 530 seashells |
| Day −1 PnL | 14 898 |
| Day −2 PnL | 15 268 |
| Trades per day | ~250 |

Numbers are from the local simulator in this repo, not the official
leaderboard — the exchange's fill model is only approximated here.

## Repository layout

```
submission.py            The trader submitted to the competition
src/
  trader.py              Modular trader entry point
  strategies/            Market maker variants (generic + emerald-specific)
data/raw/                Round 0 price and trade CSVs (days -1, -2)
backtester.py            Tick-by-tick simulator
backtest_harness.py      Batch runner across days and configs
parameter_sweep.py       Generates the config grid (1 280 combinations)
runs/                    Backtest outputs, one metrics.json per run
log_visualizer.py        Renders a run log into trading_dashboard.html
dashboard.py             PnL and position charts
scratch/                 Exploratory scripts and superseded strategy versions
```

## Running a backtest

One-time setup, then a run:

```bash
python setup_backtester.py          # copies data, installs in editable mode
python backtest_harness.py
python log_visualizer.py            # → trading_dashboard.html
```

See [`docs/BACKTEST_README.md`](docs/BACKTEST_README.md) for setup detail and
[`docs/OPTIMIZATION_README.md`](docs/OPTIMIZATION_README.md) for the parameter
sweep workflow.

## Notes

The parameter sweep grids `EMA_ALPHA`, `INV_PENALTY`, `TAKE_MARGIN` and
`FLATTEN_THRESH` for tomatoes against `INV_PENALTY` for emeralds. Emeralds turn
out to be largely insensitive to these — its fair value barely moves, so most of
the PnL variance in the sweep comes from the tomatoes parameters.
