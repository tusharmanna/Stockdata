"""Tushar v2 — QQQ (1x, no-margin) variant backtest.

QQQ is the underlying Nasdaq-100. v2 applies regime gate + vol-targeting,
capped at 1.0x (conservative, no margin). Good for comparison vs TQQQ/QLD.

Uses after-cost returns (T-bill yield on idle cash).

Reuses v1's regime logic from tusharStrategyDev.py (DRY).
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER

TRADING_DAYS = 252
TARGET_VOL = 0.45
LEV_CAP = 1.0    # Conservative: no margin

# Blended rate schedule for T-bill yield (annualized)
RATE_SPLIT_YEARS = 12
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
VOL_WINDOW = 20


def vol_target_exposure(regime_pos, qqq_ret):
    """Vol-targeted QQQ exposure, zero outside the bull regime."""
    rv = (qqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    lev = (TARGET_VOL / rv).clip(0, LEV_CAP)
    return (regime_pos * lev).clip(0, LEV_CAP)


def strat_returns(exposure, qqq_ret, dates, costs=False):
    """Causal daily returns; optionally credit cash yield."""
    e = exposure.shift(1).fillna(0.0)
    r = e * qqq_ret
    if costs:
        years = (dates - dates.iloc[0]).dt.days.values / 365.25
        tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
        idle = (1.0 - e).clip(lower=0, upper=1)
        r = r + idle * tbill / TRADING_DAYS
    return r


def metrics(ret, capital=100000):
    eq = (1.0 + ret).cumprod()
    total = eq.iloc[-1] - 1.0
    n_yr = len(ret) / TRADING_DAYS
    cagr = (eq.iloc[-1]) ** (1 / n_yr) - 1 if n_yr > 0 else np.nan
    sharpe = ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan
    max_dd = (eq / eq.cummax() - 1.0).min()
    return {"total": total, "cagr": cagr, "sharpe": sharpe,
            "max_dd": max_dd, "final": eq.iloc[-1] * capital}


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates.values, "ret": ret.values}).set_index("date")
    df["year"] = pd.DatetimeIndex(df.index).year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


def main():
    print("Loading QQQ (live)...")
    qqq_df = _load(QQQ_TICKER)

    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    idx = qqq_df.index
    regime_pos = regime_pos.loc[idx]
    qqq_ret = qqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates = pd.Series(idx, index=idx)

    exposure = vol_target_exposure(regime_pos, qqq_ret)

    # Series
    qqq_bh = qqq_ret
    v2_ideal = strat_returns(exposure, qqq_ret, dates)
    v2_cost = strat_returns(exposure, qqq_ret, dates, costs=True)

    m = {k: metrics(v) for k, v in [
        ("QQQ B&H", qqq_bh),
        ("v2 QQQ (ideal)", v2_ideal), ("v2 QQQ (after cost)", v2_cost)]}

    a = {k: annual_returns(dates, v) for k, v in [
        ("QQQ", qqq_bh), ("v2i", v2_ideal), ("v2c", v2_cost)]}

    print(f"\nRange: {idx[0].date()} to {idx[-1].date()}  |  Capital: $100,000")
    print("=" * 84)
    print("YEAR-BY-YEAR RETURNS")
    print("=" * 84)
    print(f"{'Year':<6}{'QQQ B&H':>11}{'v2 ideal':>12}{'v2 after-cost':>16}")
    print("-" * 84)
    for year in a["QQQ"].index:
        print(f"{year:<6}{a['QQQ'][year]:>10.1%}{a['v2i'][year]:>12.1%}"
              f"{a['v2c'][year]:>16.1%}")
    print("-" * 84)

    print("\nSUMMARY  ($100k start)")
    print("=" * 84)
    print(f"{'Strategy':<30}{'Total':>12}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Final $':>15}")
    print("-" * 84)
    for k in m:
        x = m[k]
        print(f"{k:<30}{x['total']:>11.0%}{x['cagr']:>8.1%}{x['sharpe']:>9.2f}"
              f"{x['max_dd']:>9.1%}{x['final']:>15,.0f}")
    print("=" * 84)

    v2f = m["v2 QQQ (after cost)"]["final"]
    qqq_f = m["QQQ B&H"]["final"]
    print(f"\nVERDICT: after-cost v2 QQQ = ${v2f:,.0f} vs QQQ B&H = ${qqq_f:,.0f}")
    print(f"         v2 Sharpe: {m['v2 QQQ (after cost)']['sharpe']:.2f} vs QQQ B&H: {m['QQQ B&H']['sharpe']:.2f}")
    print("NOTE: single-asset, single-path, in-sample. Conservative 1.0x cap")
    print("      (no margin) makes this safe for any account type.")


if __name__ == "__main__":
    main()
