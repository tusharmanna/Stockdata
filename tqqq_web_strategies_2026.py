"""Backtest of the best-known TQQQ strategies from the web, judged on 2026 YTD.

Strategies (sources in docs/superpowers/specs/2026-07-06-v2-improvement-study-design.md
discussion / chat):
  1. LRS 200-SMA  — "Leverage for the Long Run" (Gayed & Bilello, 2016 Dow Award):
                    hold TQQQ while QQQ closes above its 200d SMA, else T-bills.
  2. TQQQ/SQQQ rotation — same signal, but hold SQQQ (-3x) instead of cash below SMA.
  3. RSI(2) mean-reversion — QuantifiedStrategies-style: buy TQQQ when QQQ RSI(2) < 10,
                    exit when RSI(2) > 70; cash (T-bills) otherwise.
  4. Tushar v2    — local benchmark: v1 regime gate + vol target 0.45, cap 1.5.

All signals computed on QQQ, traded causally (signal at close t -> position for t+1).
Reported for 2026 YTD and for the full period since 2011 (6 months alone is noise).
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TRADING_DAYS = 252
TBILL = 0.04                     # flat cash yield assumption for this comparison
YTD_START = pd.Timestamp("2026-01-01")
FULL_START = pd.Timestamp("2011-01-01")   # after SMA/vol warmup


def rsi(series, period=2):
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def stats(ret, label_period):
    ex = ret - TBILL / TRADING_DAYS
    eq = (1.0 + ret).cumprod()
    n_yr = len(ret) / TRADING_DAYS
    out = {
        "total": eq.iloc[-1] - 1.0,
        "cagr": eq.iloc[-1] ** (1 / n_yr) - 1 if n_yr >= 0.99 else np.nan,
        "sharpe": ex.mean() / ex.std() * np.sqrt(TRADING_DAYS) if ex.std() > 0 else np.nan,
        "max_dd": (eq / eq.cummax() - 1.0).min(),
    }
    return out


def table(title, rows, show_cagr):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    ret_hdr = "CAGR" if show_cagr else "Return"
    print(f"{'Strategy':<26}{ret_hdr:>9}{'Sharpe':>9}{'MaxDD':>9}{'Trades':>8}")
    print("-" * 80)
    for name, s, trades in rows:
        r = s["cagr"] if show_cagr else s["total"]
        print(f"{name:<26}{r:>9.1%}{s['sharpe']:>9.2f}{s['max_dd']:>9.1%}{trades:>8}")


def n_trades(pos):
    return int((pos.diff().abs() > 0).sum())


def main():
    print("Loading QQQ, TQQQ, SQQQ (live)...")
    qqq = _load(QQQ_TICKER)
    tqqq = _load(TQQQ_TICKER)
    sqqq = _load("SQQQ")

    idx = qqq.index.intersection(tqqq.index).intersection(sqqq.index)
    qqq_c = qqq.loc[idx, "close"]
    tqqq_ret = tqqq.loc[idx, "close"].pct_change().fillna(0.0)
    sqqq_ret = sqqq.loc[idx, "close"].pct_change().fillna(0.0)
    qqq_ret = qqq_c.pct_change().fillna(0.0)
    cash_ret = pd.Series(TBILL / TRADING_DAYS, index=idx)

    # --- signals (all on QQQ, all causal via shift(1)) ---
    sma200 = qqq_c.rolling(200).mean()
    above = (qqq_c > sma200).astype(float)

    r2 = rsi(qqq_c, 2)
    # state machine: enter <10, exit >70
    in_pos, states = False, []
    for v in r2.fillna(50.0):
        if not in_pos and v < 10:
            in_pos = True
        elif in_pos and v > 70:
            in_pos = False
        states.append(1.0 if in_pos else 0.0)
    rsi_pos = pd.Series(states, index=idx)

    sig = compute_signal_v1(qqq)
    regime = (sig["regime"] == "BUY_TQQQ").astype(float).reindex(idx).fillna(0.0)
    rv20 = (tqqq_ret.rolling(20).std() * np.sqrt(TRADING_DAYS)).bfill()
    v2_expo = (regime * (0.45 / rv20)).clip(0, 1.5)

    # --- daily returns per strategy ---
    def held(pos, asset_ret):
        p = pos.shift(1).fillna(0.0)
        return p * asset_ret + (1 - p).clip(lower=0) * cash_ret

    strat = {
        "TQQQ buy & hold": (tqqq_ret, 0),
        "QQQ buy & hold": (qqq_ret, 0),
        "LRS 200-SMA (Gayed)": (held(above, tqqq_ret), n_trades(above)),
        "TQQQ/SQQQ rotation": (above.shift(1).fillna(0.0) * tqqq_ret
                               + (1 - above.shift(1).fillna(0.0)) * sqqq_ret,
                               n_trades(above)),
        "RSI(2) mean-reversion": (held(rsi_pos, tqqq_ret), n_trades(rsi_pos)),
        "Tushar v2 (local)": (v2_expo.shift(1).fillna(0.0) * tqqq_ret
                              + (1 - v2_expo.shift(1).fillna(0.0)).clip(0, 1) * cash_ret,
                              n_trades((v2_expo > 0).astype(float))),
    }

    for title, start, show_cagr in [
        (f"2026 YEAR-TO-DATE  ({YTD_START.date()} .. {idx[-1].date()})", YTD_START, False),
        (f"FULL PERIOD  ({FULL_START.date()} .. {idx[-1].date()})", FULL_START, True),
    ]:
        rows = []
        for name, (r, tr) in strat.items():
            w = r[r.index >= start]
            pos_trades = tr if start == FULL_START else None
            if pos_trades is None:
                # recount trades within the window
                pos_trades = "-" if name.endswith("hold") else ""
            rows.append((name, stats(w, title), tr if start == FULL_START else ""))
        table(title, rows, show_cagr)

    print("\nNotes:")
    print("- Signals on QQQ, positions taken next day (causal). Cash earns 4%/yr flat.")
    print("- No slippage/commissions/taxes; SQQQ rotation trades would be taxed hard.")
    print("- 6 months is far too short to rank strategies; full-period row is the context.")


if __name__ == "__main__":
    main()
