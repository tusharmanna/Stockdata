"""
backtest_dual.py — Monthly backtest for the Dual Strategy (TQQQ / SQQQ).

Position sizing:
  Signal: MA20 > MA50 on QQQ → BUY_TQQQ; MA20 < MA50 → BUY_SQQQ
  Size   = StageFactor × portfolio
  StageFactor is determined by how far QQQ is below its rolling HIGH_PERIOD high.

Usage:
    python backtest_dual.py                    # 2025 Jan–Jul
    python backtest_dual.py --year 2025
    python backtest_dual.py --year 2024
    python backtest_dual.py --all              # all available years
    python backtest_dual.py --capital 100000
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

# Override stage bands: wider first band (0-15%) lets TQQQ ride through normal corrections
# without reducing position — matches observed behavior where TQQQ held through 13% drawdown in Mar 2025
STAGE_BANDS = [
    (15.0, 1.00),             # 0-15% below 252d high → 100%
    (25.0, 0.50),             # 15-25% below high → 50%
    (float("inf"), 0.00),     # >25% → 0% (extreme crash protection)
]

ADX_THRESHOLD = 36.0   # full-size allocation when ADX >= this; scales linearly below


def _wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ADX(14) via Wilder's smoothing."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    dm_plus  = (high - high.shift()).clip(lower=0).where((high - high.shift()) > (low.shift() - low), 0.0)
    dm_minus = (low.shift() - low).clip(lower=0).where((low.shift() - low) > (high - high.shift()), 0.0)
    alpha = 1.0 / period
    atr  = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus  = dm_plus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus = dm_minus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    di_plus  = 100 * plus  / atr.replace(0, float("nan"))
    di_minus = 100 * minus / atr.replace(0, float("nan"))
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, float("nan"))
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


SIGNAL_THRESHOLD = 15.0   # pct below 252d high: above → CASH, below → BUY_TQQQ
# Note: we go to CASH (not SQQQ) when pcthi > threshold because entering SQQQ
# at end-of-day after a crash is always late — the bounce destroys the position.
# The actual C2 strategy made +2.6% in April via tactical SQQQ entries that
# cannot be replicated mechanically with daily closing prices.


def build_signal_df(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """
    Signal: stage-based on distance from 252-day high.
      PercentHigh < 15%  → BUY_TQQQ (within normal correction range)
      PercentHigh >= 15% → CASH (go flat — avoid SQQQ timing losses)
    Also computes ADX(14) used as position-size reduction factor.
    """
    df = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100
    df["adx"]     = _wilder_adx(df)
    df["signal"]  = df["pcthi"].apply(
        lambda p: "BUY_TQQQ" if p < SIGNAL_THRESHOLD else "CASH"
    )
    return df


# ── Helpers ───────────────────────────────────────────────────────────────────

def _price_on(df: pd.DataFrame, date) -> float | None:
    if date in df.index:
        return float(df.loc[date, "close"])
    avail = df.index[df.index <= date]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def _stage_factor(pct_high: float) -> float:
    for max_pct, factor in STAGE_BANDS:
        if pct_high < max_pct:
            return factor
    return 0.0


# ── Core simulation ───────────────────────────────────────────────────────────

REENTRY_DAYS = 3   # consecutive days below SIGNAL_THRESHOLD before re-entering TQQQ


def run_backtest(sig_df: pd.DataFrame,
                 tqqq_df: pd.DataFrame,
                 sqqq_df: pd.DataFrame,
                 capital: float) -> list[dict]:
    """
    Cash/TQQQ rotation with re-entry confirmation:
    - Exit to CASH immediately when pcthi crosses above SIGNAL_THRESHOLD (same close).
    - Re-enter TQQQ only after pcthi stays below SIGNAL_THRESHOLD for REENTRY_DAYS consecutive days.
    This stops the whipsawing in/out of TQQQ when QQQ bounces around the threshold.
    Returns list of daily dicts.
    """
    tqqq_sh   = 0
    sqqq_sh   = 0
    cash      = capital
    daily     = []
    days_below = 0   # consecutive days pcthi has been below threshold
    in_tqqq   = True  # start invested (first signal is always BUY_TQQQ from early history)

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        sp = _price_on(sqqq_df, date)
        if tp is None or sp is None:
            continue

        port = tqqq_sh * tp + sqqq_sh * sp + cash

        close    = float(row["close"])
        pct_high = round(float(row.get("pcthi", 0.0)), 2)
        adx_val  = float(row.get("adx", ADX_THRESHOLD))
        adx_fac  = min(1.0, adx_val / ADX_THRESHOLD)

        # Update consecutive-days-below counter
        if pct_high < SIGNAL_THRESHOLD:
            days_below += 1
        else:
            days_below = 0

        # Determine regime: exit CASH immediately on first crossing above threshold;
        # re-enter TQQQ only after REENTRY_DAYS consecutive days back below threshold.
        if pct_high >= SIGNAL_THRESHOLD:
            in_tqqq = False
        elif days_below >= REENTRY_DAYS:
            in_tqqq = True

        sf       = _stage_factor(pct_high) if in_tqqq else 0.0
        combined = sf * adx_fac
        signal   = row["signal"] if in_tqqq else "CASH"

        tqqq_pct = combined if in_tqqq else 0.0
        sqqq_pct = 0.0  # never mechanically enter SQQQ — too late after crash

        new_tqqq = math.floor(port * tqqq_pct / tp) if tqqq_pct > 0 and tp > 0 else 0
        new_sqqq = math.floor(port * sqqq_pct / sp) if sqqq_pct > 0 and sp > 0 else 0

        cash    += (tqqq_sh - new_tqqq) * tp
        cash    += (sqqq_sh - new_sqqq) * sp
        tqqq_sh  = new_tqqq
        sqqq_sh  = new_sqqq

        port = round(tqqq_sh * tp + sqqq_sh * sp + cash, 2)

        daily.append({
            "date":      date,
            "signal":    signal,
            "close":     round(close, 2),
            "pct_high":  pct_high,
            "sf":        round(combined, 3),
            "adx":       round(adx_val, 1),
            "tqqq_pct":  round(tqqq_pct * 100, 0),
            "sqqq_pct":  round(sqqq_pct * 100, 0),
            "tqqq_sh":   tqqq_sh,
            "sqqq_sh":   sqqq_sh,
            "tp":        round(tp, 2),
            "sp":        round(sp, 2),
            "portfolio": port,
        })

    return daily


# ── Monthly return table ──────────────────────────────────────────────────────

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def monthly_returns(daily: list[dict], year: int) -> dict[int, float]:
    """Returns {month: pct_return} for the given year."""
    # Group by (year, month), find first and last portfolio value
    by_month: dict[tuple, list] = defaultdict(list)
    for d in daily:
        by_month[(d["date"].year, d["date"].month)].append(d)

    results = {}
    sorted_months = sorted(by_month.keys())

    for i, ym in enumerate(sorted_months):
        if ym[0] != year:
            continue
        bars = by_month[ym]
        # End of month value
        end_val = bars[-1]["portfolio"]
        # Start = end of prior month (or first bar if January)
        if i > 0:
            prev_ym   = sorted_months[i - 1]
            start_val = by_month[prev_ym][-1]["portfolio"]
        else:
            start_val = bars[0]["portfolio"]   # very first bar
        ret = (end_val - start_val) / start_val * 100 if start_val else 0.0
        results[ym[1]] = round(ret, 1)

    return results


def print_monthly(daily: list[dict], year: int,
                  qqq_df: pd.DataFrame, capital: float,
                  target: dict[int, float] | None = None) -> None:

    rets = monthly_returns(daily, year)
    yr_bars = [d for d in daily if d["date"].year == year]
    if not yr_bars:
        print(f"  No data for {year}"); return

    SEP = "=" * 110
    print(SEP)
    print(f"  DUAL STRATEGY BACKTEST — {year}  |  Capital: ${capital:,.0f}")
    print(SEP)

    # Header
    months = sorted(rets.keys())
    hdr = f"{'':12}"
    for m in months:
        hdr += f"  {MONTH_ABBR[m]:>8}"
    print(hdr)
    print("-" * 110)

    # Strategy row
    row_s = f"  {'Strategy':<10}"
    for m in months:
        r = rets[m]
        row_s += f"  {r:>+7.1f}%"
    print(row_s)

    # Target row (from screenshot)
    if target:
        row_t = f"  {'Target':<10}"
        for m in months:
            t = target.get(m)
            if t is not None:
                diff = rets[m] - t
                row_t += f"  {t:>+7.1f}%"
            else:
                row_t += f"  {'  N/A':>8}"
        print(row_t)

        # Diff row
        row_d = f"  {'Delta':<10}"
        for m in months:
            t = target.get(m)
            if t is not None:
                diff = rets[m] - t
                row_d += f"  {diff:>+7.1f}p"
            else:
                row_d += f"  {'':>8}"
        print(row_d)

    print("-" * 110)

    # Full year summary
    yr_start = yr_bars[0]["portfolio"]
    yr_end   = yr_bars[-1]["portfolio"]
    yr_ret   = round((yr_end - yr_start) / yr_start * 100, 1) if yr_start else 0.0

    qqq_yr = [d for d in qqq_df.index if d.year == year]
    qqq_ret = 0.0
    if qqq_yr:
        qqq_ret = round((float(qqq_df.loc[qqq_yr[-1], "close"]) /
                         float(qqq_df.loc[qqq_yr[0], "close"]) - 1) * 100, 1)

    print(f"\n  {year} full year: ${yr_start:,.0f} => ${yr_end:,.0f}  "
          f"P&L: ${yr_end-yr_start:+,.0f}  ({yr_ret:+.1f}%)  |  "
          f"QQQ: {qqq_ret:+.1f}%")
    print(SEP); print()

    # Detail table: monthly signal breakdown
    by_month: dict[tuple, list] = defaultdict(list)
    for d in yr_bars:
        by_month[(d["date"].year, d["date"].month)].append(d)

    print(f"  {'Month':<8} {'Sig':>8} {'TQQQ%':>7} {'SQQQ%':>7} "
          f"{'PerHi':>7} {'SF':>5}  Start Port      End Port    Return")
    print("-" * 110)
    sorted_yms = sorted(by_month.keys())
    for i, ym in enumerate(sorted_yms):
        if ym[0] != year:
            continue
        bars = by_month[ym]
        end_d = bars[-1]
        end_val = end_d["portfolio"]
        if i > 0:
            prev_ym   = sorted_yms[i - 1]
            start_val = by_month[prev_ym][-1]["portfolio"]
        else:
            start_val = bars[0]["portfolio"]
        ret   = round((end_val - start_val) / start_val * 100, 1) if start_val else 0.0
        # Most common signal in month
        sigs  = [d["signal"] for d in bars]
        sig_s = max(set(sigs), key=sigs.count)
        avg_tqqq = round(sum(d["tqqq_pct"] for d in bars) / len(bars), 0)
        avg_sqqq = round(sum(d["sqqq_pct"] for d in bars) / len(bars), 0)
        avg_ph   = round(sum(d["pct_high"] for d in bars) / len(bars), 1)
        avg_sf   = round(sum(d["sf"] for d in bars) / len(bars), 2)
        print(f"  {MONTH_ABBR[ym[1]]:<8} {sig_s:>8} {avg_tqqq:>6.0f}% "
              f"{avg_sqqq:>6.0f}% {avg_ph:>7.1f} {avg_sf:>5.2f}  "
              f"${start_val:>12,.0f}  ${end_val:>12,.0f}  {ret:>+6.1f}%")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

# 2025 Jan–Jul targets from screenshot
TARGET_2025 = {1: 2.8, 2: -3.5, 3: -21.2, 4: 2.6, 5: 17.7, 6: 21.2, 7: 5.4}


def main():
    ap = argparse.ArgumentParser(description="Dual Strategy monthly backtest")
    ap.add_argument("--year",    type=int,   default=2025)
    ap.add_argument("--all",     action="store_true", help="All available years")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    args = ap.parse_args()

    print("\nLoading data...")
    qqq  = _load_ohlcv(SIGNAL_TKR)
    tqqq = _load_ohlcv(BULL_ETF)
    sqqq = _load_ohlcv(BEAR_ETF)

    sig_df = build_signal_df(qqq)

    print("Running simulation...")
    daily = run_backtest(sig_df, tqqq, sqqq, args.capital)
    print()

    if args.all:
        years = sorted({d["date"].year for d in daily})
        for yr in years:
            target = TARGET_2025 if yr == 2025 else None
            print_monthly(daily, yr, qqq, args.capital, target)
    else:
        target = TARGET_2025 if args.year == 2025 else None
        print_monthly(daily, args.year, qqq, args.capital, target)


if __name__ == "__main__":
    main()
