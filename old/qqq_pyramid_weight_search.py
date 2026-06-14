"""Grid search over pyramid tier weights for the QQQ 3/35 strategy.

Sweeps all (w1, w2, w3) combinations in 5% steps with w1+w2+w3 = 1:
  T1: Close > MA3   -> w1
  T2: Close > MA35  -> w2
  T3: MA3 > MA35    -> w3

Ranks by total return and Sharpe (3x leverage, 2010-2026), then prints
the year-by-year table for the best-return weights vs the 25/35/40 and
equal-thirds baselines.
"""

import sys

import numpy as np
import pandas as pd

CSV_PATH = "QQQ_2010_2026.csv"
FAST = 3
SLOW = 35
LEVERAGE = 3.0
TRADING_DAYS = 252
STEP = 0.05


def load_data(path=CSV_PATH):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except FileNotFoundError:
        sys.exit(f"ERROR: {path} not found.")
    df = df.sort_values("Date").reset_index(drop=True)
    assert df["Close"].notna().all(), "NaN in Close"
    return df


def tier_signals(close, fast=FAST, slow=SLOW):
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    t1 = (close > ma_fast).astype(float)
    t2 = (close > ma_slow).astype(float)
    t3 = (ma_fast > ma_slow).astype(float)
    warmup = ma_slow.isna()
    return t1, t2, t3, warmup


def fraction(t1, t2, t3, warmup, weights):
    w1, w2, w3 = weights
    frac = w1 * t1 + w2 * t2 + w3 * t3
    frac[warmup] = 0.0
    return frac


def backtest(close, position, leverage=LEVERAGE):
    ret = close.pct_change().fillna(0.0)
    return (position * leverage).shift(1).fillna(0.0) * ret


def metrics(ret):
    equity = (1.0 + ret).cumprod()
    total = equity.iloc[-1] - 1.0
    sharpe = ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan
    max_dd = (equity / equity.cummax() - 1.0).min()
    return total, sharpe, max_dd, equity.iloc[-1]


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates, "ret": ret}).set_index("date")
    df["year"] = df.index.year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


def main():
    df = load_data()
    close = df["Close"]
    dates = df["Date"]
    print(f"QQQ Pyramid Weight Grid Search ({FAST}/{SLOW} MAs, 3x leverage)")
    print(f"Data: {dates.iloc[0].date()} to {dates.iloc[-1].date()}")

    t1, t2, t3, warmup = tier_signals(close)

    rows = []
    steps = int(round(1.0 / STEP))
    for i in range(steps + 1):
        for j in range(steps + 1 - i):
            w1 = i * STEP
            w2 = j * STEP
            w3 = 1.0 - w1 - w2
            frac = fraction(t1, t2, t3, warmup, (w1, w2, w3))
            ret = backtest(close, frac)
            total, sharpe, max_dd, _ = metrics(ret)
            rows.append({"w1": w1, "w2": w2, "w3": round(w3, 2),
                         "total": total, "sharpe": sharpe, "max_dd": max_dd})

    grid = pd.DataFrame(rows)
    print(f"Tested {len(grid)} weight combinations (step {STEP:.0%})\n")

    def show(df_sorted, title):
        print(title)
        print(f"{'w1 (>MA3)':>10} {'w2 (>MA35)':>11} {'w3 (cross)':>11} "
              f"{'Total':>10} {'Sharpe':>7} {'MaxDD':>8}")
        print("-" * 64)
        for _, r in df_sorted.head(10).iterrows():
            print(f"{r['w1']:>9.0%} {r['w2']:>10.0%} {r['w3']:>10.0%} "
                  f"{r['total']:>9.0%} {r['sharpe']:>7.2f} {r['max_dd']:>8.1%}")
        print()

    show(grid.sort_values("total", ascending=False), "TOP 10 BY TOTAL RETURN")
    show(grid.sort_values("sharpe", ascending=False), "TOP 10 BY SHARPE")

    # Baselines for reference
    for name, w in [("Equal 33/33/33", (1/3, 1/3, 1/3)),
                    ("Weighted 25/35/40", (0.25, 0.35, 0.40))]:
        frac = fraction(t1, t2, t3, warmup, w)
        total, sharpe, max_dd, _ = metrics(backtest(close, frac))
        print(f"Baseline {name:<20} total {total:>8.0%}  Sharpe {sharpe:.2f}  MaxDD {max_dd:.1%}")

    # Year-by-year for the best-return weights
    best = grid.sort_values("total", ascending=False).iloc[0]
    bw = (best["w1"], best["w2"], best["w3"])
    print(f"\nBest by total return: w1={bw[0]:.0%} w2={bw[1]:.0%} w3={bw[2]:.0%}")

    bh_ret = close.pct_change().fillna(0.0)
    best_ret = backtest(close, fraction(t1, t2, t3, warmup, bw))
    w2540_ret = backtest(close, fraction(t1, t2, t3, warmup, (0.25, 0.35, 0.40)))

    bh_a = annual_returns(dates, bh_ret)
    best_a = annual_returns(dates, best_ret)
    w_a = annual_returns(dates, w2540_ret)

    print(f"\n{'Year':<6} {'QQQ B&H':>10} {'25/35/40':>12} "
          f"{'Best ' + f'{bw[0]:.0%}/{bw[1]:.0%}/{bw[2]:.0%}':>18}")
    print("-" * 50)
    for year in bh_a.index:
        print(f"{year:<6d} {bh_a[year]:>9.1%} {w_a[year]:>11.1%} {best_a[year]:>17.1%}")
    print("-" * 50)
    bh_total = (1 + bh_ret).prod() - 1
    w_total = (1 + w2540_ret).prod() - 1
    best_total = (1 + best_ret).prod() - 1
    print(f"{'TOTAL':<6} {bh_total:>9.1%} {w_total:>11.1%} {best_total:>17.1%}")
    print(f"\nFinal wealth from $100,000: best weights -> "
          f"${100000 * (1 + best_total):,.0f}")


if __name__ == "__main__":
    main()
