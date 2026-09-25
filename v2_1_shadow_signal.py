"""Daily shadow signal for the V2.1 balanced safety candidate.

This script is intentionally disconnected from ``run_daily_signals.py`` and all
order/account files.  It compares V2.1 with production V2 and only writes a
research history when invoked with ``--log``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from v2_1_research import StrategyConfig, load_market_data, target_exposure


BASELINE = StrategyConfig(name="v2_production_reference")
SHADOW = StrategyConfig(
    name="v2.1_balanced_shadow",
    target_vol=0.40,
    vol_model="maxroll20_down20",
    deadband=0.03,
    crash_days=5,
    crash_loss=0.08,
    crash_scale=0.5,
    crash_cooldown=5,
)
HISTORY = Path("signals/v2_1_shadow_history.csv")


def classify_action(previous: float, current: float, tolerance: float = 0.005) -> str:
    if previous <= tolerance and current > tolerance:
        return "ENTER"
    if previous > tolerance and current <= tolerance:
        return "EXIT"
    if current > previous + tolerance:
        return "INCREASE"
    if current < previous - tolerance:
        return "REDUCE"
    return "HOLD"


def latest_row(data) -> dict[str, object]:
    baseline = target_exposure(data, BASELINE)
    shadow = target_exposure(data, SHADOW)
    valid = pd.concat([baseline.rename("baseline"), shadow.rename("shadow")], axis=1).dropna()
    if len(valid) < 2:
        raise RuntimeError("Not enough valid observations to form a shadow signal")
    date = valid.index[-1]
    current = float(valid.iloc[-1].shadow)
    previous = float(valid.iloc[-2].shadow)
    trailing_5d = float(data.qqq_close.pct_change(5, fill_method=None).loc[date])
    return {
        "date": date.date().isoformat(),
        "qqq_close": float(data.qqq_close.loc[date]),
        "qqq_5d_return": trailing_5d,
        "baseline_exposure": float(valid.iloc[-1].baseline),
        "shadow_exposure": current,
        "shadow_action": classify_action(previous, current),
        "production_changed": False,
    }


def append_history(row: dict[str, object], path: Path = HISTORY) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str})
        old = old[old["date"] != row["date"]]
        new = pd.concat([old, new], ignore_index=True).sort_values("date")
    new.to_csv(path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="store_true", help="Append/replace today's shadow-history row")
    args = parser.parse_args()

    data = load_market_data()
    row = latest_row(data)
    print(f"V2.1 balanced SHADOW — {row['date']}")
    print(f"QQQ close ${row['qqq_close']:.2f}; 5d return {row['qqq_5d_return']:+.1%}")
    print(f"Production V2 target: {row['baseline_exposure']:.2f}x")
    print(f"V2.1 shadow target:   {row['shadow_exposure']:.2f}x ({row['shadow_action']})")
    print("Research only: production signal and orders are unchanged.")
    if args.log:
        append_history(row)
        print(f"Logged to {HISTORY}")


if __name__ == "__main__":
    main()
