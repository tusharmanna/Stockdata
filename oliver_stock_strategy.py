"""
oliver_stock_strategy.py — Oliver Kell Price Cycle Strategy for Any Stock

Applies Oliver Kell's "Victory in Stock Trading" price cycle framework to
individual stocks. Identifies the current cycle stage, generates actionable
signals, calculates stops, and flags market regime context via QQQ.

PRICE CYCLE STAGES
------------------
  Uptrend:   Reversal Extension → Wedge Pop → EMA Crossback → Base n' Break → Exhaustion Extension
  Downtrend: Exhaustion Extension → Wedge Drop → EMA Crossback → Base n' Break → Reversal Extension

SIGNALS
-------
  BUY        Wedge Pop (crossed above 20 EMA from below)
  ADD        EMA Crossback (pulled back to 10/20 EMA in uptrend and held)
  BUY/ADD    Base n' Break (breakout above consolidation high on volume)
  REDUCE     Exhaustion Extension #2+ (extended from 10 EMA — take partial profits)
  SELL       Wedge Drop (closed below 20 EMA after being above it)
  WATCH      Reversal Extension (bottoming process — wait for Wedge Pop)
  HOLD       Uptrend intact, no actionable signal
  CASH       Below 20 EMA, no setup present

USAGE
-----
  python oliver_stock_strategy.py AAPL
  python oliver_stock_strategy.py NVDA --start 2023-01-01
  python oliver_stock_strategy.py AAPL MSFT NVDA TSLA AMZN
  python oliver_stock_strategy.py --watchlist custom_watchlist.txt
"""

import argparse
import math
import sys
from datetime import date, datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_START       = "2022-01-01"   # default history start for scan/signal mode
BACKTEST_START   = "2015-01-01"   # default history start for backtest mode
REGIME_TICKER    = "QQQ"          # market regime indicator

EXT_THRESHOLD    = 5.0    # % above 10 EMA = Exhaustion Extension
EXT_BELOW_THRESH = -8.0   # % below 10 EMA = Reversal Extension zone
EXT_RESET        = 1.0    # % above 10 EMA where in-extension flag resets

CROSSBACK_RANGE  = 2.5    # % from 10 or 20 EMA to qualify as EMA Crossback
WEDGE_POP_LOOKBACK = 15   # days to look back for "was below 20 EMA" check

BASE_MIN_DAYS    = 8      # minimum days of consolidation for a base
BASE_MAX_DAYS    = 60     # maximum lookback for base detection
BASE_MAX_RANGE   = 12.0   # max % range (high-to-low) for tight consolidation
VOLUME_SPIKE     = 1.5    # volume multiplier to confirm a breakout

RS_DAYS          = 20     # days for relative strength calculation vs QQQ
ADX_PERIOD       = 14     # ADX lookback period
ADX_TREND_MIN    = 20     # default ADX threshold — below = choppy, skip entries

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Stage labels
# ---------------------------------------------------------------------------
STAGE_REVERSAL_EXT  = "Reversal Extension"   # bottoming — extended below, watch for pop
STAGE_WEDGE_POP     = "Wedge Pop"            # BUY — just crossed above 20 EMA
STAGE_EMA_CROSSBACK = "EMA Crossback"        # ADD — pulling back to EMA in uptrend
STAGE_BASE          = "In Base"              # consolidating above EMAs — watch for break
STAGE_BASE_BREAK    = "Base n' Break"        # BUY — breaking out of base on volume
STAGE_EXTENSION     = "Extension"            # REDUCE — extended from 10 EMA
STAGE_WEDGE_DROP    = "Wedge Drop"           # SELL — lost 20 EMA after being above it
STAGE_UPTREND       = "Uptrend"              # HOLD — above EMAs, no actionable signal
STAGE_DOWNTREND     = "Downtrend"            # CASH — below 20 EMA, bearish


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
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            raise ValueError(f"Missing column '{col}' for {ticker}")
    return df[["open", "high", "low", "close", "volume"]]


def _weekly_ema10(daily_df: pd.DataFrame) -> pd.Series:
    wk = daily_df["close"].resample("W-FRI").last().dropna()
    return wk.ewm(span=10, adjust=False).mean().reindex(daily_df.index, method="ffill")


# ---------------------------------------------------------------------------
# Indicator computation
# ---------------------------------------------------------------------------

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema10"]    = df["close"].ewm(span=10,  adjust=False).mean()
    df["ema20"]    = df["close"].ewm(span=20,  adjust=False).mean()
    df["sma50"]    = df["close"].rolling(50,  min_periods=1).mean()
    df["sma200"]   = df["close"].rolling(200, min_periods=1).mean()
    df["vol_avg20"]= df["volume"].rolling(20, min_periods=1).mean()
    df["ext_pct"]  = (df["close"] - df["ema10"]) / df["ema10"] * 100
    df["w_ema10"]  = _weekly_ema10(df)
    df["atr"]      = _atr(df, 14)
    adx, plus_di, minus_di = _adx_calc(df)
    df["adx"]      = adx
    df["di_plus"]  = plus_di
    df["di_minus"] = minus_di
    return df


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _adx_calc(df: pd.DataFrame, n: int = ADX_PERIOD):
    """Compute ADX, +DI, -DI using Wilder smoothing."""
    high       = df["high"]
    low        = df["low"]
    prev_close = df["close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move   = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm  = pd.Series(
        np.where((up_move > down_move) & (up_move > 0),   up_move,   0.0),
        index=df.index)
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index)

    alpha    = 1.0 / n
    atr_s    = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s

    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx.fillna(0), plus_di.fillna(0), minus_di.fillna(0)


# ---------------------------------------------------------------------------
# Extension count — runs through full history to track state
# ---------------------------------------------------------------------------

def compute_extension_count(df: pd.DataFrame) -> pd.Series:
    """
    For each row: how many times has price extended >= EXT_THRESHOLD% above
    the 10 EMA since the last time price was below the 20 EMA?
    Count resets to 0 when price closes below the 20 EMA.
    """
    ext_count  = np.zeros(len(df), dtype=int)
    in_ext     = False
    count      = 0

    ext_arr   = df["ext_pct"].values
    above_arr = (df["close"] > df["ema20"]).values

    for i in range(len(df)):
        if not above_arr[i]:
            count  = 0
            in_ext = False
        else:
            if ext_arr[i] >= EXT_THRESHOLD and not in_ext:
                count  += 1
                in_ext  = True
            elif ext_arr[i] < EXT_RESET and in_ext:
                in_ext = False
        ext_count[i] = count

    return pd.Series(ext_count, index=df.index, name="ext_count")


# ---------------------------------------------------------------------------
# Stage detection
# ---------------------------------------------------------------------------

def detect_stage(df: pd.DataFrame, ext_count: pd.Series) -> dict:
    """
    Analyse the last N bars and return a dict describing the current
    Oliver Kell stage, the recommended action, stop level, and notes.
    """
    if len(df) < 20:
        return {"stage": "Insufficient data", "action": "CASH",
                "stop": None, "notes": [], "vol_flag": False}

    row       = df.iloc[-1]
    close     = float(row["close"])
    ema10     = float(row["ema10"])
    ema20     = float(row["ema20"])
    sma50     = float(row["sma50"])
    sma200    = float(row["sma200"])
    ext_pct   = float(row["ext_pct"])
    w_ema10   = float(row["w_ema10"])
    vol_today = float(row["volume"])
    vol_avg   = float(row["vol_avg20"])
    atr       = float(row["atr"])
    ext_cnt   = int(ext_count.iloc[-1])

    above_20  = close > ema20
    above_50  = close > sma50
    above_200 = close > sma200

    vol_flag  = vol_today >= VOLUME_SPIKE * vol_avg  # breakout volume present

    notes = []

    # ── Helper: was price below 20 EMA recently? ────────────────────────────
    recent = df.tail(WEDGE_POP_LOOKBACK + 1).iloc[:-1]   # last N bars excluding today
    days_below_recently = int((recent["close"] < recent["ema20"]).sum())
    was_below_recently  = days_below_recently >= 3        # at least 3 of last N days below

    # ── Helper: detect base (tight consolidation above EMAs) ────────────────
    base_result = _detect_base(df)

    # ── WEDGE DROP: lost 20 EMA after being above it ────────────────────────
    # Price now below 20 EMA; was above it within the last 5 bars
    prev5_above = any(df["close"].iloc[-6:-1] > df["ema20"].iloc[-6:-1])
    if not above_20 and prev5_above:
        stage = STAGE_WEDGE_DROP
        notes.append("Price lost the 20 EMA — Wedge Drop confirmed")
        if ext_cnt >= 2:
            notes.append(f"Came after {ext_cnt} extensions — high-conviction exit")
        if above_50:
            notes.append("Still above 50 SMA — may find support; watch for recovery")
        else:
            notes.append("Also below 50 SMA — structural breakdown")
        return {
            "stage":    stage,
            "action":   "SELL",
            "stop":     None,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── DOWNTREND / CASH: below 20 EMA, not a fresh Wedge Drop ─────────────
    if not above_20:
        # Check for Reversal Extension (bottoming signal)
        if ext_pct <= EXT_BELOW_THRESH:
            # Price extended far below 10 EMA
            today_bullish = float(row["close"]) > float(row["open"])  # bullish bar
            stage = STAGE_REVERSAL_EXT
            notes.append(f"Price {abs(ext_pct):.1f}% below 10 EMA — capitulation zone")
            if today_bullish:
                notes.append("Bullish bar today — watch for Wedge Pop to confirm bottom")
            else:
                notes.append("Still selling — wait for a reversal bar before positioning")
            if vol_flag:
                notes.append("Heavy volume — institutional activity possible")
            return {
                "stage":    stage,
                "action":   "WATCH",
                "stop":     None,
                "notes":    notes,
                "vol_flag": vol_flag,
                "ext_cnt":  ext_cnt,
            }

        stage = STAGE_DOWNTREND
        notes.append("Price below 20 EMA — avoid new longs")
        if above_200:
            notes.append("Above 200 SMA — intermediate correction, not bear market")
        else:
            notes.append("Below 200 SMA — potential bear market, heightened caution")
        return {
            "stage":    stage,
            "action":   "CASH",
            "stop":     None,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── From here: price is above 20 EMA ────────────────────────────────────

    # ── EXHAUSTION EXTENSION: extended from 10 EMA ──────────────────────────
    if ext_pct >= EXT_THRESHOLD:
        stage = STAGE_EXTENSION
        action = "REDUCE" if ext_cnt >= 2 else "HOLD"
        notes.append(f"Extension #{ext_cnt}: {ext_pct:+.1f}% above 10 EMA")
        if ext_cnt >= 2:
            notes.append("2nd+ extension — take significant partial profits")
            notes.append("'Sell When You Can, Not When You Have To'")
        else:
            notes.append("1st extension — can hold but raise stops to 10 EMA")
        if close > w_ema10 * 1.05:
            notes.append("Also extended from WEEKLY 10 EMA — major topping warning")
        stop = ema10   # trail stop to 10 EMA
        return {
            "stage":    stage,
            "action":   action,
            "stop":     stop,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── WEDGE POP: just crossed above 20 EMA from below ─────────────────────
    if above_20 and was_below_recently and not base_result["in_base"]:
        # EMAs converging is a positive sign for a Wedge Pop
        ema_spread = (ema20 - ema10) / ema20 * 100   # negative = 10 EMA above 20 EMA
        stage = STAGE_WEDGE_POP
        notes.append(f"Crossed above 20 EMA after {days_below_recently} days below")
        notes.append("First clean buy area — 'From Failed Moves Come Fast Moves'")
        if abs(ema_spread) < 2.0:
            notes.append("10/20 EMA cluster tight — strong Wedge Pop signal")
        stop = ema20   # stop below 20 EMA
        return {
            "stage":    stage,
            "action":   "BUY",
            "stop":     stop,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── BASE n' BREAK: breaking out of a tight base ──────────────────────────
    if base_result["breaking_out"] and vol_flag:
        stage = STAGE_BASE_BREAK
        notes.append(f"Breaking above {BASE_MIN_DAYS}+ day base on volume ({vol_today/vol_avg:.1f}x avg)")
        notes.append(f"Base range: {base_result['base_range_pct']:.1f}% — "
                     + ("tight ✓" if base_result['base_range_pct'] < 8 else "acceptable"))
        notes.append("'Bigger the Base, the Higher in Space'")
        stop = base_result["base_low"]    # stop below base low
        return {
            "stage":    stage,
            "action":   "BUY",
            "stop":     stop,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── EMA CROSSBACK: first pullback into 10/20 EMA in uptrend ─────────────
    dist_from_ema10 = abs(close - ema10) / ema10 * 100
    dist_from_ema20 = abs(close - ema20) / ema20 * 100
    near_ema10 = dist_from_ema10 <= CROSSBACK_RANGE
    near_ema20 = dist_from_ema20 <= CROSSBACK_RANGE

    if (near_ema10 or near_ema20) and not was_below_recently and ext_cnt >= 0:
        # Only an EMA Crossback if NOT a fresh Wedge Pop (not was_below_recently)
        target_ema = ema10 if near_ema10 else ema20
        stage = STAGE_EMA_CROSSBACK
        notes.append(f"Pulled back to {'10' if near_ema10 else '20'} EMA "
                     f"({dist_from_ema10 if near_ema10 else dist_from_ema20:.1f}% away)")
        notes.append("Low-risk add/re-entry — either EMA holds and trend continues, "
                     "or break = small defined loss")
        notes.append("'Buy Right, Sit Tight' — enter against the EMA")
        stop = min(ema10, ema20) * 0.99   # 1% below the lower of the two EMAs
        return {
            "stage":    stage,
            "action":   "ADD",
            "stop":     stop,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── IN BASE: consolidating above EMAs, no breakout yet ──────────────────
    if base_result["in_base"]:
        stage = STAGE_BASE
        notes.append(f"Consolidating above EMAs — base day {base_result['base_days']} "
                     f"of potential pattern")
        notes.append(f"Base range so far: {base_result['base_range_pct']:.1f}%")
        if base_result["base_days"] >= BASE_MIN_DAYS:
            notes.append("Base mature enough — watch for breakout above "
                         f"${base_result['base_high']:.2f} on volume")
        stop = base_result["base_low"]
        return {
            "stage":    stage,
            "action":   "WATCH",
            "stop":     stop,
            "notes":    notes,
            "vol_flag": vol_flag,
            "ext_cnt":  ext_cnt,
        }

    # ── UPTREND HOLD: above EMAs, no specific setup ──────────────────────────
    stage = STAGE_UPTREND
    notes.append("Uptrend intact — above 10 and 20 EMA")
    if ext_cnt >= 1:
        notes.append(f"Extension #{ext_cnt} active — raise stops to 10 EMA (${ema10:.2f})")
    notes.append("Hold existing position; look for EMA Crossback to add")
    stop = ema10 if ext_cnt >= 1 else ema20
    return {
        "stage":    stage,
        "action":   "HOLD",
        "stop":     stop,
        "notes":    notes,
        "vol_flag": vol_flag,
        "ext_cnt":  ext_cnt,
    }


def _detect_base(df: pd.DataFrame) -> dict:
    """
    Look back up to BASE_MAX_DAYS to find a tight consolidation above the 10/20 EMA.
    Returns whether price is in a base, days in base, base high/low/range, and
    whether today is breaking out above the base.
    """
    close  = df["close"].values
    high   = df["high"].values
    ema10  = df["ema10"].values
    ema20  = df["ema20"].values
    n      = len(df)

    # Find the most recent day price was below the 20 EMA (start of base)
    base_start = None
    for i in range(n - 2, max(n - BASE_MAX_DAYS - 1, 0), -1):
        if close[i] < ema20[i]:
            base_start = i + 1
            break

    if base_start is None or base_start >= n - 1:
        return {"in_base": False, "breaking_out": False, "base_days": 0,
                "base_high": 0.0, "base_low": 0.0, "base_range_pct": 0.0}

    base_slice_hi  = high[base_start: n - 1]       # highs within base (exclude today)
    base_slice_cl  = close[base_start: n - 1]      # closes within base
    base_slice_lo  = df["low"].values[base_start: n - 1]

    if len(base_slice_cl) < BASE_MIN_DAYS:
        return {"in_base": False, "breaking_out": False, "base_days": len(base_slice_cl),
                "base_high": 0.0, "base_low": 0.0, "base_range_pct": 0.0}

    b_high      = float(base_slice_hi.max())
    b_low       = float(base_slice_lo.min())
    b_range_pct = (b_high - b_low) / b_low * 100 if b_low > 0 else 999.0
    in_base     = b_range_pct <= BASE_MAX_RANGE

    # Check if all base closes are above both EMAs
    ema10_base = ema10[base_start: n - 1]
    ema20_base = ema20[base_start: n - 1]
    all_above_ema = all(base_slice_cl > ema20_base)

    # Breaking out: today's close above the base high
    today_close   = float(close[n - 1])
    breaking_out  = in_base and all_above_ema and (today_close > b_high)

    return {
        "in_base":        in_base and all_above_ema and not breaking_out,
        "breaking_out":   breaking_out,
        "base_days":      len(base_slice_cl),
        "base_high":      b_high,
        "base_low":       b_low,
        "base_range_pct": b_range_pct,
    }


# ---------------------------------------------------------------------------
# Relative strength vs QQQ
# ---------------------------------------------------------------------------

def relative_strength(stock_df: pd.DataFrame, qqq_df: pd.DataFrame,
                       days: int = RS_DAYS) -> float | None:
    """Return stock return minus QQQ return over the last N days (%)."""
    try:
        common = stock_df.index.intersection(qqq_df.index)
        if len(common) < days + 1:
            return None
        common = common[-days - 1:]
        s_ret = (float(stock_df.loc[common[-1], "close"]) /
                 float(stock_df.loc[common[0],  "close"]) - 1) * 100
        q_ret = (float(qqq_df.loc[common[-1],  "close"]) /
                 float(qqq_df.loc[common[0],   "close"]) - 1) * 100
        return round(s_ret - q_ret, 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Market regime
# ---------------------------------------------------------------------------

def market_regime(qqq_df: pd.DataFrame) -> dict:
    """Return current QQQ regime: bullish / bearish / transitioning."""
    row      = qqq_df.iloc[-1]
    close    = float(row["close"])
    ema20    = float(row["ema20"])
    sma50    = float(row["sma50"])
    ext_pct  = float(row["ext_pct"])
    ext_count_series = compute_extension_count(qqq_df)
    ext_cnt  = int(ext_count_series.iloc[-1])

    above_20 = close > ema20
    above_50 = close > sma50

    if above_20 and above_50:
        label   = "BULLISH"
        advice  = "Full exposure — take setups with full size"
    elif above_20 and not above_50:
        label   = "TRANSITIONING"
        advice  = "Caution — QQQ above 20 EMA but below 50 SMA; use smaller size"
    else:
        label   = "BEARISH"
        advice  = "Avoid new longs — reduce/eliminate margin; tighten stops"

    return {
        "label":    label,
        "close":    close,
        "ema20":    ema20,
        "above_20": above_20,
        "ext_cnt":  ext_cnt,
        "advice":   advice,
    }


# ---------------------------------------------------------------------------
# Signal output — single stock
# ---------------------------------------------------------------------------

def print_signal(ticker: str, df: pd.DataFrame, qqq_df: pd.DataFrame,
                 show_history: bool = True) -> dict:
    df_ind  = compute_indicators(df)
    ext_cnt = compute_extension_count(df_ind)
    result  = detect_stage(df_ind, ext_cnt)
    regime  = market_regime(compute_indicators(qqq_df))
    rs      = relative_strength(df_ind, compute_indicators(qqq_df))

    row      = df_ind.iloc[-1]
    today    = df_ind.index[-1].date()
    close    = float(row["close"])
    ema10    = float(row["ema10"])
    ema20    = float(row["ema20"])
    sma50    = float(row["sma50"])
    sma200   = float(row["sma200"])
    w_ema10  = float(row["w_ema10"])
    ext_pct  = float(row["ext_pct"])
    vol_today= float(row["volume"])
    vol_avg  = float(row["vol_avg20"])
    atr      = float(row["atr"])

    action   = result["action"]
    stage    = result["stage"]
    stop     = result["stop"]
    notes    = result["notes"]
    ext_count= result["ext_cnt"]

    W   = 68
    SEP = "=" * W
    DIV = "-" * W

    action_color = {
        "BUY":    "*** BUY  ***",
        "ADD":    "*** ADD  ***",
        "SELL":   "*** SELL ***",
        "REDUCE": "*** REDUCE ***",
        "WATCH":  "  WATCH   ",
        "HOLD":   "  HOLD    ",
        "CASH":   "  CASH    ",
    }.get(action, action)

    print(f"\n{SEP}")
    print(f"  OLIVER KELL STRATEGY  --  {ticker}")
    print(f"  {today.strftime('%A, %B %d, %Y')}")
    print(SEP)

    print(f"\n  Close:           ${close:>9.2f}")
    print(f"  10-day EMA:      ${ema10:>9.2f}   ext: {ext_pct:>+.1f}%"
          + (f"  [Ext #{ext_count}]" if ext_count >= 1 else ""))
    print(f"  20-day EMA:      ${ema20:>9.2f}   {'ABOVE' if close > ema20 else 'BELOW  <<'}")
    print(f"  50-day SMA:      ${sma50:>9.2f}   {'above' if close > sma50  else 'BELOW'}")
    print(f"  200-day SMA:     ${sma200:>9.2f}   {'above' if close > sma200 else 'BELOW'}")
    print(f"  Weekly 10 EMA:   ${w_ema10:>9.2f}   {'above' if close > w_ema10 else 'BELOW'}")
    adx     = float(row["adx"])
    di_plus = float(row["di_plus"])
    di_minus= float(row["di_minus"])
    adx_label = ("TRENDING" if adx >= ADX_TREND_MIN else "choppy")
    print(f"  ATR (14):        ${atr:>9.2f}")
    print(f"  ADX (14):        {adx:>9.1f}   [{adx_label}]  +DI {di_plus:.1f}  -DI {di_minus:.1f}")
    print(f"  Volume:          {vol_today/1e6:>8.1f}M   ({vol_today/vol_avg:.1f}x avg)"
          + ("  [VOLUME SPIKE]" if result["vol_flag"] else ""))
    if rs is not None:
        rs_str = f"{rs:>+.1f}% vs QQQ ({RS_DAYS}d)"
        strong = rs >= 2
        print(f"  Rel Strength:   {rs_str}"
              + ("  [LEADING]" if strong else ("  [LAGGING]" if rs < -2 else "")))
    print()
    print(f"  Market Regime:   {regime['label']}  (QQQ {'above' if regime['above_20'] else 'below'} 20 EMA)")
    print(f"  Regime advice:   {regime['advice']}")
    print()
    print(f"  CYCLE STAGE:     {stage}")
    for note in notes:
        print(f"    * {note}")

    print()
    print(DIV)
    print(f"  ACTION:    {action_color}   ({stage})")

    if stop:
        risk_pct = (close - stop) / close * 100 if stop < close else 0
        risk_amt = close - stop if stop < close else 0
        print(f"  Stop:      ${stop:.2f}   ({risk_pct:.1f}% risk / ${risk_amt:.2f} per share)")
        if risk_amt > 0:
            print(f"  ATR risk:  {risk_amt / atr:.1f}x ATR")
    else:
        print(f"  Stop:      N/A")

    # Position size suggestion (1R = $500 risk per trade)
    if stop and stop < close and (close - stop) > 0:
        shares_500 = math.floor(500 / (close - stop))
        print(f"  Size ($500R): {shares_500} shares  =  ${shares_500 * close:,.0f} exposure")

    print(DIV)

    # Recent bar history
    if show_history:
        print(f"\n  Recent 10 bars:")
        print(f"  {'Date':<12} {'Close':>8} {'10EMA':>8} {'20EMA':>8} "
              f"{'Ext%':>6} {'Ext#':>4}  Stage")
        print(f"  {'-'*70}")
        recent_ext = ext_cnt.tail(10)
        for ts, r in df_ind.tail(10).iterrows():
            ec  = int(recent_ext.loc[ts])
            ep  = float(r["ext_pct"])
            ab  = "^" if float(r["close"]) > float(r["ema20"]) else "v"
            mark = " <--" if ts == df_ind.index[-1] else ""
            print(f"  {str(ts.date()):<12} {float(r['close']):>8.2f} "
                  f"{float(r['ema10']):>8.2f} {float(r['ema20']):>8.2f} "
                  f"{ep:>+6.1f}% {ec:>4}{ab}{mark}")
    print(SEP)

    return {
        "ticker":    ticker,
        "close":     close,
        "stage":     stage,
        "action":    action,
        "stop":      stop,
        "ext_count": ext_count,
        "rs":        rs,
        "vol_flag":  result["vol_flag"],
        "regime":    regime["label"],
    }


# ---------------------------------------------------------------------------
# Scan output — multiple tickers (compact table)
# ---------------------------------------------------------------------------

def print_scan(tickers: list[str], qqq_df: pd.DataFrame, start: str) -> None:
    regime  = market_regime(compute_indicators(qqq_df))
    qqq_ind = compute_indicators(qqq_df)
    today   = date.today()

    print(f"\n{'='*80}")
    print(f"  OLIVER KELL SCAN  --  {today.strftime('%A, %B %d, %Y')}")
    print(f"  Market Regime: {regime['label']}  "
          f"(QQQ ${regime['close']:,.2f}  {'above' if regime['above_20'] else 'BELOW'} 20 EMA)")
    print(f"{'='*80}")
    print(f"  {'Ticker':<7}  {'Stage':<22}  {'Action':<8}  "
          f"{'Close':>8}  {'Stop':>8}  {'Risk%':>6}  {'RS20d':>6}  {'Vol':>5}  Notes")
    print(f"  {'-'*78}")

    results = []
    errors  = []

    for ticker in tickers:
        try:
            df = _load(ticker, start)
            if len(df) < 30:
                errors.append(f"{ticker}: insufficient data ({len(df)} rows)")
                continue

            df_ind  = compute_indicators(df)
            ext_cnt = compute_extension_count(df_ind)
            result  = detect_stage(df_ind, ext_cnt)
            rs      = relative_strength(df_ind, qqq_ind)

            row    = df_ind.iloc[-1]
            close  = float(row["close"])
            stop   = result["stop"]
            risk   = ((close - stop) / close * 100) if stop and stop < close else 0.0
            vol_f  = result["vol_flag"]

            action_tag = {
                "BUY":    "BUY ***",
                "ADD":    "ADD ***",
                "SELL":   "SELL***",
                "REDUCE": "REDUCE ",
                "WATCH":  "WATCH  ",
                "HOLD":   "HOLD   ",
                "CASH":   "CASH   ",
            }.get(result["action"], result["action"])

            rs_str  = f"{rs:>+.1f}%" if rs is not None else "  N/A"
            stop_str = f"${stop:.2f}" if stop else "  N/A"
            note    = result["notes"][0][:30] if result["notes"] else ""

            print(f"  {ticker:<7}  {result['stage']:<22}  {action_tag:<8}  "
                  f"{close:>8.2f}  {stop_str:>8}  {risk:>5.1f}%  "
                  f"{rs_str:>6}  {'VOL' if vol_f else '   ':>5}  {note}")

            results.append({**result, "ticker": ticker, "close": close,
                            "rs": rs, "stop": stop})
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    print(f"  {'='*78}")

    # Prioritised summary
    buys    = [r for r in results if r["action"] in ("BUY", "ADD")]
    reduces = [r for r in results if r["action"] == "REDUCE"]
    sells   = [r for r in results if r["action"] == "SELL"]

    if buys:
        print(f"\n  ACTIONABLE BUYS/ADDS: "
              + ", ".join(f"{r['ticker']} ({r['stage']})" for r in buys))
    if sells:
        print(f"  EXIT SIGNALS: "
              + ", ".join(f"{r['ticker']}" for r in sells))
    if reduces:
        print(f"  TAKE PROFITS: "
              + ", ".join(f"{r['ticker']} [Ext#{r['ext_cnt']}]" for r in reduces))
    if errors:
        print(f"\n  Errors: {', '.join(errors)}")
    print(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

BACKTEST_WARMUP = 200   # bars before generating signals (need SMA200)


def run_backtest(ticker: str, df: pd.DataFrame,
                 start_capital: float = 10_000.0,
                 adx_min: float = 0.0,
                 qqq_df: pd.DataFrame | None = None,
                 rs_min: float = 0.0,
                 high_52w_max_pct: float = 0.15,
                 vol_confirm: bool = False) -> dict:
    """
    Walk-forward simulation of Oliver Kell strategy on a single stock.
    BUY/ADD → enter at next open.  SELL → exit at next open.
    100% in / 100% out (no partial sizing in backtest).

    Quality filters (applied only on entry, not exits):
      rs_min          — stock must outperform QQQ by >= rs_min% over 20 days
      high_52w_max_pct — price must be within this % of 52-week rolling high
      vol_confirm     — entry bar volume must be >= 1.2x 20-day average
    """
    df_ind  = compute_indicators(df)
    ext_cnt = compute_extension_count(df_ind)

    opens  = df_ind["open"].values
    closes = df_ind["close"].values
    dates  = df_ind.index
    n      = len(df_ind)

    if n < BACKTEST_WARMUP + 10:
        return {}

    # ── Precompute quality filter series ─────────────────────────────────────
    high_252      = df_ind["close"].rolling(252, min_periods=50).max()
    pct_from_high = (high_252 - df_ind["close"]) / high_252.replace(0, np.nan)
    vol_ratio     = df_ind["volume"] / df_ind["vol_avg20"].replace(0, np.nan)

    if qqq_df is not None:
        qqq_ret20   = qqq_df["close"].pct_change(20) * 100
        stock_ret20 = df_ind["close"].pct_change(20) * 100
        rs_series   = stock_ret20 - qqq_ret20.reindex(df_ind.index, method="ffill")
    else:
        rs_series = pd.Series(np.nan, index=df_ind.index)

    capital        = start_capital
    in_position    = False
    entry_price    = 0.0
    entry_date     = None
    shares         = 0.0
    pending_signal = None   # "BUY" or "SELL", executed on next open
    trades         = []
    equity         = []     # list of (date, portfolio_value)

    for i in range(BACKTEST_WARMUP, n):
        today_open  = float(opens[i])
        today_close = float(closes[i])
        today_date  = dates[i]

        # ── Execute pending signal at today's open ───────────────────────────
        if pending_signal == "BUY" and not in_position and today_open > 0:
            shares      = capital / today_open
            entry_price = today_open
            entry_date  = today_date
            in_position = True
            pending_signal = None

        elif pending_signal == "SELL" and in_position and today_open > 0:
            proceeds   = shares * today_open
            pnl_pct    = (today_open - entry_price) / entry_price * 100
            trades.append({
                "entry_date":  entry_date,
                "exit_date":   today_date,
                "entry_price": entry_price,
                "exit_price":  today_open,
                "pnl_pct":     pnl_pct,
                "pnl_dollars": proceeds - shares * entry_price,
                "duration":    (today_date - entry_date).days,
                "open":        False,
            })
            capital     = proceeds
            in_position = False
            shares      = 0.0
            pending_signal = None

        else:
            pending_signal = None

        # ── Mark portfolio value (mark-to-market) ────────────────────────────
        port_val = shares * today_close if in_position else capital
        equity.append((today_date, port_val))

        # ── Generate signal for this bar (execute at next open) ──────────────
        if i < n - 1:
            result  = detect_stage(df_ind.iloc[:i + 1], ext_cnt.iloc[:i + 1])
            action  = result["action"]
            adx_val  = float(df_ind["adx"].iloc[i])
            di_plus  = float(df_ind["di_plus"].iloc[i])
            di_minus = float(df_ind["di_minus"].iloc[i])
            trending = (adx_min == 0) or (adx_val >= adx_min and di_plus > di_minus)

            # Quality filters — only gate entries, never exits
            rs_val    = float(rs_series.iloc[i])
            rs_ok     = np.isnan(rs_val) or (rs_val >= rs_min)
            pfh_val   = float(pct_from_high.iloc[i])
            near_high = np.isnan(pfh_val) or (pfh_val <= high_52w_max_pct)
            vr_val    = float(vol_ratio.iloc[i])
            vol_ok    = (not vol_confirm) or np.isnan(vr_val) or (vr_val >= 1.2)
            quality_ok = rs_ok and near_high and vol_ok

            if action in ("BUY", "ADD") and not in_position and trending and quality_ok:
                pending_signal = "BUY"
            elif action == "SELL" and in_position:
                pending_signal = "SELL"

    # ── Close any open position at last close ────────────────────────────────
    if in_position:
        last_close = float(closes[-1])
        last_date  = dates[-1]
        pnl_pct    = (last_close - entry_price) / entry_price * 100
        trades.append({
            "entry_date":  entry_date,
            "exit_date":   last_date,
            "entry_price": entry_price,
            "exit_price":  last_close,
            "pnl_pct":     pnl_pct,
            "pnl_dollars": shares * last_close - shares * entry_price,
            "duration":    (last_date - entry_date).days,
            "open":        True,
        })
        capital = shares * last_close

    # ── Equity curve ─────────────────────────────────────────────────────────
    eq = pd.DataFrame(equity, columns=["date", "value"]).set_index("date")

    # ── Metrics ──────────────────────────────────────────────────────────────
    years        = (eq.index[-1] - eq.index[0]).days / 365.25
    total_return = (capital - start_capital) / start_capital
    cagr         = (capital / start_capital) ** (1 / years) - 1 if years > 0 else 0

    roll_max = eq["value"].cummax()
    max_dd   = ((eq["value"] - roll_max) / roll_max).min()

    wins   = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    avg_win  = float(np.mean([t["pnl_pct"] for t in wins]))   if wins   else 0.0
    avg_loss = float(np.mean([t["pnl_pct"] for t in losses])) if losses else 0.0

    gross_win  = sum(t["pnl_dollars"] for t in wins)   if wins   else 0.0
    gross_loss = sum(abs(t["pnl_dollars"]) for t in losses) if losses else 0.0
    profit_fac = gross_win / gross_loss if gross_loss > 0 else float("inf")

    # ── Buy-and-hold benchmark ────────────────────────────────────────────────
    bh_start = float(closes[BACKTEST_WARMUP])
    bh_end   = float(closes[-1])
    bh_cagr  = (bh_end / bh_start) ** (1 / years) - 1 if years > 0 else 0
    bh_val   = start_capital * (bh_end / bh_start)
    bh_eq    = pd.Series(
        start_capital * (df_ind["close"].values[BACKTEST_WARMUP:] / bh_start),
        index=df_ind.index[BACKTEST_WARMUP:],
    )
    bh_roll  = bh_eq.cummax()
    bh_max_dd= ((bh_eq - bh_roll) / bh_roll).min()

    # ── Annual returns ────────────────────────────────────────────────────────
    eq["year"] = eq.index.year
    bh_eq_df   = bh_eq.to_frame("value")
    bh_eq_df["year"] = bh_eq_df.index.year
    annual = {}
    for yr, grp in eq.groupby("year"):
        yr_start = grp["value"].iloc[0]
        yr_end   = grp["value"].iloc[-1]
        annual[yr] = (yr_end - yr_start) / yr_start * 100
    annual_bh = {}
    for yr, grp in bh_eq_df.groupby("year"):
        yr_start = grp["value"].iloc[0]
        yr_end   = grp["value"].iloc[-1]
        annual_bh[yr] = (yr_end - yr_start) / yr_start * 100

    return {
        "ticker":           ticker,
        "adx_min":          adx_min,
        "rs_min":           rs_min,
        "high_52w_max_pct": high_52w_max_pct,
        "vol_confirm":      vol_confirm,
        "start_cap":        start_capital,
        "end_cap":      capital,
        "total_return": total_return,
        "cagr":         cagr,
        "max_dd":       max_dd,
        "win_rate":     win_rate,
        "avg_win":      avg_win,
        "avg_loss":     avg_loss,
        "n_trades":     len(trades),
        "profit_fac":   profit_fac,
        "trades":       trades,
        "equity":       eq,
        "annual":       annual,
        "annual_bh":    annual_bh,
        "bh_cagr":      bh_cagr,
        "bh_end_cap":   bh_val,
        "bh_max_dd":    bh_max_dd,
        "years":        years,
    }


def print_backtest(r: dict) -> None:
    """Print full backtest results for a single ticker."""
    if not r:
        print("Insufficient data for backtest.")
        return

    ticker = r["ticker"]
    SEP    = "=" * 72
    DIV    = "-" * 72

    adx_tag = f"  ADX filter: >={r.get('adx_min', 0)}" if r.get('adx_min', 0) > 0 else ""
    print(f"\n{SEP}")
    print(f"  OLIVER KELL BACKTEST  --  {ticker}{adx_tag}")
    print(f"  {r['years']:.1f} years  |  "
          f"${r['start_cap']:,.0f} -> ${r['end_cap']:,.0f}  "
          f"({r['total_return']*100:+.1f}%)")
    print(SEP)

    # ── Key metrics ──────────────────────────────────────────────────────────
    print(f"\n  {'Metric':<24}  {'Oliver Kell':>14}  {'Buy & Hold':>14}")
    print(f"  {DIV[:54]}")
    print(f"  {'CAGR':<24}  {r['cagr']*100:>13.1f}%  {r['bh_cagr']*100:>13.1f}%")
    print(f"  {'Max Drawdown':<24}  {r['max_dd']*100:>13.1f}%  {r['bh_max_dd']*100:>13.1f}%")
    print(f"  {'Final Value ($10k)':<24}  ${r['end_cap']:>13,.0f}  ${r['bh_end_cap']:>13,.0f}")
    print(f"  {'Trades':<24}  {r['n_trades']:>14}")
    print(f"  {'Win Rate':<24}  {r['win_rate']*100:>13.1f}%")
    print(f"  {'Avg Win':<24}  {r['avg_win']:>13.1f}%")
    print(f"  {'Avg Loss':<24}  {r['avg_loss']:>13.1f}%")
    print(f"  {'Profit Factor':<24}  {r['profit_fac']:>14.2f}")

    # ── Trade log ────────────────────────────────────────────────────────────
    if r["trades"]:
        print(f"\n  Trade Log:")
        print(f"  {'Entry Date':<12} {'Exit Date':<12} "
              f"{'Entry':>8} {'Exit':>8} {'P&L%':>8} {'P&L$':>10}  {'Days':>5}  ")
        print(f"  {'-'*66}")
        for t in r["trades"]:
            open_tag = " *" if t.get("open") else ""
            pnl_sign = "+" if t["pnl_pct"] >= 0 else ""
            print(f"  {str(t['entry_date'].date()):<12} "
                  f"{str(t['exit_date'].date()):<12} "
                  f"${t['entry_price']:>7.2f} "
                  f"${t['exit_price']:>7.2f} "
                  f"{pnl_sign}{t['pnl_pct']:>7.1f}% "
                  f"${t['pnl_dollars']:>+9.0f}"
                  f"  {t['duration']:>5}d{open_tag}")

    # ── Annual returns ────────────────────────────────────────────────────────
    all_years = sorted(set(r["annual"]) | set(r["annual_bh"]))
    if all_years:
        print(f"\n  Annual Returns:")
        print(f"  {'Year':<6}  {'Oliver Kell':>12}  {'Buy & Hold':>12}")
        print(f"  {'-'*36}")
        for yr in all_years:
            ok  = r["annual"].get(yr)
            bh  = r["annual_bh"].get(yr)
            ok_s  = f"{ok:>+.1f}%"  if ok  is not None else "   N/A"
            bh_s  = f"{bh:>+.1f}%"  if bh  is not None else "   N/A"
            diff  = (ok - bh) if (ok is not None and bh is not None) else None
            diff_s = f"  ({diff:>+.1f}%)" if diff is not None else ""
            print(f"  {yr:<6}  {ok_s:>12}  {bh_s:>12}{diff_s}")

    print(SEP)


def print_backtest_summary(results: list[dict]) -> None:
    """Print a compact comparison table across multiple tickers."""
    print(f"\n{'='*80}")
    print(f"  OLIVER KELL BACKTEST SUMMARY")
    print(f"  {'Ticker':<7}  {'CAGR':>8}  {'BH CAGR':>8}  "
          f"{'Max DD':>8}  {'BH DD':>8}  "
          f"{'Trades':>7}  {'WinR':>6}  {'PF':>5}")
    print(f"  {'-'*78}")
    for r in results:
        if not r:
            continue
        print(f"  {r['ticker']:<7}  "
              f"{r['cagr']*100:>7.1f}%  "
              f"{r['bh_cagr']*100:>7.1f}%  "
              f"{r['max_dd']*100:>7.1f}%  "
              f"{r['bh_max_dd']*100:>7.1f}%  "
              f"{r['n_trades']:>7}  "
              f"{r['win_rate']*100:>5.0f}%  "
              f"{r['profit_fac']:>5.2f}")
    print(f"{'='*80}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Oliver Kell Price Cycle Strategy — Individual Stocks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("tickers",        nargs="*", metavar="TICKER",
                    help="One or more stock tickers")
    ap.add_argument("--watchlist",    metavar="FILE",
                    help="Text file with one ticker per line")
    ap.add_argument("--start",        default=None,
                    help="History start date (default: 2022-01-01 for scan, 2015-01-01 for backtest)")
    ap.add_argument("--no-history",   action="store_true",
                    help="Suppress the 10-bar recent history table")
    ap.add_argument("--backtest",     action="store_true",
                    help="Run walk-forward backtest instead of current signal")
    ap.add_argument("--adx-min",     type=float, default=0,
                    help="Only enter trades when ADX >= this (0=off, 20=recommended)")
    args = ap.parse_args()

    # Collect tickers
    tickers = list(args.tickers)
    if args.watchlist:
        try:
            with open(args.watchlist) as f:
                for line in f:
                    t = line.split("#")[0].strip().upper()
                    if t:
                        tickers.append(t)
        except FileNotFoundError:
            print(f"Error: watchlist file not found: {args.watchlist}")
            sys.exit(1)

    if not tickers:
        ap.print_help()
        sys.exit(0)

    tickers = [t.upper() for t in tickers]

    # ── BACKTEST MODE ────────────────────────────────────────────────────────
    if args.backtest:
        start = args.start or BACKTEST_START
        print(f"Loading data from {start}...")
        results = []
        for ticker in tickers:
            try:
                df = _load(ticker, start)
                print(f"  {ticker}: {len(df)} bars loaded")
                r  = run_backtest(ticker, df, adx_min=args.adx_min)
                results.append(r)
                print_backtest(r)
            except Exception as e:
                print(f"  {ticker}: Error — {e}")
                results.append({})
        if len(results) > 1:
            print_backtest_summary([r for r in results if r])
        return

    # ── SIGNAL / SCAN MODE ──────────────────────────────────────────────────
    start = args.start or DATA_START
    print("Loading market data...")
    try:
        qqq_df = _load(REGIME_TICKER, start)
    except Exception as e:
        print(f"Error loading QQQ: {e}")
        sys.exit(1)

    if len(tickers) == 1:
        ticker = tickers[0]
        try:
            df = _load(ticker, start)
        except Exception as e:
            print(f"Error loading {ticker}: {e}")
            sys.exit(1)
        print_signal(ticker, df, qqq_df, show_history=not args.no_history)

    else:
        print_scan(tickers, qqq_df, start)


if __name__ == "__main__":
    main()
