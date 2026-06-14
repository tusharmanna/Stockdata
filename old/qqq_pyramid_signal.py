"""QQQ 3-tier weighted pyramid signal checker for daily use.

Tier weights (25/35/40 — more weight on confirmed signals):
  T1: Close > MA3   -> +25%
  T2: Close > MA35  -> +35%
  T3: MA3 > MA35    -> +40%

Run daily to see:
  - Tier status and current position fraction (0/25/35/40/60/65/75/100%)
  - Action: SCALE UP, SCALE DOWN, HOLD, IN CASH
  - Days in current tier configuration

Backtest 2010-2026 (3x leverage): +10,021% total, Sharpe 0.98, maxDD -59.9%
(vs equal thirds +8,932%; see qqq_pyramid_weighted_backtest.py)

Logs signals to signals/qqq_pyramid_history.csv
"""

import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

TICKER = "QQQ"
FAST = 3
SLOW = 35
WEIGHTS = (0.25, 0.35, 0.40)  # T1, T2, T3 — must sum to 1
PERIOD = "3mo"
HISTORY_CSV = os.path.join("signals", "qqq_pyramid_history.csv")
STALE_DAYS = 5


def fetch_data():
    data = yf.download(TICKER, period=PERIOD, progress=False, auto_adjust=True)
    if data is None or data.empty:
        sys.exit(f"ERROR: yfinance returned no data for {TICKER}.")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if len(data) < SLOW + 1:
        sys.exit(f"ERROR: only {len(data)} bars; need at least {SLOW + 1}.")
    return data


def compute_signal(close):
    """Return tier status, position fraction, and action."""
    ma_fast = close.rolling(FAST).mean()
    ma_slow = close.rolling(SLOW).mean()

    today_close = float(close.iloc[-1])
    today_ma_fast = float(ma_fast.iloc[-1])
    today_ma_slow = float(ma_slow.iloc[-1])

    t1 = today_close > today_ma_fast
    t2 = today_close > today_ma_slow
    t3 = today_ma_fast > today_ma_slow

    w1, w2, w3 = WEIGHTS
    frac = w1 * int(t1) + w2 * int(t2) + w3 * int(t3)
    frac_pct = round(frac * 100)

    # Previous day's fraction
    prev_ma_fast = float(ma_fast.iloc[-2])
    prev_ma_slow = float(ma_slow.iloc[-2])
    prev_close = float(close.iloc[-2])
    prev_t1 = prev_close > prev_ma_fast
    prev_t2 = prev_close > prev_ma_slow
    prev_t3 = prev_ma_fast > prev_ma_slow
    prev_frac = w1 * int(prev_t1) + w2 * int(prev_t2) + w3 * int(prev_t3)

    if frac > prev_frac:
        action = "SCALE UP"
    elif frac < prev_frac:
        action = "SCALE DOWN"
    elif frac == 0:
        action = "IN CASH"
    else:
        action = "HOLD"

    # Days in current config (weighted fraction identifies the exact tier combo)
    regime = pd.Series(
        w1 * (close > ma_fast).astype(int) + w2 * (close > ma_slow).astype(int)
        + w3 * (ma_fast > ma_slow).astype(int),
        index=close.index
    )
    since_idx = len(regime) - 1
    while since_idx > 0 and regime.iloc[since_idx - 1] == regime.iloc[-1]:
        since_idx -= 1
    days_in_regime = len(regime) - since_idx

    return {
        "date": close.index[-1],
        "close": today_close,
        "ma_fast": today_ma_fast,
        "ma_slow": today_ma_slow,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "frac_pct": frac_pct,
        "action": action,
        "days": days_in_regime,
    }


def print_report(sig):
    bar_date = sig["date"].date()
    age = (datetime.now() - sig["date"].to_pydatetime().replace(tzinfo=None)).days
    if age > STALE_DAYS:
        print(f"WARNING: latest bar is {age} days old ({bar_date}) - data may be stale.")

    w1, w2, w3 = WEIGHTS
    print(f"\nQQQ {FAST}/{SLOW} Weighted Pyramid Signal ({w1:.0%}/{w2:.0%}/{w3:.0%}) - {bar_date}")
    print(f"Close: ${sig['close']:.2f}   MA{FAST}: ${sig['ma_fast']:.2f}   MA{SLOW}: ${sig['ma_slow']:.2f}")
    print(f"Tiers: T1 (close > MA{FAST}, +{w1:.0%}) {'YES' if sig['t1'] else 'NO'}  |  "
          f"T2 (close > MA{SLOW}, +{w2:.0%}) {'YES' if sig['t2'] else 'NO'}  |  "
          f"T3 (MA{FAST} > MA{SLOW}, +{w3:.0%}) {'YES' if sig['t3'] else 'NO'}")
    print(f"Position: {sig['frac_pct']}% of full 3x  |  Action: {sig['action']}  |  "
          f"Days in regime: {sig['days']}")


def append_history(sig):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    row = pd.DataFrame([{
        "date": sig["date"].date().isoformat(),
        "close": round(sig["close"], 2),
        "ma_fast": round(sig["ma_fast"], 2),
        "ma_slow": round(sig["ma_slow"], 2),
        "t1": int(sig["t1"]),
        "t2": int(sig["t2"]),
        "t3": int(sig["t3"]),
        "position_pct": sig["frac_pct"],
        "action": sig["action"],
    }])
    if os.path.exists(HISTORY_CSV):
        hist = pd.read_csv(HISTORY_CSV, dtype={"date": str})
        hist = hist[hist["date"] != row.at[0, "date"]]
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
