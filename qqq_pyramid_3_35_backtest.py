"""QQQ Pyramid 3/35 strategy backtest (2010-2026).

Uses the exact signal logic from qqq_pyramid_signal.py:
- Tier 1: Close > MA3
- Tier 2: Close > MA35
- Tier 3: MA3 > MA35
- Position fraction = (T1 + T2 + T3) / 3

Shows year-by-year results with 3x leverage against buy-and-hold.
"""

import sys
import pandas as pd
import numpy as np

CSV_PATH = "QQQ_2010_2026.csv"
FAST = 3
SLOW = 35
LEVERAGE = 3.0
TRADING_DAYS = 252


def load_data(path=CSV_PATH):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except FileNotFoundError:
        sys.exit(f"ERROR: {path} not found.")
    df = df.sort_values("Date").reset_index(drop=True)
    assert df["Close"].notna().all(), "NaN in Close"
    return df


def pyramid_fraction(close, fast=FAST, slow=SLOW):
    """Position fraction 0, 1/3, 2/3, 1 from the three tier conditions."""
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    t1 = (close > ma_fast).astype(float)
    t2 = (close > ma_slow).astype(float)
    t3 = (ma_fast > ma_slow).astype(float)
    frac = (t1 + t2 + t3) / 3.0
    frac[ma_slow.isna()] = 0.0
    return frac


def backtest(close, position, leverage):
    """Daily strategy returns from position-fraction series (causal)."""
    ret = close.pct_change().fillna(0.0)
    return (position * leverage).shift(1).fillna(0.0) * ret


def annual_returns(dates, ret):
    """Group returns by year and compute annual return."""
    df = pd.DataFrame({"date": dates, "ret": ret}).set_index("date")
    df["year"] = df.index.year
    annual = df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)
    return annual


def metrics(strat_ret, bh_ret):
    """Compute strategy metrics."""
    strat_eq = (1.0 + strat_ret).cumprod()
    bh_eq = (1.0 + bh_ret).cumprod()

    strat_total = strat_eq.iloc[-1] - 1.0
    bh_total = bh_eq.iloc[-1] - 1.0

    strat_sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(TRADING_DAYS) if strat_ret.std() > 0 else np.nan
    bh_sharpe = bh_ret.mean() / bh_ret.std() * np.sqrt(TRADING_DAYS) if bh_ret.std() > 0 else np.nan

    strat_maxdd = (strat_eq / strat_eq.cummax() - 1.0).min()
    bh_maxdd = (bh_eq / bh_eq.cummax() - 1.0).min()

    return {
        "strat_total": strat_total,
        "bh_total": bh_total,
        "strat_sharpe": strat_sharpe,
        "bh_sharpe": bh_sharpe,
        "strat_maxdd": strat_maxdd,
        "bh_maxdd": bh_maxdd,
        "strat_final_equity": strat_eq.iloc[-1],
        "bh_final_equity": bh_eq.iloc[-1],
    }


def main():
    df = load_data()
    close = df["Close"]
    dates = df["Date"]

    print(f"QQQ Pyramid 3/35 Strategy Backtest (2010-2026)")
    print(f"Data: {dates.iloc[0].date()} to {dates.iloc[-1].date()}")
    print(f"Initial capital: $100,000\n")

    # Buy & Hold
    bh_ret = close.pct_change().fillna(0.0)

    # Pyramid 3/35 with 3x leverage
    pyr_pos = pyramid_fraction(close, FAST, SLOW)
    pyr_ret = backtest(close, pyr_pos, LEVERAGE)

    # Metrics
    m = metrics(pyr_ret, bh_ret)

    # Year-by-year
    bh_annual = annual_returns(dates, bh_ret)
    pyr_annual = annual_returns(dates, pyr_ret)

    # Wealth progression
    bh_wealth = 100000 * (1.0 + bh_ret).cumprod()
    pyr_wealth = 100000 * (1.0 + pyr_ret).cumprod()

    print("=" * 70)
    print("YEAR-BY-YEAR RETURNS")
    print("=" * 70)
    print(f"{'Year':<6} {'QQQ B&H':>12} {'Pyramid 3/35 (3x)':>18} {'Pyramid Outperformance':>22}")
    print("-" * 70)

    for year in bh_annual.index:
        bh_ret_pct = bh_annual[year]
        pyr_ret_pct = pyr_annual[year]
        outperf = pyr_ret_pct - bh_ret_pct
        print(f"{year:<6d} {bh_ret_pct:>11.1%} {pyr_ret_pct:>17.1%} {outperf:>21.1%}")

    print("-" * 70)
    print(f"{'TOTAL':<6} {m['bh_total']:>11.1%} {m['strat_total']:>17.1%}")
    print("=" * 70)

    print("\nWEALTH PROGRESSION")
    print("=" * 70)
    print(f"{'Start':<20} $100,000")
    print(f"{'QQQ B&H Final':<20} ${m['bh_final_equity']*100000:,.0f}")
    print(f"{'Pyramid 3/35 Final':<20} ${m['strat_final_equity']*100000:,.0f}")
    print(f"{'Advantage':<20} ${(m['strat_final_equity'] - m['bh_final_equity'])*100000:,.0f}")
    print("=" * 70)

    print("\nSUMMARY METRICS")
    print("=" * 70)
    print(f"{'Metric':<25} {'QQQ B&H':>15} {'Pyramid 3/35':>15}")
    print("-" * 70)
    print(f"{'Total Return':<25} {m['bh_total']:>14.1%} {m['strat_total']:>14.1%}")
    print(f"{'Sharpe Ratio':<25} {m['bh_sharpe']:>15.2f} {m['strat_sharpe']:>15.2f}")
    print(f"{'Max Drawdown':<25} {m['bh_maxdd']:>14.1%} {m['strat_maxdd']:>14.1%}")
    print("=" * 70)

    # Win rate
    wins = (pyr_annual > bh_annual).sum()
    total = len(pyr_annual)
    print(f"\nPyramid 3/35 wins {wins}/{total} years ({wins*100//total}%)")


if __name__ == "__main__":
    main()
