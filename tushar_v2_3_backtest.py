"""Research backtest for Tushar v2.3 combined risk controls.

Production files are intentionally unchanged.  v2.3 combines the current v2
20-day volatility target with a 100-day QQQ trend cap and a portfolio drawdown
throttle.  The simulator also charges turnover slippage and ETF expense drag,
so the comparison is deliberately conservative.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TRADING_DAYS = 252
TARGET_VOL = 0.45
LEV_CAP = 1.0
VOL_WINDOW = 20
MA_SLOW = 100
TREND_CAP = 0.75
SLIPPAGE_BPS = 5.0       # one-way cost applied to daily exposure turnover
TQQQ_EXPENSE = 0.0095    # approximate annual TQQQ expense ratio
IS_END = pd.Timestamp("2018-12-31")
TBILL_EARLY, TBILL_LATE = 0.015, 0.05


def base_exposure(regime, tqqq_ret):
    rv = tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
    rv = rv.bfill()
    return (regime * (TARGET_VOL / rv).clip(0, LEV_CAP)).clip(0, LEV_CAP)


def trend_cap(qqq_close):
    ma = qqq_close.rolling(MA_SLOW, min_periods=MA_SLOW).mean().bfill()
    return pd.Series(np.where(qqq_close < ma, TREND_CAP, LEV_CAP), index=qqq_close.index)


def conservative_sim(target, tqqq_ret, dates, drawdown_levels=None):
    """Simulate returns causally, including cash yield, slippage and expense drag."""
    target = target.fillna(0.0).clip(0, LEV_CAP)
    equity = 1.0
    peak = 1.0
    prev_exposure = 0.0
    out, exposures, drawdowns = [], [], []
    years = (dates - dates.iloc[0]).dt.days.to_numpy() / 365.25
    tbill = np.where(years > 12, TBILL_LATE, TBILL_EARLY)
    for i, (date, asset_ret) in enumerate(zip(dates, tqqq_ret)):
        requested = float(target.iloc[i])
        prior_dd = equity / peak - 1.0
        if drawdown_levels:
            for threshold, cap in drawdown_levels:
                if prior_dd <= -threshold:
                    requested = min(requested, cap)
        # Exposure decided at yesterday's close is used for today's return.
        e = prev_exposure
        idle = max(0.0, 1.0 - e)
        gross = e * float(asset_ret) + idle * float(tbill[i]) / TRADING_DAYS
        gross -= e * TQQQ_EXPENSE / TRADING_DAYS
        turnover = abs(requested - prev_exposure)
        net = gross - turnover * SLIPPAGE_BPS / 10000.0
        equity *= 1.0 + net
        peak = max(peak, equity)
        out.append(net)
        exposures.append(e)
        drawdowns.append(equity / peak - 1.0)
        prev_exposure = requested
    return pd.Series(out, index=dates), pd.Series(exposures, index=dates), pd.Series(drawdowns, index=dates)


def metrics(ret):
    eq = (1 + ret).cumprod()
    years = len(ret) / TRADING_DAYS
    return dict(total=eq.iloc[-1] - 1, cagr=eq.iloc[-1] ** (1 / years) - 1,
                sharpe=ret.mean() / ret.std() * np.sqrt(TRADING_DAYS),
                max_dd=(eq / eq.cummax() - 1).min(), final=eq.iloc[-1] * 100000)


def report(title, rows):
    print("\n" + title)
    print("=" * 88)
    print(f"{'Strategy':<27}{'Total':>10}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Final $':>15}")
    for name, ret in rows:
        m = metrics(ret)
        print(f"{name:<27}{m['total']:>9.0%}{m['cagr']:>9.1%}{m['sharpe']:>9.2f}{m['max_dd']:>9.1%}{m['final']:>15,.0f}")


def main():
    qqq, tqqq = _load(QQQ_TICKER), _load(TQQQ_TICKER)
    idx = qqq.index.intersection(tqqq.index)
    qqq, tqqq = qqq.loc[idx], tqqq.loc[idx]
    dates = pd.Series(idx, index=idx)
    sig = compute_signal_v1(qqq)
    regime = (sig['regime'] == 'BUY_TQQQ').astype(float).loc[idx]
    t_ret = tqqq['close'].pct_change().fillna(0.0)
    q_ret = qqq['close'].pct_change().fillna(0.0)
    v2_target = base_exposure(regime, t_ret)
    v23_target = (v2_target * trend_cap(qqq['close'])).clip(0, LEV_CAP)
    v2, v2_exp, v2_dd = conservative_sim(v2_target, t_ret, dates)
    trend, trend_exp, trend_dd = conservative_sim(v23_target, t_ret, dates)
    v23, v23_exp, v23_dd = conservative_sim(v23_target, t_ret, dates,
                                             [(0.20, 0.75), (0.30, 0.50), (0.40, 0.0)])
    is_mask, oos_mask = idx <= IS_END, idx > IS_END
    rows = [('QQQ buy & hold', q_ret), ('v2 current (conservative)', v2),
            ('v2.3 trend cap only', trend), ('v2.3 combined', v23)]
    print(f"Range: {idx[0].date()} to {idx[-1].date()} | Costs: {SLIPPAGE_BPS:.0f}bp turnover + {TQQQ_EXPENSE:.2%} annual ETF drag")
    report('FULL PERIOD', rows)
    report('IN-SAMPLE THROUGH 2018', [(n, r[is_mask]) for n, r in rows])
    report('OUT-OF-SAMPLE 2019+', [(n, r[oos_mask]) for n, r in rows])
    print('\nEXPOSURE / DRAWDOWN PROTECTION')
    print(f"v2 average exposure {v2_exp.mean():.2f}, cash days {(v2_exp <= .001).mean():.1%}, max DD {v2_dd.min():.1%}")
    print(f"trend-cap-only average exposure {trend_exp.mean():.2f}, max DD {trend_dd.min():.1%}")
    print(f"v2.3 average exposure {v23_exp.mean():.2f}, cash days {(v23_exp <= .001).mean():.1%}, max DD {v23_dd.min():.1%}")
    print('Drawdown throttle: 20% -> 75% cap, 30% -> 50% cap, 40% -> cash; all decisions are next-day causal.')


if __name__ == '__main__':
    main()
