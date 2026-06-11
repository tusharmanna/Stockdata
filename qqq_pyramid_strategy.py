"""QQQ 3-tier pyramiding MA strategy backtest (2010-2026).

Position is scaled in thirds as bullish evidence accumulates, instead of the
binary 0%/100% jump of the plain 4/25 MA crossover:

  Tier 1: Close > MA4   -> +33% of full size
  Tier 2: Close > MA25  -> +33%
  Tier 3: MA4 > MA25    -> +33% (the binary crossover signal)

Position fraction f = (tiers true) / 3 -> 0, 1/3, 2/3, or 1. Scaling out is
symmetric: each condition that fails drops a third. Exposure = f x L with
L = 3 (TQQQ-style daily-rebalanced leverage) as the headline variant.

Compares against buy & hold and the binary 4/25 3x/cash champion from
qqq_backtest_2010_2026.py on the same corrected close data.
"""

import sys

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV_PATH = "QQQ_2010_2026.csv"
TRADING_DAYS = 252
FAST = 4
SLOW = 25
LEVERAGE = 3.0


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
    frac[ma_slow.isna()] = 0.0  # cash until warmup completes
    return frac


def binary_position(close, fast=FAST, slow=SLOW):
    """The existing champion: 1.0 when MA fast > MA slow, else 0 (cash)."""
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    pos = pd.Series(0.0, index=close.index)
    pos[ma_fast > ma_slow] = 1.0
    pos[ma_slow.isna()] = 0.0
    return pos


def run(close, position, leverage):
    """Daily strategy returns from a position-fraction series (causal)."""
    ret = close.pct_change().fillna(0.0)
    return (position * leverage).shift(1).fillna(0.0) * ret


def metrics(strat_ret, position):
    equity = (1.0 + strat_ret).cumprod()
    total = equity.iloc[-1] - 1.0
    sharpe = np.nan
    if strat_ret.std() > 0:
        sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(TRADING_DAYS)
    max_dd = (equity / equity.cummax() - 1.0).min()
    changes = int((position.diff().fillna(0.0) != 0).sum())
    return {"total": total, "sharpe": sharpe, "max_dd": max_dd,
            "changes": changes}


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates, "ret": ret}).set_index("date")
    df["year"] = df.index.year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


def sanity_checks(close):
    ret = close.pct_change().fillna(0.0)

    # Engine buy-and-hold must equal raw close-to-close total.
    bh_total = (1.0 + ret).prod() - 1.0
    raw_total = close.iloc[-1] / close.iloc[0] - 1.0
    assert np.isclose(bh_total, raw_total), "buy-and-hold mismatch"

    # No-lookahead: an extra day of delay must change the result.
    frac = pyramid_fraction(close)
    normal = (1 + run(close, frac, LEVERAGE)).prod()
    delayed = (1 + ((frac * LEVERAGE).shift(2).fillna(0.0) * ret)).prod()
    assert not np.isclose(normal, delayed), "position shift may be dead"

    # Degenerate: f forced to 1 everywhere must equal always-long at leverage.
    ones = pd.Series(1.0, index=close.index)
    forced = (1 + run(close, ones, LEVERAGE)).prod()
    always = (1 + (LEVERAGE * ret).shift(0)).prod()  # same series, shifted pos
    # run() shifts the position; always-long shifted is still always-long
    # except day 0, which run() zeroes. Compare against that exactly:
    always_shifted = (1 + (ones * LEVERAGE).shift(1).fillna(0.0) * ret).prod()
    assert np.isclose(forced, always_shifted), "degenerate f=1 mismatch"

    print("Sanity checks passed.")


def grid_search(close):
    rows = []
    for fast in range(3, 11):
        for slow in range(15, 51, 5):
            if fast >= slow:
                continue
            frac = pyramid_fraction(close, fast, slow)
            sr = run(close, frac, LEVERAGE)
            m = metrics(sr, frac)
            rows.append({"fast": fast, "slow": slow, **m})
    return (pd.DataFrame(rows)
            .sort_values("sharpe", ascending=False)
            .reset_index(drop=True))


def main():
    df = load_data()
    close = df["Close"]
    dates = df["Date"]
    print(f"Loaded {len(df)} rows: {dates.iloc[0].date()} to {dates.iloc[-1].date()}")
    sanity_checks(close)

    ret = close.pct_change().fillna(0.0)
    bh_pos = pd.Series(1.0, index=close.index)
    bh_m = metrics(ret, bh_pos)

    bin_pos = binary_position(close)
    bin_ret = run(close, bin_pos, LEVERAGE)
    bin_m = metrics(bin_ret, bin_pos)

    pyr_pos = pyramid_fraction(close)
    pyr_ret = run(close, pyr_pos, LEVERAGE)
    pyr_m = metrics(pyr_ret, pyr_pos)

    pyr1_ret = run(close, pyr_pos, 1.0)
    pyr1_m = metrics(pyr1_ret, pyr_pos)

    print(f"\n{'Strategy':<28} {'Total':>10} {'Sharpe':>7} {'MaxDD':>8} {'Changes':>8}")
    print("-" * 66)
    print(f"{'Buy & hold':<28} {bh_m['total']:>9.1%} {bh_m['sharpe']:>7.2f} "
          f"{bh_m['max_dd']:>8.1%} {bh_m['changes']:>8d}")
    print(f"{'Binary 4/25 3x/cash':<28} {bin_m['total']:>9.1%} {bin_m['sharpe']:>7.2f} "
          f"{bin_m['max_dd']:>8.1%} {bin_m['changes']:>8d}")
    print(f"{'Pyramid 3-tier 3x full':<28} {pyr_m['total']:>9.1%} {pyr_m['sharpe']:>7.2f} "
          f"{pyr_m['max_dd']:>8.1%} {pyr_m['changes']:>8d}")
    print(f"{'Pyramid 3-tier 1x full':<28} {pyr1_m['total']:>9.1%} {pyr1_m['sharpe']:>7.2f} "
          f"{pyr1_m['max_dd']:>8.1%} {pyr1_m['changes']:>8d}")

    # Annual table
    bh_a = annual_returns(dates, ret)
    bin_a = annual_returns(dates, bin_ret)
    pyr_a = annual_returns(dates, pyr_ret)
    print(f"\n{'Year':<6} {'B&H':>9} {'Binary 3x':>11} {'Pyramid 3x':>11}")
    print("-" * 42)
    for year in bh_a.index:
        print(f"{year:<6d} {bh_a[year]:>8.1%} {bin_a[year]:>10.1%} {pyr_a[year]:>10.1%}")
    print("-" * 42)
    print(f"{'TOTAL':<6} {bh_m['total']:>8.1%} {bin_m['total']:>10.1%} {pyr_m['total']:>10.1%}")

    # Verdict
    if pyr_m["total"] > bin_m["total"]:
        verdict = "PYRAMID WINS on total return"
    else:
        verdict = "BINARY WINS on total return"
    if pyr_m["sharpe"] > bin_m["sharpe"]:
        verdict += "; pyramid also wins on Sharpe"
    else:
        verdict += "; binary wins on Sharpe"
    print(f"\nVERDICT: {verdict}")

    # Mini grid for the pyramid rule
    grid = grid_search(close)
    print("\nTop 5 pyramid MA pairs by Sharpe:")
    top5 = grid.head(5).copy()
    top5["total"] = top5["total"].map("{:.1%}".format)
    top5["max_dd"] = top5["max_dd"].map("{:.1%}".format)
    top5["sharpe"] = top5["sharpe"].map("{:.2f}".format)
    print(top5[["fast", "slow", "sharpe", "total", "max_dd"]].to_string(index=False))

    # Chart
    fig, ax = plt.subplots(figsize=(14, 7))
    for name, r in [("Buy & Hold", ret), ("Binary 4/25 3x", bin_ret),
                    ("Pyramid 3-tier 3x", pyr_ret)]:
        eq = (1.0 + r).cumprod()
        ax.plot(dates, eq, label=f"{name} ({eq.iloc[-1] - 1:+.0%})", linewidth=1.8)
    ax.set_yscale("log")
    ax.set_title("QQQ 2010-2026: Pyramid 3-Tier vs Binary 4/25 Crossover (3x)")
    ax.set_ylabel("Growth of $1 (log)")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3, which="both")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig("qqq_pyramid_backtest.png", dpi=120)
    plt.close(fig)
    print("\nChart saved to qqq_pyramid_backtest.png")


if __name__ == "__main__":
    main()
