"""
Tune v9 parameters (V9_SHARPE_OFFSET and V9_SHARPE_SCALE) to maximize returns.

Tests multiple parameter combinations across key historical years:
- 2019: Pure bull market (baseline)
- 2020: COVID chop + recovery
- 2022: Bear market (downside protection test)
- 2023: Bull recovery
- All-time CAGR (overall)

For each combination, computes backtest metrics and compares.
Outputs recommendation for best parameter set.
"""

import pandas as pd
import yfinance as yf
from datetime import date
from collections import defaultdict
import sys
import os

# Import backtest functions from main file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load the main module and get functions
import importlib.util
spec = importlib.util.spec_from_file_location("tusharStrategyDev", "tusharStrategyDev.py")
tsdev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tsdev)

# Parameter grid to test
OFFSET_VALUES = [0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
SCALE_VALUES  = [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
KEY_YEARS     = [2019, 2020, 2022, 2023]

def compute_signal_v9_with_params(qqq_df: pd.DataFrame, offset: float, scale: float) -> pd.DataFrame:
    """Compute v9 signal with custom offset and scale parameters."""
    v1 = tsdev.compute_signal_v1(qqq_df)

    close   = qqq_df["close"]
    daily_r = close.pct_change()
    ret_5d  = (close - close.shift(5)) / close.shift(5)
    vol_5d  = daily_r.rolling(5).std()

    sharpe5 = (ret_5d / vol_5d).where(vol_5d > 0, 0.0).fillna(0.0)

    raw_pos = offset + sharpe5 * scale
    sized   = raw_pos.clip(0.0, 1.0)

    pos_list, action_list = [], []
    prev_pos = 0.0
    for i, (_, row) in enumerate(v1.iterrows()):
        if row["regime"] == "BUY_TQQQ":
            pos = float(sized.iloc[i])
        else:
            pos = 0.0
        act = ("BUY" if pos > prev_pos else "SELL" if pos < prev_pos else "HOLD")
        pos_list.append(round(pos, 4))
        action_list.append(act)
        prev_pos = pos

    out = v1.copy()
    out["sharpe5"]       = sharpe5.values
    out["position_size"] = pos_list
    out["action"]        = action_list
    return out

def extract_cagr_and_annual_returns(daily_results: list) -> tuple[float, dict]:
    """Extract CAGR and annual returns from daily backtest results."""
    if not daily_results:
        return 0.0, {}

    # Compute daily returns from portfolio values
    daily_rets = []
    for i in range(1, len(daily_results)):
        prev_port = daily_results[i-1]["portfolio"]
        curr_port = daily_results[i]["portfolio"]
        if prev_port > 0:
            daily_rets.append((curr_port - prev_port) / prev_port)
        else:
            daily_rets.append(0.0)

    # Group by year
    annual = defaultdict(list)
    for i, d in enumerate(daily_results[1:], 1):  # Skip first day, align with daily_rets
        year = d["date"].year
        annual[year].append(daily_rets[i-1])

    # Compute annual returns
    annual_rets = {}
    for year, rets in annual.items():
        if rets:
            total = 1.0
            for ret in rets:
                total *= (1 + ret)
            annual_rets[year] = (total - 1) * 100
        else:
            annual_rets[year] = 0.0

    # Compute CAGR
    if daily_rets:
        total_return = 1.0
        for ret in daily_rets:
            total_return *= (1 + ret)
        years = (daily_results[-1]["date"].year - daily_results[0]["date"].year) + 1
        cagr = (total_return ** (1 / years) - 1) * 100 if years > 0 else 0
    else:
        cagr = 0.0

    return cagr, annual_rets

def run_v9_backtest(offset: float, scale: float) -> tuple[float, dict]:
    """Run v9 backtest with given parameters. Returns (cagr, annual_returns_dict)"""
    print(f"    Loading data...", end="", flush=True)
    qqq_df  = tsdev._load("QQQ", tsdev.DATA_START)
    tqqq_df = tsdev._load("TQQQ", tsdev.DATA_START)

    print(f" Computing v9 signal...", end="", flush=True)
    sig_v9 = compute_signal_v9_with_params(qqq_df, offset, scale)

    common = sig_v9.index.intersection(tqqq_df.index)
    sig_v9 = sig_v9.loc[common]
    tqqq_al = tqqq_df.loc[common]

    print(f" Running backtest...", end="", flush=True)
    daily_v9 = tsdev.run_backtest(sig_v9, tqqq_al, 100_000.0)

    cagr, annual = extract_cagr_and_annual_returns(daily_v9)
    print(f" Done")

    return cagr, annual

def main():
    print("=" * 90)
    print("V9 PARAMETER TUNING: Testing combinations to maximize returns")
    print("=" * 90)
    print(f"\nTesting {len(OFFSET_VALUES)} * {len(SCALE_VALUES)} = {len(OFFSET_VALUES) * len(SCALE_VALUES)} combinations")
    print(f"Key years for comparison: {KEY_YEARS}")
    print()

    results = {}  # {(offset, scale): {year: return, 'cagr': cagr}}

    for i, offset in enumerate(OFFSET_VALUES):
        for j, scale in enumerate(SCALE_VALUES):
            idx = i * len(SCALE_VALUES) + j + 1
            total = len(OFFSET_VALUES) * len(SCALE_VALUES)
            print(f"[{idx:2d}/{total}] OFFSET={offset:.2f}, SCALE={scale:.2f}... ", end="", flush=True)

            try:
                cagr, annual = run_v9_backtest(offset, scale)
                results[(offset, scale)] = {'cagr': cagr}
                results[(offset, scale)].update(annual)
                print(f"CAGR={cagr:+.1f}%", end="")
                for year in KEY_YEARS:
                    if year in annual:
                        print(f" {year}={annual[year]:+.1f}%", end="")
                print()
            except Exception as e:
                print(f"ERROR: {e}")

    # Analyze results
    print("\n" + "=" * 90)
    print("RESULTS SUMMARY - Top 10 by All-Time CAGR")
    print("=" * 90)

    # Sort by CAGR
    sorted_by_cagr = sorted(results.items(), key=lambda x: x[1]['cagr'], reverse=True)

    print(f"\n{'Offset':>8} {'Scale':>8} {'CAGR':>8} {'2019':>8} {'2020':>8} {'2022':>8} {'2023':>8}")
    print("-" * 60)
    for i, ((offset, scale), metrics) in enumerate(sorted_by_cagr[:10]):
        y19 = metrics.get(2019, 0)
        y20 = metrics.get(2020, 0)
        y22 = metrics.get(2022, 0)
        y23 = metrics.get(2023, 0)
        print(f"{offset:8.2f} {scale:8.2f} {metrics['cagr']:+8.1f}% {y19:+8.1f}% {y20:+8.1f}% {y22:+8.1f}% {y23:+8.1f}%")

    # Scoring: balance bull performance with bear protection
    print("\n" + "=" * 90)
    print("COMPOSITE SCORE: Balance between CAGR, bull performance, and bear protection")
    print("=" * 90)
    print("Score = CAGR + 0.5*(2022+60)/100 + 0.3*(avg_2019_2023)/100")
    print("(Higher 2022 is better for bear protection, higher bull returns)")

    scored = []
    for (offset, scale), metrics in results.items():
        cagr = metrics['cagr']
        bear_2022 = metrics.get(2022, 0)
        bull_2019 = metrics.get(2019, 0)
        bull_2023 = metrics.get(2023, 0)
        bull_avg = (bull_2019 + bull_2023) / 2 if bull_2019 and bull_2023 else 0

        score = cagr + 0.5 * (bear_2022 + 60) / 100 + 0.3 * bull_avg / 100
        scored.append(((offset, scale), metrics, score))

    sorted_by_score = sorted(scored, key=lambda x: x[2], reverse=True)

    print(f"\n{'Offset':>8} {'Scale':>8} {'CAGR':>8} {'2022':>8} {'Bull_Avg':>8} {'Score':>8}")
    print("-" * 60)
    for i, ((offset, scale), metrics, score) in enumerate(sorted_by_score[:10]):
        y22 = metrics.get(2022, 0)
        bull_2019 = metrics.get(2019, 0)
        bull_2023 = metrics.get(2023, 0)
        bull_avg = (bull_2019 + bull_2023) / 2 if bull_2019 and bull_2023 else 0
        print(f"{offset:8.2f} {scale:8.2f} {metrics['cagr']:+8.1f}% {y22:+8.1f}% {bull_avg:+8.1f}% {score:8.2f}")

    # Recommendation
    best_offset, best_scale = sorted_by_score[0][0]
    best_metrics = sorted_by_score[0][1]

    print("\n" + "=" * 90)
    print("RECOMMENDATION")
    print("=" * 90)
    print(f"\nOptimal parameter set: V9_SHARPE_OFFSET={best_offset:.2f}, V9_SHARPE_SCALE={best_scale:.2f}")
    print(f"\nExpected performance:")
    print(f"  All-time CAGR:  {best_metrics['cagr']:+.1f}%")
    print(f"  2019 (pure bull): {best_metrics.get(2019, 0):+.1f}%")
    print(f"  2020 (chop):      {best_metrics.get(2020, 0):+.1f}%")
    print(f"  2022 (bear):      {best_metrics.get(2022, 0):+.1f}% (vs v1 -54.7%)")
    print(f"  2023 (recovery):  {best_metrics.get(2023, 0):+.1f}%")

    # Show current baseline for comparison
    current_cagr = None
    for (offset, scale), metrics in results.items():
        if offset == 1.0 and scale == 0.5:
            current_cagr = metrics['cagr']
            break

    if current_cagr:
        improvement = best_metrics['cagr'] - current_cagr
        print(f"\nImprovement vs current (OFFSET=1.0, SCALE=0.5):")
        print(f"  Current CAGR: {current_cagr:+.1f}%")
        print(f"  New CAGR:     {best_metrics['cagr']:+.1f}%")
        print(f"  Improvement:  {improvement:+.1f} percentage points")

    print()

if __name__ == '__main__':
    main()
