# Intraday Breakout Scanner

Scans tickers from `DailyWatchlist.txt` and `ActionList.txt` every hour during market hours. Any ticker that meets either of the following conditions is written to `buynow.txt`:

- **Prev-High Breakout** — current price has crossed above yesterday's high
- **MA Crossover** — yesterday's close was below a moving average (MA10/20/50/200) and the current price has crossed above it

---

## Files

| File | Purpose |
|---|---|
| `intraday_scanner.py` | Main scanner script |
| `run_buynow.bat` | Batch wrapper — runs the scanner and appends output to the daily log |
| `setup_buynow_schedule.ps1` | One-time Task Scheduler registration (run as Administrator) |
| `buynow.txt` | Output — refreshed on every run |

---

## Prerequisites

The scanner reads from `stockdata.db`, which must have been populated by `main.py`. Run `main.py` once before market open each day (or let the existing Task Scheduler job handle it at 8 PM the night before).

```
python main.py
```

No additional packages are needed beyond what is already in `requirements.txt`.

---

## How It Works

1. Loads all tickers from `DailyWatchlist.txt` and `ActionList.txt`, deduplicates them (~500 tickers total on a typical day).
2. Queries `stockdata.db` for each ticker's most recent row: yesterday's `high`, yesterday's `close`, and the four moving averages (MA10, MA20, MA50, MA200) from the indicators table.
3. Downloads today's 1-minute OHLCV bars from Yahoo Finance in batches of 100 tickers per API call (~5 calls total).
4. Takes the last bar's close as the current price.
5. Applies two conditions (capped at +25% to exclude stale-data false positives):
   - **Prev-High Breakout**: `current_price > yesterday_high`
   - **MA Crossover**: `yesterday_close < MA_value` AND `current_price >= MA_value` — checked independently for MA10, MA20, MA50, and MA200. A ticker can appear multiple times in this section if it crosses more than one MA.
6. Writes `buynow.txt` with two sections, each sorted by % above the reference level, highest first.

### buynow.txt format

```
# BuyNow - 2026-04-28 10:15:03
# Prev-High Breakouts: 4   |   MA Crossovers: 6

=== PREV HIGH BREAKOUTS (4) ===
TICKER        CURR  PREV HIGH   $ OVER   % OVER
-----------------------------------------------
ACHV          4.26       3.74    +0.52   +14.04%
TRAX         20.05      19.00    +1.05    +5.53%
SMFG         20.92      20.49    +0.43    +2.12%
WATT         32.91      32.63    +0.28    +0.86%

=== MA CROSSOVERS (6) ===
TICKER        CURR      MA   MA VALUE   $ OVER   % OVER
-------------------------------------------------------
ACHV          4.26   MA200       3.83    +0.44   +11.50%
ACHV          4.26    MA10       4.02    +0.24    +6.04%
NVDA        215.50    MA50     214.73    +0.77    +0.36%
DHF           2.43    MA20       2.42    +0.01    +0.39%
NUVL        101.98    MA50     101.95    +0.03    +0.03%
BDC         127.84    MA50     127.83    +0.01    +0.01%
```

The file is overwritten on every run — it always reflects the most recent scan only. A ticker appearing in both sections is a strong signal (price broke above yesterday's high AND crossed a key MA on the same move).

---

## Running Manually

Open a terminal in `E:\work\Stockdata` and run either of:

```bat
python intraday_scanner.py
```

```bat
run_buynow.bat
```

The batch file additionally appends timestamped output to `logs\YYYY-MM-DD.log`.

Expected runtime: ~60–90 seconds for ~500 tickers (5 batched API calls).

---

## Scheduling (Windows Task Scheduler)

### One-time setup

Open **PowerShell as Administrator** and run:

```powershell
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_buynow_schedule.ps1
```

This registers a task named **`BuyNowScanner`** with five daily triggers:

| Fire time (ET) | Days |
|---|---|
| 10:15 AM | Mon – Fri |
| 11:15 AM | Mon – Fri |
| 12:15 PM | Mon – Fri |
| 1:15 PM | Mon – Fri |
| 2:15 PM | Mon – Fri |

Each trigger runs `run_buynow.bat`, which logs to `logs\YYYY-MM-DD.log` alongside the existing daily-pipeline log.

### Verify the task was registered

```powershell
schtasks /query /tn "BuyNowScanner" /fo LIST
```

### Trigger a manual run via Task Scheduler

```bat
schtasks /run /tn "BuyNowScanner"
```

### Remove the task

```bat
schtasks /delete /tn "BuyNowScanner" /f
```

### Re-register after changes

Simply re-run the setup script — the `/Force` flag overwrites the existing task.

```powershell
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_buynow_schedule.ps1
```

---

## Logs

Output from every scheduled run is appended to:

```
logs\YYYY-MM-DD.log
```

The same log file is shared with `run_scan.bat` (the nightly pipeline). Each scanner section is bracketed by:

```
=== BuyNow scan started: Mon 04/28/2026 10:15:03.42 ===
...output...
=== BuyNow scan finished: Mon 04/28/2026 10:17:11.19 ===
```

---

## Notes

- **25% cap on both conditions**: tickers more than 25% above yesterday's high (or above an MA) are silently excluded. This filters stale-DB mismatches (e.g., a recently re-listed ticker whose DB row is many months old).
- **Failed downloads**: yfinance occasionally fails to return data for thinly traded or recently delisted tickers. These are printed as warnings and skipped; they do not cause the scan to abort.
- **Market-closed runs**: if run outside of market hours the 1m data returns the last trading session's bars. `buynow.txt` will still be written but prices will be stale — the scheduled times (10:15 AM – 2:15 PM ET) keep this from happening in normal use.
- **Timezone**: the Task Scheduler triggers fire at the local machine clock. Ensure Windows is set to Eastern Time, or adjust the trigger times in `setup_buynow_schedule.ps1` to match your local offset.
