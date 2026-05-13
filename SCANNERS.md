# Stock Scanner Reference

This document describes every scanner in the project, the logic behind each one, what signals they produce, and how to run them.

---

## Overview

| Scanner group | Script | Batch file | Frequency | Output |
|---|---|---|---|---|
| Daily scans (8 scans) | `scanner.py` | `daily.bat` | Every weekday after close | `DailyWatchlist.txt`, `ActionList.txt`, PDF, CSVs |
| Weekly scans (5 scans) | `weekly_scanner.py` | `run_weekly.bat` | Once a week (e.g. Sunday) | `WeeklyWatchlist.txt`, PDF, CSVs |
| Intraday Breakout | `intraday_scanner.py` | `run_buynow.bat` | Hourly 10:15–2:15 ET | `buynow.txt` |
| Whitelight (ETF trend) | `whitelight_strategy.py` | `run_whitelight.bat` | After market close | `whitelight_signal.txt`, console |

---

## Part 1 — Daily Scans (`scanner.py` / `daily.bat`)

Run via the daily batch file (also runs `main.py` first to update prices):

```bat
daily.bat
```

Or run directly:

```bash
python scanner.py              # opens PDF chart when done
python scanner.py --no-display # saves PDF without opening it
```

Contains 8 scans. Results are saved to the database and `charts/YYYY-MM-DD/` CSVs. Regenerates `DailyWatchlist.txt` and `ActionList.txt` at the end.

---

### Scan 1 — Inside Bar

**Function:** `run_scan()`  
**DB table:** `scan_results`  
**CSV:** `inside_bar_scan_results.csv`

Looks for stocks in a confirmed uptrend that had a quiet, inside-bar day — a common setup before a resumption of the trend.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close > MA50 and MA200 | In long-term uptrend |
| Previous close > previous MA200 | Filters spike-throughs — must have been trending, not just touching |
| Volume >= 100k | Minimum activity |
| Volume < vol_avg30 | Quieter-than-average day (contraction) |
| vol_avg30 > 1M | Institutional-grade liquidity |
| High < previous high | Inside bar condition |
| Low > previous low | Inside bar condition |

**What it means:** The stock is above both key MAs, and yesterday was a tight inside bar on below-average volume. The range is contained within the prior day's range, suggesting sellers are not pressing and a breakout attempt is likely.

---

### Scan 2 — Doji / Narrow Range near Key MA

**Function:** `run_doji_scan()`  
**DB table:** `doji_scan_results`  
**CSV:** `doji_scan_results.csv`

Finds indecision candles (doji or very narrow range) sitting close to a moving average — a coiling setup.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Volume >= 100k | Minimum activity |
| vol_avg30 > 1M | Institutional liquidity |
| Close > MA200 | Above long-term trend line |
| High < previous high | Not making new highs yet |
| Doji OR Narrow range | Body < 10% of candle range, OR (high−low)/close < 1.5% |
| Within 2% of MA20, MA50, or MA200 | Sitting at a support level |

**What it means:** The candle shows indecision right at a moving average, which often resolves with a directional move. The narrow range indicates compression before a potential expansion.

---

### Scan 3 — Red Candle near Key MA

**Function:** `run_red_candle_scan()`  
**DB table:** `red_candle_scan_results`  
**CSV:** `red_candle_scan_results.csv`

Finds stocks that pulled back (red candle) to a key moving average while staying in an uptrend. These are potential buy-the-dip setups.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Volume >= 100k | Minimum activity |
| vol_avg30 > 1M | Institutional liquidity |
| Close > MA200 | Above long-term trend line |
| Close < Open | Red candle (down day) |
| High < previous high | Not extended |
| Within 2% of MA20, MA50, or MA200 | Testing a moving average |

**What it means:** The stock is in an uptrend but had a red day and is now touching or near a moving average. A bounce off the MA is the anticipated trade.

---

### Scan 4 — IBD-Style Leader

**Function:** `run_ibd_scan()`  
**DB table:** `ibd_scan_results`  
**CSV:** `ibd_scan_results.csv`  
**Sorted by:** Distance from MA50 ascending (closest first = best entry proximity)

Finds institutional-quality stocks in a sustained uptrend that are setting up with a tight day. Based on the IBD (Investor's Business Daily) methodology.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close > MA200 | Above long-term MA (uptrend) |
| MA50 > MA200 | Confirmed, sustained uptrend — not just a bounce |
| Close > MA50 × 0.85 | Within 15% below MA50 (not broken down) |
| vol_avg30 > 1M | Institutional-grade liquidity |
| Volume >= 100k | Minimum activity |
| Inside bar OR narrow range | Inside bar (high < prev high, low > prev low), OR (high−low)/close < 1.5% |

**What it means:** A quality trending stock where the MA50 has been above MA200 (not just touched), setting up with a quiet day. The MA50 > MA200 filter distinguishes sustained uptrends from short-lived bounces.

---

---

## Part 1b — Weekly Scans (`weekly_scanner.py` / `run_weekly.bat`)

Run once per week, typically on Sunday evening after updating prices:

```bat
run_weekly.bat
```

Or run directly (assumes `main.py` has already been run):

```bash
python weekly_scanner.py
python weekly_scanner.py --no-display
```

Contains 5 scans. Results go to the DB, CSVs under `charts/YYYY-MM-DD/`, a weekly PDF, and **`WeeklyWatchlist.txt`**. The intraday scanner reads `WeeklyWatchlist.txt` automatically all week alongside the daily lists, so weekly scan tickers stay monitored intraday until the next weekly run.

---

### Scan 5 — Momentum

**Function:** `run_momentum_scan()`  
**DB table:** `momentum_scan_results`  
**CSV:** `momentum_scan_results.csv`  
**Sorted by:** 20-day return descending

Finds stocks running hard with strong recent momentum that are consolidating on a tight day.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close > MA20 and MA50 | In short and medium-term uptrend |
| MA20 > MA50 | MAs stacked (bullish alignment) |
| Close > MA50 × 1.15 | More than 15% above MA50 (extended) |
| Close < MA50 × 3.0 | Less than 200% above MA50 (filters blow-offs) |
| 20-day return > 15% | Strong recent price appreciation |
| vol_avg30 >= 50k | Minimum liquidity |
| Volume >= 50k | Minimum daily activity |
| Inside bar OR narrow range | Quiet consolidation day |

**What it means:** The stock has been running strongly (>15% in 20 days, extended above MA50) but paused today with a tight inside bar or narrow range. A continuation breakout is the expected trade.

---

### Scan 6 — StockbeeMomentum

**Function:** `run_stockbee_scan()`  
**DB table:** `stockbee_scan_results`  
**CSV:** `stockbee_scan_results.csv`  
**Sorted by:** Range expansion ratio descending

Finds explosive single-day range expansion breakouts after a period of volatility contraction — the Stockbee-style momentum breakout.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Today's range > 1.5× avg range of prior 5 days | Range expansion (energy release) |
| Close >= high × 0.95 | Closes within 5% of day's high (strong close) |
| Volume > previous day's volume | Volume confirmation |
| Volume >= 100k | Minimum activity |
| vol_avg30 >= 50k | Minimum average liquidity |
| Prior day was narrow OR red | Quiet setup before the breakout |
| Today's high > max high of last 5 days | Breaking out of a 5-day base |
| 20-day high <= today's high × 1.15 | Consolidating near highs, not bouncing from a deep drop |
| 5-day avg range < 10-day avg range | Volatility contracting before expansion |
| Close < MA50 × 1.50 | Not over-extended (prefers early breakouts) |

**What it means:** The stock was tightening (volatility contracting) and then exploded today with a wide-range candle on higher volume, breaking above the recent 5-day high with a strong close. This is a first-stage or early breakout, not a late-stage extended move.

---

### Scan 7 — Double Trouble 1% Mover

**Function:** `run_double_trouble_scan()`  
**DB table:** `double_trouble_scan_results`  
**CSV:** `double_trouble_scan_results.csv`  
**Sorted by:** close/52-week-low ratio descending

Finds stocks that have at least doubled off their 52-week lows and are now in an uptrend, with a quiet session today (±1% move). Based on the "Double Trouble" concept of stocks with persistent relative strength.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close / 52-week low >= 1.8 | Stock has roughly doubled from its lows |
| Close > MA50 | In medium-term uptrend |
| MA50 > MA200 | Confirmed, sustained uptrend |
| 3-day avg volume >= 100k | Consistent activity |
| vol_avg30 >= 500k | Institutional liquidity |
| Daily price change between −1% and +1% | Quiet day on a strong stock |

**What it means:** The stock is a proven winner (doubled off lows, MA50 above MA200) that is digesting recent gains quietly. The tight day on a strong stock is a low-risk continuation entry.

---

### Scan 8 — TI65 1% Mover

**Function:** `run_ti65_scan()`  
**DB table:** `ti65_scan_results`  
**CSV:** `ti65_scan_results.csv`  
**Sorted by:** TI65 ratio descending

Finds stocks where the short-term price average (7-day) is significantly above the medium-term average (65-day), with a quiet session today. The TI65 ratio is a momentum metric.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| avgc7 / avgc65 > 1.05 | 7-day avg close at least 5% above 65-day avg close |
| Close > MA50 > MA200 | Confirmed uptrend (price and MAs aligned) |
| 3-day avg volume >= 100k | Consistent activity |
| vol_avg30 >= 500k | Institutional liquidity |
| Daily price change between −1% and +1% | Quiet day |

**What it means:** The 7-day average price is running ahead of the 65-day average, indicating sustained short-term momentum within a longer trend. A quiet ±1% day on such a stock is a low-risk continuation setup.

---

### Scan 9 — Parabolic

**Function:** `run_parabolic_scan()`  
**DB table:** `parabolic_scan_results`  
**CSV:** `parabolic_scan_results.csv`  
**Sorted by:** 20-day return descending

Finds stocks in explosive, parabolic moves — up 50%+ from their 60-day lows and still running.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close > MA20 and MA50 | In uptrend |
| Close > MA50 × 1.50 | At least 50% above MA50 (highly extended) |
| 20-day return >= 50% | Strong recent momentum |
| 5-day return > 0% | Still moving upward |
| Rise from 60-day low >= 50% | Big move off recent lows |
| vol_avg30 >= 50k | Minimum liquidity |
| Volume >= 50k | Minimum daily activity |

**What it means:** These are explosive momentum stocks running far above their moving averages. Use these for high-risk/high-reward momentum entries or to watch for exhaustion patterns.

---

### Scan 10 — MA Cross-Up

**Function:** `run_ma_cross_up_scan()`  
**DB table:** `ma_cross_up_results`  
**CSV:** `ma_cross_up_results.csv`

Finds stocks where the closing price crossed above a moving average yesterday (from below). A narrow-range green candle confirms the cross without being overextended. Results are force-included in `ActionList.txt`.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close > Open | Green candle |
| (high−low)/close < 1.5% | Narrow range (quiet, controlled cross) |
| Volume >= 100k | Minimum activity |
| vol_avg30 >= 200k | Institutional liquidity |
| Previous close < previous MA | Was below the MA yesterday |
| Today's close > today's MA | Closed above the MA today |

Checked independently for MA20, MA50, and MA200. The `crossed_ma` field records which MA was crossed.

**What it means:** A clean, quiet cross above a key moving average. The narrow range on the crossover day is important — a wide-range cross is often exhausted; a narrow one suggests the move is just beginning.

---

### Scan 11 — MA Cross-Down

**Function:** `run_ma_cross_down_scan()`  
**DB table:** `ma_cross_down_results`  
**CSV:** `ma_cross_down_results.csv`

Finds stocks that crossed below a moving average on a very narrow red candle. These are bearish signals for stocks previously above the MA. Results are force-included in `ActionList.txt` as watchlist candidates (potential short setups or exit signals).

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close < Open | Red candle |
| (high−low)/close < 1.0% | Very narrow range (< 1% of price) |
| Volume >= 100k | Minimum activity |
| vol_avg30 >= 200k | Institutional liquidity |
| Previous close > previous MA | Was above the MA yesterday |
| Today's close < today's MA | Closed below the MA today |

Checked independently for MA20, MA50, and MA200.

**What it means:** A quiet, controlled break below a key MA. The very narrow range suggests the breakdown is not yet panicky — often the first touch below, which can be the best short entry before the stock confirms lower.

---

### Scan 12 — Near MA50 Below

**Function:** `run_near_ma50_below_scan()`  
**DB table:** `near_ma50_below_results`  
**CSV:** `near_ma50_below_results.csv`  
**Sorted by:** % below MA50 ascending (closest first)

Finds stocks trading just below their 50-day MA — within 2%. These are potential bounce candidates or stocks about to reclaim the MA. Results are force-included in `ActionList.txt`.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Close < MA50 | Price is below MA50 |
| Close >= MA50 × 0.98 | But within 2% below MA50 |
| Volume >= 100k | Minimum activity |
| vol_avg30 >= 200k | Institutional liquidity |

**What it means:** The stock is knocking on the underside of its 50-day MA. Watch for a cross above (triggers Scan 13) as the entry signal, or use as a watchlist to monitor for reclaim.

---

### Scan 13 — MA50 Cross-Up

**Function:** `run_ma50_cross_up_scan()`  
**DB table:** `ma50_cross_up_results`  
**CSV:** `ma50_cross_up_results.csv`

Specifically tracks stocks whose close crossed above their MA50 today, regardless of candle shape. No narrow-range requirement — any close above MA50 from below qualifies. Results are force-included in `ActionList.txt`.

**Conditions (all must be true):**

| Condition | Value |
|---|---|
| Previous close < previous MA50 | Was below MA50 yesterday |
| Today's close > MA50 | Closed above MA50 today |
| Volume >= 100k | Minimum activity |
| vol_avg30 >= 200k | Institutional liquidity |

**What it means:** The stock reclaimed its 50-day MA. No shape filter means this catches all crossovers, including gap-ups and wide-range days. Often used alongside Scan 12 — yesterday's "near MA50 below" becomes today's "MA50 cross-up."

---

### Watchlist and ActionList generation

After all daily scans complete, `scanner.py` does two additional things:

**DailyWatchlist.txt** — union of tickers from Scans 1, 2, 3, 4, and 10 plus any tickers in `custom_watchlist.txt`. Scans 5–9 (weekly) are not included here; their tickers live in `WeeklyWatchlist.txt`.

**ActionList.txt** — filtered subset of the daily watchlist: only tickers whose latest day is an inside bar or narrow range ((high−low)/close < 1.5%). Scans 10, 11, 12, and 13 tickers are force-included regardless of candle shape, since they represent direct signals.

**WeeklyWatchlist.txt** — written by `weekly_scanner.py` when you run it. Contains the union of all 5 weekly scan tickers. The intraday scanner merges this with `DailyWatchlist.txt` and `ActionList.txt` automatically, so those stocks remain monitored intraday throughout the week.

---

## Part 2 — Intraday Breakout Scanner (`intraday_scanner.py`)

Monitors `DailyWatchlist.txt` and `ActionList.txt` every hour during market hours. Writes `buynow.txt` with stocks meeting either condition.

### How to run

```bash
python intraday_scanner.py     # single run, prints results
run_buynow.bat                 # single run + logs to logs\YYYY-MM-DD.log
```

### Scheduling (Task Scheduler)

Register 5 daily triggers (10:15, 11:15, 12:15, 13:15, 14:15 ET, Mon–Fri):

```powershell
# Run once as Administrator
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_buynow_schedule.ps1
```

Manage the task:

```bat
schtasks /run /tn "BuyNowScanner"              :: trigger manually
schtasks /query /tn "BuyNowScanner" /fo LIST   :: check status
schtasks /delete /tn "BuyNowScanner" /f        :: remove
```

### Condition A — Prev-High Breakout

| What | Logic |
|---|---|
| Reference | Most recent `high` from `stockdata.db` (yesterday's high, since DB is not updated intraday) |
| Signal | `current_price > yesterday_high` |
| Filter | Breakout capped at +25% to exclude stale-DB mismatches |

### Condition B — MA Crossover

| What | Logic |
|---|---|
| Reference | MA10, MA20, MA50, MA200 from `indicators` table (most recent row) |
| Signal | `yesterday_close < MA_value` AND `current_price >= MA_value` |
| Filter | Capped at +25% above the MA |

Each MA is checked independently. A ticker can appear multiple times in this section (e.g., crosses both MA50 and MA200 on the same move). A ticker appearing in **both** sections — breakout above yesterday's high AND crossing a moving average — is the strongest signal.

### buynow.txt format

```
# BuyNow - 2026-04-28 10:15:03
# Prev-High Breakouts: 4   |   MA Crossovers: 6

=== PREV HIGH BREAKOUTS (4) ===
TICKER        CURR  PREV HIGH   $ OVER   % OVER
-----------------------------------------------
ACHV          4.26       3.74    +0.52   +14.04%
TRAX         20.05      19.00    +1.05    +5.53%

=== MA CROSSOVERS (6) ===
TICKER        CURR      MA   MA VALUE   $ OVER   % OVER
-------------------------------------------------------
ACHV          4.26   MA200       3.83    +0.44   +11.50%
NVDA        215.50    MA50     214.73    +0.77    +0.36%
```

Both sections are sorted by `% OVER` descending. The file is overwritten on every run.

### Data source

Current prices are fetched from Yahoo Finance via `yfinance.download()` in batches of 100 tickers using `period="1d"`, `interval="1m"`. The most recent 1-minute bar's close is used as the current price. Expected runtime: 60–90 seconds for ~500 tickers.

---

## Part 3 — Whitelight ETF Strategy (`whitelight_strategy.py`)

A trend-following strategy on 3x leveraged ETFs (TQQQ / SQQQ), reverse-engineered from the Collective2 Whitelight strategy.

### How to run

```bash
python whitelight_strategy.py                        # defaults: $10k capital, MA10, 30-day table
python whitelight_strategy.py --capital 15000        # different capital
python whitelight_strategy.py --ma 5                 # faster moving average
python whitelight_strategy.py --my-capital 3000      # your personal position size
python whitelight_strategy.py --no-trade-log         # skip historical trade table
```

### Signal logic

| Condition | Action |
|---|---|
| QQQ close > MA10 | Long TQQQ (bullish — Nasdaq uptrend) |
| QQQ close <= MA10 | Long SQQQ (bearish — Nasdaq downtrend) |

The signal requires **2 consecutive closes** on the new side before flipping (confirmation filter). A single-day cross is ignored, matching the strategy's observed behavior.

### Position sizing (RSI-based staging)

Position size is not fixed — it scales with a `StageFactor` derived from:

- **RSI_Today**: today's RSI of QQQ
- **RSI_Average**: average RSI since the current trade entry
- **PercentHigh**: how far QQQ sits below its 52-week high

Additional risk reduction factors (each multiplied in):

| Factor | Penalty trigger |
|---|---|
| currMADownFactor | QQQ below its 200-day MA |
| currRSIBreakFactor | RSI < 40 (momentum collapse) |
| currRSIROCFactor | RSI dropped >10 points in 5 days |

`EffectiveStageFactor` = product of all factors × base StageFactor. Shares = floor(capital × 2 × EffectiveStageFactor / ETF price).

### Output

- Console: trade log table, daily signal table, today's action block
- `whitelight_signal.txt`: machine-readable key=value file with today's signal, shares, cost, and all factor values

### Scheduled run

`run_whitelight.bat` runs the strategy after market close. Check `whitelight_signal.txt` each evening to see whether to switch or hold.

---

## Running the Full Pipeline

### Weekly (Sunday evening)

```bat
run_weekly.bat
```

Downloads latest prices, runs the 5 weekly scans, writes `WeeklyWatchlist.txt` and a PDF. Do this once to seed the weekly universe.

### Daily (weekday after market close — automated)

```bat
daily.bat
```

Downloads latest prices, runs the 8 daily scans, updates `DailyWatchlist.txt` and `ActionList.txt`, generates a daily PDF. Scheduled automatically via Task Scheduler at 8 PM ET.

### Intraday (10:15 AM – 2:15 PM ET — automated via Task Scheduler)

```bat
run_buynow.bat       :: or just:
python intraday_scanner.py
```

Reads `DailyWatchlist.txt` + `ActionList.txt` + `WeeklyWatchlist.txt`. Writes `buynow.txt` with prev-high breakouts and MA crossovers. Fires automatically at 10:15, 11:15, 12:15, 13:15, 14:15 ET.

### Whitelight (after market close — optional)

```bat
run_whitelight.bat   :: or:
python whitelight_strategy.py
```

---

## Common Questions

**The intraday scanner shows a stock in both sections — what does that mean?**  
The current price has broken above yesterday's high AND crossed above at least one moving average on the same move. This is the highest-conviction intraday signal.

**Why does a ticker appear multiple times in the MA Crossovers section?**  
Each MA (MA10, MA20, MA50, MA200) is checked independently. A stock can cross multiple MAs simultaneously — for example, after a prolonged decline, a recovery move might push through MA20, MA50, and MA200 all at once.

**Why does ActionList.txt contain stocks that didn't appear in the PDF charts?**  
Scans 10, 11, 12, and 13 are force-included in `ActionList.txt` but are not charted (the PDF only includes Scans 1–9). These are direct signals (MA crossovers, MA reclaims) that go straight to the action list regardless of candle shape.

**What is the 25% cap on the intraday scanner?**  
Tickers whose current price is more than 25% above the reference level (yesterday's high or a moving average) are excluded. These are almost always stale DB rows — for example, a ticker that was delisted and re-listed with a completely different price, where the DB still has the old price. Legitimate intraday breakouts are rarely more than 25% in a single session.
