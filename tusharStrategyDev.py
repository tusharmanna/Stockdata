"""
tusharStrategyDev.py  --  TusharStrategy v1 vs v2 vs v3 vs v4

STRATEGIES
----------
v1 (TusharStrategy):
  - Watch QQQ distance from its rolling 189-day high.
  - QQQ within 15% of that high  -> hold TQQQ  (bull regime)
  - QQQ falls > 15% below that high -> go to CASH
  - Re-entry: 3 consecutive days back below 15% threshold.

v2 (Hybrid: v1 + 200MA with Stepped Position Sizing):
  - Position size: 0.0 (cash), 0.5 (half), or 1.0 (full)
  - If 1 condition fires: buy/sell 50% of target position
  - If both conditions fire: buy/sell 100% of target position
  - EXIT: v1 (15% threshold) OR 200MA (below for 3 days)
  - ENTRY: v1 (3-day re-entry) OR 200MA (above for 3 days)

v3 (Graduated MA Exposure):
  - Position size: 30% (below all) → 60% (above 200) → 85% (above 50+200) → 110% (above all)
  - Uses 20-day, 50-day, and 200-day MAs
  - Daily rebalancing toward target position
  - Graduated exposure: more defensive in downtrends, aggressive in uptrends

v4 (Hybrid: v2 Signals + v3 Graduated Sizing):
  - SIGNALS: v2's sharp edge-triggered logic (v1 + 200MA)
  - SIZING: v3's graduated position (30%/60%/85%/110% based on MA count)
  - Combines sharp entry/exit with graduated position management

USAGE
-----
  python tusharStrategyDev.py                        # today's v1 signal
  python tusharStrategyDev.py --backtest --all       # v1 full history
  python tusharStrategyDev.py --v2 --all             # v1 vs v2 full history
  python tusharStrategyDev.py --v3 --all             # v1 vs v2 vs v3 full history
  python tusharStrategyDev.py --v4 --all             # v1 vs v2 vs v3 vs v4 full history
  python tusharStrategyDev.py --v4 --year 2022       # v1-v4 for specific year
"""

import argparse
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

# -- Constants -----------------------------------------------------------------
QQQ_TICKER        = "QQQ"
TQQQ_TICKER       = "TQQQ"
DEFAULT_CAPITAL   = 100_000.0
HIGH_PERIOD       = 189           # proven period from tushar_strategy.py
SIGNAL_THRESHOLD  = 15.0
REENTRY_DAYS      = 3
MA50_PERIOD       = 50
MA200_PERIOD      = 200
MA_CONFIRM_DAYS   = 3             # consecutive closes above/below MA to trigger
MA20_PERIOD       = 20            # v3 short-term MA
# v3 position sizes: 30% (0 MAs), 60% (1 MA), 85% (2 MAs), 110% (3 MAs)
DATA_START        = "2015-01-01"  # warmup start for accurate rolling high (matches tushar_strategy.py)

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# -- Data loading --------------------------------------------------------------

def _load(ticker: str, start: str = DATA_START) -> pd.DataFrame:
    try:
        raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            raise ValueError("empty")
    except Exception:
        raw = yf.Ticker(ticker).history(start=start, auto_adjust=True)
    df = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


# -- Strategy 1: TusharStrategy v1 (fixed position sizing) --------------------

def compute_signal_v1(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """QQQ 15%-below-252d-high rule."""
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
            if days_below >= REENTRY_DAYS:
                in_tqqq = True

        act = "BUY" if (in_tqqq and not prev_in) else "SELL" if (not in_tqqq and prev_in) else "HOLD"
        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        days_list.append(days_below)
        action_list.append(act)
        prev_in = in_tqqq

    df["regime"]     = regime_list
    df["days_below"] = days_list
    df["action"]     = action_list
    return df


def compute_signal_v2(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """v1 + v2 with position sizing: 50% on either condition, 100% on both conditions."""
    df = qqq_df.copy()
    # v1 indicators
    df["high189"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high189"] - df["close"]) / df["high189"] * 100
    # v2 indicators (200-day MA only)
    df["ma200"] = df["close"].rolling(MA200_PERIOD, min_periods=1).mean()

    position_size_list, action_list = [], []
    days_below_list = []
    days_above_200_list, days_below_200_list = [], []

    position_size = 1.0  # Start fully invested
    prev_position_size = 1.0
    days_below = 0  # v1 counter
    days_above_200 = 0  # v2 counter
    days_below_200 = 0  # v2 counter
    prev_v1_exit = False
    prev_ma_exit = False
    prev_v1_entry = False
    prev_ma_entry = False

    for _, row in df.iterrows():
        close = row["close"]
        pcthi = row["pcthi"]
        ma200 = row["ma200"]

        # --- v1 logic: 15%-below-189d-high rule ---
        if pcthi >= SIGNAL_THRESHOLD:
            days_below = 0
            v1_exit = True
        else:
            days_below += 1
            v1_exit = False

        v1_entry = (days_below >= REENTRY_DAYS)

        # --- v2 logic: 200-day MA crossover only ---
        if close > ma200:
            days_above_200 += 1
            days_below_200 = 0
        else:
            days_below_200 += 1
            days_above_200 = 0

        ma_exit = (days_below_200 >= MA_CONFIRM_DAYS)
        ma_entry = (days_above_200 >= MA_CONFIRM_DAYS)

        # --- Position sizing logic: only adjust on signal EDGES (transitions) ---
        # Only fire when signal STARTS (transitions from False to True)
        v1_exit_edge = v1_exit and not prev_v1_exit
        ma_exit_edge = ma_exit and not prev_ma_exit
        v1_entry_edge = v1_entry and not prev_v1_entry
        ma_entry_edge = ma_entry and not prev_ma_entry

        if v1_exit_edge or ma_exit_edge:
            if v1_exit_edge and ma_exit_edge:
                position_size = 0.0  # Both exits: close all
            else:
                position_size = max(0.0, position_size - 0.5)  # One exit: sell 50%
        elif v1_entry_edge or ma_entry_edge:
            if v1_entry_edge and ma_entry_edge:
                position_size = 1.0  # Both entries: buy full
            else:
                position_size = min(1.0, position_size + 0.5)  # One entry: buy 50%
        # else: hold position

        # Update previous state for next iteration
        prev_v1_exit = v1_exit
        prev_ma_exit = ma_exit
        prev_v1_entry = v1_entry
        prev_ma_entry = ma_entry

        # Determine action based on position size change
        if position_size > prev_position_size:
            act = "BUY"
        elif position_size < prev_position_size:
            act = "SELL"
        else:
            act = "HOLD"

        position_size_list.append(position_size)
        action_list.append(act)
        days_below_list.append(days_below)
        days_above_200_list.append(days_above_200)
        days_below_200_list.append(days_below_200)
        prev_position_size = position_size

    df["position_size"] = position_size_list
    df["action"] = action_list
    df["regime"] = ["BUY_TQQQ" if ps > 0 else "CASH" for ps in position_size_list]
    df["pcthi"] = df["pcthi"]  # keep v1 indicator
    df["days_below"] = days_below_list
    df["days_above_200"] = days_above_200_list
    df["days_below_200"] = days_below_200_list
    return df


# -- Backtest engine -----------------------------------------------------------

def compute_signal_v3(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """v3: Graduated exposure based on price above/below 20, 50, 200-day MAs."""
    df = qqq_df.copy()
    df["ma20"]  = df["close"].rolling(MA20_PERIOD,  min_periods=1).mean()
    df["ma50"]  = df["close"].rolling(MA50_PERIOD,  min_periods=1).mean()
    df["ma200"] = df["close"].rolling(MA200_PERIOD, min_periods=1).mean()

    position_size_list = []
    action_list = []

    prev_position_size = 1.0

    for _, row in df.iterrows():
        close = row["close"]
        ma20 = row["ma20"]
        ma50 = row["ma50"]
        ma200 = row["ma200"]

        # Count how many MAs price is above
        mas_above = 0
        if close > ma20:
            mas_above += 1
        if close > ma50:
            mas_above += 1
        if close > ma200:
            mas_above += 1

        # Position sizing based on MA structure
        if mas_above == 3:
            position_size = 1.10  # Above all three: aggressive (110%)
        elif mas_above == 2:
            position_size = 0.85  # Above two: strong (85%)
        elif mas_above == 1:
            position_size = 0.60  # Above one (200MA): moderate (60%)
        else:
            position_size = 0.30  # Below all: defensive (30%)

        # Determine action based on position change
        if position_size > prev_position_size:
            act = "BUY"
        elif position_size < prev_position_size:
            act = "SELL"
        else:
            act = "HOLD"

        position_size_list.append(position_size)
        action_list.append(act)
        prev_position_size = position_size

    df["position_size"] = position_size_list
    df["action"] = action_list
    df["regime"] = ["BUY_TQQQ" if ps > 0 else "CASH" for ps in position_size_list]
    df["ma20"] = df["ma20"]
    df["ma50"] = df["ma50"]
    df["ma200"] = df["ma200"]
    return df


def compute_signal_v4(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """v4: v2's sharp exits (to 0%) with MA-based entry sizing (30%/60%/85%/110% based on MA count)."""
    df = qqq_df.copy()
    # v1 indicators
    df["high189"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high189"] - df["close"]) / df["high189"] * 100
    # MA indicators
    df["ma20"]  = df["close"].rolling(MA20_PERIOD,  min_periods=1).mean()
    df["ma50"]  = df["close"].rolling(MA50_PERIOD,  min_periods=1).mean()
    df["ma200"] = df["close"].rolling(MA200_PERIOD, min_periods=1).mean()

    position_size_list, action_list = [], []
    days_below_list = []
    days_above_200_list, days_below_200_list = [], []

    position_size = 1.0  # Start fully invested
    prev_position_size = 1.0
    days_below = 0
    days_above_200 = 0
    days_below_200 = 0
    prev_v1_exit = False
    prev_ma_exit = False
    prev_v1_entry = False
    prev_ma_entry = False

    for _, row in df.iterrows():
        close = row["close"]
        pcthi = row["pcthi"]
        ma20 = row["ma20"]
        ma50 = row["ma50"]
        ma200 = row["ma200"]

        # --- v1 logic: 15%-below-189d-high rule ---
        if pcthi >= SIGNAL_THRESHOLD:
            days_below = 0
            v1_exit = True
        else:
            days_below += 1
            v1_exit = False

        v1_entry = (days_below >= REENTRY_DAYS)

        # --- 200-day MA logic ---
        if close > ma200:
            days_above_200 += 1
            days_below_200 = 0
        else:
            days_below_200 += 1
            days_above_200 = 0

        ma_exit = (days_below_200 >= MA_CONFIRM_DAYS)
        ma_entry = (days_above_200 >= MA_CONFIRM_DAYS)

        # --- Hybrid: v2 sharp exits, MA-based entry sizing ---
        v1_exit_edge = v1_exit and not prev_v1_exit
        ma_exit_edge = ma_exit and not prev_ma_exit
        v1_entry_edge = v1_entry and not prev_v1_entry
        ma_entry_edge = ma_entry and not prev_ma_entry

        # Exits are always sharp (immediate to 0%)
        if v1_exit_edge or ma_exit_edge:
            position_size = 0.0
        # Entries use MA-based graduated sizing
        elif v1_entry_edge or ma_entry_edge:
            mas_above = 0
            if close > ma20:
                mas_above += 1
            if close > ma50:
                mas_above += 1
            if close > ma200:
                mas_above += 1

            if mas_above == 3:
                position_size = 1.0
            elif mas_above == 2:
                position_size = 0.85
            elif mas_above == 1:
                position_size = 0.60
            else:
                position_size = 0.30
        # else: position_size persists

        # Update previous state for next iteration
        prev_v1_exit = v1_exit
        prev_ma_exit = ma_exit
        prev_v1_entry = v1_entry
        prev_ma_entry = ma_entry

        # Determine action based on position size change
        if position_size > prev_position_size:
            act = "BUY"
        elif position_size < prev_position_size:
            act = "SELL"
        else:
            act = "HOLD"

        position_size_list.append(position_size)
        action_list.append(act)
        days_below_list.append(days_below)
        days_above_200_list.append(days_above_200)
        days_below_200_list.append(days_below_200)
        prev_position_size = position_size

    df["position_size"] = position_size_list
    df["action"] = action_list
    df["regime"] = ["BUY_TQQQ" if ps > 0 else "CASH" for ps in position_size_list]
    df["pcthi"] = df["pcthi"]
    df["days_below"] = days_below_list
    df["days_above_200"] = days_above_200_list
    df["days_below_200"] = days_below_200_list
    df["ma20"] = df["ma20"]
    df["ma50"] = df["ma50"]
    df["ma200"] = df["ma200"]
    return df


def _price_on(df: pd.DataFrame, dt) -> float | None:
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest(sig_df: pd.DataFrame, price_df: pd.DataFrame, capital: float) -> list[dict]:
    """Backtest with position sizing support (v1 or v2 with partial positions)."""
    shares  = 0
    cash    = capital
    daily   = []

    for dt, row in sig_df.iterrows():
        p = _price_on(price_df, dt)
        if p is None:
            continue

        # Get position size (default 1.0 for v1 compatibility)
        pos_size = row.get("position_size", 1.0 if row["regime"] == "BUY_TQQQ" else 0.0)

        # Calculate current portfolio value
        port_value = shares * p + cash

        # Calculate target position in dollars and shares
        target_dollars = pos_size * port_value
        target_shares = math.floor(target_dollars / p) if p > 0 else 0

        # Adjust shares to reach target
        delta_shares = target_shares - shares
        if delta_shares > 0:
            # Buy
            cost = delta_shares * p
            if cost <= cash:
                cash -= cost
                shares = target_shares
        elif delta_shares < 0:
            # Sell
            shares = target_shares
            cash += abs(delta_shares) * p

        port = round(shares * p + cash, 2)
        daily.append({
            "date":        dt,
            "portfolio":   port,
            "regime":      row["regime"],
            "action":      row["action"],
            "position":    pos_size,
            "pcthi":       float(row.get("pcthi", 0.0)),
            "shares":      shares,
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
                      "pcthi": 0.0, "exposure": 50.0, "position_mult": 1.0})
    return daily


# -- Reporting helpers ---------------------------------------------------------

def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i - 1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(x):
    return f"{x:+.1f}%" if x is not None else "—"


def _diff(a, b, width):
    if a is None or b is None:
        return "—"
    return f"{a - b:+.1f}%".rjust(width)


def print_backtest(daily_v1: list[dict], daily_tbh: list[dict], years: list[int],
                   capital: float) -> None:
    """Backtest results: v1 vs TQQQ B&H."""
    r_v1  = _monthly_rets(daily_v1)
    r_tbh = _monthly_rets(daily_tbh)

    W   = 65
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  TusharStrategy v1 Backtest  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_v1 = cum_tbh = capital

    for year in years:
        ytbh0 = cum_tbh
        yv10  = cum_v1

        print(f"  -- {year} " + "-" * (W - 10))
        print(f"  {'Month':<7} {'TQQQ B&H':>10} {'v1':>10}")
        print(DIV)

        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)

            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100

            print(f"  {MONTHS[m]:<7} {_fmt(tbh):>10} {_fmt(v1):>10}")

        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        yr_totals.append((year, fy_tbh, fy_v1))
        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)

        print(f"  {'Total %':<7} {_fmt(ov_tbh):>10} {_fmt(ov_v1):>10}")
        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10}")
        print(f"\n  Final values:  TQQQ B&H ${cum_tbh:,.0f}  |  v1 ${cum_v1:,.0f}")
        print(SEP)
    print()


def print_v2_comparison(daily_v1: list[dict], daily_v2: list[dict], daily_tbh: list[dict],
                        years: list[int], capital: float) -> None:
    """v1 vs v2 (hybrid) annual comparison."""
    r_v1  = _monthly_rets(daily_v1)
    r_v2  = _monthly_rets(daily_v2)
    r_tbh = _monthly_rets(daily_tbh)

    W   = 70
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  v1 vs v2 (Hybrid: v1 + 200MA)  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_v1 = cum_v2 = cum_tbh = capital

    for year in years:
        yv10 = cum_v1
        yv20 = cum_v2
        ytbh0 = cum_tbh

        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)
            v2  = r_v2.get(ym)

            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100
            if v2:  cum_v2  *= 1 + v2  / 100

        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        fy_v2  = round((cum_v2  / yv20  - 1) * 100, 1)
        v2_diff = fy_v2 - fy_v1

        yr_totals.append((year, fy_tbh, fy_v1, fy_v2))
        if yr_totals == [(years[0], fy_tbh, fy_v1, fy_v2)]:
            print(f"  {'Year':<7} {'TQQQ B&H':>10} {'v1':>10} {'v2':>10} {'v2-v1':>8}")
            print(DIV)

        print(f"  {year:<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10} {_fmt(fy_v2):>10} {_fmt(v2_diff):>8}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)
        ov_v2  = round((cum_v2  / capital - 1) * 100, 1)

        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10} {_fmt(cagr(cum_v2)):>10}")
        print(f"  {'Final':<7} ${cum_tbh:>9,.0f} ${cum_v1:>9,.0f} ${cum_v2:>9,.0f}")
        print(f"\n{SEP}\n")


def print_v3_comparison(daily_v1: list[dict], daily_v2: list[dict], daily_v3: list[dict],
                        daily_tbh: list[dict], years: list[int], capital: float) -> None:
    """v1 vs v2 vs v3 annual comparison."""
    r_v1  = _monthly_rets(daily_v1)
    r_v2  = _monthly_rets(daily_v2)
    r_v3  = _monthly_rets(daily_v3)
    r_tbh = _monthly_rets(daily_tbh)

    W   = 85
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  v1 vs v2 vs v3 (Graduated MA)  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_v1 = cum_v2 = cum_v3 = cum_tbh = capital

    for year in years:
        yv10 = cum_v1
        yv20 = cum_v2
        yv30 = cum_v3
        ytbh0 = cum_tbh

        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)
            v2  = r_v2.get(ym)
            v3  = r_v3.get(ym)

            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100
            if v2:  cum_v2  *= 1 + v2  / 100
            if v3:  cum_v3  *= 1 + v3  / 100

        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        fy_v2  = round((cum_v2  / yv20  - 1) * 100, 1)
        fy_v3  = round((cum_v3  / yv30  - 1) * 100, 1)

        yr_totals.append((year, fy_tbh, fy_v1, fy_v2, fy_v3))
        if yr_totals == [(years[0], fy_tbh, fy_v1, fy_v2, fy_v3)]:
            print(f"  {'Year':<7} {'TQQQ B&H':>10} {'v1':>10} {'v2':>10} {'v3':>10}")
            print(DIV)

        print(f"  {year:<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10} {_fmt(fy_v2):>10} {_fmt(fy_v3):>10}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)
        ov_v2  = round((cum_v2  / capital - 1) * 100, 1)
        ov_v3  = round((cum_v3  / capital - 1) * 100, 1)

        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10} {_fmt(cagr(cum_v2)):>10} {_fmt(cagr(cum_v3)):>10}")
        print(f"  {'Final':<7} ${cum_tbh:>9,.0f} ${cum_v1:>9,.0f} ${cum_v2:>9,.0f} ${cum_v3:>9,.0f}")
        print(f"\n{SEP}\n")


def print_v4_comparison(daily_v1: list[dict], daily_v2: list[dict], daily_v3: list[dict],
                        daily_v4: list[dict], daily_tbh: list[dict], years: list[int], capital: float) -> None:
    """v1 vs v2 vs v3 vs v4 annual comparison."""
    r_v1  = _monthly_rets(daily_v1)
    r_v2  = _monthly_rets(daily_v2)
    r_v3  = _monthly_rets(daily_v3)
    r_v4  = _monthly_rets(daily_v4)
    r_tbh = _monthly_rets(daily_tbh)

    W   = 100
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  v1 vs v2 vs v3 vs v4 (Hybrid: v2 Signals + v3 Sizing)  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_v1 = cum_v2 = cum_v3 = cum_v4 = cum_tbh = capital

    for year in years:
        yv10 = cum_v1
        yv20 = cum_v2
        yv30 = cum_v3
        yv40 = cum_v4
        ytbh0 = cum_tbh

        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)
            v2  = r_v2.get(ym)
            v3  = r_v3.get(ym)
            v4  = r_v4.get(ym)

            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100
            if v2:  cum_v2  *= 1 + v2  / 100
            if v3:  cum_v3  *= 1 + v3  / 100
            if v4:  cum_v4  *= 1 + v4  / 100

        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        fy_v2  = round((cum_v2  / yv20  - 1) * 100, 1)
        fy_v3  = round((cum_v3  / yv30  - 1) * 100, 1)
        fy_v4  = round((cum_v4  / yv40  - 1) * 100, 1)

        yr_totals.append((year, fy_tbh, fy_v1, fy_v2, fy_v3, fy_v4))
        if yr_totals == [(years[0], fy_tbh, fy_v1, fy_v2, fy_v3, fy_v4)]:
            print(f"  {'Year':<7} {'TQQQ B&H':>10} {'v1':>10} {'v2':>10} {'v3':>10} {'v4':>10}")
            print(DIV)

        print(f"  {year:<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10} {_fmt(fy_v2):>10} {_fmt(fy_v3):>10} {_fmt(fy_v4):>10}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _, _, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)
        ov_v2  = round((cum_v2  / capital - 1) * 100, 1)
        ov_v3  = round((cum_v3  / capital - 1) * 100, 1)
        ov_v4  = round((cum_v4  / capital - 1) * 100, 1)

        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10} {_fmt(cagr(cum_v2)):>10} {_fmt(cagr(cum_v3)):>10} {_fmt(cagr(cum_v4)):>10}")
        print(f"  {'Final':<7} ${cum_tbh:>9,.0f} ${cum_v1:>9,.0f} ${cum_v2:>9,.0f} ${cum_v3:>9,.0f} ${cum_v4:>9,.0f}")
        print(f"\n{SEP}\n")


def print_v2_trade_log(sig_v2: pd.DataFrame, tqqq_df: pd.DataFrame) -> None:
    """Print v2 (hybrid) trade log with position sizing."""
    trades = []
    for dt, row in sig_v2.iterrows():
        if row["action"] in ("BUY", "SELL"):
            tqqq_p = _price_on(tqqq_df, dt)
            if tqqq_p is None:
                continue

            # Check which conditions triggered
            pcthi = row.get("pcthi", 0)
            days_below = row.get("days_below", 0)
            d200 = row.get("days_below_200", 0) if row["action"] == "SELL" else row.get("days_above_200", 0)
            pos_size = row.get("position_size", 0)

            # Determine trigger source(s)
            if row["action"] == "SELL":
                v1_fired = (pcthi >= SIGNAL_THRESHOLD)
                ma_fired = (d200 >= MA_CONFIRM_DAYS)
            else:  # BUY
                v1_fired = (days_below >= REENTRY_DAYS and pcthi < SIGNAL_THRESHOLD)
                ma_fired = (d200 >= MA_CONFIRM_DAYS)

            if v1_fired and ma_fired:
                trigger = "v1 + 200MA (both)"
                size_pct = "100%"
            elif v1_fired:
                trigger = "v1 (15%)"
                size_pct = "50%"
            elif ma_fired:
                direction = "above" if row["action"] == "BUY" else "below"
                trigger = f"200MA ({direction})"
                size_pct = "50%"
            else:
                trigger = "?"
                size_pct = "?"

            trades.append({
                "date": dt,
                "action": row["action"],
                "price": tqqq_p,
                "trigger": trigger,
                "size": size_pct,
                "pos": pos_size
            })

    if trades:
        print(f"\n  v2 (Hybrid: v1 + 200MA) Trade Log with Position Sizing:")
        print(f"  {'Date':<12} {'Act':<4} {'TQQQ Price':>12} {'Trigger':<20} {'Size':<6} {'Target%':<8}")
        print(f"  {'-'*70}")
        for t in trades:
            print(f"  {t['date'].date()} {t['action']:<4} ${t['price']:>10.2f}  {t['trigger']:<20} {t['size']:<6} {t['pos']*100:>6.0f}%")
        print(f"\n  Total: {len(trades)} signals ({sum(1 for t in trades if t['action']=='BUY')} buys, {sum(1 for t in trades if t['action']=='SELL')} sells)\n")


def print_v4_trade_log(sig_v4: pd.DataFrame, tqqq_df: pd.DataFrame) -> None:
    """Print v4 (hybrid: v2 signals + v3 sizing) trade log."""
    trades = []
    for dt, row in sig_v4.iterrows():
        if row["action"] in ("BUY", "SELL"):
            tqqq_p = _price_on(tqqq_df, dt)
            if tqqq_p is None:
                continue

            # Check which conditions triggered
            pcthi = row.get("pcthi", 0)
            days_below = row.get("days_below", 0)
            d200 = row.get("days_below_200", 0) if row["action"] == "SELL" else row.get("days_above_200", 0)
            pos_size = row.get("position_size", 0)

            # Determine trigger source(s) for signal (v2 logic)
            if row["action"] == "SELL":
                v1_fired = (pcthi >= SIGNAL_THRESHOLD)
                ma_fired = (d200 >= MA_CONFIRM_DAYS)
            else:  # BUY
                v1_fired = (days_below >= REENTRY_DAYS and pcthi < SIGNAL_THRESHOLD)
                ma_fired = (d200 >= MA_CONFIRM_DAYS)

            if v1_fired and ma_fired:
                trigger = "v1 + 200MA"
            elif v1_fired:
                trigger = "v1 (15%)"
            elif ma_fired:
                direction = "above" if row["action"] == "BUY" else "below"
                trigger = f"200MA ({direction})"
            else:
                trigger = "?"

            trades.append({
                "date": dt,
                "action": row["action"],
                "price": tqqq_p,
                "trigger": trigger,
                "pos": pos_size
            })

    if trades:
        print(f"\n  v4 (Hybrid: v2 Signals + v3 Sizing) Trade Log:")
        print(f"  {'Date':<12} {'Act':<4} {'TQQQ Price':>12} {'Signal':<15} {'Target%':<8}")
        print(f"  {'-'*60}")
        for t in trades:
            print(f"  {t['date'].date()} {t['action']:<4} ${t['price']:>10.2f}  {t['trigger']:<15} {t['pos']*100:>6.0f}%")
        print(f"\n  Total: {len(trades)} signals ({sum(1 for t in trades if t['action']=='BUY')} buys, {sum(1 for t in trades if t['action']=='SELL')} sells)\n")


def print_daily_signal(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame) -> None:
    row       = sig_df.iloc[-1]
    today     = sig_df.index[-1].date()
    qqq_close = float(row["close"])
    high252   = float(row["high252"])
    pcthi     = float(row["pcthi"])
    regime    = row["regime"]
    action    = row["action"]

    W   = 60
    SEP = "=" * W
    print(f"\n{SEP}")
    print(f"  v1 Signal: {today}")
    print(f"{SEP}")
    print(f"  QQQ Close:     ${qqq_close:>8.2f}")
    print(f"  189d High:     ${high252:>8.2f}")
    print(f"  % Below High:  {pcthi:>8.1f}%")
    print(f"  Regime:        {regime}")
    print(f"  Action:        {action}")
    print(SEP)


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capital",  type=float, default=DEFAULT_CAPITAL,
                    help="Portfolio capital (default: 100000)")
    ap.add_argument("--backtest", action="store_true",
                    help="Run backtest (default: today's signal)")
    ap.add_argument("--v2",       action="store_true",
                    help="Compare v1 vs v2 MA-crossover strategy")
    ap.add_argument("--v3",       action="store_true",
                    help="Compare v1 vs v2 vs v3 graduated MA exposure")
    ap.add_argument("--v4",       action="store_true",
                    help="Compare v1 vs v2 vs v3 vs v4 (v2 signals + v3 sizing)")
    ap.add_argument("--all",      action="store_true",
                    help="Backtest all years")
    ap.add_argument("--year",     type=int,
                    help="Backtest specific year")
    args = ap.parse_args()

    print("\nLoading QQQ and TQQQ data...")
    qqq_df  = _load(QQQ_TICKER,  DATA_START)
    tqqq_df = _load(TQQQ_TICKER, DATA_START)

    print("Computing v1 signal...")
    sig_v1 = compute_signal_v1(qqq_df)

    if args.v4:
        print("Computing v2, v3, and v4 signals...")
        sig_v2 = compute_signal_v2(qqq_df)
        sig_v3 = compute_signal_v3(qqq_df)
        sig_v4 = compute_signal_v4(qqq_df)
        # Align all to common trading dates
        common = sig_v1.index.intersection(tqqq_df.index)
        tqqq_al = tqqq_df.loc[common]
        sig_v1 = sig_v1.loc[common]
        sig_v2 = sig_v2.loc[common]
        sig_v3 = sig_v3.loc[common]
        sig_v4 = sig_v4.loc[common]
        daily_v1 = run_backtest(sig_v1, tqqq_al, args.capital)
        daily_v2 = run_backtest(sig_v2, tqqq_al, args.capital)
        daily_v3 = run_backtest(sig_v3, tqqq_al, args.capital)
        daily_v4 = run_backtest(sig_v4, tqqq_al, args.capital)
        daily_tbh = run_buyhold(tqqq_al, args.capital)
        if args.all:
            years = sorted(set(d["date"].year for d in daily_v1))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]
        print_v4_comparison(daily_v1, daily_v2, daily_v3, daily_v4, daily_tbh, years, args.capital)
        print_v4_trade_log(sig_v4, tqqq_al)
    elif args.v3:
        print("Computing v2 and v3 signals...")
        sig_v2 = compute_signal_v2(qqq_df)
        sig_v3 = compute_signal_v3(qqq_df)
        # Align all to common trading dates
        common = sig_v1.index.intersection(tqqq_df.index)
        tqqq_al = tqqq_df.loc[common]
        sig_v1 = sig_v1.loc[common]
        sig_v2 = sig_v2.loc[common]
        sig_v3 = sig_v3.loc[common]
        daily_v1 = run_backtest(sig_v1, tqqq_al, args.capital)
        daily_v2 = run_backtest(sig_v2, tqqq_al, args.capital)
        daily_v3 = run_backtest(sig_v3, tqqq_al, args.capital)
        daily_tbh = run_buyhold(tqqq_al, args.capital)
        if args.all:
            years = sorted(set(d["date"].year for d in daily_v1))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]
        print_v3_comparison(daily_v1, daily_v2, daily_v3, daily_tbh, years, args.capital)
    elif args.v2:
        print("Computing v2 signal...")
        sig_v2 = compute_signal_v2(qqq_df)
        # Align all to common trading dates
        common = sig_v1.index.intersection(tqqq_df.index)
        tqqq_al = tqqq_df.loc[common]
        sig_v1 = sig_v1.loc[common]
        sig_v2 = sig_v2.loc[common]
        daily_v1 = run_backtest(sig_v1, tqqq_al, args.capital)
        daily_v2 = run_backtest(sig_v2, tqqq_al, args.capital)
        daily_tbh = run_buyhold(tqqq_al, args.capital)
        if args.all:
            years = sorted(set(d["date"].year for d in daily_v1))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]
        print_v2_comparison(daily_v1, daily_v2, daily_tbh, years, args.capital)
        print_v2_trade_log(sig_v2, tqqq_al)
    elif args.backtest:
        # Align to common dates
        common  = sig_v1.index.intersection(tqqq_df.index)
        sig_v1  = sig_v1.loc[common]
        tqqq_al = tqqq_df.loc[common]

        print("Running backtest...")
        daily_v1  = run_backtest(sig_v1, tqqq_al, args.capital)
        daily_tbh = run_buyhold(tqqq_al, args.capital)

        start_year = int(DATA_START[:4])
        if args.all:
            years = sorted(set(d["date"].year for d in daily_v1 if d["date"].year >= start_year))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]

        print_backtest(daily_v1, daily_tbh, years, args.capital)
    else:
        print_daily_signal(sig_v1, tqqq_df)


if __name__ == "__main__":
    main()
