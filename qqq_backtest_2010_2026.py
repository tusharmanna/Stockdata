"""QQQ backtest 2010-2026: MA-crossover strategy vs buy-and-hold.

Applies the same 10/20 baseline and 4/25 best-grid configs to 16 years
of QQQ history. Shows annual returns and cumulative comparison.
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV_PATH = "QQQ_2010_2026.csv"
TRADING_DAYS = 252


def load_data(path=CSV_PATH):
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    assert df["Close"].notna().all(), "NaN in Close"
    return df


def backtest(close, fast, slow, l_long, l_short):
    ret = close.pct_change().fillna(0.0)
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    position = pd.Series(0.0, index=close.index)
    position[fast_ma > slow_ma] = float(l_long)
    position[fast_ma < slow_ma] = -float(l_short)
    position[slow_ma.isna()] = 0.0
    strat_ret = position.shift(1).fillna(0.0) * ret
    return strat_ret, position


def metrics(strat_ret):
    equity = (1.0 + strat_ret).cumprod()
    total = equity.iloc[-1] - 1.0
    sharpe = np.nan
    if strat_ret.std() > 0:
        sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(TRADING_DAYS)
    max_dd = (equity / equity.cummax() - 1.0).min()
    return {"total": total, "sharpe": sharpe, "max_dd": max_dd}


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates, "ret": ret}).set_index("date")
    df["year"] = df.index.year
    annual = df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)
    return annual


def main():
    df = load_data()
    close = df["Close"]
    dates = df["Date"]

    print(f"Loaded {len(df)} rows: {dates.iloc[0].date()} to {dates.iloc[-1].date()}")
    print(f"Full history: {len(df) / 252:.1f} years\n")

    # Buy-and-hold
    bh_ret = close.pct_change().fillna(0.0)
    bh_m = metrics(bh_ret)

    # Baseline 10/20 3x/1x
    base_ret, _ = backtest(close, 10, 20, 3, 1)
    base_m = metrics(base_ret)

    # Best grid 4/25 3x/0x
    best_ret, _ = backtest(close, 4, 25, 3, 0)
    best_m = metrics(best_ret)

    print(f"{'Strategy':<25} {'Total Return':>14} {'Ann. Sharpe':>14} {'Max DD':>12}")
    print("-" * 66)
    print(f"{'Buy & hold':<25} {bh_m['total']:>13.1%} {bh_m['sharpe']:>14.2f} {bh_m['max_dd']:>11.1%}")
    print(f"{'Baseline 10/20 3x/1x':<25} {base_m['total']:>13.1%} {base_m['sharpe']:>14.2f} {base_m['max_dd']:>11.1%}")
    print(f"{'Best grid 4/25 3x/0x':<25} {best_m['total']:>13.1%} {best_m['sharpe']:>14.2f} {best_m['max_dd']:>11.1%}")

    # Annual breakdown
    print("\n" + "=" * 66)
    print("Annual Returns by Year")
    print("=" * 66)
    bh_annual = annual_returns(dates, bh_ret)
    base_annual = annual_returns(dates, base_ret)
    best_annual = annual_returns(dates, best_ret)

    print(f"{'Year':<8} {'B&H':>10} {'Baseline':>12} {'Best Grid':>12}")
    print("-" * 45)
    for year in bh_annual.index:
        bh_y = bh_annual[year]
        base_y = base_annual[year]
        best_y = best_annual[year]
        print(f"{year:<8d} {bh_y:>9.1%} {base_y:>11.1%} {best_y:>11.1%}")

    print("-" * 45)
    print(f"{'TOTAL':<8} {bh_m['total']:>9.1%} {base_m['total']:>11.1%} {best_m['total']:>11.1%}")

    # Plot
    fig, ax = plt.subplots(figsize=(14, 7))
    bh_eq = (1.0 + bh_ret).cumprod()
    base_eq = (1.0 + base_ret).cumprod()
    best_eq = (1.0 + best_ret).cumprod()

    ax.plot(dates, bh_eq, label=f"Buy & Hold ({bh_m['total']:.0%})", linewidth=2)
    ax.plot(dates, base_eq, label=f"Baseline 10/20 ({base_m['total']:.0%})", linewidth=2)
    ax.plot(dates, best_eq, label=f"Best Grid 4/25 ({best_m['total']:.0%})", linewidth=2, linestyle='--')

    ax.set_title("QQQ Strategy Backtest: 2010–2026")
    ax.set_ylabel("Growth of $1")
    ax.set_xlabel("Year")
    ax.legend(loc="upper left", fontsize=11)
    ax.grid(alpha=0.3)
    ax.set_yscale('log')
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig("qqq_2010_2026_backtest.png", dpi=120)
    plt.close(fig)
    print(f"\nEquity curves saved to qqq_2010_2026_backtest.png")


if __name__ == "__main__":
    main()
