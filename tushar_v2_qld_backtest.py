"""Tushar v2 — QLD (2x, no-margin) variant backtest.

QLD is the 2x Nasdaq-100 ETF, used in retirement accounts (Roth/HSA/401k)
where margin is not allowed. Strategy: v1 regime gate + vol-targeting,
capped at 100% of cash (no margin).

Uses after-cost returns (T-bill yield on idle cash, but no margin financing
since the cap is 1.0).

Reuses v1's regime logic from tusharStrategyDev.py (DRY).
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER

QLD_TICKER = "QLD"
TRADING_DAYS = 252
TARGET_VOL = 0.45
LEV_CAP = 1.0    # No margin — cap at 100% of account

# Blended, regime-realistic rate schedule for T-bill yield (annualized)
RATE_SPLIT_YEARS = 12          # ~2010-2021 vs 2022-2026
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
VOL_WINDOW = 20


def vol_target_exposure(regime_pos, qld_ret):
    """Vol-targeted QLD exposure, zero outside the bull regime."""
    rv = (qld_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    lev = (TARGET_VOL / rv).clip(0, LEV_CAP)
    return (regime_pos * lev).clip(0, LEV_CAP)


def strat_returns(exposure, qld_ret, dates, costs=False):
    """Causal daily returns; optionally credit cash yield (no margin charge)."""
    e = exposure.shift(1).fillna(0.0)
    r = e * qld_ret
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
    print("Loading QQQ and QLD (live)...")
    qqq_df = _load(QQQ_TICKER)
    qld_df = _load(QLD_TICKER)

    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    idx = qqq_df.index.intersection(qld_df.index)
    regime_pos = regime_pos.loc[idx]
    qld_ret = qld_df.loc[idx, "close"].pct_change().fillna(0.0)
    qqq_ret = qqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates = pd.Series(idx, index=idx)

    exposure = vol_target_exposure(regime_pos, qld_ret)

    # Series
    qqq_bh = qqq_ret
    qld_bh = qld_ret
    v2_qld_ideal = strat_returns(exposure, qld_ret, dates)
    v2_qld_cost = strat_returns(exposure, qld_ret, dates, costs=True)

    m = {k: metrics(v) for k, v in [
        ("QQQ B&H", qqq_bh), ("QLD B&H", qld_bh),
        ("v2 QLD (ideal)", v2_qld_ideal), ("v2 QLD (after cost)", v2_qld_cost)]}

    a = {k: annual_returns(dates, v) for k, v in [
        ("QQQ", qqq_bh), ("QLD", qld_bh), ("v2i", v2_qld_ideal), ("v2c", v2_qld_cost)]}

    print(f"\nRange: {idx[0].date()} to {idx[-1].date()}  |  Capital: $100,000")
    print("=" * 84)
    print("YEAR-BY-YEAR RETURNS")
    print("=" * 84)
    print(f"{'Year':<6}{'QQQ B&H':>11}{'QLD B&H':>11}{'v2 ideal':>12}{'v2 after-cost':>16}")
    print("-" * 84)
    for year in a["QQQ"].index:
        print(f"{year:<6}{a['QQQ'][year]:>10.1%}{a['QLD'][year]:>11.1%}"
              f"{a['v2i'][year]:>12.1%}{a['v2c'][year]:>16.1%}")
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

    v2f = m["v2 QLD (after cost)"]["final"]
    print(f"\nVERDICT: after-cost v2 QLD = ${v2f:,.0f}  |  Sharpe {m['v2 QLD (after cost)']['sharpe']:.2f}")
    print("NOTE: single-asset, single-path, in-sample. No margin (cap=1.0) means")
    print("      this works in Roth/HSA/401k accounts. Trade-off: smaller returns")
    print("      than 3x leverage but shallower drawdown and tax-free growth.")


if __name__ == "__main__":
    main()
