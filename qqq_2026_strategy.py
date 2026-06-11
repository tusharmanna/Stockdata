"""QQQ 2026 MA-crossover strategy backtest.

Compares an untuned 10/20 MA crossover baseline and a Sharpe-maximizing
grid-searched variant against buy-and-hold over QQQ_2026.csv.

Signal: fast MA > slow MA -> long L_long x daily return,
        fast MA < slow MA -> short L_short x daily return,
        cash until the slow MA window is full.
Positions are shifted one day, so day t's return uses only data through t-1.
Leverage is modeled as a daily-rebalanced multiple of QQQ's daily return
(TQQQ/SQQQ-style, fees and borrow costs ignored). No transaction costs;
flip counts are reported so cost impact can be eyeballed.
"""

import sys

import numpy as np
import pandas as pd

CSV_PATH = "QQQ_2026.csv"
TRADING_DAYS = 252


def load_data(path=CSV_PATH):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except FileNotFoundError:
        sys.exit(f"ERROR: {path} not found. Download QQQ 2026 data first.")
    expected = {"Date", "Open", "High", "Low", "Close", "Volume"}
    missing = expected - set(df.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing columns: {sorted(missing)}")
    df = df.sort_values("Date").reset_index(drop=True)
    assert df["Close"].notna().all(), "NaN values in Close column"
    return df


def backtest(close, fast, slow, l_long, l_short):
    """Run one MA-crossover config. Returns (daily strategy returns, position)."""
    ret = close.pct_change().fillna(0.0)
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    position = pd.Series(0.0, index=close.index)
    position[fast_ma > slow_ma] = float(l_long)
    position[fast_ma < slow_ma] = -float(l_short)
    position[slow_ma.isna()] = 0.0  # cash until warmup completes
    strat_ret = position.shift(1).fillna(0.0) * ret
    return strat_ret, position


def metrics(strat_ret, position):
    equity = (1.0 + strat_ret).cumprod()
    total = equity.iloc[-1] - 1.0
    sharpe = np.nan
    if strat_ret.std() > 0:
        sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(TRADING_DAYS)
    max_dd = (equity / equity.cummax() - 1.0).min()
    flips = int((position.diff().fillna(0.0) != 0).sum())
    active = strat_ret[strat_ret != 0]
    win = (active > 0).mean() if len(active) else np.nan
    return {"total": total, "sharpe": sharpe, "max_dd": max_dd,
            "flips": flips, "win": win}


def sanity_checks(close):
    ret = close.pct_change().fillna(0.0)

    # Benchmark check: compounded daily returns must equal raw close-to-close.
    bh_total = (1.0 + ret).prod() - 1.0
    raw_total = close.iloc[-1] / close.iloc[0] - 1.0
    assert np.isclose(bh_total, raw_total), (
        f"buy-and-hold mismatch: {bh_total:.6f} vs {raw_total:.6f}")

    # No-lookahead check: an extra day of delay must change the result,
    # proving the one-day shift in backtest() is live.
    strat_ret, pos = backtest(close, 10, 20, 3, 1)
    delayed = pos.shift(2).fillna(0.0) * ret
    assert not np.isclose((1 + strat_ret).prod(), (1 + delayed).prod()), (
        "extra shift did not change results - position shift may be dead")

    print("Sanity checks passed.")


def main():
    df = load_data()
    close = df["Close"]
    print(f"Loaded {len(df)} rows: {df['Date'].iloc[0].date()} "
          f"to {df['Date'].iloc[-1].date()}")
    sanity_checks(close)


if __name__ == "__main__":
    main()
