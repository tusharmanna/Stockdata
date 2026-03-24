# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Program

```bash
# Auto-detect: first run downloads 300-day history; subsequent runs fetch today only
python main.py

# Force re-download of full 300-day history
python main.py --history

# Force re-download of today's data (bypasses dedup, useful after market close ~5–6 PM ET)
python main.py --today

# Run both scans + generate PDF chart (opens automatically)
python scanner.py

# Regenerate PDF from existing scan results without re-scanning
python chart.py

# Run full pipeline (download + scan + chart), saves PDF, no popup
python run_scan.py
```

## Dependencies

```bash
pip install -r requirements.txt
# yfinance, pandas, requests, mplfinance — sqlite3 and matplotlib are stdlib/bundled
```

## Architecture

All data flows in one direction: **download → store → compute → scan → chart**.

```
ticker_list.py   →  downloader.py  →  database.py (prices table)
                                           ↓
                                    indicators.py  →  database.py (indicators table)
                                           ↓
                                     scanner.py    →  database.py (scan_results, doji_scan_results)
                                           ↓
                                      chart.py     →  charts/YYYY-MM-DD/scan_results.pdf
```

**`ticker_list.py`** — fetches ~10,000 US tickers from a GitHub-hosted flat file (rreichel3/US-Stock-Symbols) with an S&P 500 CSV fallback.

**`downloader.py`** — downloads OHLCV via `yfinance.download()` in batches of 100 tickers (`BATCH_SIZE`). Uses `group_by="ticker"` for multi-ticker batches, which returns a MultiIndex DataFrame that must be flattened with `_flatten_columns()`. Single-ticker batches return a flat DataFrame directly. Data is upserted via `database.upsert_prices()`.

**`database.py`** — thin SQLite wrapper (`stockdata.db` in project root). WAL mode enabled. All functions open and close their own connection. Four tables: `prices`, `indicators`, `scan_results`, `doji_scan_results`.

**`indicators.py`** — `recompute_all()` loops every ticker in `prices`, calls `compute_indicators()` which uses `pandas.Series.rolling(min_periods=1)` so MAs are always populated (no NaN gaps even at the start of history). Called at the end of every `main.py` run.

**`scanner.py`** — runs two scans against the DB and calls `chart.plot_results()` when done.
- **Scan 1 (Inside Bar)**: close above ma50 and ma200, volume below vol_avg30 (and ≥ 100k), candle is an inside bar (high < prev_high, low > prev_low). Saves to `scan_results`.
- **Scan 2 (Doji/NR near MA)**: volume ≥ 100k, doji (body < 10% of range) or narrow range (range < 1.5% of price), close within 2% of ma20, ma50, or ma200. Saves to `doji_scan_results`.
- Pass `--no-display` to skip auto-opening the PDF (used by `run_daily.bat`).

**`chart.py`** — generates a single PDF with candlestick charts for all scan results.
- Last 60 trading days of OHLCV + MA10/20/50/200 overlaid.
- Entry (green dashed) = day's high, Stop (red dashed) = day's low.
- Position sizing box (bottom left): Shares, Entry, Stop, Risk ($100 fixed), Cost Basis.
- Filters: entry ≥ $5, range ≥ $0.05 absolute, range ≥ 0.5% of price.
- Always saves PDF; opens it automatically unless `show=False`.

## Database Schema

```sql
prices            (ticker, date PK) — raw OHLCV, auto_adjust=True from yfinance
indicators        (ticker, date PK) — ma10, ma20, ma50, ma200, vol_avg30
scan_results      (scan_date, ticker PK) — inside bar scan snapshot
doji_scan_results (scan_date, ticker PK) — doji/NR scan snapshot with open, body_pct, range_pct
```

Join `prices` and `indicators` on `(ticker, date)`. Both scan tables store denormalized snapshots so past results are self-contained.

## Charting Constants (chart.py)

| Constant           | Default | Description                              |
|--------------------|---------|------------------------------------------|
| `LOOKBACK`         | 60      | Trading days of history shown per chart  |
| `RISK_DOLLARS`     | 100     | Fixed risk per trade for position sizing |
| `MIN_PRICE`        | 5.0     | Skip tickers with entry below this       |
| `MIN_RISK_PER_SHARE` | 0.05  | Skip if high-low < this (absolute)       |
| `MIN_RANGE_PCT`    | 0.005   | Skip if (high-low)/price < 0.5%          |

## Automation (Windows Task Scheduler)

`run_daily.bat` runs `main.py` then `scanner.py --no-display` every weekday at 8 PM ET, appends output to `logs\YYYY-MM-DD.log`, and saves the PDF to `charts\YYYY-MM-DD\scan_results.pdf`.

**One-time setup (PowerShell as Administrator):**
```powershell
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_schedule.ps1
```

**Useful task commands:**
```bat
schtasks /run /tn "StockDataDaily"        :: trigger manually
schtasks /delete /tn "StockDataDaily" /f  :: remove task
taskschd.msc                              :: open Task Scheduler UI
```

Logs accumulate in `logs\` — not auto-purged.

## Key Behaviours to Preserve

- `INSERT OR REPLACE` is used everywhere — re-runs are safe and idempotent.
- `has_date(ticker, date)` is the dedup guard for daily updates; `force=True` on `download_today()` bypasses it.
- The previous trading day in the scanner is found via `MAX(date) WHERE date < latest_date`, not `date - 1 day`, so weekends and holidays are handled correctly.
- Tickers with `$`, `/`, or spaces in their symbol are stripped before download — yfinance cannot handle them.
- `stockdata.db` is gitignored (221 MB, exceeds GitHub's limit) — regenerate by running `python main.py`.
- `charts/` and `data/` are gitignored — charts are regenerated by running `python chart.py`.
