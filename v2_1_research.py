"""V2.1 research harness for the volatility-targeted TQQQ strategy.

This module is deliberately isolated from production.  It does not alter or feed
``tushar_v2_signal.py``.  Its job is to compare a small, pre-declared family of
causal alternatives under consistent data, execution, cash-yield, and stress
assumptions, then report the return/drawdown Pareto frontier.

Key conventions
---------------
* A signal formed with close ``t`` is first held for return ``t+1``.
* Rolling estimators never back-fill missing warm-up observations.
* Idle capital earns the historical 13-week Treasury-bill yield proxy.
* Results include a configurable rebalance band and trading friction.
* Pre-TQQQ history is a stress proxy only; it is never treated as actual fund data.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf


TRADING_DAYS = 252
TQQQ_EXPENSE = 0.0097
ACTUAL_START = pd.Timestamp("2010-02-11")
OOS_START = pd.Timestamp("2019-01-01")


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    target_vol: float = 0.45
    cap: float = 1.0
    vol_model: str = "roll20"
    high_period: int = 189
    gate_threshold: float = 0.15
    reentry_days: int = 3
    graded_start: float | None = None
    graded_end: float | None = None
    vix_filter: str = "none"
    crash_days: int = 0
    crash_loss: float = 0.0
    crash_scale: float = 1.0
    crash_cooldown: int = 0
    deadband: float = 0.02
    trade_bps: float = 2.0
    execution_lag: int = 1


@dataclass
class MarketData:
    index: pd.DatetimeIndex
    qqq_close: pd.Series
    qqq_ret: pd.Series
    tqqq_ret: pd.Series
    synthetic_ret: pd.Series
    combined_ret: pd.Series
    rf_daily: pd.Series
    vix: pd.Series
    vix3m: pd.Series
    actual_mask: pd.Series


@dataclass(frozen=True)
class Performance:
    cagr: float
    sharpe: float
    sortino: float
    max_dd: float
    calmar: float
    worst_1y: float
    worst_day: float
    cvar_95: float
    turnover_year: float
    avg_exposure: float
    final_100k: float


def _download(symbol: str, start: str) -> pd.DataFrame:
    raw = yf.download(symbol, start=start, auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        raw = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if raw is None or raw.empty:
        raise RuntimeError(f"No data returned for {symbol}")
    out = raw.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.columns = [str(c).lower() for c in out.columns]
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out


def load_market_data(start: str = "1998-01-01") -> MarketData:
    qqq = _download("QQQ", start)
    tqqq = _download("TQQQ", start)
    irx = _download("^IRX", start)
    vix = _download("^VIX", start)
    try:
        vix3m = _download("^VIX3M", start)
    except Exception:
        vix3m = pd.DataFrame(index=qqq.index, data={"close": np.nan})

    idx = qqq.index
    qclose = qqq["close"].reindex(idx).ffill()
    qret = qclose.pct_change(fill_method=None).fillna(0.0)

    # ^IRX is an annualized percentage yield.  It is a cash-return proxy, not a
    # tradable total-return index.  Keep a conservative fallback for missing days.
    irx_yield = irx["close"].reindex(idx).ffill() / 100.0
    fallback = pd.Series(np.where(idx < "2022-01-01", 0.015, 0.05), index=idx)
    rf_daily = irx_yield.where(irx_yield.notna(), fallback).clip(0.0, 0.20) / TRADING_DAYS

    tclose = tqqq["close"].reindex(idx)
    actual = tclose.pct_change(fill_method=None)
    synthetic = (3.0 * qret - 2.0 * rf_daily - TQQQ_EXPENSE / TRADING_DAYS).clip(lower=-0.95)
    combined = actual.combine_first(synthetic).fillna(0.0)
    actual_mask = tclose.notna()

    return MarketData(
        index=idx,
        qqq_close=qclose,
        qqq_ret=qret,
        tqqq_ret=actual,
        synthetic_ret=synthetic,
        combined_ret=combined,
        rf_daily=rf_daily,
        vix=vix["close"].reindex(idx).ffill(),
        vix3m=vix3m["close"].reindex(idx).ffill(),
        actual_mask=actual_mask,
    )


def binary_regime(
    close: pd.Series,
    high_period: int = 189,
    threshold: float = 0.15,
    reentry_days: int = 3,
) -> tuple[pd.Series, pd.Series]:
    high = close.rolling(high_period, min_periods=high_period).max()
    distance = (high - close) / high
    invested = False
    inside_days = 0
    values: list[float] = []
    for value in distance:
        if not np.isfinite(value):
            invested = False
            inside_days = 0
        elif value >= threshold:
            invested = False
            inside_days = 0
        else:
            inside_days += 1
            if inside_days >= reentry_days:
                invested = True
        values.append(float(invested))
    return pd.Series(values, index=close.index), distance


def regime_weight(close: pd.Series, config: StrategyConfig) -> pd.Series:
    binary, distance = binary_regime(
        close, config.high_period, config.gate_threshold, config.reentry_days
    )
    if config.graded_start is None or config.graded_end is None:
        return binary
    if config.graded_end <= config.graded_start:
        raise ValueError("graded_end must exceed graded_start")
    graded = ((config.graded_end - distance)
              / (config.graded_end - config.graded_start)).clip(0.0, 1.0)
    return graded.fillna(0.0)


def annualized_vol(ret: pd.Series, model: str) -> pd.Series:
    def rolling(window: int) -> pd.Series:
        return ret.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(TRADING_DAYS)

    if model.startswith("roll"):
        return rolling(int(model.removeprefix("roll")))
    if model == "ewma06":
        return ret.ewm(alpha=0.06, adjust=False, min_periods=20).std(bias=False) * np.sqrt(TRADING_DAYS)
    downside20 = (ret.clip(upper=0.0).pow(2).rolling(20, min_periods=20).mean().pow(0.5)
                  * np.sqrt(2.0 * TRADING_DAYS))
    if model == "downside20":
        # sqrt(2) puts downside semi-deviation on roughly the same scale as total
        # volatility for a symmetric return distribution.
        return downside20
    if model == "max10_60":
        return pd.concat([rolling(10), rolling(60)], axis=1).max(axis=1, skipna=False)
    if model == "blend10_60":
        return 0.5 * rolling(10) + 0.5 * rolling(60)
    if model == "max20_60":
        return pd.concat([rolling(20), rolling(60)], axis=1).max(axis=1, skipna=False)
    if model == "maxroll20_down20":
        return pd.concat([rolling(20), downside20], axis=1).max(axis=1, skipna=False)
    if model == "maxroll10_roll20":
        return pd.concat([rolling(10), rolling(20)], axis=1).max(axis=1, skipna=False)
    if model == "maxroll10_down20":
        return pd.concat([rolling(10), downside20], axis=1).max(axis=1, skipna=False)
    raise ValueError(f"Unknown volatility model: {model}")


def _persistent_scale(trigger: pd.Series, scale: float, cooldown: int) -> pd.Series:
    remaining = 0
    values: list[float] = []
    for active in trigger.fillna(False):
        if bool(active):
            remaining = max(1, cooldown)
        values.append(scale if remaining > 0 else 1.0)
        remaining = max(0, remaining - 1)
    return pd.Series(values, index=trigger.index)


def risk_scale(data: MarketData, config: StrategyConfig) -> pd.Series:
    scale = pd.Series(1.0, index=data.index)
    if config.vix_filter != "none":
        inverted = data.vix > data.vix3m
        elevated = data.vix > 25.0
        trigger = inverted & elevated & data.vix3m.notna()
        if config.vix_filter == "inv25_zero":
            scale = scale.where(~trigger, 0.0)
        elif config.vix_filter == "inv25_half":
            scale = scale.where(~trigger, 0.5)
        elif config.vix_filter == "vix30_half":
            scale = scale.where(~(data.vix > 30.0), 0.5)
        else:
            raise ValueError(f"Unknown VIX filter: {config.vix_filter}")
    if config.crash_days > 0:
        trailing = data.qqq_close.pct_change(config.crash_days, fill_method=None)
        trigger = trailing <= -config.crash_loss
        scale = scale * _persistent_scale(
            trigger, config.crash_scale, config.crash_cooldown
        )
    return scale.clip(0.0, 1.0)


def apply_deadband(target: pd.Series, band: float) -> pd.Series:
    if band <= 0:
        return target.copy()
    held = 0.0
    values: list[float] = []
    for desired in target.fillna(0.0):
        if abs(float(desired) - held) >= band:
            held = float(desired)
        values.append(held)
    return pd.Series(values, index=target.index)


def target_exposure(data: MarketData, config: StrategyConfig) -> pd.Series:
    regime = regime_weight(data.qqq_close, config)
    vol = annualized_vol(data.combined_ret, config.vol_model)
    raw = config.target_vol / vol.replace(0.0, np.nan)
    target = (regime * risk_scale(data, config) * raw).clip(0.0, config.cap)
    return apply_deadband(target.fillna(0.0), config.deadband)


def strategy_path(
    data: MarketData,
    config: StrategyConfig,
    extended: bool = False,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    target = target_exposure(data, config)
    held = target.shift(config.execution_lag).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs())
    asset = data.combined_ret if extended else data.tqqq_ret.fillna(0.0)
    ret = held * asset + (1.0 - held) * data.rf_daily
    ret = ret - turnover * config.trade_bps / 10_000.0
    if extended:
        mask = data.index >= pd.Timestamp("1999-03-10")
    else:
        mask = data.actual_mask & (data.index >= ACTUAL_START)
    return ret[mask], held[mask], turnover[mask]


def performance(
    ret: pd.Series,
    held: pd.Series,
    turnover: pd.Series,
    rf_daily: pd.Series | None = None,
) -> Performance:
    valid = ret.replace([np.inf, -np.inf], np.nan).dropna()
    held = held.reindex(valid.index).fillna(0.0)
    turnover = turnover.reindex(valid.index).fillna(0.0)
    eq = (1.0 + valid).cumprod()
    years = len(valid) / TRADING_DAYS
    cagr = eq.iloc[-1] ** (1.0 / years) - 1.0
    drawdown = eq / eq.cummax() - 1.0
    if rf_daily is None:
        excess = valid
    else:
        excess = valid - rf_daily.reindex(valid.index).fillna(0.0)
    std = excess.std(ddof=1)
    sharpe = excess.mean() / std * np.sqrt(TRADING_DAYS) if std > 0 else np.nan
    downside = excess[excess < 0].std(ddof=1)
    sortino = excess.mean() / downside * np.sqrt(TRADING_DAYS) if downside > 0 else np.nan
    max_dd = float(drawdown.min())
    calmar = cagr / abs(max_dd) if max_dd < 0 else np.nan
    if len(eq) > TRADING_DAYS:
        rolling_1y = eq.iloc[TRADING_DAYS:].to_numpy() / eq.iloc[:-TRADING_DAYS].to_numpy() - 1.0
        worst_1y = float(np.min(rolling_1y))
    else:
        worst_1y = np.nan
    cutoff = valid.quantile(0.05)
    cvar = float(valid[valid <= cutoff].mean())
    return Performance(
        cagr=float(cagr),
        sharpe=float(sharpe),
        sortino=float(sortino),
        max_dd=max_dd,
        calmar=float(calmar),
        worst_1y=worst_1y,
        worst_day=float(valid.min()),
        cvar_95=cvar,
        turnover_year=float(turnover.mean() * TRADING_DAYS),
        avg_exposure=float(held.mean()),
        final_100k=float(eq.iloc[-1] * 100_000.0),
    )


def conservative_tax_path(ret: pd.Series, tax_rate: float) -> pd.Series:
    """Stress taxes at each year-end; intentionally not a tax-lot engine.

    Every positive calendar-year portfolio gain is treated as taxable and losses
    receive no benefit.  This is conservative and is reported only as a stress
    result, never as an exact after-tax forecast.
    """
    out = ret.copy()
    equity = 1.0
    prior_year_end = 1.0
    for _, year_ret in ret.groupby(ret.index.year):
        last = year_ret.index[-1]
        for dt, daily in year_ret.items():
            before = equity
            equity *= 1.0 + daily
            if dt == last:
                gain = max(equity - prior_year_end, 0.0)
                equity -= gain * tax_rate
            out.loc[dt] = equity / before - 1.0
        prior_year_end = equity
    return out


def candidate_set() -> list[StrategyConfig]:
    candidates: dict[str, StrategyConfig] = {}

    def add(config: StrategyConfig) -> None:
        candidates[config.name] = config

    add(StrategyConfig(name="baseline_causal"))

    models = ["roll10", "roll20", "roll40", "roll60", "ewma06",
              "downside20", "max10_60", "blend10_60", "max20_60",
              "maxroll20_down20", "maxroll10_roll20", "maxroll10_down20"]
    for model in models:
        for target in (0.35, 0.40, 0.45, 0.50):
            for cap in (0.75, 1.0):
                add(StrategyConfig(
                    name=f"vol={model}_tv={target:.2f}_cap={cap:.2f}",
                    vol_model=model, target_vol=target, cap=cap,
                ))

    # Gate sensitivity stays intentionally coarse.
    for high in (126, 189, 252):
        for threshold in (0.125, 0.15, 0.175):
            for reentry in (1, 3, 5):
                add(StrategyConfig(
                    name=f"gate={high}_{threshold:.3f}_{reentry}",
                    high_period=high, gate_threshold=threshold, reentry_days=reentry,
                ))
    for start, end in ((0.08, 0.18), (0.10, 0.20), (0.12, 0.20), (0.12, 0.25)):
        add(StrategyConfig(
            name=f"graded={start:.2f}_{end:.2f}", graded_start=start, graded_end=end,
        ))

    # Test filters alone and with the estimator families that have an economic
    # rationale in volatile markets.  Avoid a full combinatorial data-mining grid.
    filter_bases = [
        StrategyConfig(name="tmp", vol_model=model, target_vol=target)
        for model in ("roll20", "downside20", "max10_60", "max20_60",
                      "maxroll20_down20")
        for target in (0.35, 0.40, 0.45)
    ]
    for base in filter_bases:
        for vf in ("inv25_zero", "inv25_half", "vix30_half"):
            add(replace(base, name=f"{base.vol_model}_{base.target_vol:.2f}_{vf}", vix_filter=vf))
        for days, loss, scale, cooldown in (
            (3, 0.06, 0.5, 3), (3, 0.08, 0.5, 3),
            (5, 0.08, 0.5, 5), (5, 0.10, 0.5, 5),
            (5, 0.08, 0.0, 3),
        ):
            add(replace(
                base,
                name=f"{base.vol_model}_{base.target_vol:.2f}_crash{days}_{loss:.2f}_{scale:.1f}_{cooldown}",
                crash_days=days, crash_loss=loss, crash_scale=scale,
                crash_cooldown=cooldown,
            ))
        add(replace(
            base,
            name=f"{base.vol_model}_{base.target_vol:.2f}_vix_crash_combo",
            vix_filter="inv25_zero", crash_days=5, crash_loss=0.08,
            crash_scale=0.5, crash_cooldown=5,
        ))

    # Stage-two neighborhood: the broad screen consistently identifies normalized
    # downside volatility near a 35% target.  Wider action bands test whether that
    # result remains useful after enforcing the baseline turnover budget.
    refinement_filters = (
        (0, 0.00, 1.0, 0, "none"),
        (3, 0.06, 0.5, 3, "crash3_06"),
        (3, 0.08, 0.5, 3, "crash3_08"),
        (5, 0.08, 0.5, 5, "crash5_08"),
    )
    for target in (0.33, 0.34, 0.35, 0.36, 0.37):
        for band in (0.03, 0.04, 0.05):
            for days, loss, scale, cooldown, label in refinement_filters:
                add(StrategyConfig(
                    name=f"refine_down20_tv={target:.2f}_band={band:.2f}_{label}",
                    vol_model="downside20", target_vol=target, deadband=band,
                    crash_days=days, crash_loss=loss, crash_scale=scale,
                    crash_cooldown=cooldown,
                ))

    # A hybrid risk estimate takes the larger of ordinary and normalized downside
    # volatility. At target <= 45%, it can never request more exposure than the
    # current roll20 rule, directly addressing sudden-gap exposure.
    for target in (0.40, 0.425, 0.45):
        for band in (0.02, 0.03, 0.05):
            for days, loss, scale, cooldown, label in refinement_filters:
                add(StrategyConfig(
                    name=f"hybrid_tv={target:.3f}_band={band:.2f}_{label}",
                    vol_model="maxroll20_down20", target_vol=target,
                    deadband=band, crash_days=days, crash_loss=loss,
                    crash_scale=scale, crash_cooldown=cooldown,
                ))

    # Cap refinement is the simplest possible risk control: it leaves the
    # existing V2 estimator and regime gate intact and only trims peak exposure.
    # Include it so a more complicated volatility model must beat a transparent
    # lower-cap alternative on the same assumptions.
    for cap in (0.80, 0.85, 0.90, 0.95):
        for band in (0.02, 0.03, 0.05):
            for days, loss, scale, cooldown, label in refinement_filters:
                add(StrategyConfig(
                    name=f"cap_refine={cap:.2f}_band={band:.2f}_{label}",
                    cap=cap, deadband=band, crash_days=days,
                    crash_loss=loss, crash_scale=scale,
                    crash_cooldown=cooldown,
                ))
    return list(candidates.values())


def _window_metrics(
    ret: pd.Series,
    held: pd.Series,
    turnover: pd.Series,
    rf_daily: pd.Series,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> Performance | None:
    mask = (ret.index >= pd.Timestamp(start)) & (ret.index <= pd.Timestamp(end))
    if mask.sum() < 100:
        return None
    return performance(ret[mask], held[mask], turnover[mask], rf_daily)


def evaluate_candidate(data: MarketData, config: StrategyConfig) -> dict[str, float | str]:
    ret, held, turnover = strategy_path(data, config, extended=False)
    full = performance(ret, held, turnover, data.rf_daily)
    oos_mask = ret.index >= OOS_START
    oos = performance(ret[oos_mask], held[oos_mask], turnover[oos_mask], data.rf_daily)
    ext_ret, ext_held, ext_turn = strategy_path(data, config, extended=True)
    extended = performance(ext_ret, ext_held, ext_turn, data.rf_daily)

    fold_specs = [
        ("2015-01-01", "2016-12-31"),
        ("2017-01-01", "2018-12-31"),
        ("2019-01-01", "2020-12-31"),
        ("2021-01-01", "2022-12-31"),
        ("2023-01-01", "2024-12-31"),
        ("2025-01-01", "2027-12-31"),
    ]
    folds = [m for start, end in fold_specs
             if (m := _window_metrics(ret, held, turnover, data.rf_daily, start, end)) is not None]

    row: dict[str, float | str] = {"name": config.name, **asdict(config)}
    for prefix, values in (("full", full), ("oos", oos), ("extended", extended)):
        for key, value in asdict(values).items():
            row[f"{prefix}_{key}"] = value
    row["fold_median_sharpe"] = float(np.median([m.sharpe for m in folds]))
    row["fold_median_calmar"] = float(np.median([m.calmar for m in folds]))
    row["fold_worst_cagr"] = float(np.min([m.cagr for m in folds]))
    row["fold_worst_dd"] = float(np.min([m.max_dd for m in folds]))

    for tax_rate in (0.24, 0.32):
        taxed = conservative_tax_path(ret, tax_rate)
        taxed_perf = performance(taxed, held, turnover)
        row[f"tax{int(tax_rate*100)}_cagr"] = taxed_perf.cagr
        row[f"tax{int(tax_rate*100)}_final_100k"] = taxed_perf.final_100k
    return row


def pareto_frontier(frame: pd.DataFrame, cagr_col: str, dd_col: str) -> pd.DataFrame:
    keep: list[bool] = []
    for i, row in frame.iterrows():
        dominates = (
            (frame[cagr_col] >= row[cagr_col])
            & (frame[dd_col] >= row[dd_col])
            & ((frame[cagr_col] > row[cagr_col]) | (frame[dd_col] > row[dd_col]))
        )
        dominates.loc[i] = False
        keep.append(not bool(dominates.any()))
    return frame.loc[keep].copy()


def add_acceptance(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    base = out.loc[out["name"] == "baseline_causal"].iloc[0]
    out["passes"] = (
        (out["full_cagr"] >= base["full_cagr"] - 0.05)
        & (out["full_max_dd"] >= base["full_max_dd"] + 0.05)
        & (out["oos_cagr"] >= base["oos_cagr"] - 0.05)
        & (out["oos_max_dd"] >= base["oos_max_dd"] + 0.04)
        & (out["oos_sharpe"] >= base["oos_sharpe"] - 0.02)
        & (out["extended_max_dd"] >= base["extended_max_dd"] + 0.05)
        & (out["full_turnover_year"] <= base["full_turnover_year"] * 1.25)
        & (out["fold_worst_cagr"] >= base["fold_worst_cagr"] - 0.05)
    )
    # Rank instead of inventing one absolute utility function.  This favors the
    # center of the return/risk frontier and consistency across subperiods.
    rank_cols = ["oos_cagr", "oos_sharpe", "oos_calmar",
                 "fold_median_sharpe", "fold_median_calmar", "extended_calmar"]
    ranks = [out[col].rank(pct=True) for col in rank_cols]
    out["robust_score"] = pd.concat(ranks, axis=1).mean(axis=1)
    return out


def print_report(results: pd.DataFrame, top: int = 15) -> None:
    base = results.loc[results["name"] == "baseline_causal"].iloc[0]
    print("\nCAUSAL, EXECUTION-ADJUSTED BASELINE")
    print(f"CAGR {base.full_cagr:.1%} | Sharpe {base.full_sharpe:.2f} | "
          f"MaxDD {base.full_max_dd:.1%} | extended MaxDD {base.extended_max_dd:.1%} | "
          f"turnover {base.full_turnover_year:.1f}x/year")

    passed = results[results["passes"]].sort_values("robust_score", ascending=False)
    print(f"\nSTRICT ACCEPTANCE: {len(passed)} of {len(results)} candidates passed")
    columns = ["name", "full_cagr", "full_sharpe", "full_max_dd",
               "oos_cagr", "oos_sharpe", "oos_max_dd", "extended_max_dd",
               "fold_worst_cagr", "full_turnover_year", "robust_score"]
    display = passed.head(top) if len(passed) else results.sort_values(
        ["oos_calmar", "oos_sharpe"], ascending=False
    ).head(top)
    print(display[columns].to_string(index=False, formatters={
        "full_cagr": "{:.1%}".format, "full_max_dd": "{:.1%}".format,
        "oos_cagr": "{:.1%}".format, "oos_max_dd": "{:.1%}".format,
        "extended_max_dd": "{:.1%}".format, "fold_worst_cagr": "{:.1%}".format,
        "full_sharpe": "{:.2f}".format, "oos_sharpe": "{:.2f}".format,
        "full_turnover_year": "{:.1f}".format, "robust_score": "{:.3f}".format,
    }))

    frontier = pareto_frontier(results, "oos_cagr", "oos_max_dd").sort_values("oos_cagr")
    print("\nOOS RETURN/DRAWDOWN PARETO FRONTIER")
    print(frontier[["name", "oos_cagr", "oos_max_dd", "oos_sharpe", "passes"]]
          .to_string(index=False, formatters={
              "oos_cagr": "{:.1%}".format, "oos_max_dd": "{:.1%}".format,
              "oos_sharpe": "{:.2f}".format,
          }))

    if len(passed):
        winner = passed.iloc[0]
        print("\nRESEARCH WINNER (not automatically promoted)")
        print(f"{winner['name']}: full CAGR {winner.full_cagr:.1%}, "
              f"full DD {winner.full_max_dd:.1%}; OOS CAGR {winner.oos_cagr:.1%}, "
              f"OOS DD {winner.oos_max_dd:.1%}; tax-stress CAGR "
              f"{winner.tax24_cagr:.1%}/{winner.tax32_cagr:.1%}.")
    else:
        print("\nVERDICT: no candidate cleared the pre-declared acceptance bar; current V2 stands.")


def run(output: Path | None = None, top: int = 15) -> pd.DataFrame:
    print("Downloading QQQ, TQQQ, ^IRX, ^VIX and ^VIX3M...")
    data = load_market_data()
    configs = candidate_set()
    print(f"Evaluating {len(configs)} pre-declared candidates...")
    rows = [evaluate_candidate(data, config) for config in configs]
    results = add_acceptance(pd.DataFrame(rows))
    print_report(results, top=top)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        results.sort_values("robust_score", ascending=False).to_csv(output, index=False)
        print(f"\nSaved detailed results to {output}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional CSV results path")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    run(args.output, args.top)


if __name__ == "__main__":
    main()
