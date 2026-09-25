"""Compare current TQQQ v2 with a 50/50 TQQQ/UDOW invested sleeve.

Both strategies use the production QQQ regime and TQQQ-based 20-day volatility
exposure.  The requested variant splits that exposure equally between TQQQ and
UDOW and rebalances to 50/50 daily.  Signals are shifted one trading day to keep
returns causal, and idle capital earns the same simplified T-bill schedule used
by the existing v2 research.

This is a research comparison only; it does not change production signals.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER


TRADING_DAYS = 252
TARGET_VOL = 0.45
VOL_WINDOW = 20
LEV_CAP = 1.0
IS_END = pd.Timestamp("2018-12-31")

RATE_SPLIT_YEARS = 12
TBILL_EARLY = 0.015
TBILL_LATE = 0.05


def rate_series(dates: pd.Series) -> pd.Series:
    years = (dates - dates.iloc[0]).dt.days.values / 365.25
    rates = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
    return pd.Series(rates / TRADING_DAYS, index=dates.index)


def exposure_from_vol(regime: pd.Series, returns: pd.Series) -> pd.Series:
    realized_vol = returns.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
    realized_vol = realized_vol.bfill()
    return (regime * (TARGET_VOL / realized_vol)).clip(0.0, LEV_CAP)


def strategy_returns(
    exposure: pd.Series,
    invested_return: pd.Series,
    cash_return: pd.Series,
) -> pd.Series:
    held_exposure = exposure.shift(1).fillna(0.0)
    idle = (1.0 - held_exposure).clip(0.0, 1.0)
    return held_exposure * invested_return + idle * cash_return


def metrics(returns: pd.Series, cash_return: pd.Series) -> dict:
    equity = (1.0 + returns).cumprod()
    years = len(returns) / TRADING_DAYS
    excess = returns - cash_return
    drawdown = equity / equity.cummax() - 1.0
    return {
        "cagr": equity.iloc[-1] ** (1.0 / years) - 1.0,
        "sharpe": excess.mean() / excess.std() * np.sqrt(TRADING_DAYS),
        "max_dd": drawdown.min(),
        "growth": equity.iloc[-1],
    }


def format_row(label: str, result: dict) -> str:
    return (
        f"{label:<31}"
        f"{result['cagr']:>10.1%}"
        f"{result['sharpe']:>10.2f}"
        f"{result['max_dd']:>11.1%}"
        f"{result['growth']:>12.1f}x"
    )


def main() -> None:
    print("Loading QQQ, TQQQ, and UDOW...")
    qqq_full = _load(QQQ_TICKER)
    tqqq = _load(TQQQ_TICKER)
    udow = _load("UDOW")

    # Build the regime on QQQ's full history before aligning ETF inception dates,
    # matching the production backtest's rolling-high warmup behavior.
    signal = compute_signal_v1(qqq_full)
    index = qqq_full.index.intersection(tqqq.index).intersection(udow.index)
    tqqq = tqqq.loc[index]
    udow = udow.loc[index]

    regime = (signal.loc[index, "regime"] == "BUY_TQQQ").astype(float)
    tqqq_return = tqqq["close"].pct_change().fillna(0.0)
    udow_return = udow["close"].pct_change().fillna(0.0)
    mixed_return = 0.5 * tqqq_return + 0.5 * udow_return
    dates = pd.Series(index, index=index)
    cash_return = rate_series(dates)

    # Apples-to-apples test: keep the production exposure signal and only change
    # what is held inside the invested sleeve.
    production_exposure = exposure_from_vol(regime, tqqq_return)
    baseline = strategy_returns(production_exposure, tqqq_return, cash_return)
    requested_mix = strategy_returns(production_exposure, mixed_return, cash_return)

    # Diagnostic: size from the blend's own volatility. This is not the requested
    # production rule, but shows whether measuring the diversified sleeve changes
    # the conclusion at the same 45% target and 1.0 cap.
    mix_exposure = exposure_from_vol(regime, mixed_return)
    mix_own_vol = strategy_returns(mix_exposure, mixed_return, cash_return)

    variants = {
        "Current v2: 100% TQQQ": baseline,
        "Requested: 50% TQQQ / UDOW": requested_mix,
        "50/50, sized on blend vol": mix_own_vol,
    }

    masks = {
        "Full common history": np.ones(len(index), dtype=bool),
        "In-sample through 2018": index <= IS_END,
        "Out-of-sample from 2019": index > IS_END,
    }

    print(f"\nCommon range: {index[0].date()} to {index[-1].date()}")
    print("Daily-rebalanced blend; adjusted ETF prices; no tax or slippage model.")
    for window_name, mask in masks.items():
        print(f"\n{window_name}")
        print("-" * 74)
        print(f"{'Strategy':<31}{'CAGR':>10}{'Sharpe':>10}{'Max DD':>11}{'Growth':>12}")
        print("-" * 74)
        for label, returns in variants.items():
            print(format_row(label, metrics(returns[mask], cash_return[mask])))

    print("\nOut-of-sample subperiods")
    print("-" * 74)
    print(f"{'Period':<15}{'TQQQ v2 CAGR':>16}{'50/50 CAGR':>15}{'TQQQ DD':>13}{'50/50 DD':>13}")
    print("-" * 74)
    periods = [
        ("2019-2021", "2019-01-01", "2021-12-31"),
        ("2022-2023", "2022-01-01", "2023-12-31"),
        ("2024-latest", "2024-01-01", str(index[-1].date())),
    ]
    for label, start, end in periods:
        mask = (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))
        base_stats = metrics(baseline[mask], cash_return[mask])
        mix_stats = metrics(requested_mix[mask], cash_return[mask])
        print(
            f"{label:<15}{base_stats['cagr']:>16.1%}{mix_stats['cagr']:>15.1%}"
            f"{base_stats['max_dd']:>13.1%}{mix_stats['max_dd']:>13.1%}"
        )

    correlation = tqqq_return.loc[index > IS_END].corr(udow_return.loc[index > IS_END])
    print(f"\nOOS daily-return correlation, TQQQ vs UDOW: {correlation:.2f}")


if __name__ == "__main__":
    main()
