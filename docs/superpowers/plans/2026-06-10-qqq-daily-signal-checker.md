# QQQ Daily Signal Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `qqq_signal.py`, a daily-run tool that downloads fresh QQQ data from yfinance and prints ENTER / EXIT / HOLD LONG / HOLD CASH per the 4/25 MA crossover strategy, logging each signal to a history CSV and wired into `run_daily.bat`.

**Architecture:** One flat script (repo convention). Stateless: every run downloads ~3 months of QQQ bars, computes both today's and yesterday's regime from that data, and derives the action from the regime transition — no saved state to drift. History CSV is write-only (a log, never an input).

**Tech Stack:** Python, yfinance, pandas (already in requirements.txt).

**Spec:** `docs/superpowers/specs/2026-06-10-qqq-daily-signal-checker-design.md`

---

### Task 1: `qqq_signal.py` — fetch, signal, report, history

**Files:**
- Create: `qqq_signal.py`

- [ ] **Step 1: Create the script**

```python
"""QQQ daily signal checker for the 4/25 MA crossover strategy.

Run daily (manually or via run_daily.bat). Downloads fresh QQQ data from
yfinance, computes the 4-day and 25-day moving averages, and prints the
action: ENTER (buy TQQQ), EXIT (sell TQQQ to cash), HOLD LONG, or HOLD CASH.

Logic matches the backtest in qqq_backtest_2010_2026.py: regime is LONG when
MA4 > MA25, else CASH; the signal from today's close is executed at the next
market open. See docs/GRID_STRATEGY_GUIDE.md.

Appends each day's signal to signals/qqq_signal_history.csv (write-only log;
re-running the same day replaces that day's row).
"""

import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

TICKER = "QQQ"
FAST = 4
SLOW = 25
PERIOD = "3mo"  # ~63 trading days; needs SLOW + 1 = 26 minimum
HISTORY_CSV = os.path.join("signals", "qqq_signal_history.csv")
STALE_DAYS = 5  # warn if latest bar is older than this many calendar days


def fetch_data():
    data = yf.download(TICKER, period=PERIOD, progress=False, auto_adjust=True)
    if data is None or data.empty:
        sys.exit(f"ERROR: yfinance returned no data for {TICKER}. "
                 "Check your internet connection and try again.")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if len(data) < SLOW + 1:
        sys.exit(f"ERROR: only {len(data)} bars downloaded; "
                 f"need at least {SLOW + 1} for the {FAST}/{SLOW} signal.")
    return data


def compute_signal(close):
    """Return a dict describing the latest signal.

    Regime: LONG when MA4 > MA25, else CASH (matches backtest, where the
    position is 0 on equality and during warmup).
    """
    ma_fast = close.rolling(FAST).mean()
    ma_slow = close.rolling(SLOW).mean()
    regime = pd.Series("CASH", index=close.index)
    regime[ma_fast > ma_slow] = "LONG"

    today, prev = regime.iloc[-1], regime.iloc[-2]
    if prev == "CASH" and today == "LONG":
        action, advice = "ENTER", "Buy TQQQ at next market open"
    elif prev == "LONG" and today == "CASH":
        action, advice = "EXIT", "Sell TQQQ at next market open, move to cash"
    elif today == "LONG":
        action, advice = "HOLD LONG", "Stay in TQQQ"
    else:
        action, advice = "HOLD CASH", "Stay in cash"

    # Walk backward to find when the current regime started.
    since_idx = len(regime) - 1
    while since_idx > 0 and regime.iloc[since_idx - 1] == today:
        since_idx -= 1

    return {
        "date": close.index[-1],
        "close": float(close.iloc[-1]),
        "ma_fast": float(ma_fast.iloc[-1]),
        "ma_slow": float(ma_slow.iloc[-1]),
        "gap_pct": float(ma_fast.iloc[-1] / ma_slow.iloc[-1] - 1.0) * 100,
        "regime": today,
        "action": action,
        "advice": advice,
        "since_date": close.index[since_idx],
        "regime_days": len(regime) - since_idx,
    }


def print_report(sig):
    bar_date = sig["date"].date()
    age = (datetime.now() - sig["date"].to_pydatetime().replace(tzinfo=None)).days
    if age > STALE_DAYS:
        print(f"WARNING: latest bar is {age} days old ({bar_date}) - "
              "data may be stale.")

    print(f"\n{TICKER} {FAST}/{SLOW} MA Signal - {bar_date}")
    print(f"Close: ${sig['close']:.2f}   MA{FAST}: ${sig['ma_fast']:.2f}   "
          f"MA{SLOW}: ${sig['ma_slow']:.2f}   Gap: {sig['gap_pct']:+.2f}%")
    print(f"Regime: {sig['regime']} (since {sig['since_date'].date()}, "
          f"{sig['regime_days']} trading days)")
    print(f"Action: {sig['action']} - {sig['advice']}")


def append_history(sig):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    row = pd.DataFrame([{
        "date": sig["date"].date().isoformat(),
        "close": round(sig["close"], 2),
        "ma4": round(sig["ma_fast"], 2),
        "ma25": round(sig["ma_slow"], 2),
        "regime": sig["regime"],
        "action": sig["action"],
    }])
    if os.path.exists(HISTORY_CSV):
        hist = pd.read_csv(HISTORY_CSV, dtype={"date": str})
        hist = hist[hist["date"] != row.at[0, "date"]]  # replace same-day row
        hist = pd.concat([hist, row], ignore_index=True).sort_values("date")
    else:
        hist = row
    hist.to_csv(HISTORY_CSV, index=False)
    print(f"Logged to {HISTORY_CSV}")


def main():
    data = fetch_data()
    sig = compute_signal(data["Close"])
    print_report(sig)
    append_history(sig)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run and verify against known data**

Run: `python qqq_signal.py`
Expected output shape (values will reflect live data):
```
QQQ 4/25 MA Signal - 2026-06-09
Close: $722.98   MA4: $...   MA25: $...   Gap: +...%
Regime: ...
Action: ... - ...
Logged to signals\qqq_signal_history.csv
```

Cross-check the MAs independently (note: signal uses auto-adjusted yfinance data,
same as the backtest CSV):

```powershell
python -c "import pandas as pd; df = pd.read_csv('QQQ_2010_2026.csv'); c = df['Close']; print('MA4:', c.rolling(4).mean().iloc[-1], 'MA25:', c.rolling(25).mean().iloc[-1])"
```
Expected: MA4/MA25 match the script's printed values to within a few cents
(the stored CSV ends 2026-06-09; if the live download has newer bars, recompute
mentally or accept regime agreement as the check).

- [ ] **Step 3: Verify idempotent history (run twice, one row per date)**

Run: `python qqq_signal.py` (a second time), then:
```powershell
python -c "import pandas as pd; h = pd.read_csv('signals/qqq_signal_history.csv'); print(h); assert h['date'].is_unique, 'DUPLICATE DATES'"
```
Expected: the history prints with exactly one row per date, no assertion error.

- [ ] **Step 4: Commit**

```bash
git add qqq_signal.py
git commit -m "Add daily QQQ 4/25 MA signal checker (ENTER/EXIT/HOLD)"
```

---

### Task 2: Wire into `run_daily.bat` and ignore the signals dir

**Files:**
- Modify: `run_daily.bat` (add one line after the scanner line)
- Modify: `.gitignore` (add `signals/` — generated output, same convention as `charts/`)

- [ ] **Step 1: Add the signal line to run_daily.bat**

Change lines 12-14 of `run_daily.bat` from:

```bat
python main.py >> "%LOG_FILE%" 2>&1
python scanner.py --no-display >> "%LOG_FILE%" 2>&1
echo === Run finished: %date% %time% === >> "%LOG_FILE%"
```

to:

```bat
python main.py >> "%LOG_FILE%" 2>&1
python scanner.py --no-display >> "%LOG_FILE%" 2>&1
python qqq_signal.py >> "%LOG_FILE%" 2>&1
echo === Run finished: %date% %time% === >> "%LOG_FILE%"
```

- [ ] **Step 2: Add signals/ to .gitignore**

Read `.gitignore` first; append this line following its existing style:

```
signals/
```

- [ ] **Step 3: Verify the batch pipeline runs the signal step**

Run: `cmd /c run_daily.bat` is too slow (full download+scan). Instead verify just the new line's behavior:
```powershell
python qqq_signal.py >> test_signal_log.txt 2>&1; Get-Content test_signal_log.txt; Remove-Item test_signal_log.txt
```
Expected: the full signal block appears in the file content (proves stdout redirection works for the .bat context).

- [ ] **Step 4: Commit**

```bash
git add run_daily.bat .gitignore
git commit -m "Run QQQ signal checker in daily 8 PM pipeline"
```

---

### Task 3: Document the tool in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (add to "Running the Program" section)

- [ ] **Step 1: Add the command to CLAUDE.md's Running the Program block**

In the `## Running the Program` code block, after the `python backfill_recent.py` entry, add:

```bash
# Print today's 4/25 MA crossover signal for QQQ (ENTER/EXIT/HOLD) + log to signals/
python qqq_signal.py
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "Document qqq_signal.py in CLAUDE.md"
```
