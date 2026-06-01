"""
oliver_strategy.py — Oliver Kell Price Cycle Strategy applied to TQQQ

Based on the plan document OLIVER_KELL_PRICE_CYCLE_PLAN.md.
Uses QQQ as the regime indicator; trades TQQQ.

STRATEGY RULES
--------------
  EXIT (Wedge Drop):
    QQQ closes below its 20-day EMA for EXIT_DAYS consecutive days.

  ENTRY (Wedge Pop):
    QQQ closes above its 20-day EMA for REENTRY_DAYS consecutive days.

  Exhaustion Extension tracking (informational — not a hard exit):
    Each time QQQ extends >= EXT_THRESHOLD% above its 10-day EMA,
    count one "extension". Reset when price returns near 10 EMA.
    2nd extension = profit-taking warning; displayed in signal output.
    Extension count resets to 0 on every new CASH period.

  Weekly timeframe check (regime context):
    QQQ weekly 10 EMA computed from Friday closes.
    When close > weekly 10 EMA: tailwind. Below: headwind.

USAGE
-----
  python oliver_strategy.py                            # today's signal
  python oliver_strategy.py --backtest --all           # backtest all years
  python oliver_strategy.py --compare --all            # Oliver vs Tushar v1 vs TQQQ B&H
  python oliver_strategy.py --compare --all --start 2010-01-01
  python oliver_strategy.py --exit-days 2 --reentry-days 2 --compare --all
"""

import argparse
import math
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QQQ_TICKER      = "QQQ"
TQQQ_TICKER     = "TQQQ"
DEFAULT_CAPITAL = 100_000.0
DATA_START      = "2010-01-01"

EXIT_DAYS       = 2      # consecutive closes below 20 EMA → exit (Wedge Drop)
REENTRY_DAYS    = 2      # consecutive closes above 20 EMA → re-entry (Wedge Pop)
EXT_THRESHOLD   = 3.0    # % above 10 EMA to count as an "extension"
EXT_RESET       = 0.5    # % above 10 EMA at which we reset the "in extension" flag

# Mode names
MODE_EMA20     = "ema20"      # exit on N-day close below 20 EMA (simple)
MODE_WEDGEDROP = "wedgedrop"  # exit only after 2nd extension + 20 EMA loss, or 50 SMA loss
MODE_SMA50     = "sma50"      # exit on 50 SMA loss; entry on 20 EMA
MODE_ENHANCED  = "enhanced"   # v1 macro exit + Oliver Wedge Drop gated by pullback depth

# Enhanced mode: minimum pcthi to allow Wedge Drop exit
# In slow bull years QQQ stays < 5% below 252d high → exit suppressed (just an EMA Crossback)
# In real corrections (>5% below high) the Wedge Drop exit is allowed
WEDGEDROP_PCTHI = 5.0   # % below 252d high required for Wedge Drop to fire

# Tushar v1 constants (for comparison)
HIGH_PERIOD       = 252
SIGNAL_THRESHOLD  = 15.0
V1_REENTRY_DAYS   = 3

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load(ticker: str, start: str = DATA_START) -> pd.DataFrame:
    try:
        raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            raise ValueError("empty")
    except Exception:
        raw = yf.Ticker(ticker).history(start=start, auto_adjust=True)
    df = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                  for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


def _weekly_ema10(daily_df: pd.DataFrame) -> pd.Series:
    """Weekly 10 EMA using Friday-close resampling, forward-filled to daily."""
    wk = daily_df["close"].resample("W-FRI").last().dropna()
    wk_ema = wk.ewm(span=10, adjust=False).mean()
    return wk_ema.reindex(daily_df.index, method="ffill")


# ---------------------------------------------------------------------------
# Oliver Kell signal
# ---------------------------------------------------------------------------

def compute_signal_oliver(
    qqq_df: pd.DataFrame,
    exit_days: int    = EXIT_DAYS,
    reentry_days: int = REENTRY_DAYS,
    ext_threshold: float = EXT_THRESHOLD,
) -> pd.DataFrame:
    """
    Wedge Drop exit + Wedge Pop re-entry on QQQ, trading TQQQ.
    Exhaustion extension tracking is purely informational.
    """
    df = qqq_df.copy()
    df["ema10"]  = df["close"].ewm(span=10,  adjust=False).mean()
    df["ema20"]  = df["close"].ewm(span=20,  adjust=False).mean()
    df["sma50"]  = df["close"].rolling(50,  min_periods=1).mean()
    df["sma200"] = df["close"].rolling(200, min_periods=1).mean()
    df["ext_pct"] = (df["close"] - df["ema10"]) / df["ema10"] * 100
    df["w_ema10"] = _weekly_ema10(df)   # weekly 10 EMA for context

    close_arr  = df["close"].values
    ema10_arr  = df["ema10"].values
    ema20_arr  = df["ema20"].values
    wema10_arr = df["w_ema10"].values
    ext_arr    = df["ext_pct"].values

    regime_list  = []
    action_list  = []
    ext_cnt_list = []  # running extension count
    ext_warn_list= []  # True when 2nd+ extension active
    entry_list   = []
    exit_list    = []

    in_tqqq       = True
    prev_in       = False
    consec_above  = 0
    consec_below  = 0
    ext_count     = 0    # number of extensions from 10 EMA this trend
    in_ext        = False

    for i in range(len(df)):
        close  = float(close_arr[i])
        ema20  = float(ema20_arr[i])
        ext_pct = float(ext_arr[i])

        # Track consecutive closes above/below 20 EMA
        if close > ema20:
            consec_above += 1
            consec_below  = 0
        else:
            consec_below += 1
            consec_above  = 0

        # Extension counting (only while in TQQQ to track the current trend)
        if in_tqqq:
            if ext_pct >= ext_threshold and not in_ext:
                ext_count += 1
                in_ext = True
            elif ext_pct < EXT_RESET and in_ext:
                in_ext = False   # price came back to near 10 EMA

        # Wedge Drop exit: EXIT_DAYS consecutive closes below 20 EMA
        exit_sig = in_tqqq and (consec_below >= exit_days)

        # Wedge Pop entry: REENTRY_DAYS consecutive closes above 20 EMA
        entry_sig = (not in_tqqq) and (consec_above >= reentry_days)

        if exit_sig:
            in_tqqq   = False
            ext_count = 0
            in_ext    = False

        if entry_sig:
            in_tqqq = True

        act = ("BUY"  if (in_tqqq and not prev_in) else
               "SELL" if (not in_tqqq and prev_in) else "HOLD")

        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        ext_cnt_list.append(ext_count)
        ext_warn_list.append(ext_count >= 2)
        entry_list.append(entry_sig)
        exit_list.append(exit_sig)
        prev_in = in_tqqq

    df["regime"]   = regime_list
    df["action"]   = action_list
    df["ext_count"] = ext_cnt_list
    df["ext_warn"]  = ext_warn_list
    df["entry"]    = entry_list
    df["exit"]     = exit_list
    return df


# ---------------------------------------------------------------------------
# Oliver Kell signal — Wedge Drop mode (faithful to the book)
# ---------------------------------------------------------------------------

def compute_signal_oliver_wedgedrop(
    qqq_df: pd.DataFrame,
    exit_days: int       = EXIT_DAYS,
    reentry_days: int    = REENTRY_DAYS,
    ext_threshold: float = EXT_THRESHOLD,
) -> pd.DataFrame:
    """
    True Wedge Drop exit logic — matches Oliver Kell's description:

    EXIT A (Wedge Drop):  ext_count >= 2  AND  close < 20 EMA for exit_days
      → Had 2+ extensions from 10 EMA (euphoria), now reversing through 20 EMA
    EXIT B (50 SMA break): close < 50 SMA for exit_days
      → Major trend support lost regardless of extension count (bear market signal)
    HOLD on simple 20 EMA touch when ext_count < 2:
      → This is an EMA Crossback / Base n' Break — a buy/add signal, NOT a sell

    ENTRY (Wedge Pop): close > 20 EMA for reentry_days consecutive days
    """
    df = qqq_df.copy()
    df["ema10"]   = df["close"].ewm(span=10,  adjust=False).mean()
    df["ema20"]   = df["close"].ewm(span=20,  adjust=False).mean()
    df["sma50"]   = df["close"].rolling(50,  min_periods=1).mean()
    df["sma200"]  = df["close"].rolling(200, min_periods=1).mean()
    df["ext_pct"] = (df["close"] - df["ema10"]) / df["ema10"] * 100
    df["w_ema10"] = _weekly_ema10(df)

    close_arr  = df["close"].values
    ema20_arr  = df["ema20"].values
    sma50_arr  = df["sma50"].values
    ext_arr    = df["ext_pct"].values

    regime_list   = []
    action_list   = []
    ext_cnt_list  = []
    ext_warn_list = []
    entry_list    = []
    exit_list     = []
    exit_reason_list = []   # "wedgedrop" | "sma50" | ""

    in_tqqq       = True
    prev_in       = False
    consec_above  = 0
    consec_below_ema20 = 0
    consec_below_sma50 = 0
    ext_count     = 0
    in_ext        = False

    for i in range(len(df)):
        close   = float(close_arr[i])
        ema20   = float(ema20_arr[i])
        sma50   = float(sma50_arr[i])
        ext_pct = float(ext_arr[i])

        # Consecutive days above 20 EMA (for re-entry)
        if close > ema20:
            consec_above += 1
            consec_below_ema20 = 0
        else:
            consec_below_ema20 += 1
            consec_above = 0

        # Consecutive days below 50 SMA (for forced exit)
        if close < sma50:
            consec_below_sma50 += 1
        else:
            consec_below_sma50 = 0

        # Extension counting (only while in TQQQ)
        if in_tqqq:
            if ext_pct >= ext_threshold and not in_ext:
                ext_count += 1
                in_ext = True
            elif ext_pct < EXT_RESET and in_ext:
                in_ext = False

        # EXIT A: True Wedge Drop — 2+ extensions, now losing 20 EMA
        wedgedrop_exit = (in_tqqq and
                          ext_count >= 2 and
                          consec_below_ema20 >= exit_days)

        # EXIT B: 50 SMA break — forced exit regardless of extension count
        sma50_exit = (in_tqqq and consec_below_sma50 >= exit_days)

        exit_sig   = wedgedrop_exit or sma50_exit
        exit_reason = ("wedgedrop" if wedgedrop_exit else
                       "sma50"     if sma50_exit     else "")

        # ENTRY: Wedge Pop — N consecutive closes above 20 EMA
        entry_sig = (not in_tqqq) and (consec_above >= reentry_days)

        if exit_sig:
            in_tqqq   = False
            ext_count = 0
            in_ext    = False

        if entry_sig:
            in_tqqq = True

        act = ("BUY"  if (in_tqqq and not prev_in) else
               "SELL" if (not in_tqqq and prev_in) else "HOLD")

        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        ext_cnt_list.append(ext_count)
        ext_warn_list.append(ext_count >= 2)
        entry_list.append(entry_sig)
        exit_list.append(exit_sig)
        exit_reason_list.append(exit_reason)
        prev_in = in_tqqq

    df["regime"]      = regime_list
    df["action"]      = action_list
    df["ext_count"]   = ext_cnt_list
    df["ext_warn"]    = ext_warn_list
    df["entry"]       = entry_list
    df["exit"]        = exit_list
    df["exit_reason"] = exit_reason_list
    return df


# ---------------------------------------------------------------------------
# Oliver Kell signal — SMA50 mode (exit on 50 SMA, entry on 20 EMA)
# ---------------------------------------------------------------------------

def compute_signal_oliver_sma50(
    qqq_df: pd.DataFrame,
    exit_days: int    = EXIT_DAYS,
    reentry_days: int = REENTRY_DAYS,
) -> pd.DataFrame:
    """
    Exit: QQQ closes below 50 SMA for exit_days (major trend support lost).
    Entry: QQQ closes above 20 EMA for reentry_days (Wedge Pop).
    Fewer whipsaws than pure 20 EMA exit; more responsive than 252d high rule.
    """
    df = qqq_df.copy()
    df["ema10"]   = df["close"].ewm(span=10,  adjust=False).mean()
    df["ema20"]   = df["close"].ewm(span=20,  adjust=False).mean()
    df["sma50"]   = df["close"].rolling(50,  min_periods=1).mean()
    df["sma200"]  = df["close"].rolling(200, min_periods=1).mean()
    df["ext_pct"] = (df["close"] - df["ema10"]) / df["ema10"] * 100
    df["w_ema10"] = _weekly_ema10(df)

    close_arr  = df["close"].values
    ema20_arr  = df["ema20"].values
    sma50_arr  = df["sma50"].values
    ext_arr    = df["ext_pct"].values

    regime_list   = []
    action_list   = []
    ext_cnt_list  = []
    ext_warn_list = []
    entry_list    = []
    exit_list     = []

    in_tqqq      = True
    prev_in      = False
    consec_above = 0
    consec_below = 0
    ext_count    = 0
    in_ext       = False

    for i in range(len(df)):
        close   = float(close_arr[i])
        ema20   = float(ema20_arr[i])
        sma50   = float(sma50_arr[i])
        ext_pct = float(ext_arr[i])

        if close > ema20:
            consec_above += 1
            consec_below  = 0
        else:
            consec_above = 0

        if close < sma50:
            consec_below += 1
        else:
            consec_below = 0

        if in_tqqq:
            if ext_pct >= EXT_THRESHOLD and not in_ext:
                ext_count += 1
                in_ext = True
            elif ext_pct < EXT_RESET and in_ext:
                in_ext = False

        exit_sig  = in_tqqq and (consec_below >= exit_days)
        entry_sig = (not in_tqqq) and (consec_above >= reentry_days)

        if exit_sig:
            in_tqqq   = False
            ext_count = 0
            in_ext    = False
        if entry_sig:
            in_tqqq = True

        act = ("BUY"  if (in_tqqq and not prev_in) else
               "SELL" if (not in_tqqq and prev_in) else "HOLD")

        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        ext_cnt_list.append(ext_count)
        ext_warn_list.append(ext_count >= 2)
        entry_list.append(entry_sig)
        exit_list.append(exit_sig)
        prev_in = in_tqqq

    df["regime"]    = regime_list
    df["action"]    = action_list
    df["ext_count"] = ext_cnt_list
    df["ext_warn"]  = ext_warn_list
    df["entry"]     = entry_list
    df["exit"]      = exit_list
    return df


# ---------------------------------------------------------------------------
# Oliver Kell signal — Enhanced mode (v1 macro exit + gated Wedge Drop)
# ---------------------------------------------------------------------------

def compute_signal_oliver_enhanced(
    qqq_df: pd.DataFrame,
    exit_days: int       = EXIT_DAYS,
    reentry_days: int    = REENTRY_DAYS,
    ext_threshold: float = EXT_THRESHOLD,
    v1_thresh: float     = SIGNAL_THRESHOLD,
    wedgedrop_pcthi: float = WEDGEDROP_PCTHI,
) -> pd.DataFrame:
    """
    Enhanced Oliver: v1's proven macro exit + Oliver's faster Wedge Pop re-entry.

    EXIT: v1 rule — exit immediately when pcthi >= v1_thresh (15% below 252d high).
          This is the only exit. No wedgedrop, no 50 SMA — v1's exit is already excellent.

    RE-ENTRY (context-adaptive):
      If pcthi has been < v1_thresh for >= V1_REENTRY_DAYS days (v1 macro condition met)
      AND close is above 20 EMA for >= reentry_days (Oliver Wedge Pop confirmed):
          → Re-enter.  Both conditions required to prevent bear-bounce traps.
      This gives us:
        - v1's filter against re-entering during deep downtrends (pcthi still > 15%)
        - Oliver's faster timing within the recovery window (Wedge Pop vs 3-day dip count)

    Result vs v1: same exits, potentially faster re-entry in sharp V-recoveries (2020, 2023).
    Vs old Oliver (wedgedrop/ema20): eliminates all the slow-bull and bear-bounce whipsaws.
    """
    df = qqq_df.copy()
    df["ema10"]   = df["close"].ewm(span=10,  adjust=False).mean()
    df["ema20"]   = df["close"].ewm(span=20,  adjust=False).mean()
    df["sma50"]   = df["close"].rolling(50,  min_periods=1).mean()
    df["sma200"]  = df["close"].rolling(200, min_periods=1).mean()
    df["ext_pct"] = (df["close"] - df["ema10"]) / df["ema10"] * 100
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100
    df["w_ema10"] = _weekly_ema10(df)

    close_arr  = df["close"].values
    ema20_arr  = df["ema20"].values
    ext_arr    = df["ext_pct"].values
    pcthi_arr  = df["pcthi"].values

    regime_list      = []
    action_list      = []
    ext_cnt_list     = []
    ext_warn_list    = []
    entry_list       = []
    exit_list        = []
    exit_reason_list = []

    in_tqqq       = True
    prev_in       = False
    consec_above  = 0
    ext_count     = 0
    in_ext        = False
    days_v1_below = 0   # consecutive days where pcthi < v1_thresh

    for i in range(len(df)):
        close   = float(close_arr[i])
        ema20   = float(ema20_arr[i])
        ext_pct = float(ext_arr[i])
        pcthi   = float(pcthi_arr[i])

        # Consecutive closes above 20 EMA (for Oliver Wedge Pop re-entry check)
        if close > ema20:
            consec_above += 1
        else:
            consec_above = 0

        # v1-style day counter: resets when pcthi climbs back >= v1_thresh
        if pcthi < v1_thresh:
            days_v1_below += 1
        else:
            days_v1_below = 0

        # Extension counting (only while invested)
        if in_tqqq:
            if ext_pct >= ext_threshold and not in_ext:
                ext_count += 1
                in_ext = True
            elif ext_pct < EXT_RESET and in_ext:
                in_ext = False

        # ── EXIT: v1 macro rule only ──────────────────────────────────────────
        exit_sig    = in_tqqq and (pcthi >= v1_thresh)
        exit_reason = "macro" if exit_sig else ""

        # ── ENTRY: Oliver Wedge Pop gated by v1 macro condition ───────────────
        # Both must be satisfied:
        #   1. v1 gate: pcthi < v1_thresh for >= V1_REENTRY_DAYS (market macro recovery)
        #   2. Oliver : close > 20 EMA for >= reentry_days (Wedge Pop momentum)
        # Together they require the market to have genuinely recovered from the drawdown
        # (pcthi filter) AND be showing upside momentum (EMA filter).
        # This prevents dead-cat-bounce entries while still catching sharp V-recoveries
        # earlier than v1's pure 3-day pcthi count.
        v1_gate     = days_v1_below >= V1_REENTRY_DAYS
        oliver_gate = consec_above  >= reentry_days
        entry_sig   = (not in_tqqq) and v1_gate and oliver_gate

        if exit_sig:
            in_tqqq   = False
            ext_count = 0
            in_ext    = False

        if entry_sig:
            in_tqqq = True

        act = ("BUY"  if (in_tqqq and not prev_in) else
               "SELL" if (not in_tqqq and prev_in) else "HOLD")

        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        ext_cnt_list.append(ext_count)
        ext_warn_list.append(ext_count >= 2)
        entry_list.append(entry_sig)
        exit_list.append(exit_sig)
        exit_reason_list.append(exit_reason)
        prev_in = in_tqqq

    df["regime"]      = regime_list
    df["action"]      = action_list
    df["ext_count"]   = ext_cnt_list
    df["ext_warn"]    = ext_warn_list
    df["entry"]       = entry_list
    df["exit"]        = exit_list
    df["exit_reason"] = exit_reason_list
    return df


# ---------------------------------------------------------------------------
# Tushar v1 signal (for comparison)
# ---------------------------------------------------------------------------

def compute_signal_v1(qqq_df: pd.DataFrame) -> pd.DataFrame:
    df = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100

    regime_list, days_list, action_list = [], [], []
    days_below = 0
    in_tqqq    = True
    prev_in    = False

    for pcthi in df["pcthi"]:
        if pcthi >= SIGNAL_THRESHOLD:
            days_below = 0
            in_tqqq    = False
        else:
            days_below += 1
            if days_below >= V1_REENTRY_DAYS:
                in_tqqq = True

        act = ("BUY"  if (in_tqqq and not prev_in) else
               "SELL" if (not in_tqqq and prev_in) else "HOLD")
        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        days_list.append(days_below)
        action_list.append(act)
        prev_in = in_tqqq

    df["regime"]     = regime_list
    df["days_below"] = days_list
    df["action"]     = action_list
    return df


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def _price_on(df: pd.DataFrame, dt) -> float | None:
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest(sig_df: pd.DataFrame, price_df: pd.DataFrame,
                 capital: float) -> list[dict]:
    shares  = 0
    cash    = capital
    daily   = []
    prev_in = False

    for dt, row in sig_df.iterrows():
        p = _price_on(price_df, dt)
        if p is None:
            continue
        in_pos = (row["regime"] == "BUY_TQQQ")

        if in_pos and not prev_in:
            ns    = math.floor(cash / p) if p > 0 else 0
            cash -= ns * p
            shares = ns
        elif not in_pos and prev_in:
            cash  += shares * p
            shares = 0

        prev_in = in_pos
        port    = round(shares * p + cash, 2)
        daily.append({
            "date":       dt,
            "portfolio":  port,
            "regime":     row["regime"],
            "action":     row["action"],
            "close":      float(row.get("close", p)),
            "tqqq_close": p,
            "entry":      bool(row.get("entry", False)),
            "exit":       bool(row.get("exit",  False)),
            "ext_count":  int(row.get("ext_count", 0)),
            "ext_warn":   bool(row.get("ext_warn", False)),
        })
    return daily


def run_buyhold(price_df: pd.DataFrame, capital: float) -> list[dict]:
    shares = 0
    cash   = capital
    daily  = []
    for i, (dt, row) in enumerate(price_df.iterrows()):
        p = float(row["close"])
        if i == 0:
            shares = math.floor(cash / p) if p > 0 else 0
            cash  -= shares * p
        daily.append({"date": dt, "portfolio": round(shares * p + cash, 2),
                      "regime": "BUY_TQQQ", "action": "HOLD",
                      "close": p, "tqqq_close": p,
                      "entry": False, "exit": False,
                      "ext_count": 0, "ext_warn": False})
    return daily


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _ticker_monthly_rets(df: pd.DataFrame) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d, row in df.iterrows():
        bm[(d.year, d.month)].append(float(row["close"]))
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(v: float | None, w: int = 8) -> str:
    if v is None:
        return "N/A".rjust(w)
    s = "+" if v >= 0 else ""
    return f"{s}{v:.1f}%".rjust(w)


def _diff(a, b, w: int = 9) -> str:
    if a is None or b is None:
        return "N/A".rjust(w)
    v = a - b
    return (("+" if v >= 0 else "") + f"{v:.1f}%").rjust(w)


def _cagr(final: float, capital: float, n_yr: float) -> float:
    if n_yr <= 0 or final <= 0:
        return 0.0
    return round(((final / capital) ** (1 / n_yr) - 1) * 100, 1)


def _max_dd(daily: list[dict]) -> float:
    """Maximum drawdown from peak portfolio value."""
    peak = daily[0]["portfolio"]
    max_dd = 0.0
    for d in daily:
        p = d["portfolio"]
        if p > peak:
            peak = p
        dd = (p - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
    return round(max_dd, 1)


def _n_trades(daily: list[dict]) -> int:
    return sum(1 for d in daily if d["exit"])


# ---------------------------------------------------------------------------
# Comparison report: TQQQ B&H | Tushar v1 | Oliver
# ---------------------------------------------------------------------------

def print_comparison(
    daily_oliv: list[dict],
    daily_v1:   list[dict],
    daily_tbh:  list[dict],
    qqq_df:     pd.DataFrame,
    tqqq_df:    pd.DataFrame,
    years:      list[int],
    capital:    float,
    exit_days:  int,
    reentry_days: int,
    mode: str = MODE_ENHANCED,
) -> None:
    r_oliv = _monthly_rets(daily_oliv)
    r_v1   = _monthly_rets(daily_v1)
    r_tbh  = _monthly_rets(daily_tbh)
    r_q    = _ticker_monthly_rets(qqq_df)

    W   = 94
    SEP = "=" * W
    DIV = "-" * W

    cum_tbh  = capital
    cum_v1   = capital
    cum_oliv = capital

    print(f"\n{SEP}")
    print(f"  COMPARISON: TQQQ B&H | Tushar v1 | Oliver Kell Strategy")
    print(f"  Oliver mode: {_mode_label(mode, exit_days, reentry_days)}")
    print(f"  Extension warning fires on 2nd extension from 10 EMA (informational)")
    print(f"  Capital: ${capital:,.0f}")
    print(SEP)

    yr_totals = []
    all_years = sorted(set(ym[0] for ym in r_v1 if ym[0] in years))

    for year in all_years:
        months = sorted(ym for ym in r_v1 if ym[0] == year)
        if not months:
            continue

        ytbh0  = cum_tbh
        yv10   = cum_v1
        yoliv0 = cum_oliv

        yr_e = sum(1 for d in daily_oliv if d.get("entry") and d["date"].year == year)
        yr_x = sum(1 for d in daily_oliv if d.get("exit")  and d["date"].year == year)
        yr_w = sum(1 for d in daily_oliv if d.get("ext_warn") and d["date"].year == year
                   and d["regime"] == "BUY_TQQQ")

        print(f"\n  -- {year} {'-'*68}")
        print(f"  {'Month':<7} {'TQQQ B&H':>9}  {'Tushar v1':>10}  {'Oliver':>8}  "
              f"{'Oliv-v1':>8}  Notes")
        print(DIV)

        for ym in months:
            m   = ym[1]
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)
            oliv = r_oliv.get(ym)

            if tbh:  cum_tbh  *= 1 + tbh  / 100
            if v1:   cum_v1   *= 1 + v1   / 100
            if oliv: cum_oliv *= 1 + oliv / 100

            me = sum(1 for d in daily_oliv
                     if d.get("entry") and d["date"].year == ym[0] and d["date"].month == ym[1])
            mx = sum(1 for d in daily_oliv
                     if d.get("exit")  and d["date"].year == ym[0] and d["date"].month == ym[1])
            mw = sum(1 for d in daily_oliv
                     if d.get("ext_warn") and d["regime"] == "BUY_TQQQ"
                     and d["date"].year == ym[0] and d["date"].month == ym[1])
            notes = (("" + (f" E{me}" if me else "") +
                      (f" X{mx}" if mx else "") +
                      (f" W{mw}d" if mw else "")))

            print(f"  {MONTHS[m]:<7} {_fmt(tbh):>9}  {_fmt(v1):>10}  "
                  f"{_fmt(oliv):>8}  {_diff(oliv, v1, 8):>8}  {notes}")

        fy_tbh  = round((cum_tbh  / ytbh0  - 1) * 100, 1)
        fy_v1   = round((cum_v1   / yv10   - 1) * 100, 1)
        fy_oliv = round((cum_oliv / yoliv0 - 1) * 100, 1)
        yr_totals.append((year, fy_tbh, fy_v1, fy_oliv, yr_e, yr_x))

        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_tbh):>9}  {_fmt(fy_v1):>10}  "
              f"{_fmt(fy_oliv):>8}  {_diff(fy_oliv, fy_v1, 8):>8}  E{yr_e} X{yr_x}")

    if len(all_years) > 1:
        print(f"\n{SEP}")
        print(f"  ANNUAL SUMMARY")
        print(DIV)
        print(f"  {'Year':<7} {'TQQQ B&H':>9}  {'Tushar v1':>10}  {'Oliver':>8}  {'Oliv-v1':>8}")
        print(DIV)
        for y, tbh, v1, oliv, e, x in yr_totals:
            print(f"  {str(y):<7} {_fmt(tbh):>9}  {_fmt(v1):>10}  "
                  f"{_fmt(oliv):>8}  {_diff(oliv, v1, 8):>8}  E{e} X{x}")
        print(DIV)

        n_yr = ((date.today().year - all_years[0]) +
                (date.today().month - 1) / 12 + (date.today().day - 1) / 365)

        ov_tbh  = round((cum_tbh  / capital - 1) * 100, 1)
        ov_v1   = round((cum_v1   / capital - 1) * 100, 1)
        ov_oliv = round((cum_oliv / capital - 1) * 100, 1)

        cagr_tbh  = _cagr(cum_tbh,  capital, n_yr)
        cagr_v1   = _cagr(cum_v1,   capital, n_yr)
        cagr_oliv = _cagr(cum_oliv, capital, n_yr)

        dd_tbh  = _max_dd(daily_tbh)
        dd_v1   = _max_dd(daily_v1)
        dd_oliv = _max_dd(daily_oliv)

        n_ex_oliv = _n_trades(daily_oliv)
        n_ex_v1   = _n_trades(daily_v1)

        print(f"  {'Total %':<7} {_fmt(ov_tbh):>9}  {_fmt(ov_v1):>10}  "
              f"{_fmt(ov_oliv):>8}  {_diff(ov_oliv, ov_v1, 8):>8}")
        print(f"  {'CAGR':<7} {_fmt(cagr_tbh):>9}  {_fmt(cagr_v1):>10}  "
              f"{_fmt(cagr_oliv):>8}  {_diff(cagr_oliv, cagr_v1, 8):>8}")
        print(f"  {'Max DD':<7} {_fmt(dd_tbh):>9}  {_fmt(dd_v1):>10}  "
              f"{_fmt(dd_oliv):>8}")
        print(f"  {'Exits':<7} {'N/A':>9}  {n_ex_v1:>10}  {n_ex_oliv:>8}")
        print(f"\n  Final values:  TQQQ B&H ${cum_tbh:,.0f}  |  "
              f"Tushar v1 ${cum_v1:,.0f}  |  Oliver ${cum_oliv:,.0f}")
        print(SEP)

    # Entry/exit event log for Oliver
    events = ([(d["date"], "ENTRY", d["tqqq_close"]) for d in daily_oliv if d.get("entry")] +
              [(d["date"], "EXIT",  d["tqqq_close"]) for d in daily_oliv if d.get("exit")])
    if events:
        n_e = sum(1 for _, t, _ in events if t == "ENTRY")
        n_x = sum(1 for _, t, _ in events if t == "EXIT")
        print(f"\n  OLIVER ENTRY/EXIT LOG  ({n_e} entries, {n_x} exits)")
        print(f"  {'Date':<12}  {'Type':<6}  {'TQQQ':>10}  {'Ext#':>5}")
        print(f"  {'-'*40}")
        ext_count_map = {d["date"]: d["ext_count"] for d in daily_oliv}
        for dt, typ, p in sorted(events):
            ec = ext_count_map.get(dt, 0)
            print(f"  {str(dt.date()):<12}  {typ:<6}  ${p:>9.2f}  {ec:>5}")
    print()


# ---------------------------------------------------------------------------
# Single-strategy backtest report
# ---------------------------------------------------------------------------

def print_backtest(daily: list[dict], qqq_df: pd.DataFrame,
                   years: list[int], capital: float,
                   exit_days: int, reentry_days: int) -> None:
    ts_r  = _monthly_rets(daily)
    qqq_r = _ticker_monthly_rets(qqq_df)

    W   = 62
    SEP = "=" * W
    DIV = "-" * W

    cum_q  = capital
    cum_ts = capital

    print(f"\n{SEP}")
    print(f"  Oliver Kell Strategy  —  Backtest  |  Capital: ${capital:,.0f}")
    print(f"  Exit: {exit_days}d below 20 EMA  |  Entry: {reentry_days}d above 20 EMA")
    print(f"  Extension warning: 2nd+ extension from 10 EMA (W flag)")
    print(SEP)

    yr_totals = []
    all_years = sorted(set(ym[0] for ym in ts_r if ym[0] in years))

    for year in all_years:
        months_in = sorted(ym for ym in ts_r if ym[0] == year)
        if not months_in:
            continue
        yq0 = cum_q
        yt0 = cum_ts
        print(f"\n  -- {year} {'-'*44}")
        print(f"  {'Month':<7}  {'QQQ':>8}  {'Oliver':>9}  {'Regime':<10}  Notes")
        print(DIV)
        for ym in months_in:
            m  = ym[1]
            q  = qqq_r.get(ym)
            ts = ts_r.get(ym)

            # Regime label for the month
            regime_days = [d for d in daily
                           if d["date"].year == ym[0] and d["date"].month == ym[1]]
            in_days  = sum(1 for d in regime_days if d["regime"] == "BUY_TQQQ")
            out_days = len(regime_days) - in_days
            regime_lbl = ("TQQQ" if in_days > out_days else
                          "CASH" if out_days > in_days else "MIX")

            # Extension warning days
            warn_days = sum(1 for d in regime_days if d.get("ext_warn"))
            me = sum(1 for d in regime_days if d.get("entry"))
            mx = sum(1 for d in regime_days if d.get("exit"))
            notes = (("" + (f" E{me}" if me else "") +
                      (f" X{mx}" if mx else "") +
                      (f" W{warn_days}d" if warn_days else "")))

            if q:  cum_q  *= 1 + q  / 100
            if ts: cum_ts *= 1 + ts / 100
            print(f"  {MONTHS[m]:<7}  {_fmt(q):>8}  {_fmt(ts):>9}  {regime_lbl:<10}  {notes}")

        fy_q  = round((cum_q  / yq0 - 1) * 100, 1)
        fy_ts = round((cum_ts / yt0 - 1) * 100, 1)
        yr_totals.append((year, fy_q, fy_ts))
        print(DIV)
        print(f"  {'FY '+str(year):<7}  {_fmt(fy_q):>8}  {_fmt(fy_ts):>9}")

    if len(all_years) > 1:
        print(f"\n{SEP}")
        print(f"  ANNUAL SUMMARY")
        print(DIV)
        print(f"  {'Year':<7}  {'QQQ':>8}  {'Oliver':>9}")
        print(DIV)
        for y, q, ts in yr_totals:
            print(f"  {str(y):<7}  {_fmt(q):>8}  {_fmt(ts):>9}")
        print(DIV)
        n_yr = ((date.today().year - all_years[0]) +
                (date.today().month - 1) / 12 + (date.today().day - 1) / 365)
        cagr = round(((cum_ts / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 else 0.0
        print(f"  {'CAGR':<7}  {'':>8}  {_fmt(cagr):>9}")
        print(f"  {'Max DD':<7}  {'':>8}  {_fmt(_max_dd(daily)):>9}")
        print(f"  {'Exits':<7}  {'':>8}  {_n_trades(daily):>9}")
        print(f"  Final value: ${cum_ts:>14,.0f}")
        print(SEP)
    print()


# ---------------------------------------------------------------------------
# Daily signal
# ---------------------------------------------------------------------------

def print_daily_signal(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame,
                       exit_days: int, reentry_days: int,
                       mode: str = MODE_ENHANCED) -> None:
    row        = sig_df.iloc[-1]
    today      = sig_df.index[-1].date()
    qqq_close  = float(row["close"])
    ema10      = float(row["ema10"])
    ema20      = float(row["ema20"])
    sma50      = float(row["sma50"])
    sma200     = float(row["sma200"])
    ext_pct    = float(row["ext_pct"])
    ext_count  = int(row["ext_count"])
    ext_warn   = bool(row["ext_warn"])
    w_ema10    = float(row["w_ema10"])
    regime     = row["regime"]
    action     = row["action"]
    tqqq_close = float(tqqq_df.iloc[-1]["close"]) if not tqqq_df.empty else 0.0
    pcthi      = float(row.get("pcthi", 0.0))
    high252    = float(row.get("high252", qqq_close))

    W   = 64
    SEP = "=" * W
    DIV = "-" * W

    def indicator_bar(val, ref, label):
        diff = (val - ref) / ref * 100
        marker = (">" if val > ref else "<")
        return f"  {label:<18} ${val:>8.2f}   {marker}EMA  {diff:>+.1f}%"

    print(f"\n{SEP}")
    print(f"  OLIVER KELL STRATEGY  —  Daily Signal")
    print(f"  {today.strftime('%A, %B %d, %Y')}")
    print(SEP)

    print(f"\n  QQQ Close:       ${qqq_close:>8.2f}")
    print(f"  10-day EMA:      ${ema10:>8.2f}   ext: {ext_pct:>+.1f}%"
          + ("  *** 2ND EXTENSION WARNING ***" if ext_warn else ""))
    print(f"  20-day EMA:      ${ema20:>8.2f}   {'ABOVE' if qqq_close > ema20 else 'BELOW  <<'}")
    print(f"  50-day SMA:      ${sma50:>8.2f}   {'above' if qqq_close > sma50  else 'BELOW'}")
    print(f"  200-day SMA:     ${sma200:>8.2f}   {'above' if qqq_close > sma200 else 'BELOW'}")
    print(f"  Wkly 10 EMA:     ${w_ema10:>8.2f}   {'above' if qqq_close > w_ema10 else 'BELOW'}")
    if mode == MODE_ENHANCED:
        exit_gap = SIGNAL_THRESHOLD - pcthi
        print(f"  252d High:       ${high252:>8.2f}   pcthi: {pcthi:>+.1f}%  "
              + (f"exit trigger at -{SIGNAL_THRESHOLD}%  ({exit_gap:.1f}% margin)"
                 if exit_gap > 0 else "  *** EXIT ZONE ***"))
    print(f"  Extension count: {ext_count}  (2+ = profit-taking warning active)")
    print(f"  TQQQ Close:      ${tqqq_close:>8.2f}")

    print()
    print(f"  CYCLE STAGE:")
    if qqq_close > ema20:
        if ext_count == 0:
            print(f"    Wedge Pop / EMA Crossback zone — early trend")
        elif ext_count == 1:
            print(f"    Base n' Break zone — trend is running")
        else:
            print(f"    *** EXHAUSTION EXTENSION #{ext_count} — consider profit taking ***")
    else:
        print(f"    Below 20 EMA — WEDGE DROP / CASH phase")
        if qqq_close > sma200:
            print(f"    (Above 200 SMA — intermediate correction, not bear market)")
        else:
            print(f"    (Below 200 SMA — potential bear market — heightened caution)")

    print()
    print(DIV)
    if action == "BUY":
        print(f"  ACTION:  *** BUY TQQQ ***   (Wedge Pop: {reentry_days}d above 20 EMA confirmed)")
    elif action == "SELL":
        print(f"  ACTION:  *** SELL TQQQ ***  (Wedge Drop: {exit_days}d below 20 EMA confirmed)")
    else:
        if regime == "BUY_TQQQ":
            if ext_warn:
                print(f"  ACTION:  HOLD TQQQ — but 2nd extension active; consider partial profit")
            else:
                print(f"  ACTION:  HOLD TQQQ  (trend intact above 20 EMA)")
        else:
            print(f"  ACTION:  STAY CASH  (below 20 EMA — wait for Wedge Pop)")
    print(DIV)

    print(f"\n  Recent history (last 10 trading days):")
    print(f"  {'Date':<12} {'QQQ':>8} {'10EMA':>8} {'20EMA':>8} {'Ext%':>6} {'Ext#':>4} "
          f"{'Regime':<10} Action")
    print(f"  {'-'*72}")
    for ts, r in sig_df.tail(10).iterrows():
        marker = " <--" if ts == sig_df.index[-1] else ""
        ep = float(r["ext_pct"])
        ec = int(r["ext_count"])
        print(f"  {str(ts.date()):<12} {float(r['close']):>8.2f} "
              f"{float(r['ema10']):>8.2f} {float(r['ema20']):>8.2f} "
              f"{ep:>+6.1f}% {ec:>4}  {r['regime']:<10} {r['action']}{marker}")
    print(SEP)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _get_signal(mode: str, qqq_df, exit_days, reentry_days, ext_threshold):
    """Dispatch to the right signal function by mode."""
    if mode == MODE_WEDGEDROP:
        return compute_signal_oliver_wedgedrop(qqq_df, exit_days, reentry_days, ext_threshold)
    elif mode == MODE_SMA50:
        return compute_signal_oliver_sma50(qqq_df, exit_days, reentry_days)
    elif mode == MODE_ENHANCED:
        return compute_signal_oliver_enhanced(qqq_df, exit_days, reentry_days, ext_threshold)
    else:  # MODE_EMA20 (default)
        return compute_signal_oliver(qqq_df, exit_days, reentry_days, ext_threshold)


def _mode_label(mode, exit_days, reentry_days):
    if mode == MODE_WEDGEDROP:
        return (f"wedgedrop: exit after 2nd ext + {exit_days}d below 20EMA, "
                f"or {exit_days}d below 50SMA | entry {reentry_days}d above 20EMA")
    elif mode == MODE_SMA50:
        return f"sma50: exit {exit_days}d below 50SMA | entry {reentry_days}d above 20EMA"
    elif mode == MODE_ENHANCED:
        return (f"enhanced: macro exit at {SIGNAL_THRESHOLD}% below 252d high "
                f"OR wedgedrop (ext>=2, {exit_days}d<20EMA, pcthi>={WEDGEDROP_PCTHI}%) "
                f"| entry {reentry_days}d above 20EMA")
    else:
        return f"ema20: exit {exit_days}d below 20EMA | entry {reentry_days}d above 20EMA"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Oliver Kell Price Cycle Strategy on TQQQ")
    ap.add_argument("--capital",       type=float, default=DEFAULT_CAPITAL)
    ap.add_argument("--backtest",      action="store_true")
    ap.add_argument("--compare",       action="store_true",
                    help="Oliver vs Tushar v1 vs TQQQ B&H")
    ap.add_argument("--year",          type=int,   default=None)
    ap.add_argument("--all",           action="store_true")
    ap.add_argument("--start",         default=DATA_START)
    ap.add_argument("--mode",          default=MODE_ENHANCED,
                    choices=[MODE_EMA20, MODE_WEDGEDROP, MODE_SMA50, MODE_ENHANCED],
                    help=(f"Exit rule: enhanced (v1 macro + gated wedgedrop) | "
                          f"wedgedrop (2nd ext + 20EMA loss OR 50SMA loss) | "
                          f"sma50 (N-day close<50SMA) | "
                          f"ema20 (N-day close<20EMA). Default: {MODE_ENHANCED}"))
    ap.add_argument("--exit-days",     type=int,   default=EXIT_DAYS)
    ap.add_argument("--reentry-days",  type=int,   default=REENTRY_DAYS)
    ap.add_argument("--ext-threshold", type=float, default=EXT_THRESHOLD,
                    help=f"Pct above 10 EMA to count as extension (default: {EXT_THRESHOLD})")
    args = ap.parse_args()

    print("\nLoading QQQ and TQQQ data...")
    qqq_df  = _load(QQQ_TICKER,  args.start)
    tqqq_df = _load(TQQQ_TICKER, args.start)

    start_year = int(args.start[:4])
    label = _mode_label(args.mode, args.exit_days, args.reentry_days)

    if args.compare:
        print(f"Computing signals ({label})...")
        sig_oliv = _get_signal(args.mode, qqq_df,
                               args.exit_days, args.reentry_days, args.ext_threshold)
        sig_v1   = compute_signal_v1(qqq_df)

        common   = sig_oliv.index.intersection(sig_v1.index)
        sig_oliv = sig_oliv.loc[common]
        sig_v1   = sig_v1.loc[common]
        tqqq_al  = tqqq_df.loc[tqqq_df.index.intersection(common)]
        qqq_al   = qqq_df.loc[qqq_df.index.intersection(common)]

        print("Running backtests...")
        daily_oliv = run_backtest(sig_oliv, tqqq_al, args.capital)
        daily_v1   = run_backtest(sig_v1,   tqqq_al, args.capital)
        daily_tbh  = run_buyhold(tqqq_al,            args.capital)

        if args.all:
            years = sorted(set(d["date"].year for d in daily_v1
                               if d["date"].year >= start_year))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]

        print_comparison(daily_oliv, daily_v1, daily_tbh,
                         qqq_al, tqqq_al, years,
                         args.capital, args.exit_days, args.reentry_days, args.mode)

    elif args.backtest:
        print(f"Computing signal ({label})...")
        sig_oliv = _get_signal(args.mode, qqq_df,
                               args.exit_days, args.reentry_days, args.ext_threshold)
        daily    = run_backtest(sig_oliv, tqqq_df, args.capital)

        if args.all:
            years = sorted(set(d["date"].year for d in daily
                               if d["date"].year >= start_year))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]

        print_backtest(daily, qqq_df, years, args.capital,
                       args.exit_days, args.reentry_days)

    else:
        print("Computing signal...")
        sig_oliv = _get_signal(args.mode, qqq_df,
                               args.exit_days, args.reentry_days, args.ext_threshold)
        print_daily_signal(sig_oliv, tqqq_df, args.exit_days, args.reentry_days, args.mode)


if __name__ == "__main__":
    main()
