"""Tushar v2 QQQ Signal (1x, no-margin, conservative).

QQQ is the underlying Nasdaq-100 index. v2 applies:
- Regime gate from v1 (BULL/CASH based on 189d high)
- Vol-targeting with cap at 1.0x (no margin, safe for any account)
- Target vol = 0.45 (defensive)

Output: Daily signal with regime, QQQ 20d vol, target exposure.
Log: signals/tushar_v2_qqq_history.csv (idempotent, same-day replace)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER

TRADING_DAYS = 252
TARGET_VOL = 0.45
LEV_CAP = 1.0    # Conservative: no margin
VOL_WINDOW = 20


def main():
    print(f"Tushar v2 QQQ Signal (no-margin, conservative) Signal - {datetime.now().strftime('%Y-%m-%d')}")

    # Load QQQ
    qqq_df = _load(QQQ_TICKER)

    # Regime gate (v1 logic)
    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    # QQQ returns and vol
    qqq_ret = qqq_df["close"].pct_change().fillna(0.0)
    rv = (qqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()

    # Vol-targeted exposure (only in BULL regime)
    lev = (TARGET_VOL / rv).clip(0, LEV_CAP)
    exposure = (regime_pos * lev).clip(0, LEV_CAP)

    # Latest values
    latest_close = qqq_df["close"].iloc[-1]
    latest_high189 = sig["high252"].iloc[-1]
    latest_pcthi = sig["pcthi"].iloc[-1]
    latest_regime = "BUY_QQQ" if regime_pos.iloc[-1] == 1 else "CASH"
    latest_vol = rv.iloc[-1] * 100
    latest_exposure = exposure.iloc[-1]

    # Action vs yesterday
    if len(exposure) > 1:
        prev_exposure = exposure.iloc[-2]
        if prev_exposure == 0 and latest_exposure > 0:
            action = "ENTER BULL"
        elif prev_exposure > 0 and latest_exposure == 0:
            action = "EXIT TO CASH"
        elif latest_exposure > prev_exposure + 0.05:
            action = "LEVER UP"
        elif latest_exposure < prev_exposure - 0.05:
            action = "LEVER DOWN"
        else:
            action = "HOLD"
    else:
        action = "HOLD"

    # Display
    print(f"QQQ Close: ${latest_close:.2f}   189d High: ${latest_high189:.2f}   % Below High: {latest_pcthi:.1f}%")
    print(f"Regime: {latest_regime}   QQQ 20d Vol: {latest_vol:.0f}%")
    print(f"Target: Hold {latest_exposure:.2f}x QQQ   Action: {action}")

    # Log to CSV
    csv_path = "signals/tushar_v2_qqq_history.csv"
    try:
        df_log = pd.read_csv(csv_path)
        today_str = datetime.now().strftime("%Y-%m-%d")
        df_log = df_log[df_log["date"] != today_str]  # Remove today if exists (idempotent)
    except FileNotFoundError:
        df_log = pd.DataFrame(columns=["date", "qqq_close", "pcthi", "regime", "qqq_vol", "exposure", "action"])

    new_row = pd.DataFrame([{
        "date": datetime.now().strftime("%Y-%m-%d"),
        "qqq_close": latest_close,
        "pcthi": latest_pcthi,
        "regime": latest_regime,
        "qqq_vol": latest_vol,
        "exposure": latest_exposure,
        "action": action
    }])

    df_log = pd.concat([df_log, new_row], ignore_index=True)
    df_log.to_csv(csv_path, index=False)
    print(f"Logged to {csv_path}")


if __name__ == "__main__":
    main()
