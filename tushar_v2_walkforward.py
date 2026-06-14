"""Walk-forward test for Tushar v2 vol-targeting.

The honest question: is the vol-target edge real, or did we just fit target_vol
to 2010-2026 history? Protocol:

  1. IN-SAMPLE  (2010-2018): grid target_vol, pick the best by Sharpe.
  2. OUT-OF-SAMPLE (2019-2026): apply ONLY that chosen param. Does v2 still beat
     v1 baseline on a window it never saw?
  3. Robustness: show OOS Sharpe across ALL target_vols. If it's flat, the edge is
     structural (not param-dependent). If it's peaky, it's fragile/overfit.

Uses after-cost returns (financing on margin + cash yield), cap = 1.5 (aggressive).
Reuses v1 regime logic from tusharStrategyDev.py.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TRADING_DAYS = 252
LEV_CAP = 1.5
VOL_WINDOW = 20
IS_END = "2018-12-31"          # in-sample through 2018, OOS from 2019
TARGET_GRID = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

RATE_SPLIT_YEARS = 12
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
MARGIN_EARLY, MARGIN_LATE = 0.025, 0.06


def exposure(regime_pos, tqqq_ret, target_vol):
    rv = (tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    lev = (target_vol / rv).clip(0, LEV_CAP)
    return (regime_pos * lev).clip(0, LEV_CAP)


def returns(expo, tqqq_ret, dates, costs=True):
    e = expo.shift(1).fillna(0.0)
    r = e * tqqq_ret
    if costs:
        years = (dates - dates.iloc[0]).dt.days.values / 365.25
        tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
        margin = np.where(years > RATE_SPLIT_YEARS, MARGIN_LATE, MARGIN_EARLY)
        r = (r - (e - 1).clip(lower=0) * margin / TRADING_DAYS
             + (1 - e).clip(lower=0, upper=1) * tbill / TRADING_DAYS)
    return r


def stats(ret):
    eq = (1.0 + ret).cumprod()
    n_yr = len(ret) / TRADING_DAYS
    return {
        "cagr": eq.iloc[-1] ** (1 / n_yr) - 1 if n_yr > 0 else np.nan,
        "sharpe": ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan,
        "max_dd": (eq / eq.cummax() - 1.0).min(),
        "grow": eq.iloc[-1],
    }


def main():
    print("Loading QQQ and TQQQ (live)...")
    qqq_df = _load(QQQ_TICKER)
    tqqq_df = _load(TQQQ_TICKER)
    sig = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    idx = qqq_df.index.intersection(tqqq_df.index)
    regime_pos = regime_pos.loc[idx]
    tqqq_ret = tqqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates = pd.Series(idx, index=idx)

    is_mask = idx <= pd.Timestamp(IS_END)
    oos_mask = ~is_mask

    def window(series, mask):
        return series[mask]

    # v1 baseline (regime only) per window
    v1 = returns(regime_pos, tqqq_ret, dates, costs=True)

    rows = []
    for tv in TARGET_GRID:
        expo = exposure(regime_pos, tqqq_ret, tv)
        r = returns(expo, tqqq_ret, dates, costs=True)
        is_s = stats(window(r, is_mask))
        oos_s = stats(window(r, oos_mask))
        rows.append((tv, is_s, oos_s))

    print(f"\nIn-sample: {idx[0].date()} .. {IS_END}   "
          f"Out-of-sample: 2019-01-01 .. {idx[-1].date()}")

    print("\n" + "=" * 78)
    print("STEP 1-3: target_vol grid  (after-cost, cap 1.5x)")
    print("=" * 78)
    print(f"{'target':>7}{'  | IS Sharpe':>13}{'IS CAGR':>10}{'  || OOS Sharpe':>16}"
          f"{'OOS CAGR':>10}{'OOS MaxDD':>11}")
    print("-" * 78)
    best_is = max(rows, key=lambda x: x[1]["sharpe"])
    for tv, is_s, oos_s in rows:
        mark = "  <- IS best" if tv == best_is[0] else ""
        print(f"{tv:>7.2f}{is_s['sharpe']:>13.2f}{is_s['cagr']:>10.1%}"
              f"{oos_s['sharpe']:>16.2f}{oos_s['cagr']:>10.1%}{oos_s['max_dd']:>11.1%}{mark}")

    # v1 baseline per window
    v1_is = stats(window(v1, is_mask))
    v1_oos = stats(window(v1, oos_mask))

    chosen_tv = best_is[0]
    chosen_oos = best_is[2]

    print("\n" + "=" * 78)
    print("THE TEST: param chosen on IS only, judged on OOS it never saw")
    print("=" * 78)
    print(f"Chosen target_vol (best IS Sharpe): {chosen_tv:.2f}")
    print(f"{'':<22}{'Sharpe':>9}{'CAGR':>9}{'MaxDD':>9}")
    print("-" * 49)
    print(f"{'v1 baseline (OOS)':<22}{v1_oos['sharpe']:>9.2f}{v1_oos['cagr']:>9.1%}{v1_oos['max_dd']:>9.1%}")
    print(f"{'v2 @chosen (OOS)':<22}{chosen_oos['sharpe']:>9.2f}{chosen_oos['cagr']:>9.1%}{chosen_oos['max_dd']:>9.1%}")

    # Robustness summary
    oos_sharpes = [o["sharpe"] for _, _, o in rows]
    spread = max(oos_sharpes) - min(oos_sharpes)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    won_sharpe = chosen_oos["sharpe"] > v1_oos["sharpe"]
    print(f"- OOS Sharpe: v2 {chosen_oos['sharpe']:.2f} vs v1 {v1_oos['sharpe']:.2f}  "
          f"-> v2 {'WINS' if won_sharpe else 'LOSES'} out of sample")
    print(f"- OOS Sharpe spread across all target_vols: {spread:.2f} "
          f"({'FLAT = structural/robust' if spread < 0.10 else 'PEAKY = param-sensitive'})")
    print(f"- IS-best target ({chosen_tv:.2f}) "
          f"{'is near the OOS-best too' if abs(chosen_tv - max(rows, key=lambda x: x[2]['sharpe'])[0]) <= 0.10 else 'drifts from OOS-best (caution)'}")


if __name__ == "__main__":
    main()
