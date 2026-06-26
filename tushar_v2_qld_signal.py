"""Tushar v2 daily signal — QLD variant for no-margin accounts (Roth / HSA / 401k).

Same v1 regime gate (QQQ within 15% of 189d high), but the trading vehicle is
QLD (2x Nasdaq-100) and exposure is CAPPED AT 1.0 (100% of cash) because
retirement/HSA accounts cannot use margin. Vol-target uses QLD's own volatility:

    target % of account in QLD = clip(0.45 / realized_vol_QLD, 0, 1.0)   (bull only)

Backtest 2010-2026 (cap 1.0, after cash yield): CAGR +30.6%, Sharpe 0.99,
maxDD -39% -- vs QLD buy & hold 32.4% / 0.89 / -64%. The overlay keeps most of
2x Nasdaq's return while taming the drawdown.

Logs to signals/tushar_v2_qld_history.csv (idempotent same-day replace).
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

from tusharStrategyDev import compute_signal_v1

TARGET_VOL = 0.45
LEV_CAP = 1.0          # NO MARGIN in Roth/401k/HSA -> max 100% of cash
VOL_WINDOW = 20
TRADING_DAYS = 252
VEHICLE = "QLD"        # 2x Nasdaq-100 (leverage is internal to the fund)
PERIOD = "1y"
HISTORY_CSV = os.path.join("signals", "tushar_v2_qld_history.csv")
STALE_DAYS = 5
BACKFILL_DAYS = 5   # backfill up to this many missed trading days


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


def _build_rows(sig, rv, idx):
    """Compute signal rows for every date in idx (skips first row — needs prev)."""
    rows = []
    for i in range(1, len(idx)):
        today = sig.iloc[i]
        prev  = sig.iloc[i - 1]
        bull      = today["regime"] == "BUY_TQQQ"
        prev_bull = prev["regime"]  == "BUY_TQQQ"
        expo      = exposure_for(bull,      float(rv.iloc[i]))
        prev_expo = exposure_for(prev_bull, float(rv.iloc[i - 1]))

        if not prev_bull and bull:
            action = "ENTER"
        elif prev_bull and not bull:
            action = "EXIT"
        elif not bull:
            action = "IN CASH"
        elif expo > prev_expo + 0.02:
            action = "SCALE UP"
        elif expo < prev_expo - 0.02:
            action = "SCALE DOWN"
        else:
            action = "HOLD"

        rows.append({
            "date":      idx[i],
            "qqq_close": float(today["close"]),
            "high189":   float(today["high252"]),
            "pcthi":     float(today["pcthi"]),
            "regime":    "BULL" if bull else "CASH",
            "qld_vol":   float(rv.iloc[i]),
            "exposure":  expo,
            "action":    action,
        })
    return rows


def compute():
    """Return signal rows for any dates missing from history (up to BACKFILL_DAYS)."""
    qqq = _fetch("QQQ")
    qld = _fetch(VEHICLE)

    qqq_low = qqq.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    sig = compute_signal_v1(qqq_low)

    qld_ret = qld["Close"].pct_change()
    rv      = (qld_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()

    idx     = sig.index.intersection(rv.index)
    sig, rv = sig.loc[idx], rv.loc[idx]

    all_rows = _build_rows(sig, rv, idx)

    logged = set()
    if os.path.exists(HISTORY_CSV):
        hist   = pd.read_csv(HISTORY_CSV, dtype={"date": str})
        logged = set(hist["date"].tolist())

    recent  = all_rows[-BACKFILL_DAYS:]   # only the last N trading days
    missing = [r for r in recent
               if r["date"].date().isoformat() not in logged]
    return missing


def report(s):
    bar = s["date"].date()
    age = (datetime.now() - s["date"].to_pydatetime().replace(tzinfo=None)).days
    if age > STALE_DAYS:
        print(f"WARNING: latest bar is {age} days old ({bar}) - data may be stale.")
    print(f"\nTushar v2 {VEHICLE} Signal (no-margin, Roth/HSA/401k) - {bar}")
    print(f"QQQ Close: ${s['qqq_close']:.2f}   189d High: ${s['high189']:.2f}   "
          f"% Below High: {s['pcthi']:.1f}%")
    print(f"Regime: {s['regime']}   {VEHICLE} 20d Vol: {s['qld_vol']:.0%}")
    pct = int(round(s["exposure"] * 100))
    if pct > 0:
        print(f"Target: {pct}% of account in {VEHICLE}   Action: {s['action']}")
    else:
        print(f"Target: CASH (0% {VEHICLE})   Action: {s['action']}")
    if age > 1:
        print(f"NOTE: signal is {age} day(s) old — backfilled from historical data.")


def append_history(rows):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    new = pd.DataFrame([{
        "date":       r["date"].date().isoformat(),
        "qqq_close":  round(r["qqq_close"], 2),
        "pcthi":      round(r["pcthi"], 1),
        "regime":     r["regime"],
        "qld_vol":    round(r["qld_vol"], 3),
        "pct_in_qld": int(round(r["exposure"] * 100)),
        "action":     r["action"],
    } for r in rows])
    if os.path.exists(HISTORY_CSV):
        hist  = pd.read_csv(HISTORY_CSV, dtype={"date": str})
        dates = set(new["date"].tolist())
        hist  = hist[~hist["date"].isin(dates)]
        hist  = pd.concat([hist, new], ignore_index=True).sort_values("date")
    else:
        hist = new
    hist.to_csv(HISTORY_CSV, index=False)
    print(f"Logged {len(rows)} row(s) to {HISTORY_CSV}")


def main():
    rows = compute()
    if not rows:
        print("No new dates to log — already up to date.")
        return
    if len(rows) > 1:
        print(f"Backfilling {len(rows) - 1} missed day(s)...")
    report(rows[-1])
    append_history(rows)


if __name__ == "__main__":
    main()
