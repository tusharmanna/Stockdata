# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

**Core Files (Active):**
- `tusharStrategyDev.py` — v1 strategy backtest engine (189d high regime gate)
- `EnterOrdersIB.py` — Interactive Brokers order entry tool
- `orders.txt` — Order list for EnterOrdersIB
- Infrastructure: `main.py`, `database.py`, `downloader.py`, `indicators.py`, `scanner.py`, `chart.py`

**Archived Files:**
- `old/` — Legacy strategies and experimental code moved here for cleanup

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

Connects to Interactive Brokers (TWS or Gateway) via the `ibapi` Python library and places bracket orders from `orders.txt` with split profit targets.

```bash
pip install ibapi yfinance   # one-time

python EnterOrdersIB.py                   # paper trading, market orders, TWS port 7497
python EnterOrdersIB.py --live            # live trading, market orders, TWS port 7496
python EnterOrdersIB.py --limit           # use limit orders (requires TICKER PRICE in orders.txt)
python EnterOrdersIB.py --port 4002       # IB Gateway paper
python EnterOrdersIB.py --host 192.168.1.5 --port 7497  # remote TWS
python EnterOrdersIB.py --client-id 2    # override IB client ID (default 1)
python EnterOrdersIB.py --all            # send all orders without per-order confirmation
```

**`orders.txt`** — one per line, optional price, `#` for comments.
- **Market orders (default)**: `TICKER` — price fetched automatically from yfinance current close
- **Limit orders (--limit)**: `TICKER PRICE` — uses specified price from file

**Order logic:**
- Connects to IB, validates connection.
- **Entry**: Market order (default, fetches current price) OR limit order if `--limit` flag + price specified.
- **Stop**: Current day's low from yfinance (live market data, not database).
- **Split profit targets** (OCA linked):
  - **TP1** at Entry + 1R: sells 1/3 of shares (1:1 reward/risk)
  - **TP2** at Entry + 3R: sells 2/3 of shares (1:3 reward/risk)
- **Position sizing**: Shares = `floor($50 / (entry − current_low))` (Risk = $50 per trade).
- **Max Gain**: shares × 3 × RPS (accounts for split profit target strategy).
- **OCA bracket**: Stop, TP1, and TP2 linked via OCA group — first fill cancels remaining.
- Prints full order summary with both targets and split quantities.
- Steps through each order for individual confirmation (unless `--all` flag).
- Per-order prompt: `[y]` = send to IB, `[n]` = skip, `[q]` = quit remaining.

**Example trade (market order):**
```
AAPL: Current low = $190, Current price = $200
Entry:  $200 (market)
Stop:   $190 (current low from yfinance)
RPS:    $10
Shares: floor($50 / $10) = 5

TP1:    $210 (Entry + 1R)  → Sell 2 shares (1:1 gain)
TP2:    $230 (Entry + 3R)  → Sell 3 shares (3:1 gain)
Risk:   5 × $10 = $50
Max Gain: 2×$10 + 3×$30 = $110
```

**IB setup required in TWS/Gateway:**
- Edit → Global Configuration → API → Settings → enable "Enable ActiveX and Socket Clients"
- Uncheck "Read-Only API" when placing live orders

## Testing (EnterOrdersIB.py)

Unit tests verify all critical logic: profit targets, position sizing, max gain calculations, and order format parsing.

```bash
# Run all tests
python test_EnterOrdersIB.py -v

# Or use the test runner
run_tests.bat
```

**Test Coverage (23 tests):**
- Profit targets: TP1 (Entry + 1R), TP2 (Entry + 3R)
- Share splitting: 1/3 at TP1, 2/3 at TP2
- Max gain: `(tp1_qty * 1R) + (tp2_qty * 3R)` (not `shares * 3R`)
- Position sizing: `floor($50 / rps)`
- Risk/reward: max_loss, cost_basis, RPS
- Order format: TICKER (market) vs TICKER PRICE (limit)

**Automated Testing:**
- Pre-commit hook runs tests automatically when EnterOrdersIB.py is modified
- Tests must pass before commit is allowed
- Manual runs: `python test_EnterOrdersIB.py -v` or `run_tests.bat`

All tests must pass before pushing to GitHub.

## Strategy Files

**tusharStrategyDev.py** — The active strategy testing and backtesting engine.

```bash
# v1 Strategy (189d high regime gate with 15% threshold)
python tusharStrategyDev.py --backtest --all      # Full history backtest
python tusharStrategyDev.py --backtest --year 2025  # Specific year
python tusharStrategyDev.py --backtest --sqqq-hedge --all  # With SQQQ hedge

# Without --backtest, shows today's signal
python tusharStrategyDev.py
```

**Performance Summary:**
- v1 CAGR: +43.5% (2010-2026, $100k → $37.5M)
- Best years: 2013 (+139%), 2023 (+139%), 2017 (+118%)
- Bear market 2022: -54.7% (vs TQQQ B&H -79%)

## Key Behaviours to Preserve

- `INSERT OR REPLACE` is used everywhere — re-runs are safe and idempotent.
- `has_date(ticker, date)` is the dedup guard for daily updates; `force=True` on `download_today()` bypasses it.
- The previous trading day in the scanner is found via `MAX(date) WHERE date < latest_date`, not `date - 1 day`, so weekends and holidays are handled correctly.
- Tickers with `$`, `/`, or spaces in their symbol are stripped before download — yfinance cannot handle them.
- `stockdata.db` is gitignored (large file, exceeds GitHub's limit) — regenerate by running `python main.py`.
- `charts/` and `data/` are gitignored — charts are regenerated by running `python chart.py`.
- Each `charts/YYYY-MM-DD/` folder contains the PDF plus `inside_bar_scan_results.csv` and `doji_scan_results.csv` from that day's scan.
- **Archived:** All legacy strategies (Donchian, Whitelight, Oliver, etc.) are in `old/` folder.
