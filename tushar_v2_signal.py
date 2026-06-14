"""Tushar v2 daily signal — volatility-targeted v1 (defensive).

Run daily to see:
  - v1 regime (BULL = QQQ within 15% of 189d high, else CASH)
  - TQQQ 20-day realized volatility
  - Target TQQQ exposure: clip(0.45 / realized_vol, 0, 1.5)
  - Action vs yesterday: ENTER / EXIT / LEVER UP / LEVER DOWN / HOLD / IN CASH

target_vol = 0.45 is the walk-forward-endorsed setting: out of sample it matched
v1's Sharpe while cutting max drawdown from ~-57% to ~-43%.

Logs to signals/tushar_v2_history.csv (idempotent same-day replace).
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from tusharStrategyDev import compute_signal_v1

TARGET_VOL = 0.45   # walk-forward-endorsed defensive setting (was 0.75 aggressive)
LEV_CAP = 1.5
VOL_WINDOW = 20
TRADING_DAYS = 252
PERIOD = "1y"
HISTORY_CSV = os.path.join("signals", "tushar_v2_history.csv")
STALE_DAYS = 5


def _fetch(ticker):
    data = yf.download(ticker, period=PERIOD, progress=False, auto_adjust=True)
    if data is None or data.empty:
        sys.exit(f"ERROR: yfinance returned no data for {ticker}.")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.index = pd.to_datetime(data.index).tz_localize(None)
    return data


def exposure_for(regime_bull, realized_vol):
    if not regime_bull:
        return 0.0
    return float(np.clip(TARGET_VOL / realized_vol, 0.0, LEV_CAP))


def compute():
    qqq = _fetch("QQQ")
    tqqq = _fetch("TQQQ")

    qqq_low = qqq.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    sig = compute_signal_v1(qqq_low)

    tqqq_ret = tqqq["Close"].pct_change()
    rv = (tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()

    # align
    idx = sig.index.intersection(rv.index)
    sig, rv = sig.loc[idx], rv.loc[idx]

    today = sig.iloc[-1]
    prev = sig.iloc[-2]
    bull = today["regime"] == "BUY_TQQQ"
    prev_bull = prev["regime"] == "BUY_TQQQ"

    expo = exposure_for(bull, float(rv.iloc[-1]))
    prev_expo = exposure_for(prev_bull, float(rv.iloc[-2]))

    if not prev_bull and bull:
        action = "ENTER"
    elif prev_bull and not bull:
        action = "EXIT"
    elif not bull:
        action = "IN CASH"
    elif expo > prev_expo + 0.02:
        action = "LEVER UP"
    elif expo < prev_expo - 0.02:
        action = "LEVER DOWN"
    else:
        action = "HOLD"

    return {
        "date": idx[-1],
        "qqq_close": float(today["close"]),
        "high189": float(today["high252"]),
        "pcthi": float(today["pcthi"]),
        "regime": "BULL" if bull else "CASH",
        "tqqq_vol": float(rv.iloc[-1]),
        "exposure": expo,
        "action": action,
    }


def report(s):
    bar = s["date"].date()
    age = (datetime.now() - s["date"].to_pydatetime().replace(tzinfo=None)).days
    if age > STALE_DAYS:
        print(f"WARNING: latest bar is {age} days old ({bar}) - data may be stale.")
    print(f"\nTushar v2 (vol-targeted, defensive) Signal - {bar}")
    print(f"QQQ Close: ${s['qqq_close']:.2f}   189d High: ${s['high189']:.2f}   "
          f"% Below High: {s['pcthi']:.1f}%")
    print(f"Regime: {s['regime']}   TQQQ 20d Vol: {s['tqqq_vol']:.0%}")
    if s["exposure"] > 0:
        print(f"Target: Hold {s['exposure']:.2f}x TQQQ   Action: {s['action']}")
    else:
        print(f"Target: CASH (0x TQQQ)   Action: {s['action']}")


def append_history(s):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    row = pd.DataFrame([{
        "date": s["date"].date().isoformat(),
        "qqq_close": round(s["qqq_close"], 2),
        "pcthi": round(s["pcthi"], 1),
        "regime": s["regime"],
        "tqqq_vol": round(s["tqqq_vol"], 3),
        "exposure": round(s["exposure"], 2),
        "action": s["action"],
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
    s = compute()
    report(s)
    append_history(s)


if __name__ == "__main__":
    main()
