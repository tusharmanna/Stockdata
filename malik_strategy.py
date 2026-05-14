"""
malik_strategy.py  --  Malik Strategy: Dynamic TQQQ/SQQQ Position Trading

STRATEGY OVERVIEW
-----------------
7 trading systems across TQQQ (3x long) and SQQQ (3x inverse short):
  - 1 Momentum LONG (TQQQ) - rides strong uptrends with heavy position
  - 3 Mean Reversion LONG (TQQQ) - buy dips in uptrends
  - 1 Mean Reversion SHORT (SQQQ) - short oversold conditions
  - 2 Momentum SHORT (SQQQ) - fade strong downtrends

SIGNALS
-------
  - Trend detection: 50-day and 250-day moving averages
  - Momentum: Bollinger Bands (20-day, 2 std dev)
  - Position sizing: Based on how extended NDX is from MAs
  - Average: ~2 trades/week, ~10 trades/month

USAGE
-----
  python malik_strategy.py                    # today's signal
  python malik_strategy.py --backtest --all   # full history backtest
  python malik_strategy.py --backtest --year 2025
"""

import argparse
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

# -- Constants -----------------------------------------------------------------
QQQ_TICKER        = "QQQ"  # Proxy for NDX
TQQQ_TICKER       = "TQQQ"
SQQQ_TICKER       = "SQQQ"
DEFAULT_CAPITAL   = 100_000.0
DATA_START        = "2015-01-01"

# Moving averages and Bollinger Bands
MA50_PERIOD       = 50
MA250_PERIOD      = 250
BB_PERIOD         = 20
BB_STD_DEV        = 2.0

# Position sizing thresholds (% from moving average)
EXTENSION_LIGHT   = 3.0    # 0-3% extended: light position (0.25x base)
EXTENSION_NORMAL  = 8.0    # 3-8% extended: normal position (0.5x base)
EXTENSION_HEAVY   = 15.0   # 8-15% extended: heavy position (0.75x base)
EXTENSION_EXTREME = 20.0   # 15%+ extended: extreme position (1.0x base)

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


# -- Signal computation -------------------------------------------------------

def compute_signals(qqq_df: pd.DataFrame, tqqq_df: pd.DataFrame, sqqq_df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate Malik strategy signals for TQQQ and SQQQ positions.

    Returns:
      DataFrame with columns:
        - regime: 'TQQQ', 'SQQQ', or 'CASH'
        - position_size: 0.0 to 1.0 (fraction of capital)
        - extension: % NDX is extended from 50-MA
        - momentum: True if in BB momentum phase
    """
    # Align all data to common dates
    common = qqq_df.index.intersection(tqqq_df.index).intersection(sqqq_df.index)
    qqq = qqq_df.loc[common].copy()
    tqqq = tqqq_df.loc[common].copy()
    sqqq = sqqq_df.loc[common].copy()

    # Compute moving averages and Bollinger Bands for QQQ (NDX proxy)
    qqq["ma50"] = qqq["close"].rolling(MA50_PERIOD, min_periods=1).mean()
    qqq["ma250"] = qqq["close"].rolling(MA250_PERIOD, min_periods=1).mean()
    qqq["bb_mid"] = qqq["close"].rolling(BB_PERIOD, min_periods=1).mean()
    qqq["bb_std"] = qqq["close"].rolling(BB_PERIOD, min_periods=1).std()
    qqq["bb_upper"] = qqq["bb_mid"] + BB_STD_DEV * qqq["bb_std"]
    qqq["bb_lower"] = qqq["bb_mid"] - BB_STD_DEV * qqq["bb_std"]

    # Compute TQQQ moving averages for breakout detection
    tqqq["ma200"] = tqqq["close"].rolling(200, min_periods=1).mean()

    # Calculate extension: how far NDX (QQQ) is from 50-MA
    qqq["extension"] = (qqq["close"] - qqq["ma50"]) / qqq["ma50"] * 100
    qqq["extension_abs"] = qqq["extension"].abs()

    # Momentum phase: when price breaks out of Bollinger Bands
    qqq["momentum"] = (qqq["close"] > qqq["bb_upper"]) | (qqq["close"] < qqq["bb_lower"])

    # Determine regime and position size
    regime_list = []
    pos_size_list = []

    for i, (dt, row) in enumerate(qqq.iterrows()):
        close = row["close"]
        ma50 = row["ma50"]
        ma250 = row["ma250"]
        extension = row["extension"]
        extension_abs = row["extension_abs"]
        momentum = row["momentum"]

        # Trend determination
        in_uptrend = (ma50 > ma250) and (close > ma50)
        in_downtrend = (ma50 < ma250) or (close < ma50)

        # Position sizing based on extension
        if extension_abs < EXTENSION_LIGHT:
            pos_mult = 0.25
        elif extension_abs < EXTENSION_NORMAL:
            pos_mult = 0.50
        elif extension_abs < EXTENSION_HEAVY:
            pos_mult = 0.75
        else:
            pos_mult = 1.0

        # Boost position if in momentum phase
        if momentum:
            pos_mult = min(1.0, pos_mult * 1.3)

        # Determine regime based on trend
        if in_uptrend:
            regime = "TQQQ"
            pos_size = pos_mult
        elif in_downtrend:
            regime = "SQQQ"
            pos_size = pos_mult
        else:
            regime = "CASH"
            pos_size = 0.0

        regime_list.append(regime)
        pos_size_list.append(pos_size)

    qqq["regime"] = regime_list
    qqq["position_size"] = pos_size_list

    return qqq


# -- Backtest engine -----------------------------------------------------------

def _price_on(df: pd.DataFrame, dt) -> float | None:
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest_malik(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame, sqqq_df: pd.DataFrame,
                       capital: float) -> list[dict]:
    """Backtest Malik strategy with position sizing."""
    tqqq_shares = sqqq_shares = 0
    cash = capital
    daily = []
    prev_regime = "CASH"

    for dt, row in sig_df.iterrows():
        tqqq_p = _price_on(tqqq_df, dt)
        sqqq_p = _price_on(sqqq_df, dt)
        if tqqq_p is None or sqqq_p is None:
            continue

        regime = row["regime"]
        pos_size = float(row["position_size"])

        # Exit old position
        if prev_regime == "TQQQ" and regime != "TQQQ":
            cash += tqqq_shares * tqqq_p
            tqqq_shares = 0
        elif prev_regime == "SQQQ" and regime != "SQQQ":
            cash += sqqq_shares * sqqq_p
            sqqq_shares = 0

        # Enter new position
        if regime == "TQQQ" and prev_regime != "TQQQ":
            ns = math.floor(cash * pos_size / tqqq_p) if tqqq_p > 0 else 0
            cash -= ns * tqqq_p
            tqqq_shares = ns
        elif regime == "SQQQ" and prev_regime != "SQQQ":
            ns = math.floor(cash * pos_size / sqqq_p) if sqqq_p > 0 else 0
            cash -= ns * sqqq_p
            sqqq_shares = ns
        elif regime == "CASH":
            tqqq_shares = sqqq_shares = 0

        prev_regime = regime
        port = round(tqqq_shares * tqqq_p + sqqq_shares * sqqq_p + cash, 2)
        daily.append({
            "date": dt,
            "portfolio": port,
            "regime": regime,
            "pos_size": pos_size,
            "tqqq_shares": tqqq_shares,
            "sqqq_shares": sqqq_shares,
        })
    return daily


def run_buyhold_qqq(qqq_df: pd.DataFrame, capital: float) -> list[dict]:
    """Buy-and-hold QQQ (proxy for comparison)."""
    shares = 0
    cash = capital
    daily = []
    for i, (dt, row) in enumerate(qqq_df.iterrows()):
        p = float(row["close"])
        if i == 0:
            shares = math.floor(cash / p) if p > 0 else 0
            cash -= shares * p
        daily.append({"date": dt, "portfolio": round(shares * p + cash, 2),
                      "regime": "HOLD", "pos_size": 1.0})
    return daily


# -- Reporting -----------------------------------------------------------------

def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i - 1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(x):
    return f"{x:+.1f}%" if x is not None else "—"


def print_backtest(daily_malik: list[dict], daily_qqq: list[dict], years: list[int],
                   capital: float) -> None:
    """Print backtest results."""
    r_malik = _monthly_rets(daily_malik)
    r_qqq = _monthly_rets(daily_qqq)

    W = 65
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  Malik Strategy Backtest  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_malik = cum_qqq = capital

    for year in years:
        ym0 = cum_malik
        yq0 = cum_qqq

        print(f"  -- {year} " + "-" * (W - 10))
        print(f"  {'Month':<7} {'QQQ B&H':>10} {'Malik':>10}")
        print(DIV)

        for m in range(1, 13):
            ym = (year, m)
            qqq = r_qqq.get(ym)
            malik = r_malik.get(ym)

            if qqq: cum_qqq *= 1 + qqq / 100
            if malik: cum_malik *= 1 + malik / 100

            print(f"  {MONTHS[m]:<7} {_fmt(qqq):>10} {_fmt(malik):>10}")

        fy_qqq = round((cum_qqq / yq0 - 1) * 100, 1)
        fy_malik = round((cum_malik / ym0 - 1) * 100, 1)
        yr_totals.append((year, fy_qqq, fy_malik))
        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_qqq):>10} {_fmt(fy_malik):>10}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_qqq = round((cum_qqq / capital - 1) * 100, 1)
        ov_malik = round((cum_malik / capital - 1) * 100, 1)

        print(f"  {'Total %':<7} {_fmt(ov_qqq):>10} {_fmt(ov_malik):>10}")
        print(f"  {'CAGR':<7} {_fmt(cagr(cum_qqq)):>10} {_fmt(cagr(cum_malik)):>10}")
        print(f"\n  Final values:  QQQ B&H ${cum_qqq:,.0f}  |  Malik ${cum_malik:,.0f}")
        print(SEP)
    print()


def print_daily_signal(sig_df: pd.DataFrame) -> None:
    row = sig_df.iloc[-1]
    today = sig_df.index[-1].date()
    close = float(row["close"])
    ma50 = float(row["ma50"])
    ma250 = float(row["ma250"])
    extension = float(row["extension"])
    regime = row["regime"]
    pos_size = float(row["position_size"])

    W = 60
    SEP = "=" * W
    print(f"\n{SEP}")
    print(f"  Malik Signal: {today}")
    print(f"{SEP}")
    print(f"  QQQ Close:     ${close:>8.2f}")
    print(f"  50-day MA:     ${ma50:>8.2f}")
    print(f"  250-day MA:    ${ma250:>8.2f}")
    print(f"  Extension:     {extension:>8.1f}%")
    print(f"  Position:      {pos_size:>8.1%}")
    print(f"  Regime:        {regime}")
    print(SEP)


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capital",  type=float, default=DEFAULT_CAPITAL,
                    help="Portfolio capital (default: 100000)")
    ap.add_argument("--backtest", action="store_true",
                    help="Run backtest (default: today's signal)")
    ap.add_argument("--all",      action="store_true",
                    help="Backtest all years")
    ap.add_argument("--year",     type=int,
                    help="Backtest specific year")
    args = ap.parse_args()

    print("\nLoading data...")
    qqq_df = _load(QQQ_TICKER, DATA_START)
    tqqq_df = _load(TQQQ_TICKER, DATA_START)
    sqqq_df = _load(SQQQ_TICKER, DATA_START)

    print("Computing Malik signals...")
    sig = compute_signals(qqq_df, tqqq_df, sqqq_df)

    if args.backtest:
        print("Running backtest...")
        daily_malik = run_backtest_malik(sig, tqqq_df, sqqq_df, args.capital)
        daily_qqq = run_buyhold_qqq(sig, args.capital)

        if args.all:
            years = sorted(set(d["date"].year for d in daily_malik if d["date"].year >= 2015))
        elif args.year:
            years = [args.year]
        else:
            years = [date.today().year]

        print_backtest(daily_malik, daily_qqq, years, args.capital)
    else:
        print_daily_signal(sig)


if __name__ == "__main__":
    main()
