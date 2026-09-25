"""Preliminary 5-minute Opening Range Breakout backtest for QQQ.

Rules
-----
* Opening range is the 09:30-09:35 ET bar.
* Confirm a breakout when a later 5-minute bar closes outside that range.
* Enter at the next bar's open; take at most one trade per session.
* Stop at the opposite side of the opening range.
* Exit at the selected R target, the stop, or the 15:55 bar close.
* If stop and target occur in one bar, assume the stop happened first.
* Apply one basis point of adverse execution at entry and exit.

The script sweeps profit targets without selecting a winner. Yahoo currently
limits 5-minute history, so this is a short-horizon diagnostic, not sufficient
evidence for deployment.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf


TICKER = "QQQ"
INTERVAL = "5m"
PERIOD = "60d"
SLIPPAGE_BPS_PER_SIDE = 1.0
RISK_PER_TRADE = 0.01
MAX_NOTIONAL = 1.0
TARGETS = (0.5, 1.0, 2.0, 3.0, 10.0, None)


@dataclass
class Trade:
    date: object
    side: str
    entry_time: object
    entry: float
    exit: float
    reason: str
    risk: float
    net_asset_return: float
    portfolio_return: float

    @property
    def net_r(self) -> float:
        return self.net_asset_return * self.entry / self.risk


def load_bars() -> pd.DataFrame:
    bars = yf.download(
        TICKER,
        period=PERIOD,
        interval=INTERVAL,
        auto_adjust=True,
        prepost=False,
        progress=False,
    )
    if bars is None or bars.empty:
        raise RuntimeError("No QQQ intraday data returned by Yahoo Finance.")
    if isinstance(bars.columns, pd.MultiIndex):
        bars.columns = bars.columns.get_level_values(0)
    bars.columns = [str(column).lower() for column in bars.columns]
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize("America/New_York")
    else:
        bars.index = bars.index.tz_convert("America/New_York")
    return bars[["open", "high", "low", "close", "volume"]].dropna()


def adverse_execution(price: float, side: str, entering: bool) -> float:
    slip = SLIPPAGE_BPS_PER_SIDE / 10_000.0
    if (side == "LONG" and entering) or (side == "SHORT" and not entering):
        return price * (1.0 + slip)
    return price * (1.0 - slip)


def backtest(bars: pd.DataFrame, target_r: float | None) -> list[Trade]:
    trades = []
    for session_date, day in bars.groupby(bars.index.date):
        day = day.between_time("09:30", "15:55")
        if len(day) < 3 or day.index[0].time() != pd.Timestamp("09:30").time():
            continue

        opening = day.iloc[0]
        range_high = float(opening["high"])
        range_low = float(opening["low"])
        if range_high <= range_low:
            continue

        signal_index = None
        side = None
        for index_position in range(1, len(day) - 1):
            close = float(day.iloc[index_position]["close"])
            if close > range_high:
                signal_index, side = index_position, "LONG"
                break
            if close < range_low:
                signal_index, side = index_position, "SHORT"
                break
        if signal_index is None:
            continue

        entry_position = signal_index + 1
        entry_bar = day.iloc[entry_position]
        raw_entry = float(entry_bar["open"])
        stop = range_low if side == "LONG" else range_high
        risk = raw_entry - stop if side == "LONG" else stop - raw_entry
        if risk <= 0:
            continue

        target = None
        if target_r is not None:
            target = raw_entry + target_r * risk if side == "LONG" else raw_entry - target_r * risk

        raw_exit = float(day.iloc[-1]["close"])
        reason = "EOD"
        for position in range(entry_position, len(day)):
            bar = day.iloc[position]
            hit_stop = float(bar["low"]) <= stop if side == "LONG" else float(bar["high"]) >= stop
            hit_target = False
            if target is not None:
                hit_target = float(bar["high"]) >= target if side == "LONG" else float(bar["low"]) <= target

            # Five-minute OHLC cannot reveal ordering; use the adverse assumption.
            if hit_stop:
                raw_exit, reason = stop, "STOP"
                break
            if hit_target:
                raw_exit, reason = target, "TARGET"
                break

        entry = adverse_execution(raw_entry, side, entering=True)
        exit_price = adverse_execution(raw_exit, side, entering=False)
        direction = 1.0 if side == "LONG" else -1.0
        net_asset_return = direction * (exit_price - entry) / entry
        stop_fraction = risk / raw_entry
        notional = min(MAX_NOTIONAL, RISK_PER_TRADE / stop_fraction)
        portfolio_return = notional * net_asset_return
        trades.append(
            Trade(
                date=session_date,
                side=side,
                entry_time=day.index[entry_position],
                entry=entry,
                exit=exit_price,
                reason=reason,
                risk=risk,
                net_asset_return=net_asset_return,
                portfolio_return=portfolio_return,
            )
        )
    return trades


def summarize(trades: list[Trade], session_count: int) -> dict:
    returns = pd.Series([trade.portfolio_return for trade in trades], dtype=float)
    if returns.empty:
        return {key: np.nan for key in ("win_rate", "avg_r", "profit_factor", "total", "max_dd")}
    wins = returns > 0
    gross_profit = returns[returns > 0].sum()
    gross_loss = -returns[returns < 0].sum()
    daily = pd.Series(0.0, index=range(session_count))
    for position, value in enumerate(returns):
        daily.iloc[position] = value
    equity = (1.0 + daily).cumprod()
    return {
        "trades": len(trades),
        "win_rate": wins.mean(),
        "avg_r": np.mean([trade.net_r for trade in trades]),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else np.inf,
        "total": equity.iloc[-1] - 1.0,
        "max_dd": (equity / equity.cummax() - 1.0).min(),
    }


def main() -> None:
    bars = load_bars()
    session_count = len(set(bars.index.date))
    first_date, last_date = bars.index[0].date(), bars.index[-1].date()
    print(f"QQQ 5-minute ORB: {first_date} to {last_date} ({session_count} sessions)")
    print(
        f"One trade/day, next-bar entry, 1 bp/side execution cost, "
        f"{RISK_PER_TRADE:.0%} risk target capped at {MAX_NOTIONAL:.0f}x notional."
    )
    print("-" * 82)
    print(f"{'Target':>9}{'Trades':>9}{'Win rate':>12}{'Avg R':>10}{'Profit factor':>16}{'Return':>12}{'Max DD':>11}")
    print("-" * 82)
    for target in TARGETS:
        trades = backtest(bars, target)
        result = summarize(trades, session_count)
        label = "EOD" if target is None else f"{target:g}R"
        print(
            f"{label:>9}{result['trades']:>9}{result['win_rate']:>12.1%}{result['avg_r']:>10.2f}"
            f"{result['profit_factor']:>16.2f}{result['total']:>12.1%}{result['max_dd']:>11.1%}"
        )


if __name__ == "__main__":
    main()
