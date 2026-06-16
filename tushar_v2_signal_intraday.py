"""Tushar v2 intraday signal — for execution 30 mins before market close.

Uses intraday data (1-minute bars) up to current time to simulate today's
"close" and calculate the v2 signal for same-day execution at 3:30 PM ET.

⚠️ EXPERIMENTAL: Intraday signals are noisier than daily closes. Use with caution.

Usage:
    python tushar_v2_signal_intraday.py

Output: Same format as tushar_v2_signal.py but based on intraday data.
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from tusharStrategyDev import compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TARGET_VOL = 0.45
LEV_CAP = 1.5
VOL_WINDOW = 20
TRADING_DAYS = 252
VEHICLE = "TQQQ"
PERIOD = "60d"  # 60 days to get enough history
HISTORY_CSV = os.path.join("signals", "tushar_v2_intraday_history.csv")
STALE_DAYS = 5


def _fetch_intraday(ticker):
    """Fetch intraday 1-min data for today + daily history."""
    # Get intraday 1-min data (last 59 days to include today)
    intra = yf.download(ticker, period="60d", interval="1m", progress=False, auto_adjust=True)
    if intra is None or intra.empty:
        sys.exit(f"ERROR: yfinance returned no intraday data for {ticker}.")

    # Ensure proper column names (lowercase)
    intra.columns = [col.lower() for col in intra.columns]
    intra.index = pd.to_datetime(intra.index).tz_localize(None)

    return intra


def _fetch_daily(ticker):
    """Fetch full daily history for 189-day regime calculation."""
    daily = yf.download(ticker, period="1y", progress=False, auto_adjust=True)
    if daily is None or daily.empty:
        sys.exit(f"ERROR: yfinance returned no daily data for {ticker}.")

    daily.columns = [col.lower() for col in daily.columns]
    daily.index = pd.to_datetime(daily.index).tz_localize(None)

    return daily


def exposure_for(regime_bull, realized_vol):
    if not regime_bull:
        return 0.0
    return float(np.clip(TARGET_VOL / realized_vol, 0.0, LEV_CAP))


def compute_intraday_signal():
    """Compute v2 signal using intraday data up to now."""
    print("Fetching intraday + daily data...")

    # Get daily data for regime (189d high)
    qqq_daily = _fetch_daily(QQQ_TICKER)
    tqqq_intra = _fetch_intraday(TQQQ_TICKER)
    qqq_intra = _fetch_intraday(QQQ_TICKER)

    # Align on common dates
    last_intra_time = tqqq_intra.index[-1]
    last_intra_date = last_intra_time.date()

    print(f"Intraday data up to: {last_intra_time}")

    # ===== Regime gate (using daily data) =====
    # For regime, we need the 189-day high from completed days
    # Use daily data through yesterday + today's previous close if available

    # Get the most recent complete daily close before now
    daily_up_to_yesterday = qqq_daily[qqq_daily.index.date < last_intra_date]

    if len(daily_up_to_yesterday) < 189:
        sys.exit(f"ERROR: Not enough daily history ({len(daily_up_to_yesterday)} < 189 days).")

    # Calculate regime based on yesterday's data
    sig_yesterday = compute_signal_v1(daily_up_to_yesterday.rename(columns=str.lower))
    regime_yesterday = sig_yesterday.iloc[-1]["regime"] == "BUY_TQQQ"

    # For intraday, assume regime doesn't change within a day (conservative)
    # If it does, we'd use regime_yesterday as the operational regime
    regime_bull = regime_yesterday

    # ===== Volatility from recent intraday + daily =====
    # Calculate 20-day rolling vol using daily closes + today's intraday vol

    # Get last 20 days of daily closes
    daily_20d = qqq_daily.iloc[-20:] if len(qqq_daily) >= 20 else qqq_daily

    # Add today's intraday closes (one per minute) to the vol calculation
    tqqq_today = tqqq_intra[tqqq_intra.index.date == last_intra_date]

    if len(tqqq_today) == 0:
        # No intraday data for today, use yesterday
        tqqq_ret = tqqq_intra["close"].pct_change().dropna()
        realized_vol = (tqqq_ret.rolling(VOL_WINDOW * 390).std() * np.sqrt(TRADING_DAYS)).iloc[-1]
        realized_vol = max(realized_vol, 0.01)  # Floor at 1%
    else:
        # Mix yesterday's closes + today's intraday
        yesterday_closes = tqqq_intra[tqqq_intra.index.date == (last_intra_date - timedelta(days=1))]["close"]
        today_closes = tqqq_today["close"]

        if len(yesterday_closes) > 0:
            # Combine: end of yesterday + today's intraday
            combined = pd.concat([yesterday_closes.tail(1), today_closes])
            intra_ret = combined.pct_change().dropna()

            # Annualize the intraday returns (390 mins in a trading day)
            intra_vol = intra_ret.std() * np.sqrt(TRADING_DAYS * 390)
            realized_vol = max(intra_vol, 0.01)
        else:
            realized_vol = 0.45  # Safe default

    # ===== Today's intraday close =====
    today_close = float(tqqq_today["close"].iloc[-1])
    today_high = float(tqqq_today["high"].max())

    # ===== Regime gate values (from yesterday/historical) =====
    yesterday_row = sig_yesterday.iloc[-1]
    high189 = float(yesterday_row["high252"])
    pcthi = float(yesterday_row["pcthi"])

    # Calculate exposure
    expo = exposure_for(regime_bull, realized_vol)

    # For action, compare to yesterday's exposure
    prev_expo = exposure_for(regime_yesterday, realized_vol)  # Use same vol for comparison

    if regime_bull and not regime_yesterday:
        action = "ENTER"
    elif not regime_bull and regime_yesterday:
        action = "EXIT"
    elif not regime_bull:
        action = "IN CASH"
    elif expo > prev_expo + 0.02:
        action = "SCALE UP"
    elif expo < prev_expo - 0.02:
        action = "SCALE DOWN"
    else:
        action = "HOLD"

    return {
        "date": last_intra_time,
        "qqq_close": float(qqq_intra["close"].iloc[-1]),
        "high189": high189,
        "pcthi": pcthi,
        "regime": "BULL" if regime_bull else "CASH",
        "tqqq_vol": realized_vol,
        "exposure": expo,
        "action": action,
        "intraday": True,
    }


def report(s):
    bar = s["date"]
    age = (datetime.now() - s["date"].to_pydatetime().replace(tzinfo=None)).seconds / 3600

    print(f"\n⚡ Tushar v2 Intraday Signal (EXPERIMENTAL) — {bar.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"(Intraday data up to ~3:30 PM ET)")
    print(f"\nQQQ Close: ${s['qqq_close']:.2f}   189d High: ${s['high189']:.2f}   "
          f"% Below High: {s['pcthi']:.1f}%")
    print(f"Regime: {s['regime']}   TQQQ 20d Vol (intraday): {s['tqqq_vol']:.0%}")
    pct = int(round(s["exposure"] * 100))
    if pct > 0:
        print(f"Target: Hold {s['exposure']:.2f}x TQQQ ({pct}% of account)")
    else:
        print(f"Target: CASH (0% TQQQ)")
    print(f"Action: {s['action']}")
    print(f"\n⚠️  WARNING: Intraday signals are NOISIER than daily closes.")
    print(f"   Only act if you're confident about same-day execution.")


def append_history(s):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    row = pd.DataFrame([{
        "date": s["date"].isoformat(),
        "qqq_close": round(s["qqq_close"], 2),
        "pcthi": round(s["pcthi"], 1),
        "regime": s["regime"],
        "tqqq_vol": round(s["tqqq_vol"], 3),
        "exposure": round(s["exposure"], 2),
        "action": s["action"],
        "intraday": s["intraday"],
    }])
    if os.path.exists(HISTORY_CSV):
        hist = pd.read_csv(HISTORY_CSV, dtype={"date": str})
        # Remove today's entries to replace with latest
        hist = hist[~hist["date"].str.startswith(row.at[0, "date"][:10])]
        hist = pd.concat([hist, row], ignore_index=True).sort_values("date")
    else:
        hist = row
    hist.to_csv(HISTORY_CSV, index=False)
    print(f"\nLogged to {HISTORY_CSV}")


def main():
    s = compute_intraday_signal()
    report(s)
    append_history(s)


if __name__ == "__main__":
    main()
