"""Tushar v2 — volatility-targeted v1 (aggressive) backtest.

v1 holds TQQQ in the bull regime (QQQ within 15% of its 189d high) else cash.
Analysis showed v1 is ~93% buy-and-hold TQQQ, so the only non-overfit lever is
HOW the position is sized while invested. v2 sizes the TQQQ position by recent
realized volatility instead of a binary 0/100%:

    exposure = clip(target_vol / realized_vol_TQQQ, 0, cap)   (only in bull regime)

Defensive settings: target_vol = 0.45, cap = 1.5. This is the one configuration the
walk-forward test endorsed (tushar_v2_walkforward.py): out of sample it matched v1's
Sharpe (~1.09) while cutting max drawdown from ~-57% to ~-43%. Note vol-targeting did
NOT add risk-adjusted edge out of sample — it is a risk-reduction knob, not alpha.
Because cap > 1.0 allows margin on top of a 3x ETF, the backtest charges financing on
the borrowed portion and credits T-bill yield on idle cash — the after-cost row is the
honest figure.

Reuses v1's regime logic from tusharStrategyDev.py (DRY).
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TRADING_DAYS = 252
TARGET_VOL = 0.45   # walk-forward-endorsed defensive setting (was 0.75 aggressive)
LEV_CAP = 1.5
VOL_WINDOW = 20

# Blended, regime-realistic rate schedule (annualized).
RATE_SPLIT_YEARS = 12          # ~2010-2021 vs 2022-2026
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
MARGIN_EARLY, MARGIN_LATE = 0.025, 0.06   # tbill + ~1% broker spread


def vol_target_exposure(regime_pos, tqqq_ret):
    """Vol-targeted TQQQ exposure, zero outside the bull regime."""
    rv = (tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    lev = (TARGET_VOL / rv).clip(0, LEV_CAP)
    return (regime_pos * lev).clip(0, LEV_CAP)


def strat_returns(exposure, tqqq_ret, dates, costs=False):
    """Causal daily returns; optionally charge financing and credit cash yield."""
    e = exposure.shift(1).fillna(0.0)
    r = e * tqqq_ret
    if costs:
        years = (dates - dates.iloc[0]).dt.days.values / 365.25
        tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
        margin = np.where(years > RATE_SPLIT_YEARS, MARGIN_LATE, MARGIN_EARLY)
        borrowed = (e - 1.0).clip(lower=0)
        idle = (1.0 - e).clip(lower=0, upper=1)
        r = r - borrowed * margin / TRADING_DAYS + idle * tbill / TRADING_DAYS
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
    print("Loading QQQ and TQQQ (live)...")
    qqq_df = _load(QQQ_TICKER)
    tqqq_df = _load(TQQQ_TICKER)

    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    idx = qqq_df.index.intersection(tqqq_df.index)
    regime_pos = regime_pos.loc[idx]
    tqqq_ret = tqqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    qqq_ret = qqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates = pd.Series(idx, index=idx)

    exposure = vol_target_exposure(regime_pos, tqqq_ret)

    # Series
    qqq_bh = qqq_ret
    tqqq_bh = tqqq_ret
    v1 = strat_returns(regime_pos, tqqq_ret, dates)
    v2_ideal = strat_returns(exposure, tqqq_ret, dates)
    v2_cost = strat_returns(exposure, tqqq_ret, dates, costs=True)

    m = {k: metrics(v) for k, v in [
        ("QQQ B&H", qqq_bh), ("TQQQ B&H", tqqq_bh), ("v1 baseline", v1),
        ("v2 vol-target (ideal)", v2_ideal), ("v2 vol-target (after cost)", v2_cost)]}

    a = {k: annual_returns(dates, v) for k, v in [
        ("QQQ", qqq_bh), ("v1", v1), ("v2i", v2_ideal), ("v2c", v2_cost)]}

    print(f"\nRange: {idx[0].date()} to {idx[-1].date()}  |  Capital: $100,000")
    print("=" * 84)
    print("YEAR-BY-YEAR RETURNS")
    print("=" * 84)
    print(f"{'Year':<6}{'QQQ B&H':>11}{'v1':>11}{'v2 ideal':>12}{'v2 after-cost':>16}")
    print("-" * 84)
    for year in a["v1"].index:
        print(f"{year:<6}{a['QQQ'][year]:>10.1%}{a['v1'][year]:>11.1%}"
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

    v1f, v2f = m["v1 baseline"]["final"], m["v2 vol-target (after cost)"]["final"]
    print(f"\nVERDICT: after-cost v2 = ${v2f:,.0f} vs v1 = ${v1f:,.0f} "
          f"({v2f/v1f:.2f}x)  |  Sharpe {m['v2 vol-target (after cost)']['sharpe']:.2f} "
          f"vs {m['v1 baseline']['sharpe']:.2f}")
    print("NOTE: single-asset, single-path, in-sample. The honest edge is the Sharpe lift +")
    print("      a leverage dial — not new predictive skill. Treat the dollar figure as a")
    print("      best case (real margin rates, slippage, and taxes erode it further).")


if __name__ == "__main__":
    main()
