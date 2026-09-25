"""Anchored two-year walk-forward test for the V2.1 safety family.

Every fold selects a configuration using only data available before that fold,
then holds the selection fixed for the next two calendar years.  This is a
research diagnostic; it does not feed the production signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from v2_1_research import (
    ACTUAL_START,
    StrategyConfig,
    load_market_data,
    performance,
    strategy_path,
)


@dataclass(frozen=True)
class FoldChoice:
    test_start: str
    test_end: str
    selected: str
    train_score: float
    test_cagr: float
    test_sharpe: float
    test_max_dd: float


BASELINE = StrategyConfig(name="baseline_causal")


def safety_family() -> list[StrategyConfig]:
    """Small family fixed before the walk-forward run.

    The hybrid estimator is at least as conservative as V2's roll20 estimator
    at the same target.  We vary only target, action band, and one continuation-
    crash overlay to keep selection pressure modest.
    """
    out = [BASELINE]
    for target in (0.40, 0.425, 0.45):
        for band in (0.03, 0.05):
            out.append(StrategyConfig(
                name=f"hybrid_{target:.3f}_{band:.2f}_none",
                target_vol=target,
                vol_model="maxroll20_down20",
                deadband=band,
            ))
            out.append(StrategyConfig(
                name=f"hybrid_{target:.3f}_{band:.2f}_crash5_08",
                target_vol=target,
                vol_model="maxroll20_down20",
                deadband=band,
                crash_days=5,
                crash_loss=0.08,
                crash_scale=0.5,
                crash_cooldown=5,
            ))
    return out


def _slice(series: pd.Series, start: str, end: str) -> pd.Series:
    return series[(series.index >= pd.Timestamp(start)) &
                  (series.index <= pd.Timestamp(end))]


def choose_on_training(data, configs, train_end: str) -> tuple[StrategyConfig, float]:
    """Choose by train-only Calmar subject to a modest return floor.

    A candidate must retain baseline CAGR minus five percentage points and stay
    within 1.25x baseline turnover.  Among eligible candidates, Calmar is the
    objective.  There is no test-period information in this decision.
    """
    base_ret, base_held, base_turn = strategy_path(data, BASELINE)
    train_start = ACTUAL_START.strftime("%Y-%m-%d")
    base_train = performance(
        _slice(base_ret, train_start, train_end),
        _slice(base_held, train_start, train_end),
        _slice(base_turn, train_start, train_end),
        data.rf_daily,
    )

    eligible: list[tuple[float, StrategyConfig]] = []
    for config in configs:
        ret, held, turn = strategy_path(data, config)
        metrics = performance(
            _slice(ret, train_start, train_end),
            _slice(held, train_start, train_end),
            _slice(turn, train_start, train_end),
            data.rf_daily,
        )
        if (metrics.cagr >= base_train.cagr - 0.05 and
                metrics.turnover_year <= base_train.turnover_year * 1.25):
            eligible.append((metrics.calmar, config))
    if not eligible:
        return BASELINE, base_train.calmar
    score, selected = max(eligible, key=lambda item: item[0])
    return selected, score


def run_walk_forward(data, configs=None) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    configs = safety_family() if configs is None else configs
    fold_specs = [
        ("2014-12-31", "2015-01-01", "2016-12-31"),
        ("2016-12-31", "2017-01-01", "2018-12-31"),
        ("2018-12-31", "2019-01-01", "2020-12-31"),
        ("2020-12-31", "2021-01-01", "2022-12-31"),
        ("2022-12-31", "2023-01-01", "2024-12-31"),
        ("2024-12-31", "2025-01-01", "2027-12-31"),
    ]
    base_ret, base_held, _ = strategy_path(data, BASELINE)
    wf_parts: list[pd.Series] = []
    base_parts: list[pd.Series] = []
    rows: list[FoldChoice] = []
    prior_held: float | None = None

    for train_end, test_start, test_end in fold_specs:
        selected, score = choose_on_training(data, configs, train_end)
        ret, held, turn = strategy_path(data, selected)
        test_ret = _slice(ret, test_start, test_end).copy()
        if test_ret.empty:
            continue
        test_held = held.reindex(test_ret.index)
        test_turn = turn.reindex(test_ret.index)
        # Correct the one rebalance at each fold boundary. ``strategy_path``
        # assumes its config was already active before the test; the walk-forward
        # portfolio may be switching from a different prior selection.
        first = test_ret.index[0]
        if prior_held is None:
            earlier = base_held[base_held.index < first]
            prior_held = float(earlier.iloc[-1]) if len(earlier) else 0.0
        modeled_turn = float(test_turn.loc[first])
        actual_turn = abs(float(test_held.loc[first]) - prior_held)
        test_ret.loc[first] -= (actual_turn - modeled_turn) * selected.trade_bps / 10_000.0
        metrics = performance(test_ret, test_held, test_turn, data.rf_daily)
        wf_parts.append(test_ret)
        base_parts.append(base_ret.reindex(test_ret.index))
        rows.append(FoldChoice(
            test_start=test_start,
            test_end=str(test_ret.index[-1].date()),
            selected=selected.name,
            train_score=score,
            test_cagr=metrics.cagr,
            test_sharpe=metrics.sharpe,
            test_max_dd=metrics.max_dd,
        ))
        prior_held = float(test_held.iloc[-1])

    return pd.DataFrame([row.__dict__ for row in rows]), pd.concat(wf_parts), pd.concat(base_parts)


def main() -> None:
    print("Loading market data for anchored walk-forward validation...")
    data = load_market_data()
    folds, wf_ret, base_ret = run_walk_forward(data)
    zeros = pd.Series(0.0, index=wf_ret.index)
    wf = performance(wf_ret, zeros, zeros, data.rf_daily)
    base = performance(base_ret, zeros, zeros, data.rf_daily)

    print("\nTRAIN-ONLY SELECTION, FOLLOWING TWO-YEAR TEST")
    print(folds.to_string(index=False, formatters={
        "train_score": "{:.2f}".format,
        "test_cagr": "{:.1%}".format,
        "test_sharpe": "{:.2f}".format,
        "test_max_dd": "{:.1%}".format,
    }))
    print("\nSTITCHED WALK-FORWARD RESULT (2015-present)")
    print(f"baseline CAGR {base.cagr:.1%}, Sharpe {base.sharpe:.2f}, DD {base.max_dd:.1%}")
    print(f"selected CAGR {wf.cagr:.1%}, Sharpe {wf.sharpe:.2f}, DD {wf.max_dd:.1%}")


if __name__ == "__main__":
    main()
