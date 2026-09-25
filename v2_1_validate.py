"""Independent validation report for the fixed V2.1 safety finalist.

This file does not alter the production strategy.  The candidate was frozen after
the broad and local-neighborhood screens in ``v2_1_research.py``.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from v2_1_research import (
    StrategyConfig,
    conservative_tax_path,
    load_market_data,
    performance,
    strategy_path,
    target_exposure,
)


BASELINE = StrategyConfig(name="baseline_causal")
FINALIST = StrategyConfig(
    name="v2.1_safety_finalist",
    target_vol=0.40,
    vol_model="maxroll20_down20",
    deadband=0.03,
    crash_days=5,
    crash_loss=0.08,
    crash_scale=0.5,
    crash_cooldown=5,
)


def metrics_for(data, config, extended=False, start=None, end=None):
    ret, held, turn = strategy_path(data, config, extended=extended)
    mask = pd.Series(True, index=ret.index)
    if start is not None:
        mask &= ret.index >= pd.Timestamp(start)
    if end is not None:
        mask &= ret.index <= pd.Timestamp(end)
    return performance(ret[mask], held[mask], turn[mask], data.rf_daily), ret[mask], held[mask], turn[mask]


def paired_block_bootstrap(base: pd.Series, candidate: pd.Series, block=20, trials=2000, seed=20260815):
    pair = pd.concat([base.rename("base"), candidate.rename("candidate")], axis=1).dropna()
    values = pair.to_numpy()
    n = len(values)
    rng = np.random.default_rng(seed)
    dcagr = np.empty(trials)
    ddd = np.empty(trials)
    dcalmar = np.empty(trials)

    def stats(x):
        eq = np.cumprod(1.0 + x)
        years = len(x) / 252
        cagr = eq[-1] ** (1 / years) - 1
        dd = np.min(eq / np.maximum.accumulate(eq) - 1)
        calmar = cagr / abs(dd) if dd < 0 else np.nan
        return cagr, dd, calmar

    max_start = n - block + 1
    blocks_needed = int(np.ceil(n / block))
    for i in range(trials):
        starts = rng.integers(0, max_start, size=blocks_needed)
        sample = np.concatenate([values[s:s + block] for s in starts], axis=0)[:n]
        bs = stats(sample[:, 0])
        cs = stats(sample[:, 1])
        dcagr[i] = cs[0] - bs[0]
        ddd[i] = cs[1] - bs[1]
        dcalmar[i] = cs[2] - bs[2]
    return {
        "median_cagr_diff": float(np.median(dcagr)),
        "p_cagr_not_worse_5pp": float(np.mean(dcagr >= -0.05)),
        "median_dd_improvement": float(np.median(ddd)),
        "p_dd_improves_4pp": float(np.mean(ddd >= 0.04)),
        "p_calmar_improves": float(np.mean(dcalmar > 0)),
        "p_joint": float(np.mean((dcagr >= -0.05) & (ddd >= 0.04) & (dcalmar > 0))),
    }


def print_pair(label, base, candidate):
    print(f"{label:<24}  base CAGR {base.cagr:>6.1%} DD {base.max_dd:>6.1%} Sh {base.sharpe:>4.2f}"
          f"  |  V2.1 CAGR {candidate.cagr:>6.1%} DD {candidate.max_dd:>6.1%} Sh {candidate.sharpe:>4.2f}")


def main():
    print("Loading market data for fixed-finalist validation...")
    data = load_market_data()

    base, base_ret, _, _ = metrics_for(data, BASELINE)
    finalist, finalist_ret, finalist_held, finalist_turn = metrics_for(data, FINALIST)
    base_ext, _, _, _ = metrics_for(data, BASELINE, extended=True)
    final_ext, _, _, _ = metrics_for(data, FINALIST, extended=True)

    print("\nFIXED CONFIGURATION")
    print(FINALIST)
    print("\nACTUAL TQQQ / EXTENDED STRESS")
    print_pair("2010-present", base, finalist)
    print_pair("1999 stress proxy", base_ext, final_ext)

    print("\nTWO-YEAR REGIME WINDOWS")
    periods = [
        ("2011-2012", "2011-01-01", "2012-12-31"),
        ("2013-2014", "2013-01-01", "2014-12-31"),
        ("2015-2016", "2015-01-01", "2016-12-31"),
        ("2017-2018", "2017-01-01", "2018-12-31"),
        ("2019-2020", "2019-01-01", "2020-12-31"),
        ("2021-2022", "2021-01-01", "2022-12-31"),
        ("2023-2024", "2023-01-01", "2024-12-31"),
        ("2025-now", "2025-01-01", "2027-12-31"),
    ]
    for label, start, end in periods:
        bm, *_ = metrics_for(data, BASELINE, start=start, end=end)
        cm, *_ = metrics_for(data, FINALIST, start=start, end=end)
        print_pair(label, bm, cm)

    print("\nEXECUTION SENSITIVITY")
    print(f"{'lag/cost':<12}{'base CAGR':>11}{'base DD':>10}{'V2.1 CAGR':>12}{'V2.1 DD':>10}{'turn/yr':>10}")
    execution_pairs = []
    for lag in (1, 2):
        for bps in (2.0, 5.0, 10.0):
            bc = replace(BASELINE, execution_lag=lag, trade_bps=bps)
            fc = replace(FINALIST, execution_lag=lag, trade_bps=bps)
            bm, *_ = metrics_for(data, bc)
            fm, *_ = metrics_for(data, fc)
            execution_pairs.append((lag, bps, bm, fm))
            print(f"{lag}d/{bps:.0f}bp{bm.cagr:>12.1%}{bm.max_dd:>10.1%}"
                  f"{fm.cagr:>12.1%}{fm.max_dd:>10.1%}{fm.turnover_year:>10.1f}")

    print("\nPAIRED 20-DAY BLOCK BOOTSTRAP (2,000 trials)")
    boot = paired_block_bootstrap(base_ret, finalist_ret)
    for key, value in boot.items():
        print(f"{key:<28}: {value:.1%}")

    print("\nTAX STRESS")
    for tax in (0.24, 0.32, 0.40):
        taxed = conservative_tax_path(finalist_ret, tax)
        tm = performance(taxed, finalist_held, finalist_turn)
        print(f"{tax:.0%}: CAGR {tm.cagr:.1%}, final $100k -> ${tm.final_100k:,.0f}")

    latest_base = float(target_exposure(data, BASELINE).iloc[-1])
    latest_final = float(target_exposure(data, FINALIST).iloc[-1])
    print("\nSUDDEN-GAP EXPOSURE")
    print(f"Latest target: baseline {latest_base:.2f}x, V2.1 {latest_final:.2f}x")
    for qqq_shock in (-0.10, -0.15, -0.20):
        tqqq_shock = max(-0.95, 3 * qqq_shock)
        print(f"QQQ {qqq_shock:+.0%} / approximate TQQQ {tqqq_shock:+.0%}: "
              f"baseline {latest_base*tqqq_shock:+.1%}, V2.1 {latest_final*tqqq_shock:+.1%}")

    checks = {
        "full CAGR within 5pp": finalist.cagr >= base.cagr - 0.05,
        "full drawdown improves 5pp": finalist.max_dd >= base.max_dd + 0.05,
        "full Sharpe within 0.02": finalist.sharpe >= base.sharpe - 0.02,
        "extended drawdown improves 5pp": final_ext.max_dd >= base_ext.max_dd + 0.05,
        "two-day-lag drawdown improves 4pp": all(
            fm.max_dd >= bm.max_dd + 0.04
            for lag, _, bm, fm in execution_pairs if lag == 2
        ),
        "bootstrap joint probability >=60%": boot["p_joint"] >= 0.60,
        "latest exposure no higher": latest_final <= latest_base,
    }
    print("\nPROMOTION VERDICT")
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {label}")
    print("READY" if all(checks.values()) else "NOT READY — keep production V2 unchanged; shadow only")


if __name__ == "__main__":
    main()
