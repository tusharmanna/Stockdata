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

# Print today's 4/25 MA crossover signal for QQQ (ENTER/EXIT/HOLD) + log to signals/
python qqq_signal.py
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
- **Profit Target** (OCA linked):
  - **Target** at Entry + 3R: sells all shares (1:3 reward/risk)
- **Position sizing**: Shares = `floor($50 / (entry − current_low))` (Risk = $50 per trade).
- **Max Gain**: `shares × 3R` — all shares sold at 1:3 reward/risk ratio.
- **OCA bracket**: Stop and Target linked via OCA group — first fill cancels the other.
- Prints full order summary with entry, stop, target, and gain projections.
- Steps through each order for individual confirmation (unless `--all` flag).
- Per-order prompt: `[y]` = send to IB, `[n]` = skip, `[q]` = quit remaining.

**Example trade (market order):**
```
ALOY: Current low = $9.50, Current price = $10.20
Entry:  $10.20 (market)
Stop:   $9.50 (current low from yfinance)
RPS:    $0.70
Shares: floor($50 / $0.70) = 71

Target: $12.30 (Entry + 3R) → Sell all 71 shares (3:1 gain)
Risk:   71 × $0.70 = $49.70
Max Gain: 71 × $2.10 = $149.10
```

**IB setup required in TWS/Gateway:**
- Edit → Global Configuration → API → Settings → enable "Enable ActiveX and Socket Clients"
- Uncheck "Read-Only API" when placing live orders

## Testing (EnterOrdersIB.py)

Unit tests verify all critical logic: profit target, position sizing, max gain calculations, and order format parsing.

```bash
# Run all tests
python test_EnterOrdersIB.py -v

# Or use the test runner
run_tests.bat
```

**Test Coverage (18 tests):**
- Profit target: Entry + 3R (single target, all shares)
- Max gain: `shares × 3R`
- Position sizing: `floor($50 / rps)`
- Risk/reward: max_loss, cost_basis, RPS
- Order format: TICKER (market) vs TICKER PRICE (limit)

**Integration Tests (Full Pipeline):**
- `test_integration_mock.py` — validates order calculations using actual `orders.txt` with mock market data (no external dependencies)
  - Tests market order price fetching, stop loss calculation, profit targets, share split, max gain formula
  - Includes 6 validation assertions per order
  - Useful for testing without yfinance network calls
  - Run with: `python test_integration_mock.py`
- `test_integration_EnterOrders.py` — alternative integration test using live yfinance data
  - Same validation logic as mock version but fetches real market prices
  - Run with: `python test_integration_EnterOrders.py`

**Automated Testing:**
- Pre-commit hook runs tests automatically when EnterOrdersIB.py is modified
- Tests must pass before commit is allowed
- Manual runs: `python test_EnterOrdersIB.py -v` or `run_tests.bat`
- Integration test runs: `python test_integration_mock.py` (recommended) or `python test_integration_EnterOrders.py`

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

### Tushar v2 — Volatility-Targeted v1 (Defensive)

v2 keeps v1's regime gate unchanged but **changes how the position is sized while invested**.

**Why v2 exists:** Analysis showed v1 is ~93% just buy-and-hold TQQQ (only 7% in cash, 20 regime switches in 16 years). So tuning the gate (189-day window / 15% threshold / 3-day re-entry) is the overfitting trap — it only affects 7% of the time. The only structural lever is position *sizing* the other 93%.

**The strategy:**
- **Regime gate:** identical to v1 (BULL = QQQ within 15% of 189-day high; else CASH). In CASH, exposure = 0.
- **Position sizing in BULL regime:** `exposure = clip(target_vol / realized_vol_TQQQ, 0, 1.5)`
  - `target_vol = 0.45` (annualized), `cap = 1.5`
  - `realized_vol_TQQQ = TQQQ_daily_ret.rolling(20).std() × √252`
  - Plain English: **delever when TQQQ gets volatile, lever up (within cap) when it's calm.** During a 2022-style crash the position automatically shrinks; during calm uptrends it can hold up to 1.5× TQQQ.
- **Costs (modeled honestly):** financing charged on the borrowed portion when exposure > 1.0 (margin on top of a 3x ETF); T-bill yield credited on idle cash. Rate schedule: ~1.5% (2010–2021), ~5–6% (2022–2026). TQQQ's expense ratio is already in its price.
- **Causal:** `exposure.shift(1) × TQQQ_daily_ret` — today's signal trades tomorrow.

**Performance (2010–2026, $100k, after cost):**
- v2 defensive: CAGR +44.5% | Sharpe **1.03** | Max DD **−46.5%** | $40.5M
- vs v1 baseline: CAGR +43.1% | Sharpe 0.96 | Max DD −58.9% | $34.7M
- Crash protection: 2022 −35.1% (v1 −54.7%), 2011 −15.3% (v1 −26.5%)

**⚠️ Honest caveat — what the walk-forward proved:** A clean walk-forward (fit `target_vol` on 2010–2018, verify on 2019–2026) showed **out-of-sample Sharpe is flat (~1.08) across every target_vol from 0.45 to 0.90, and identical to v1's**. Vol-targeting did **not** add risk-adjusted edge out of sample — it is a **risk-reduction knob, not alpha**. Higher target → more return *and* proportionally more drawdown (same Sharpe). `target_vol = 0.45` is the defensive setting the walk-forward endorses: it cuts max drawdown ~−59% → ~−43% (OOS) at v1-equivalent Sharpe. The favorable full-sample numbers above are partly in-sample drift; the *repeatable* benefit is shallower drawdowns, not extra return. All results are single-asset, single-path; live/taxed/slippage results will be lower.

**Files & usage:**
```bash
python tushar_v2_backtest.py      # Year-by-year + summary: QQQ B&H, TQQQ B&H, v1, v2 (ideal & after-cost)
python tushar_v2_signal.py        # Daily signal: regime, TQQQ vol, target exposure (e.g. "Hold 0.57x TQQQ")
python tushar_v2_walkforward.py   # Out-of-sample validation (fit 2010-2018, test 2019-2026)
python tushar_v2_stresstest.py    # Survivability: holding-period, drawdown depth+duration, withdrawals
```
All reuse v1's regime logic (`_load`, `compute_signal_v1`) from `tusharStrategyDev.py` and fetch QQQ + TQQQ live via yfinance. The signal tool logs to `signals/tushar_v2_history.csv`. To change risk appetite, edit `TARGET_VOL` in `tushar_v2_backtest.py` and `tushar_v2_signal.py` (higher = more return + more drawdown, same Sharpe).

### Tushar v2 — No-Margin Variant for Roth / HSA / 401k (QLD)

Retirement and HSA accounts **cannot use margin** (IRS rule) and often cannot trade TQQQ, so leverage must come from *inside* a fund. Use **QLD (2x Nasdaq-100)** — fund-internal leverage, no margin account needed — with the same v2 overlay (v1 regime gate + vol-target) but **capped at 100% of cash** (cap = 1.0). Bonus: trades incur no tax in these accounts, so the regime switching is friction-free.

```bash
python tushar_v2_qld_signal.py    # Daily signal: regime, QLD vol, "% of account in QLD" (e.g. "85% QLD")
```
Signal logs to `signals/tushar_v2_qld_history.csv`. Regime is computed on QQQ; vol-target uses QLD's own 20d realized vol; exposure = `clip(0.45 / QLD_vol, 0, 1.0)` in BULL regime, else 0.

**Backtest 2010–2026 ($100k, cap 1.0, after cash yield):**

| Strategy | CAGR | Sharpe | Max DD | Final $ |
|---|---|---|---|---|
| QLD Buy & Hold | **32.4%** | 0.89 | **−63.7%** | **$10.0M** |
| QLD overlay (regime + vol-target) | 30.6% | **0.99** | **−39.1%** | $7.98M |

**Honest finding — the overlay is a RISK-reducer, not a return-enhancer.** On a no-margin 2x vehicle it *underperforms* buy & hold on total return ($7.98M vs $10.0M) and beats B&H in only **3 of 17 years**. Its value is a far gentler ride: max drawdown −39% vs −64%, Sharpe 0.99 vs 0.89. The 2022 row captures it — buy & hold fell from $4.7M to $1.86M; the overlay went $2.9M → $1.91M (less at the peak, more at the bottom). The overlay's *return* edge only appears at 3x (TQQQ), where drawdown protection compounds enough to win; at 1x (QQQ) or 2x (QLD) you give up return for safety.

**Vehicle choice by account:**
- **Roth IRA** — best home (tax-free gains). Confirm broker allows QLD (most do — it needs no margin).
- **HSA** — good if it has a brokerage option *and* the money will stay invested long-term (fails if you need it for near-term medical bills).
- **401k** — usually a fixed fund menu with no QLD/QQQ; buy-and-hold the most growth/Nasdaq-tilted index fund offered instead.

**Decision (personal, not mathematical):** For a long-horizon account you truly won't touch and can hold through a −64% drawdown, **plain QLD buy & hold is simpler and ends richer**. Choose the overlay if you'd doubt your ability to hold through −64% without panic-selling — it trades ~20% of terminal wealth to nearly halve the worst drawdown.

## QQQ Moving Average Crossover Strategies (2010–2026 Backtest)

Two daily-bar strategies trade QQQ using moving average crossovers. Both download live data from yfinance on every run (no local CSV dependency for signals).

### Strategy 1: Binary 4/25 Crossover (3x leverage)

**Signal:** Long 3x when MA4 > MA25, else cash.

**Performance (2010–2026):**
- Total return: **+7,373%** ($100k → $7.47M)
- CAGR: **30.0%** | Sharpe: 0.87 | Max drawdown: -66.9%
- Wins vs B&H: 12/17 years
- Best year: 2020 (+187.5%) | Worst year: 2022 (-55.6%)

**Daily signal tool:**
```bash
python qqq_signal.py          # Run anytime; fetches latest QQQ close from yfinance
```

Outputs: Close, MA4, MA25, regime (LONG/CASH), days in regime, action (ENTER/EXIT/HOLD).

**Automatic daily at 8 PM ET** (included in `run_daily.bat`):
```powershell
# One-time setup (admin):
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_schedule.ps1
```

**Backtest:**
```bash
python qqq_2026_strategy.py          # 2026 only (109 bars)
python qqq_backtest_2010_2026.py     # Full 16-year history with year-by-year table
```

### Strategy 2: Weighted Pyramid 3/35 Crossover (3x leverage, 25/35/40 weights)

**Signal:** Scale position as bullish tiers accumulate, weighted toward confirmed signals:
- T1: Close > MA3 → +25% position (noisy fast tier, lowest weight)
- T2: Close > MA35 → +35% position
- T3: MA3 > MA35 → +40% position (confirmed crossover, highest weight)

Position = sum of true tiers: 0%, 25%, 35%, 40%, 60%, 65%, 75%, or 100%. Symmetric scale-out: each tier false drops its weight.

**Performance (2010–2026):**
- Total return: **+10,021%** ($100k → $10.12M)
- Sharpe: **0.98** | Max drawdown: -59.9%
- Beats equal-thirds pyramid (+8,932%) in 13/17 years; beats B&H in 11/17 years
- Best year: 2023 (+100.5%) | Worst year: 2022 (-46.3%)
- Weight grid search (`qqq_pyramid_weight_search.py`): returns rise with more weight on T3, but 25/35/40 keeps the shallowest drawdown; Sharpe-optimal is ~20/10/70 (0.99)

**Key advantage:** Reduces whipsaw damage in choppy markets (2015, 2018, 2024) by partial entries/exits. Trades some upside in explosive recoveries (2020 +187% binary vs +71% pyramid) for steadier compounding overall.

**Daily signal tool:**
```bash
python qqq_pyramid_signal.py  # Run anytime; fetches latest QQQ close from yfinance
```

Outputs: Close, MA3, MA35, tier status (T1/T2/T3 with weights), position % (0–100), action (SCALE UP/DOWN/HOLD/IN CASH).

**Automatic daily at 3:30 PM ET** (30 min before close, intraday signal):
```powershell
# One-time setup (admin):
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_pyramid_schedule.ps1

# Manage task:
schtasks /run /tn "StockDataPyramidSignal"        # trigger manually
schtasks /delete /tn "StockDataPyramidSignal" /f  # remove task
```

**Backtest:**
```bash
python qqq_pyramid_strategy.py            # Compares binary, pyramid at 4/25, grid search for best MA pair
python qqq_pyramid_3_35_backtest.py       # Equal-thirds 3/35 year-by-year vs B&H
python qqq_pyramid_weighted_backtest.py   # 25/35/40 weights vs equal thirds, year-by-year
python qqq_pyramid_weight_search.py       # Grid search over all tier-weight combos
```

### Signal History

Both tools log signals to CSV for backtesting / tracking:
```bash
cat signals/qqq_signal_history.csv          # Binary 4/25 history
cat signals/qqq_pyramid_history.csv         # Pyramid 3/35 history
```

### Causal Backtesting Notes

- Both strategies use `position.shift(1)` so day t's position is executed at day t+1's open — matches real trading.
- yfinance `auto_adjust=True` applies splits/dividends to historical Close prices (corrected in 2026-06-10).
- MA windows are computed with `min_periods=window` (full window required, no NaN gaps).
- Leverage is daily-rebalanced (TQQQ/SQQQ style): exposure = position fraction × 3.

### Running Both Simultaneously

You can run both signal tools for side-by-side recommendations:
```bash
python qqq_signal.py && python qqq_pyramid_signal.py
```

Example output (today's signals from live yfinance):
```
Binary 4/25:    HOLD CASH (since Jun 9)
Pyramid 3/35:   66% invested, SCALE UP
```

## Key Behaviours to Preserve

- `INSERT OR REPLACE` is used everywhere — re-runs are safe and idempotent.
- `has_date(ticker, date)` is the dedup guard for daily updates; `force=True` on `download_today()` bypasses it.
- The previous trading day in the scanner is found via `MAX(date) WHERE date < latest_date`, not `date - 1 day`, so weekends and holidays are handled correctly.
- Tickers with `$`, `/`, or spaces in their symbol are stripped before download — yfinance cannot handle them.
- `stockdata.db` is gitignored (large file, exceeds GitHub's limit) — regenerate by running `python main.py`.
- `charts/` and `data/` are gitignored — charts are regenerated by running `python chart.py`.
- Each `charts/YYYY-MM-DD/` folder contains the PDF plus `inside_bar_scan_results.csv` and `doji_scan_results.csv` from that day's scan.
- **Archived:** All legacy strategies (Donchian, Whitelight, Oliver, etc.) are in `old/` folder.
