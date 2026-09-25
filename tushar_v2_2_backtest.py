"""Tushar v2.2 backtest: v2 volatility targeting with softer risk caps.

This is a research script only. Production v2 signal files are unchanged.

Rules:
  - Keep the existing v1 regime gate:
      QQQ within 15% of its 189-day high -> bull regime, else cash.
  - Base TQQQ exposure is current v2:
      clip(0.45 / 20-day annualized TQQQ realized volatility, 0, 1.0)
  - Test several softer risk caps while still in the bull regime:
      QQQ close >= 50-day MA      -> normal v2 exposure
      QQQ close < 50-day MA       -> cap at 0.50x TQQQ
      QQQ close < 100-day MA      -> cap at 0.25x TQQQ
      bearish 15% regime gate     -> 0.00x TQQQ
    plus less aggressive 100-day-only and drawdown-ramp variants.

All strategy returns are causal: exposure computed at close t is shifted and used
for the next trading day's TQQQ return.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER


TRADING_DAYS = 252
TARGET_VOL = 0.45
LEV_CAP = 1.0
VOL_WINDOW = 20
MA_FAST = 50
MA_SLOW = 100
FAST_CAP = 0.50
SLOW_CAP = 0.25
IS_END = pd.Timestamp("2018-12-31")

RATE_SPLIT_YEARS = 12
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
MARGIN_EARLY, MARGIN_LATE = 0.025, 0.06


def v2_exposure(regime_pos, tqqq_ret):
    rv = (tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    return (regime_pos * (TARGET_VOL / rv).clip(0, LEV_CAP)).clip(0, LEV_CAP)


def trend_cap(qqq_close):
    ma50 = qqq_close.rolling(MA_FAST, min_periods=MA_FAST).mean()
    ma100 = qqq_close.rolling(MA_SLOW, min_periods=MA_SLOW).mean()
    cap = pd.Series(LEV_CAP, index=qqq_close.index, dtype=float)
    cap = cap.where(qqq_close >= ma50, FAST_CAP)
    cap = cap.where(qqq_close >= ma100, SLOW_CAP)
    return cap.bfill()


def trend_cap_100d(qqq_close, below_cap):
    ma100 = qqq_close.rolling(MA_SLOW, min_periods=MA_SLOW).mean()
    cap = pd.Series(LEV_CAP, index=qqq_close.index, dtype=float)
    cap = cap.where(qqq_close >= ma100, below_cap)
    return cap.bfill()


def drawdown_ramp_cap(pcthi, full_until, zero_at):
    """Linear cap from 1.0 at full_until% below high to 0.0 at zero_at%."""
    dist = pcthi / 100.0
    cap = ((zero_at - dist) / (zero_at - full_until)).clip(0.0, 1.0)
    return cap.fillna(LEV_CAP)


def after_cost_returns(exposure, tqqq_ret, dates):
    e = exposure.shift(1).fillna(0.0)
    years = (dates - dates.iloc[0]).dt.days.values / 365.25
    tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
    margin = np.where(years > RATE_SPLIT_YEARS, MARGIN_LATE, MARGIN_EARLY)
    borrowed = (e - 1.0).clip(lower=0.0)
    idle = (1.0 - e).clip(lower=0.0, upper=1.0)
    return e * tqqq_ret - borrowed * margin / TRADING_DAYS + idle * tbill / TRADING_DAYS


def metrics(ret, capital=100_000):
    eq = (1.0 + ret).cumprod()
    n_yr = len(ret) / TRADING_DAYS
    return {
        "total": eq.iloc[-1] - 1.0,
        "cagr": eq.iloc[-1] ** (1.0 / n_yr) - 1.0 if n_yr > 0 else np.nan,
        "sharpe": ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan,
        "max_dd": (eq / eq.cummax() - 1.0).min(),
        "final": eq.iloc[-1] * capital,
    }


def annual_returns(dates, ret):
    df = pd.DataFrame({"date": dates.values, "ret": ret.values}).set_index("date")
    df["year"] = pd.DatetimeIndex(df.index).year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


def exposure_stats(exposure):
    return {
        "avg": exposure.mean(),
        "median": exposure.median(),
        "full_days": (exposure >= 0.99).mean(),
        "half_or_less": (exposure <= 0.50).mean(),
        "cash_days": (exposure <= 0.001).mean(),
    }


def print_summary(title, rows):
    print("\n" + title)
    print("=" * 92)
    print(f"{'Strategy':<28}{'Total':>10}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Final $':>15}")
    print("-" * 92)
    for name, ret in rows:
        m = metrics(ret)
        print(f"{name:<28}{m['total']:>9.0%}{m['cagr']:>9.1%}{m['sharpe']:>9.2f}"
              f"{m['max_dd']:>9.1%}{m['final']:>15,.0f}")


def main():
    print("Loading QQQ and TQQQ...")
    qqq = _load(QQQ_TICKER)
    tqqq = _load(TQQQ_TICKER)

    idx = qqq.index.intersection(tqqq.index)
    qqq = qqq.loc[idx]
    tqqq = tqqq.loc[idx]
    dates = pd.Series(idx, index=idx)

    sig = compute_signal_v1(qqq)
    regime = (sig["regime"] == "BUY_TQQQ").astype(float).loc[idx]
    tqqq_ret = tqqq["close"].pct_change().fillna(0.0)
    qqq_ret = qqq["close"].pct_change().fillna(0.0)

    v1_ret = after_cost_returns(regime, tqqq_ret, dates)
    v2_exp = v2_exposure(regime, tqqq_ret)
    v2_ret = after_cost_returns(v2_exp, tqqq_ret, dates)

    cap = trend_cap(qqq["close"])
    variants = {
        "v2.2 MA50/100 cap": (v2_exp * cap).clip(0, LEV_CAP),
        "v2.2 MA100 cap50": (v2_exp * trend_cap_100d(qqq["close"], 0.50)).clip(0, LEV_CAP),
        "v2.2 MA100 cap75": (v2_exp * trend_cap_100d(qqq["close"], 0.75)).clip(0, LEV_CAP),
        "v2.2 ramp 5-15": (v2_exp * drawdown_ramp_cap(sig["pcthi"].loc[idx], 0.05, 0.15)).clip(0, LEV_CAP),
        "v2.2 ramp 8-15": (v2_exp * drawdown_ramp_cap(sig["pcthi"].loc[idx], 0.08, 0.15)).clip(0, LEV_CAP),
        "v2.2 ramp 10-15": (v2_exp * drawdown_ramp_cap(sig["pcthi"].loc[idx], 0.10, 0.15)).clip(0, LEV_CAP),
    }
    variant_returns = {
        name: after_cost_returns(exp, tqqq_ret, dates)
        for name, exp in variants.items()
    }

    is_mask = idx <= IS_END
    oos_mask = idx > IS_END

    rows = [
        ("QQQ buy & hold", qqq_ret),
        ("v1 regime baseline", v1_ret),
        ("v2 current", v2_ret),
    ]
    rows.extend(variant_returns.items())

    print(f"\nRange: {idx[0].date()} to {idx[-1].date()}  |  Capital: $100,000")
    print_summary("FULL PERIOD", rows)
    print_summary("IN-SAMPLE THROUGH 2018", [(n, r[is_mask]) for n, r in rows])
    print_summary("OUT-OF-SAMPLE 2019+", [(n, r[oos_mask]) for n, r in rows])

    annual = {
        "QQQ": annual_returns(dates, qqq_ret),
        "v1": annual_returns(dates, v1_ret),
        "v2": annual_returns(dates, v2_ret),
    }

    print("\nYEAR-BY-YEAR RETURNS")
    print("=" * 92)
    best_oos_name, best_oos_ret = max(
        variant_returns.items(),
        key=lambda item: metrics(item[1][oos_mask])["sharpe"],
    )
    annual_best = annual_returns(dates, best_oos_ret)

    print(f"{'Year':<6}{'QQQ':>10}{'v1':>10}{'v2':>10}{'best':>10}{'best-v2':>12}")
    print("-" * 92)
    for year in annual["v2"].index:
        diff = annual_best[year] - annual["v2"][year]
        print(f"{year:<6}{annual['QQQ'][year]:>9.1%}{annual['v1'][year]:>10.1%}"
              f"{annual['v2'][year]:>10.1%}{annual_best[year]:>10.1%}{diff:>12.1%}")
    print(f"Best-by-OOS-Sharpe variant shown above: {best_oos_name}")

    print("\nEXPOSURE PROFILE")
    print("=" * 92)
    print(f"{'Strategy':<20}{'Avg':>8}{'Median':>10}{'Full days':>12}"
          f"{'<=50% days':>13}{'Cash days':>11}")
    print("-" * 92)
    for name, exp in [("v2 current", v2_exp), *variants.items()]:
        s = exposure_stats(exp)
        print(f"{name:<20}{s['avg']:>8.2f}{s['median']:>10.2f}{s['full_days']:>12.1%}"
              f"{s['half_or_less']:>13.1%}{s['cash_days']:>11.1%}")

    v2 = metrics(v2_ret)
    v2_oos = metrics(v2_ret[oos_mask])
    best = metrics(best_oos_ret)
    best_oos = metrics(best_oos_ret[oos_mask])
    print("\nVERDICT")
    print("=" * 92)
    print(f"Best OOS variant: {best_oos_name}")
    print(f"Full period: best CAGR {best['cagr']:.1%} vs v2 {v2['cagr']:.1%}; "
          f"MaxDD {best['max_dd']:.1%} vs {v2['max_dd']:.1%}; "
          f"Sharpe {best['sharpe']:.2f} vs {v2['sharpe']:.2f}.")
    print(f"OOS 2019+: best CAGR {best_oos['cagr']:.1%} vs v2 {v2_oos['cagr']:.1%}; "
          f"MaxDD {best_oos['max_dd']:.1%} vs {v2_oos['max_dd']:.1%}; "
          f"Sharpe {best_oos['sharpe']:.2f} vs {v2_oos['sharpe']:.2f}.")
    if best_oos["sharpe"] > v2_oos["sharpe"] and best_oos["max_dd"] >= v2_oos["max_dd"]:
        print("Best v2.2 variant passes the first OOS check: better Sharpe and no deeper max drawdown.")
    else:
        print("No v2.2 variant passes the first OOS check versus current v2.")


if __name__ == "__main__":
    main()
