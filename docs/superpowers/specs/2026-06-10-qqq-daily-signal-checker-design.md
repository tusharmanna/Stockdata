# QQQ Daily Signal Checker — Design

**Date:** 2026-06-10
**Status:** Approved by user

## Goal

A daily-run script that tells the user what the 4/25 MA crossover strategy says to do today:
**ENTER** (buy TQQQ), **EXIT** (sell TQQQ, go to cash), or **HOLD** (stay long / stay in cash).
Logic must exactly match the backtested strategy in `qqq_2026_strategy.py` /
`qqq_backtest_2010_2026.py` (see `docs/GRID_STRATEGY_GUIDE.md`).

## User-confirmed decisions

- **Run modes:** both manual (`python qqq_signal.py`) and scheduled — appended to the existing
  `run_daily.bat` so it runs at 8 PM ET and its output lands in `logs\YYYY-MM-DD.log`.
- **Data approach:** fresh yfinance download every run (chosen over `stockdata.db` coupling or
  incremental CSV appends — stateless and cannot drift).

## Deliverable

`qqq_signal.py` in the repo root. Standalone; no database; depends on yfinance + pandas only.

## Data

- Download QQQ daily bars for the last 90 calendar days via `yfinance.download("QQQ", period="3mo")`.
- Flatten possible MultiIndex columns (same pattern as `downloader.py`).
- Hard fail with a clear message if the download is empty or has fewer than 26 rows
  (25-day MA needs 25 bars; crossover detection needs one more).
- Freshness check: warn prominently if the latest bar is more than 5 calendar days old.

## Signal logic (must match backtest)

- `ma4` = 4-day rolling mean of Close; `ma25` = 25-day rolling mean of Close.
- Regime on a given day: **LONG** if `ma4 > ma25`, else **CASH**.
- Compare latest bar's regime vs the prior bar's regime:
  - CASH → LONG: action `ENTER` — "Buy TQQQ at next market open"
  - LONG → CASH: action `EXIT` — "Sell TQQQ at next market open, move to cash"
  - LONG → LONG: action `HOLD LONG` — "Stay in TQQQ"
  - CASH → CASH: action `HOLD CASH` — "Stay in cash"

## Console output

```
QQQ 4/25 MA Signal — 2026-06-09
Close: $722.98   MA4: $726.55   MA25: $718.40   Gap: +1.13%
Regime: LONG (since 2026-04-08, 43 trading days)
Action: HOLD LONG — stay in TQQQ
```

- Gap = `(ma4 / ma25 - 1)` as a percent — shows how close the next flip is.
- "since" date = most recent crossover date, found by scanning the regime series backward.
- If freshness check fails, print a `WARNING:` line above the block.

## Signal history

- Append the latest bar's row to `signals/qqq_signal_history.csv` with columns:
  `date, close, ma4, ma25, regime, action`.
- Idempotent: if a row for that date already exists, replace it (load CSV, drop matching date,
  append, sort by date, rewrite). Create `signals/` directory and CSV on first run.

## Automation

- Add one line to `run_daily.bat` after the scanner step:
  `python qqq_signal.py >> %LOGFILE% 2>&1` (matching the file's existing logging style — inspect
  the actual file at implementation time and follow its conventions).
- Timing note: signal computed from today's close at 8 PM ET; execution is at the next open,
  matching the backtest's `position.shift(1)` convention.

## Error handling

- Empty/short download → `sys.exit` with actionable message.
- yfinance import failure → standard traceback is acceptable (dependency listed in requirements).
- Never opens windows/popups; output is plain text for log files.

## Testing

- Run once manually and verify the printed regime/action against the last rows of
  `QQQ_2010_2026.csv` MAs computed independently.
- Verify the history CSV is created and that re-running the same day does not duplicate the row.
- No permanent test file (research/ops tool, same convention as the backtest scripts).

## Out of scope (YAGNI)

- Email/SMS/push notifications.
- Position sizing or order placement (user has `EnterOrdersIB.py` for orders).
- Charts.
- Other tickers/parameters (hardcode QQQ, 4, 25; constants at top of file for easy editing).
