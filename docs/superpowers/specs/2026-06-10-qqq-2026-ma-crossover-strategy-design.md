# QQQ 2026 MA-Crossover Strategy — Design

**Date:** 2026-06-10
**Status:** Approved pending user spec review

## Goal

Build a daily-bar trading strategy over `QQQ_2026.csv` (109 trading days, 2026-01-02 to 2026-06-09)
that beats buy-and-hold (+16.75%) using causal signals, with both an untuned robust baseline and a
grid-searched variant optimized for Sharpe ratio.

## Scope decisions (user-confirmed)

- **Instruments/direction:** everything allowed — leveraged long (TQQQ-style) and short (SQQQ-style).
- **Optimization:** both a robust untuned baseline and a grid-searched variant, reported side by side.
- **Approach:** fast/slow MA crossover regime switch (chosen over Donchian breakout and v9-style blend
  for its low parameter count on a 109-bar series).
- **Grid objective:** annualized Sharpe ratio (daily returns, rf = 0). Total return reported alongside.

## Deliverable

`qqq_2026_strategy.py` in the repo root — standalone script, reads `QQQ_2026.csv`, no database
dependency. Follows the existing flat-script convention (like `tusharStrategyDev.py`).

## Signal logic (causal, no lookahead)

1. Compute fast MA and slow MA of Close with full-window rolling means (`min_periods = window`).
   Strategy is in cash until the slow MA is valid.
2. At each day's close: fast MA > slow MA → **long** state; fast MA < slow MA → **short** state.
3. The position taken at day t's close earns day t+1's close-to-close return: the daily strategy
   return is `position.shift(1) × leverage × daily_ret`, so the return on day t uses only
   information through day t−1.

## Leverage modeling

Daily-rebalanced multiple of QQQ's daily return, matching how leveraged ETFs behave (fees and borrow
costs ignored):

- Long state: `L_long × ret`
- Short state: `−L_short × ret`
- `L_short = 0` means "cash instead of short" and is part of the grid.

## Variants

1. **Robust baseline:** 10/20 MA, 3× long, 1× short — no tuning.
2. **Grid search:** fast ∈ {3, 4, …, 15} (step 1), slow ∈ {10, 15, …, 50} (step 5), fast < slow,
   L_long ∈ {1, 2, 3}, L_short ∈ {0, 1, 2, 3}. Objective: maximize annualized Sharpe. Report the top 5 configs with
   both Sharpe and total return so the user can judge neighborhood flatness (flat = trustworthy,
   lone spike = curve-fit).

## Output

- Console table for baseline, best grid config, and buy-and-hold: total return, annualized Sharpe,
  max drawdown, number of position flips, win rate.
- Top-5 grid configs table.
- Equity-curve chart saved to `qqq_2026_strategy_results.png` with all three curves overlaid
  (matplotlib, no auto-open).

## Sanity checks (built into the script)

- **No-lookahead check:** shifting the position series one extra day must change the result —
  proves the shift is live, not a no-op.
- **Benchmark check:** engine-computed buy-and-hold must match the raw close-to-close figure
  within floating-point tolerance.

## Error handling

- Hard fail with a clear message if `QQQ_2026.csv` is missing or has unexpected columns.
- Assert no NaN in Close after load.

## Testing

Sanity checks above run on every execution (assertions). No separate test file — the script is a
one-shot research tool, not production order flow (unlike `EnterOrdersIB.py`, which has its own
test suite).

## Known limitations (accepted)

- 109 bars is a small sample; the grid-searched result is in-sample and will overstate live
  performance. The robust baseline and top-5 neighborhood table exist to calibrate that.
- Leverage model ignores ETF expense ratios, borrow costs, and intraday rebalance slippage.
- No transaction costs (user declined; flip count is reported so cost impact can be eyeballed).
