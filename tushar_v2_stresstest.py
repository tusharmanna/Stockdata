"""Tushar v2 survivability stress test.

Not another optimization. This asks the questions that decide whether you can
actually hold v2 with real money:

  1. Holding-period outcomes — if you started at the WORST possible time, what
     CAGR did you get over 1/3/5/10 years? How often were you positive?
  2. Drawdown depth AND duration — not just "how far down" but "how long
     underwater" (the part that breaks people).
  3. Sequence risk — the specific "started Jan 2021, right before 2022" path.
  4. Withdrawal stress — $1M start, pulling income out: does it survive a bad
     start, or does sequence-of-returns deplete it?

Uses v2 after-cost daily returns (defensive target_vol=0.45, cap 1.5), reusing
v1's regime logic from tusharStrategyDev.py.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TRADING_DAYS = 252
TARGET_VOL, LEV_CAP, VOL_WINDOW = 0.45, 1.5, 20
RATE_SPLIT_YEARS = 12
TBILL_EARLY, TBILL_LATE = 0.015, 0.05
MARGIN_EARLY, MARGIN_LATE = 0.025, 0.06


def v2_returns():
    qqq = _load(QQQ_TICKER)
    tqqq = _load(TQQQ_TICKER)
    sig = compute_signal_v1(qqq)
    regime = (sig["regime"] == "BUY_TQQQ").astype(float)
    idx = qqq.index.intersection(tqqq.index)
    regime = regime.loc[idx]
    tret = tqqq.loc[idx, "close"].pct_change().fillna(0.0)
    rv = (tret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    expo = (regime * (TARGET_VOL / rv).clip(0, LEV_CAP)).clip(0, LEV_CAP)
    e = expo.shift(1).fillna(0.0)
    years = (pd.Series(idx, index=idx) - idx[0]).dt.days.values / 365.25
    tbill = np.where(years > RATE_SPLIT_YEARS, TBILL_LATE, TBILL_EARLY)
    margin = np.where(years > RATE_SPLIT_YEARS, MARGIN_LATE, MARGIN_EARLY)
    r = (e * tret - (e - 1).clip(lower=0) * margin / TRADING_DAYS
         + (1 - e).clip(lower=0, upper=1) * tbill / TRADING_DAYS)
    return r


def rolling_cagr(ret, years):
    eq = (1 + ret).cumprod().values
    h = int(years * TRADING_DAYS)
    if h >= len(eq):
        return None
    out = [(eq[i + h] / eq[i]) ** (1 / years) - 1 for i in range(len(eq) - h)]
    return np.array(out)


def drawdown_episodes(ret):
    eq = (1 + ret).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1
    episodes = []
    in_dd = False
    for i in range(len(eq)):
        if dd.iloc[i] < 0 and not in_dd:
            in_dd, start, trough, tval = True, eq.index[i], eq.index[i], dd.iloc[i]
        elif in_dd:
            if dd.iloc[i] < tval:
                tval, trough = dd.iloc[i], eq.index[i]
            if dd.iloc[i] >= 0:  # recovered
                episodes.append((tval, start, trough, eq.index[i]))
                in_dd = False
    if in_dd:
        episodes.append((tval, start, trough, None))  # still underwater
    return sorted(episodes, key=lambda x: x[0])


def main():
    ret = v2_returns()
    eq = (1 + ret).cumprod()
    print(f"v2 daily returns: {ret.index[0].date()} to {ret.index[-1].date()} "
          f"({len(ret)} days)\n")

    # 1. Holding-period outcomes
    print("=" * 70)
    print("1. HOLDING-PERIOD OUTCOMES  (start at EVERY day, hold N years)")
    print("=" * 70)
    print(f"{'Horizon':<9}{'Worst CAGR':>12}{'Median':>10}{'Best':>10}{'% Positive':>13}")
    print("-" * 70)
    for n in [1, 3, 5, 10]:
        c = rolling_cagr(ret, n)
        if c is None:
            continue
        print(f"{str(n)+'-yr':<9}{c.min():>11.0%}{np.median(c):>10.0%}"
              f"{c.max():>10.0%}{(c > 0).mean():>12.0%}")
    print("\nReading: even the worst 5-year start matters more than the average.")

    # 2. Drawdown depth + duration
    print("\n" + "=" * 70)
    print("2. WORST DRAWDOWNS  (depth + how long underwater)")
    print("=" * 70)
    print(f"{'Depth':>8}{'Peak':>13}{'Trough':>13}{'Recovered':>13}{'Underwater':>13}")
    print("-" * 70)
    for depth, start, trough, rec in drawdown_episodes(ret)[:5]:
        rec_s = rec.date().isoformat() if rec is not None else "NOT YET"
        if rec is not None:
            uw = f"{(rec - start).days} days"
        else:
            uw = f"{(ret.index[-1] - start).days}+ days"
        print(f"{depth:>8.0%}{start.date().isoformat():>13}{trough.date().isoformat():>13}"
              f"{rec_s:>13}{uw:>13}")

    # 3. The 2021-start path (right before 2022)
    print("\n" + "=" * 70)
    print("3. SEQUENCE RISK: started 2021-01-04 (right before the 2022 crash)")
    print("=" * 70)
    start = pd.Timestamp("2021-01-04")
    sub = ret[ret.index >= start]
    sub_eq = (1 + sub).cumprod() * 100000
    trough_val = sub_eq.min()
    trough_dt = sub_eq.idxmin()
    # recovery to 100k
    recovered = sub_eq[sub_eq.index > trough_dt]
    rec_dt = recovered[recovered >= 100000].index
    rec_str = rec_dt[0].date().isoformat() if len(rec_dt) else "not yet"
    print(f"$100,000 invested 2021-01-04:")
    print(f"  Fell to ${trough_val:,.0f} ({trough_val/100000-1:+.0%}) by {trough_dt.date()}")
    print(f"  Back above $100k: {rec_str}")
    print(f"  Value today: ${sub_eq.iloc[-1]:,.0f} ({sub_eq.iloc[-1]/100000-1:+.0%})")

    # 4. Withdrawal stress
    print("\n" + "=" * 70)
    print("4. WITHDRAWAL STRESS: $1,000,000 start, withdraw $50k/yr (~$4,167/mo)")
    print("=" * 70)
    for label, s0 in [("From inception", ret.index[0]),
                      ("From 2021-01 (bad start)", pd.Timestamp("2021-01-04"))]:
        r = ret[ret.index >= s0]
        bal = 1_000_000.0
        monthly = 50000 / 12
        min_bal = bal
        cur_month = r.index[0].month
        for dt, dr in r.items():
            bal *= (1 + dr)
            if dt.month != cur_month:
                bal -= monthly
                cur_month = dt.month
            min_bal = min(min_bal, bal)
            if bal <= 0:
                print(f"  {label:<26}: DEPLETED at {dt.date()}")
                break
        else:
            print(f"  {label:<26}: low ${min_bal:,.0f}  ->  final ${bal:,.0f}")

    print("\nNote: after-cost gross of TAX. Real margin calls during a deep")
    print("drawdown could force liquidation at the worst possible moment.")


if __name__ == "__main__":
    main()
