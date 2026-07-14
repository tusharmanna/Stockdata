# CODEX.md

This file is the Codex working context for this repository. It summarizes the current project shape as read on 2026-07-08, with emphasis on the active v2 volatility strategy and `EnterOrdersIB.py`.

## Project Purpose

`Stockdata` is a Python trading research and automation repo. The active production focus is daily Nasdaq strategy signals:

- TQQQ v2: leveraged/margin account strategy using TQQQ.
- QLD v2: no-margin account strategy for Roth/HSA/401k-style accounts.
- QQQ v2: conservative comparison/monitoring signal.

The repo also contains a stock scanner/charting pipeline and an Interactive Brokers bracket order entry tool. Most older strategy experiments live under `old/` and should be treated as archived unless explicitly revived.

## Primary Context Files

Read these first when resuming work:

- `CLAUDE.md` - broad project guide and historical rationale.
- `README.md` - daily signal automation and notification workflow.
- `docs/STRATEGY_COMPARISON.md` - performance comparison and strategy rationale.
- `docs/superpowers/specs/2026-07-06-v2-improvement-study-design.md` - latest v2 improvement study and "no adoption" conclusion.
- `docs/accounts_summary.md` - generated/current account allocation state. This file is modified by automation and may already be dirty.

## Active v2 Strategy

Core idea: keep the original v1 regime gate, but size exposure by realized volatility while in the bull regime.

Shared v1 regime engine:

- File: `tusharStrategyDev.py`
- Function: `compute_signal_v1(qqq_df)`
- Inputs: QQQ OHLCV with lowercase columns.
- Rule:
  - Rolling high window: `HIGH_PERIOD = 189`.
  - CASH when QQQ is at least `15.0%` below its rolling 189-day high.
  - Re-enter only after `REENTRY_DAYS = 3` consecutive days back inside the threshold.
  - Output regime is `BUY_TQQQ` or `CASH`.

TQQQ v2:

- Files: `tushar_v2_signal.py`, `tushar_v2_backtest.py`, `tushar_v2_walkforward.py`, `tushar_v2_stresstest.py`.
- Constants: `TARGET_VOL = 0.45`, `LEV_CAP = 1.5`, `VOL_WINDOW = 20`, `TRADING_DAYS = 252`.
- Exposure in bull regime: `clip(0.45 / realized_vol_TQQQ, 0, 1.5)`.
- Exposure in cash regime: `0.0`.
- Realized volatility: 20-day rolling standard deviation of TQQQ daily returns, annualized by `sqrt(252)`.
- Signal history: `signals/tushar_v2_history.csv`.
- Signal script backfills only the last `BACKFILL_DAYS = 5` trading bars and deduplicates by market-bar date.

QLD v2:

- Files: `tushar_v2_qld_signal.py`, `tushar_v2_qld_backtest.py`.
- Same regime gate based on QQQ.
- Trading vehicle is QLD.
- Constants: `TARGET_VOL = 0.45`, `LEV_CAP = 1.0`, `VOL_WINDOW = 20`.
- Exposure in bull regime: `clip(0.45 / realized_vol_QLD, 0, 1.0)`.
- Signal history: `signals/tushar_v2_qld_history.csv`.
- Intended for no-margin accounts. It is a drawdown reducer, not a total-return enhancer versus QLD buy-and-hold.

QQQ v2:

- Files: `tushar_v2_qqq_signal.py`, `tushar_v2_qqq_backtest.py`.
- Conservative comparison signal with QQQ, cap 1.0.
- Note: unlike TQQQ/QLD signal scripts, `tushar_v2_qqq_signal.py` logs using `datetime.now()` rather than the latest downloaded market-bar date.

## v2 Research Conclusions To Preserve

The current selected v2 is deliberately defensive. Do not treat higher `TARGET_VOL` as a free improvement.

- Walk-forward split: fit 2010-2018, judge 2019-2026.
- OOS Sharpe was broadly flat across target volatility values from 0.45 to 0.90.
- Vol targeting is considered a risk/drawdown knob, not alpha.
- `TARGET_VOL = 0.45` is the endorsed defensive setting because it reduces drawdown at roughly v1-equivalent Sharpe.
- The 2026-07-06 improvement study tested alternate vol estimators, cash defensive assets, graded regime, and VIX filters. No change was adopted.

If changing strategy logic, use the same discipline:

- Causal returns using shifted exposure.
- Fit parameters only on 2010-2018.
- Judge OOS on 2019-2026.
- After-cost returns for TQQQ margin exposure.
- Adoption bar: better OOS Sharpe and no materially worse max drawdown.

## Daily Automation

`run_daily_signals.py` runs:

1. `tushar_v2_signal.py`
2. `tushar_v2_qld_signal.py`
3. `tushar_v2_qqq_signal.py`

It then reads the CSV histories, writes summary artifacts under `signals/`, updates `docs/accounts_summary.md`, syncs account data, optionally opens `portfolio_dashboard.html`, and sends notifications when environment variables are configured.

Important files generated or consumed:

- `signals/tushar_v2_history.csv`
- `signals/tushar_v2_qld_history.csv`
- `signals/tushar_v2_qqq_history.csv`
- `signals/exposure_history.js`
- `signals/account_data.js`
- `signals/sms_summary.txt`
- `portfolio_dashboard.html`

Avoid hand-editing generated signal/account outputs unless the user explicitly asks.

## EnterOrdersIB.py

`EnterOrdersIB.py` is separate from v2 allocation. It places discretionary stock bracket orders from `orders.txt` through Interactive Brokers.

Order source:

- File: `orders.txt`
- Format: `TICKER` for market entry or `TICKER PRICE` for limit entry.
- `#` starts a comment line.

Order logic:

- Default mode is paper trading, TWS port `7497`.
- `--live` switches to live port `7496`.
- `--limit` requires prices in `orders.txt`; otherwise entry is market and current close is fetched from yfinance for display/calculation.
- Stop is the current day's low from yfinance.
- Risk per trade: `RISK_DOLLARS = 50.0`.
- Risk per share: `entry - current_low`.
- Shares: `floor(50 / risk_per_share)`.
- Target: `entry + 3R`, where `R = entry - stop`.
- Bracket uses parent buy plus stop sell plus target limit sell.
- Stop and target are linked via OCA group.
- Without `--all`, each order prompts for confirmation before submission.

Relevant tests:

- `test_EnterOrdersIB.py`
- `test_integration_mock.py`
- `test_integration_EnterOrders.py` uses live yfinance data.

## Scanner/Charting Pipeline

Separate from v2 signals:

- `main.py` downloads/update prices and indicators.
- `scanner.py` runs inside-bar, doji/narrow-range, and red-candle scans.
- `chart.py` creates chart PDFs and position-sizing boxes.
- SQLite database is `stockdata.db` and is intentionally not tracked.

Data flow: download -> store -> compute indicators -> scan -> chart.

## Current Worktree Note

At the time this file was created, `docs/accounts_summary.md` was already modified. Treat that as user/automation state and do not revert it casually.

## Engineering Notes

- Prefer existing constants and helper functions over creating parallel implementations.
- Be careful with yfinance data freshness. Signal scripts warn if the latest bar is older than `STALE_DAYS = 5`.
- Keep `signals/*_history.csv` writes idempotent.
- Tests and scripts may require network access for yfinance; mock tests are safer for local verification when network is unavailable.
- Existing Markdown has some mojibake/encoding artifacts. Avoid broad formatting rewrites unless that is the task.
