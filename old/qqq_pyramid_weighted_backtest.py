"""QQQ weighted pyramid 3/35 backtest: 25/35/40 tier weights vs equal thirds.

Tier conditions (same as qqq_pyramid_signal.py):
  T1: Close > MA3   -> weight w1
  T2: Close > MA35  -> weight w2
  T3: MA3 > MA35    -> weight w3

Equal thirds (1/3 each) is the existing champion; this script tests
weights (0.25, 0.35, 0.40) — less on the noisy fast tier, more on the
confirmed crossover — and reports year-by-year results vs buy & hold.
"""

import sys

import numpy as np
import pandas as pd

CSV_PATH = "QQQ_2010_2026.csv"
FAST = 3
SLOW = 35
LEVERAGE = 3.0
TRADING_DAYS = 252

EQUAL_WEIGHTS = (1 / 3, 1 / 3, 1 / 3)
NEW_WEIGHTS = (0.25, 0.35, 0.40)


def load_data(path=CSV_PATH):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except FileNotFoundError:
        sys.exit(f"ERROR: {path} not found.")
    df = df.sort_values("Date").reset_index(drop=True)
    assert df["Close"].notna().all(), "NaN in Close"
    return df


def pyramid_fraction(close, fast=FAST, slow=SLOW, weights=EQUAL_WEIGHTS):
    """Weighted position fraction from the three tier conditions."""
    w1, w2, w3 = weights
    assert np.isclose(w1 + w2 + w3, 1.0), "weights must sum to 1"
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    t1 = (close > ma_fast).astype(float)
    t2 = (close > ma_slow).astype(float)
    t3 = (ma_fast > ma_slow).astype(float)
    frac = w1 * t1 + w2 * t2 + w3 * t3
    frac[ma_slow.isna()] = 0.0  # cash until warmup completes
    return frac


def backtest(close, position, leverage):
    """Daily strategy returns from position-fraction series (causal)."""
    ret = close.pct_change().fillna(0.0)
    return (position * leverage).shift(1).fillna(0.0) * ret


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates, "ret": ret}).set_index("date")
    df["year"] = df.index.year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


def metrics(ret):
    equity = (1.0 + ret).cumprod()
    total = equity.iloc[-1] - 1.0
    sharpe = ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan
    max_dd = (equity / equity.cummax() - 1.0).min()
    return {"total": total, "sharpe": sharpe, "max_dd": max_dd,
            "final": equity.iloc[-1]}


def main():
    df = load_data()
    close = df["Close"]
    dates = df["Date"]

    print(f"QQQ Weighted Pyramid Backtest ({FAST}/{SLOW} MAs, 3x leverage)")
    print(f"Data: {dates.iloc[0].date()} to {dates.iloc[-1].date()}")
    print(f"Initial capital: $100,000\n")

    bh_ret = close.pct_change().fillna(0.0)

    eq_pos = pyramid_fraction(close, weights=EQUAL_WEIGHTS)
    eq_ret = backtest(close, eq_pos, LEVERAGE)

    wt_pos = pyramid_fraction(close, weights=NEW_WEIGHTS)
    wt_ret = backtest(close, wt_pos, LEVERAGE)

    bh_m = metrics(bh_ret)
    eq_m = metrics(eq_ret)
    wt_m = metrics(wt_ret)

    bh_a = annual_returns(dates, bh_ret)
    eq_a = annual_returns(dates, eq_ret)
    wt_a = annual_returns(dates, wt_ret)

    print("=" * 78)
    print("YEAR-BY-YEAR RETURNS")
    print("=" * 78)
    print(f"{'Year':<6} {'QQQ B&H':>10} {'Equal 33/33/33':>16} {'Weighted 25/35/40':>18} {'Wt - Eq':>10}")
    print("-" * 78)
    for year in bh_a.index:
        diff = wt_a[year] - eq_a[year]
        print(f"{year:<6d} {bh_a[year]:>9.1%} {eq_a[year]:>15.1%} {wt_a[year]:>17.1%} {diff:>9.1%}")
    print("-" * 78)
    print(f"{'TOTAL':<6} {bh_m['total']:>9.1%} {eq_m['total']:>15.1%} {wt_m['total']:>17.1%}")
    print("=" * 78)

    print("\nWEALTH PROGRESSION ($100,000 start)")
    print("=" * 78)
    print(f"{'QQQ B&H':<28} ${bh_m['final'] * 100000:>14,.0f}")
    print(f"{'Equal 33/33/33 pyramid':<28} ${eq_m['final'] * 100000:>14,.0f}")
    print(f"{'Weighted 25/35/40 pyramid':<28} ${wt_m['final'] * 100000:>14,.0f}")
    print("=" * 78)

    print("\nSUMMARY METRICS")
    print("=" * 78)
    print(f"{'Metric':<16} {'QQQ B&H':>12} {'Equal 33/33/33':>16} {'Weighted 25/35/40':>18}")
    print("-" * 78)
    print(f"{'Total Return':<16} {bh_m['total']:>11.1%} {eq_m['total']:>15.1%} {wt_m['total']:>17.1%}")
    print(f"{'Sharpe Ratio':<16} {bh_m['sharpe']:>12.2f} {eq_m['sharpe']:>16.2f} {wt_m['sharpe']:>18.2f}")
    print(f"{'Max Drawdown':<16} {bh_m['max_dd']:>11.1%} {eq_m['max_dd']:>15.1%} {wt_m['max_dd']:>17.1%}")
    print("=" * 78)

    wt_vs_eq = (wt_a > eq_a).sum()
    wt_vs_bh = (wt_a > bh_a).sum()
    n = len(wt_a)
    print(f"\nWeighted 25/35/40 beats equal thirds in {wt_vs_eq}/{n} years, "
          f"beats B&H in {wt_vs_bh}/{n} years")

    if wt_m["total"] > eq_m["total"]:
        verdict = "WEIGHTED 25/35/40 WINS on total return"
    else:
        verdict = "EQUAL THIRDS WINS on total return"
    if wt_m["sharpe"] > eq_m["sharpe"]:
        verdict += "; weighted also wins on Sharpe"
    else:
        verdict += "; equal thirds wins on Sharpe"
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
