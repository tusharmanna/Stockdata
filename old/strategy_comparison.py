"""
strategy_comparison.py — Month-by-month comparison of three approaches vs C2 target.

  QQQ           : Buy-and-hold QQQ benchmark
  TQQQ Strategy : Daily ADX-scaled rebalancing; CASH when QQQ >15% below 252d high
  TusharStrategy: Buy all-in TQQQ on signal, hold fixed shares until signal changes

Signal (both strategies):
  pctHigh = (252d-high - close) / 252d-high × 100
  pctHigh < 15%  => BUY_TQQQ
  pctHigh >= 15% => CASH  (3-day confirmation required to re-enter TQQQ after exit)

Data: loaded directly from yfinance (not the local DB) so any date range works.

Usage:
    python strategy_comparison.py                        # 2022-present, all years
    python strategy_comparison.py --year 2025
    python strategy_comparison.py --start 2020-01-01
    python strategy_comparison.py --capital 100000
"""

import argparse
import math
from collections import defaultdict

import pandas as pd
import yfinance as yf

from whitelight_strategy import DEFAULT_CAPITAL, HIGH_PERIOD, BULL_ETF, SIGNAL_TKR

DEFAULT_START = "2022-01-01"


def _load_yf(ticker: str, start: str) -> pd.DataFrame:
    """Download OHLCV from yfinance, return DataFrame indexed by date."""
    raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    if raw.empty:
        raise ValueError(f"No data returned for {ticker}")
    df = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]

# ── Constants ─────────────────────────────────────────────────────────────────

SIGNAL_THRESHOLD = 15.0
REENTRY_DAYS     = 3
ADX_THRESHOLD    = 36.0
STAGE_BANDS      = [(15.0, 1.00), (25.0, 0.50), (float("inf"), 0.00)]

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# C2 Collective2 actual monthly returns (from screenshot)
TARGET_RETURNS = {
    2023: {1:12.8, 2:-5.1, 3:7.3,  4:-0.9, 5:23.8, 6:12.1, 7:10.1, 8:-1.8, 9:-6.1, 10:-2.9, 11:9.7,  12:3.6},
    2024: {1:7.3,  2:4.5,  3:-0.6, 4:-8.6, 5:19.2, 6:1.7,  7:-3.3, 8:1.0,  9:-4.0, 10:-0.7, 11:-9.1, 12:5.2},
    2025: {1:2.8,  2:-3.5, 3:-21.2,4:2.6,  5:17.7, 6:21.2, 7:5.4,  8:4.0,  9:11.5, 10:-0.7, 11:1.4,  12:-1.8},
    2026: {1:-4.9, 2:-4.9, 3:-1.6, 4:23.8},
}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    dm_plus  = (high - high.shift()).clip(lower=0).where((high - high.shift()) > (low.shift() - low), 0.0)
    dm_minus = (low.shift() - low).clip(lower=0).where((low.shift() - low) > (high - high.shift()), 0.0)
    alpha = 1.0 / period
    atr   = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus  = dm_plus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus = dm_minus.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    di_p  = 100 * plus  / atr.replace(0, float("nan"))
    di_m  = 100 * minus / atr.replace(0, float("nan"))
    dx    = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, float("nan"))
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
    return df


# ── Strategy 1: TQQQ Strategy (daily ADX-scaled rebalancing) ──────────────────

def run_tqqq_strategy(sig_df: pd.DataFrame,
                      tqqq_df: pd.DataFrame,
                      capital: float) -> list[dict]:
    """
    Each day: compute target allocation = StageFactor × ADX_factor, rebalance to it.
    Exit to CASH immediately when pcthi >= SIGNAL_THRESHOLD.
    Re-enter only after REENTRY_DAYS consecutive days below threshold.
    """
    tqqq_sh    = 0
    cash       = capital
    daily      = []
    days_below = 0
    in_tqqq    = True

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        if tp is None:
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

        new_sh  = math.floor(port * tqqq_pct / tp) if tqqq_pct > 0 and tp > 0 else 0
        cash   += (tqqq_sh - new_sh) * tp
        tqqq_sh = new_sh
        port    = round(tqqq_sh * tp + cash, 2)

        daily.append({"date": date, "portfolio": port,
                      "signal": "BUY_TQQQ" if in_tqqq else "CASH"})

    return daily


# ── Strategy 2: TusharStrategy (buy-and-hold until signal changes) ────────────

def run_modified_strategy(sig_df: pd.DataFrame,
                          tqqq_df: pd.DataFrame,
                          capital: float) -> list[dict]:
    """
    Buy 100% of portfolio into TQQQ when regime turns BUY_TQQQ; hold fixed shares.
    Sell all TQQQ immediately when pcthi crosses above SIGNAL_THRESHOLD.
    Re-enter after REENTRY_DAYS consecutive days below threshold.

    Unlike the TQQQ Strategy, no daily rebalancing — shares are held constant between
    regime changes, so the effective % exposure rises with price (mimicking C2 behavior).
    """
    tqqq_sh      = 0
    cash         = capital
    daily        = []
    days_below   = 0
    in_tqqq      = True   # start in TQQQ regime (pcthi is tiny at data start)
    prev_in_tqqq = False  # triggers initial buy on first bar

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        if tp is None:
            continue

        pct_high = round(float(row.get("pcthi", 0.0)), 2)

        # Update regime
        if pct_high >= SIGNAL_THRESHOLD:
            days_below = 0
            in_tqqq    = False
        else:
            days_below += 1
            if days_below >= REENTRY_DAYS:
                in_tqqq = True

        # Trade only on regime change
        if in_tqqq and not prev_in_tqqq:
            # Enter: buy as many TQQQ shares as cash allows
            new_sh  = math.floor(cash / tp) if tp > 0 else 0
            cash   -= new_sh * tp
            tqqq_sh = new_sh
        elif not in_tqqq and prev_in_tqqq:
            # Exit: liquidate entire TQQQ position
            cash   += tqqq_sh * tp
            tqqq_sh = 0

        prev_in_tqqq = in_tqqq
        port = round(tqqq_sh * tp + cash, 2)

        daily.append({"date": date, "portfolio": port,
                      "signal": "BUY_TQQQ" if in_tqqq else "CASH"})

    return daily


# ── Monthly return calculator ─────────────────────────────────────────────────

def monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    """Returns {(year, month): pct_return} for all months covered."""
    by_month: dict[tuple, list] = defaultdict(list)
    for d in daily:
        by_month[(d["date"].year, d["date"].month)].append(d["portfolio"])

    sorted_months = sorted(by_month.keys())
    results: dict[tuple, float] = {}
    for i, ym in enumerate(sorted_months):
        end_val   = by_month[ym][-1]
        start_val = by_month[sorted_months[i - 1]][-1] if i > 0 else by_month[ym][0]
        results[ym] = round((end_val - start_val) / start_val * 100, 1) if start_val else 0.0
    return results


def qqq_monthly_rets(qqq_df: pd.DataFrame) -> dict[tuple, float]:
    """Returns {(year, month): pct_return} from QQQ close prices."""
    by_month: dict[tuple, list] = defaultdict(list)
    for date, row in qqq_df.iterrows():
        by_month[(date.year, date.month)].append(float(row["close"]))

    sorted_months = sorted(by_month.keys())
    results: dict[tuple, float] = {}
    for i, ym in enumerate(sorted_months):
        end_price   = by_month[ym][-1]
        start_price = by_month[sorted_months[i - 1]][-1] if i > 0 else by_month[ym][0]
        results[ym] = round((end_price - start_price) / start_price * 100, 1) if start_price else 0.0
    return results


# ── Comparison table printer ──────────────────────────────────────────────────

def _yr_return(rets: dict[tuple, float], year: int) -> float:
    product = 1.0
    for (y, m), r in sorted(rets.items()):
        if y == year:
            product *= 1 + r / 100
    return round((product - 1) * 100, 1)


def _target_yr_return(year: int) -> float | None:
    tgt = TARGET_RETURNS.get(year)
    if not tgt:
        return None
    product = 1.0
    for r in tgt.values():
        product *= 1 + r / 100
    return round((product - 1) * 100, 1)


def _pct(val: float | None) -> str:
    if val is None:
        return "   N/A  "
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%".rjust(8)


def _dol(val: float | None) -> str:
    if val is None:
        return "        N/A"
    return f"${val:>10,.0f}"


def print_comparison(qqq_r:  dict[tuple, float],
                     tqqq_r: dict[tuple, float],
                     mod_r:  dict[tuple, float],
                     years:  list[int],
                     capital: float) -> None:

    W   = 140
    SEP = "=" * W
    DIV = "-" * W

    # Running portfolios — all start at capital on first bar; C2 starts at capital on its first data month
    qqq_port  = capital
    tqqq_port = capital
    mod_port  = capital
    c2_port   = capital
    c2_started = False

    print(f"\n{SEP}")
    print(f"  STRATEGY COMPARISON  |  Capital: ${capital:,.0f}")
    print(f"  Signal: QQQ >15% below 252d high => CASH | <15% => TQQQ")
    print(SEP)
    print(f"  {'Period':<10}  "
          f"{'QQQ (Buy & Hold)':^20}  "
          f"{'TQQQ Strategy (Daily Rebal)':^26}  "
          f"{'TusharStrategy (Buy & Hold)':^22}  "
          f"{'C2 Target (Actual)':^20}")
    print(f"  {'':10}  "
          f"{'%Ret':>8}  {'Portfolio':>11}  "
          f"{'%Ret':>8}  {'Portfolio':>11}  "
          f"  {'%Ret':>8}  {'Portfolio':>11}  "
          f"{'%Ret':>8}  {'Portfolio':>11}")
    print(DIV)

    for year in years:
        months_in_year = sorted(ym for ym in qqq_r if ym[0] == year)
        if not months_in_year:
            continue

        yr_q_start   = qqq_port
        yr_tqqq_start = tqqq_port
        yr_mod_start  = mod_port
        yr_c2_start   = c2_port if c2_started else None

        print(f"\n  -- {year} {'-'*126}")

        for ym in months_in_year:
            m   = ym[1]
            q   = qqq_r.get(ym)
            ts  = tqqq_r.get(ym)
            ms  = mod_r.get(ym)
            tgt = TARGET_RETURNS.get(year, {}).get(m)

            if q  is not None: qqq_port  *= 1 + q  / 100
            if ts is not None: tqqq_port *= 1 + ts / 100
            if ms is not None: mod_port  *= 1 + ms / 100
            if tgt is not None:
                if not c2_started:
                    c2_port    = capital
                    c2_started = True
                    yr_c2_start = capital
                c2_port *= 1 + tgt / 100

            c2_dol = _dol(c2_port) if c2_started else _dol(None)

            print(f"  {MONTH_ABBR[m]:<10}  "
                  f"{_pct(q)}  {_dol(qqq_port)}  "
                  f"{_pct(ts)}  {_dol(tqqq_port)}  "
                  f"  {_pct(ms)}  {_dol(mod_port)}  "
                  f"{_pct(tgt)}  {c2_dol}")

        # Year-end summary row
        q_yr   = round((qqq_port  / yr_q_start    - 1) * 100, 1)
        ts_yr  = round((tqqq_port / yr_tqqq_start  - 1) * 100, 1)
        ms_yr  = round((mod_port  / yr_mod_start   - 1) * 100, 1)
        c2_yr  = round((c2_port   / yr_c2_start    - 1) * 100, 1) if yr_c2_start else None

        print(DIV)
        print(f"  {'FY '+str(year):<10}  "
              f"{_pct(q_yr)}  {_dol(qqq_port)}  "
              f"{_pct(ts_yr)}  {_dol(tqqq_port)}  "
              f"  {_pct(ms_yr)}  {_dol(mod_port)}  "
              f"{_pct(c2_yr)}  {_dol(c2_port) if c2_started else _dol(None)}")
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Strategy comparison: TQQQ Strategy vs TusharStrategy vs QQQ")
    ap.add_argument("--year",    type=int,   default=None,          help="Single year (default: all)")
    ap.add_argument("--start",   type=str,   default=DEFAULT_START, help="Start date YYYY-MM-DD")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL)
    args = ap.parse_args()

    print(f"\nLoading data from {args.start} via yfinance...")
    qqq  = _load_yf(SIGNAL_TKR, args.start)
    tqqq = _load_yf(BULL_ETF,   args.start)

    sig_df = build_signal_df(qqq)

    print("Running TQQQ Strategy (daily rebalancing)...")
    tqqq_daily = run_tqqq_strategy(sig_df, tqqq, args.capital)

    print("Running TusharStrategy (buy and hold)...")
    mod_daily  = run_modified_strategy(sig_df, tqqq, args.capital)
    print()

    qqq_r  = qqq_monthly_rets(qqq)
    tqqq_r = monthly_rets(tqqq_daily)
    mod_r  = monthly_rets(mod_daily)

    # Determine which years to show
    all_years = sorted({ym[0] for ym in tqqq_r})
    years = [args.year] if args.year else all_years

    # Only show months that exist in our DB (QQQ data)
    print_comparison(qqq_r, tqqq_r, mod_r, years, args.capital)


if __name__ == "__main__":
    main()
