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

# Backfill tickers whose most recent row is behind the DB-wide latest date
python backfill_recent.py
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

**`ticker_list.py`** — fetches US tickers from multiple sources in order (optimized for daily use):
1. **NASDAQ Screener API** (`api.nasdaq.com/api/screener/stocks`) — ~7,000 NYSE/NASDAQ/AMEX tickers (primary: fast, reliable)
2. **GitHub fallback** (rreichel3/US-Stock-Symbols, ~10k tickers) — comprehensive all-exchange source
3. **SEC company_tickers.json** (`sec.gov/files/company_tickers.json`) — official but rate-limited, fallback only
4. **S&P 500 CSV** (datasets/s-and-p-500-companies) — last-resort fallback

Requires `User-Agent` header to avoid 403s. Uses NASDAQ as primary for daily reliability; SEC is authoritative for one-time comprehensive lists.

**`downloader.py`** — downloads OHLCV via `yfinance.download()` in batches of 100 tickers (`BATCH_SIZE`). Uses `group_by="ticker"` for multi-ticker batches, which returns a MultiIndex DataFrame that must be flattened with `_flatten_columns()`. Single-ticker batches return a flat DataFrame directly. Data is upserted via `database.upsert_prices()`.

**`database.py`** — thin SQLite wrapper (`stockdata.db` in project root). WAL mode enabled. All functions open and close their own connection. Five tables: `prices`, `indicators`, `scan_results`, `doji_scan_results`, `failed_tickers`.

**`backfill_recent.py`** — finds all tickers whose latest row is behind the DB-wide latest date, re-downloads the last 14 calendar days (~7 trading days) for them, and recomputes indicators. Skips tickers already in `failed_tickers`. Marks tickers that return no data as failed/delisted.

**`indicators.py`** — `recompute_all()` loops every ticker in `prices`, calls `compute_indicators()` which uses `pandas.Series.rolling(min_periods=1)` so MAs are always populated (no NaN gaps even at the start of history). Called at the end of every `main.py` run.

**`scanner.py`** — runs two scans against the DB and calls `chart.plot_results()` when done.
- **Scan 1 (Inside Bar)**: close above ma50 and ma200, prev_close also above ma200 (filters spike-throughs), vol_avg30 > 1M, volume below vol_avg30 (and ≥ 100k), candle is an inside bar (high < prev_high, low > prev_low). Saves to `scan_results` and `charts/YYYY-MM-DD/inside_bar_scan_results.csv`.
- **Scan 2 (Doji/NR near MA)**: vol_avg30 > 1M, volume ≥ 100k, close above ma200, doji (body < 10% of range) or narrow range (range < 1.5% of price), high < prev_high, close within 2% of ma20, ma50, or ma200. Saves to `doji_scan_results` and `charts/YYYY-MM-DD/doji_scan_results.csv`.
- **Scan 3 (Red Candle near MA)**: vol_avg30 > 1M, volume ≥ 100k, close above ma200, red candle (close < open), high < prev_high, close within 2% of ma20, ma50, or ma200. Saves to `red_candle_scan_results` and `charts/YYYY-MM-DD/red_candle_scan_results.csv`.
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
scan_results            (scan_date, ticker PK) — inside bar scan snapshot
doji_scan_results       (scan_date, ticker PK) — doji/NR scan snapshot with open, body_pct, range_pct
red_candle_scan_results (scan_date, ticker PK) — red candle near MA snapshot with open, body_pct, range_pct
failed_tickers          (ticker PK, reason, added_date) — delisted/no-data tickers skipped on future runs
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

## Order Entry (EnterOrdersIB.py)

Connects to Interactive Brokers (TWS or Gateway) via the `ibapi` Python library and places bracket orders from a watchlist file.

```bash
pip install ibapi   # one-time

python EnterOrdersIB.py                   # paper trading, TWS port 7497
python EnterOrdersIB.py --live            # live trading,  TWS port 7496
python EnterOrdersIB.py --port 4002       # IB Gateway paper
python EnterOrdersIB.py --host 192.168.1.5 --port 7497  # remote TWS
python EnterOrdersIB.py --client-id 2    # override IB client ID (default 1)
```

**`stocks2buy.txt`** — one ticker per line, `#` for comments. Edit before each run.

**Order logic:**
- Connects to IB and fetches live price via `reqMktData` snapshot (tick 4/68 = real-time/delayed LAST).
- Calls `reqMarketDataType(3)` after connecting so IB falls back to delayed data for tickers without a real-time subscription (silences error 10089).
- Reads yesterday's close and low from `stockdata.db` (most recent row — assumes `main.py` has NOT been run today).
- **Condition**: if `live > prev_close` → Market order + Stop Loss child at `prev_low`. Tickers where `live <= prev_close` are skipped.
- Shares = `floor($100 / (live − prev_low))`.
- Prints full order summary (all qualifying tickers), then steps through each order one at a time for individual confirmation before sending.
- Per-order prompt: `[y]` = send to IB, `[n]` = skip, `[q]` = quit remaining.

**IB setup required in TWS/Gateway:**
- Edit → Global Configuration → API → Settings → enable "Enable ActiveX and Socket Clients"
- Uncheck "Read-Only API" when placing live orders

## Key Behaviours to Preserve

- `INSERT OR REPLACE` is used everywhere — re-runs are safe and idempotent.
- `has_date(ticker, date)` is the dedup guard for daily updates; `force=True` on `download_today()` bypasses it.
- The previous trading day in the scanner is found via `MAX(date) WHERE date < latest_date`, not `date - 1 day`, so weekends and holidays are handled correctly.
- Tickers with `$`, `/`, or spaces in their symbol are stripped before download — yfinance cannot handle them.
- `stockdata.db` is gitignored (large file, exceeds GitHub's limit) — regenerate by running `python main.py`.
- `charts/` and `data/` are gitignored — charts are regenerated by running `python chart.py`.
- Each `charts/YYYY-MM-DD/` folder contains the PDF plus `inside_bar_scan_results.csv` and `doji_scan_results.csv` from that day's scan.
