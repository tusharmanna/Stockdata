"""
backtest_tqqq_strategy.py — TQQQ Strategy: daily ADX-scaled TQQQ/CASH rotation.

Signal: QQQ pctHigh = distance from 252-day rolling high.
  pctHigh < 15%  → BUY_TQQQ  (normal correction — stay invested)
  pctHigh >= 15% → CASH      (deep drawdown — go flat, avoid SQQQ timing losses)

Position sizing:
  Allocation = StageFactor × ADX_factor
  StageFactor  : 1.0 when pctHigh < 15%, 0.5 when 15-25%, 0.0 above 25%
  ADX_factor   : min(1.0, ADX(14) / 36)  — scales down in low-momentum markets
  Re-entry confirmation: must be below threshold for 3 consecutive days after a CASH exit.

Usage:
    python backtest_tqqq_strategy.py                 # current year
    python backtest_tqqq_strategy.py --year 2025
    python backtest_tqqq_strategy.py --all           # all available years
    python backtest_tqqq_strategy.py --capital 100000
"""

import argparse
import math
from collections import defaultdict

import pandas as pd

from whitelight_strategy import (
    _load_ohlcv,
    DEFAULT_CAPITAL, HIGH_PERIOD,
    BULL_ETF, BEAR_ETF, SIGNAL_TKR,
)

STAGE_BANDS = [
    (15.0, 1.00),
    (25.0, 0.50),
    (float("inf"), 0.00),
]

ADX_THRESHOLD    = 36.0
SIGNAL_THRESHOLD = 15.0
REENTRY_DAYS     = 3

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TARGET_RETURNS = {
    2023: {1:12.8, 2:-5.1, 3:7.3, 4:-0.9, 5:23.8, 6:12.1, 7:10.1, 8:-1.8, 9:-6.1, 10:-2.9, 11:9.7, 12:3.6},
    2024: {1:7.3, 2:4.5, 3:-0.6, 4:-8.6, 5:19.2, 6:1.7, 7:-3.3, 8:1.0, 9:-4.0, 10:-0.7, 11:-9.1, 12:5.2},
    2025: {1:2.8, 2:-3.5, 3:-21.2, 4:2.6, 5:17.7, 6:21.2, 7:5.4, 8:4.0, 9:11.5, 10:-0.7, 11:1.4, 12:-1.8},
    2026: {1:-4.9, 2:-4.9, 3:-1.6, 4:23.8},
}


def _wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    dm_plus  = (high - high.shift()).clip(lower=0).where((high - high.shift()) > (low.shift() - low), 0.0)
    dm_minus = (low.shift() - low).clip(lower=0).where((low.shift() - low) > (high - high.shift()), 0.0)
    alpha = 1.0 / period
    atr   = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus  = dm_plus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus = dm_minus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    di_plus  = 100 * plus  / atr.replace(0, float("nan"))
    di_minus = 100 * minus / atr.replace(0, float("nan"))
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, float("nan"))
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def _stage_factor(pct_high: float) -> float:
    for max_pct, factor in STAGE_BANDS:
        if pct_high < max_pct:
            return factor
    return 0.0


def _price_on(df: pd.DataFrame, date) -> float | None:
    if date in df.index:
        return float(df.loc[date, "close"])
    avail = df.index[df.index <= date]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def build_signal_df(qqq_df: pd.DataFrame) -> pd.DataFrame:
    df = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100
    df["adx"]     = _wilder_adx(df)
    df["signal"]  = df["pcthi"].apply(lambda p: "BUY_TQQQ" if p < SIGNAL_THRESHOLD else "CASH")
    return df


def run_backtest(sig_df: pd.DataFrame,
                 tqqq_df: pd.DataFrame,
                 sqqq_df: pd.DataFrame,
                 capital: float) -> list[dict]:
    """
    Daily ADX-scaled TQQQ/CASH rotation with 3-day re-entry confirmation.
    """
    tqqq_sh    = 0
    cash       = capital
    daily      = []
    days_below = 0
    in_tqqq    = True

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        sp = _price_on(sqqq_df, date)
        if tp is None or sp is None:
            continue

        port     = tqqq_sh * tp + cash
        pct_high = round(float(row.get("pcthi", 0.0)), 2)
        adx_val  = float(row.get("adx", ADX_THRESHOLD))
        adx_fac  = min(1.0, adx_val / ADX_THRESHOLD)

        if pct_high >= SIGNAL_THRESHOLD:
            days_below = 0
            in_tqqq    = False
        else:
            days_below += 1
            if days_below >= REENTRY_DAYS:
                in_tqqq = True

        sf       = _stage_factor(pct_high) if in_tqqq else 0.0
        combined = sf * adx_fac
        tqqq_pct = combined if in_tqqq else 0.0

        new_tqqq = math.floor(port * tqqq_pct / tp) if tqqq_pct > 0 and tp > 0 else 0
        cash    += (tqqq_sh - new_tqqq) * tp
        tqqq_sh  = new_tqqq
        port     = round(tqqq_sh * tp + cash, 2)

        daily.append({
            "date":      date,
            "signal":    "BUY_TQQQ" if in_tqqq else "CASH",
            "close":     round(float(row["close"]), 2),
            "pct_high":  pct_high,
            "sf":        round(combined, 3),
            "adx":       round(adx_val, 1),
            "tqqq_pct":  round(tqqq_pct * 100, 0),
            "tqqq_sh":   tqqq_sh,
            "tp":        round(tp, 2),
            "portfolio": port,
        })

    return daily


def monthly_returns(daily: list[dict], year: int) -> dict[int, float]:
    by_month: dict[tuple, list] = defaultdict(list)
    for d in daily:
        by_month[(d["date"].year, d["date"].month)].append(d)

    results      = {}
    sorted_months = sorted(by_month.keys())

    for i, ym in enumerate(sorted_months):
        if ym[0] != year:
            continue
        bars      = by_month[ym]
        end_val   = bars[-1]["portfolio"]
        start_val = by_month[sorted_months[i - 1]][-1]["portfolio"] if i > 0 else bars[0]["portfolio"]
        results[ym[1]] = round((end_val - start_val) / start_val * 100, 1) if start_val else 0.0

    return results


def print_monthly(daily: list[dict], year: int,
                  qqq_df: pd.DataFrame, capital: float) -> None:
    rets    = monthly_returns(daily, year)
    yr_bars = [d for d in daily if d["date"].year == year]
    if not yr_bars:
        print(f"  No data for {year}"); return

    target = TARGET_RETURNS.get(year, {})
    SEP    = "=" * 120
    print(SEP)
    print(f"  TQQQ STRATEGY BACKTEST — {year}  |  Capital: ${capital:,.0f}")
    print(SEP)

    months = sorted(rets.keys())
    print(f"{'':12}" + "".join(f"  {MONTH_ABBR[m]:>8}" for m in months))
    print("-" * 120)
    print(f"  {'Strategy':<10}" + "".join(f"  {rets[m]:>+7.1f}%" for m in months))

    if target:
        print(f"  {'C2 Target':<10}" + "".join(
            f"  {target[m]:>+7.1f}%" if m in target else f"  {'N/A':>8}" for m in months))
        print(f"  {'Delta':<10}" + "".join(
            f"  {rets[m]-target[m]:>+7.1f}p" if m in target else f"  {'':>8}" for m in months))

    print("-" * 120)

    yr_start = yr_bars[0]["portfolio"]
    yr_end   = yr_bars[-1]["portfolio"]
    yr_ret   = round((yr_end - yr_start) / yr_start * 100, 1) if yr_start else 0.0

    qqq_yr  = [d for d in qqq_df.index if d.year == year]
    qqq_ret = 0.0
    if qqq_yr:
        qqq_ret = round((float(qqq_df.loc[qqq_yr[-1], "close"]) /
                         float(qqq_df.loc[qqq_yr[0], "close"]) - 1) * 100, 1)

    print(f"\n  {year} full year: ${yr_start:,.0f} → ${yr_end:,.0f}  "
          f"P&L: ${yr_end-yr_start:+,.0f}  ({yr_ret:+.1f}%)  |  QQQ: {qqq_ret:+.1f}%")
    if year in TARGET_RETURNS:
        tgt = TARGET_RETURNS[year]
        prod = 1.0
        for m in sorted(tgt):
            prod *= 1 + tgt[m] / 100
        print(f"  C2 Target full year: {(prod-1)*100:+.1f}%")
    print(SEP); print()


def main():
    ap = argparse.ArgumentParser(description="TQQQ Strategy monthly backtest")
    ap.add_argument("--year",    type=int,   default=2025)
    ap.add_argument("--all",     action="store_true")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    args = ap.parse_args()

    print("\nLoading data...")
    qqq  = _load_ohlcv(SIGNAL_TKR)
    tqqq = _load_ohlcv(BULL_ETF)
    sqqq = _load_ohlcv(BEAR_ETF)

    sig_df = build_signal_df(qqq)

    print("Running TQQQ Strategy...")
    daily = run_backtest(sig_df, tqqq, sqqq, args.capital)
    print()

    years = sorted({d["date"].year for d in daily}) if args.all else [args.year]
    for yr in years:
        print_monthly(daily, yr, qqq, args.capital)


if __name__ == "__main__":
    main()
