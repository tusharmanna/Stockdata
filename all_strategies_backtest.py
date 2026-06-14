"""Consolidated backtest of every strategy discussed, on one common date range.

Prints year-by-year annual returns and a summary table (total, CAGR, Sharpe,
maxDD, final $ from $100k) so all numbers are consistent and reproducible.

Bases (important for fair reading):
- v1 / v2: traded on REAL TQQQ (its fees/decay are in the price). After-cost =
  margin financing on exposure>1 + T-bill yield on idle cash.
- Binary / Pyramid: 3x DAILY-REBALANCED QQQ (idealized; slightly optimistic vs
  a real 3x ETF). No financing modeled -- these are the committed-script numbers.
- QLD overlay: REAL QLD (2x), cap 1.0 (no margin), + cash yield.
- QQQ gated: REAL QQQ (1x), + cash yield.
"""

import numpy as np
import pandas as pd

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TD = 252


def regime_pos(qqq):
    sig = compute_signal_v1(qqq)
    return (sig["regime"] == "BUY_TQQQ").astype(float)


def main():
    qqq = _load(QQQ_TICKER)
    tq = _load(TQQQ_TICKER)
    qld = _load("QLD")
    idx = qqq.index.intersection(tq.index).intersection(qld.index)

    c = qqq.loc[idx, "close"]
    qret = c.pct_change().fillna(0)
    tret = tq.loc[idx, "close"].pct_change().fillna(0)
    lret = qld.loc[idx, "close"].pct_change().fillna(0)
    reg = regime_pos(qqq).loc[idx]

    yrs = (pd.Series(idx, index=idx) - idx[0]).dt.days.values / 365.25
    tb = np.where(yrs > 12, 0.05, 0.015)
    mg = np.where(yrs > 12, 0.06, 0.025)

    def lever_cost(e, base):
        e = e.shift(1).fillna(0)
        return (e * base - (e - 1).clip(lower=0) * mg / TD
                + (1 - e).clip(lower=0, upper=1) * tb / TD)

    # --- moving averages for crossover strategies ---
    ma4, ma25 = c.rolling(4).mean(), c.rolling(25).mean()
    ma3, ma35 = c.rolling(3).mean(), c.rolling(35).mean()
    binary = pd.Series(np.where(ma4 > ma25, 1.0, 0.0), index=idx)
    pyr_eq = ((c > ma3).astype(float) + (c > ma25).astype(float) + (ma4 > ma25).astype(float)) / 3.0
    # equal-thirds uses 3/35 per the live tool
    pyr_eq = ((c > ma3).astype(float) + (c > ma35).astype(float) + (ma3 > ma35).astype(float)) / 3.0
    pyr_w = 0.25 * (c > ma3) + 0.35 * (c > ma35) + 0.40 * (ma3 > ma35)
    for s in (binary, pyr_eq, pyr_w):
        s[ma35.isna()] = 0.0

    rv_t = (tret.rolling(20).std() * np.sqrt(TD)).bfill()
    rv_l = (lret.rolling(20).std() * np.sqrt(TD)).bfill()

    strategies = {
        "QQQ B&H (1x)": qret,
        "TQQQ B&H (3x)": tret,
        "QQQ Gated (1x)": lever_cost(reg.clip(0, 1.0), qret),
        "QLD Overlay (2x)": lever_cost((reg * (0.45 / rv_l).clip(0, 1.0)).clip(0, 1.0), lret),
        "Binary 4/25 (3x)": (binary * 3).shift(1).fillna(0) * qret,
        "Pyramid 33/33/33 (3x)": (pyr_eq * 3).shift(1).fillna(0) * qret,
        "Pyramid 25/35/40 (3x)": (pyr_w * 3).shift(1).fillna(0) * qret,
        "v1 (3x TQQQ)": lever_cost(reg.clip(0, 1.0), tret),
        "v2 defensive (3x)": lever_cost((reg * (0.45 / rv_t).clip(0, 1.5)).clip(0, 1.5), tret),
        "v2 aggressive (3x)": lever_cost((reg * (0.75 / rv_t).clip(0, 1.5)).clip(0, 1.5), tret),
    }

    def annual(r):
        d = pd.DataFrame({"r": np.asarray(r)}, index=idx); d["y"] = d.index.year
        return d.groupby("y")["r"].apply(lambda x: (1 + x).prod() - 1)

    def summary(r):
        r = pd.Series(np.asarray(r), index=idx); eq = (1 + r).cumprod(); n = len(r) / TD
        return (eq.iloc[-1] - 1, eq.iloc[-1] ** (1 / n) - 1,
                r.mean() / r.std() * np.sqrt(TD), (eq / eq.cummax() - 1).min(),
                eq.iloc[-1] * 100000)

    ann = {k: annual(v) for k, v in strategies.items()}
    years = ann["QQQ B&H (1x)"].index

    print(f"COMMON RANGE: {idx[0].date()} .. {idx[-1].date()}\n")
    print("ANNUAL RETURNS (%)")
    hdr = "Year " + "".join(f"{k.split(' (')[0][:13]:>15}" for k in strategies)
    print(hdr)
    for y in years:
        print(f"{y:<5}" + "".join(f"{ann[k][y]*100:>14.1f}" for k in strategies))

    print("\nSUMMARY ($100k start)")
    print(f"{'Strategy':<24}{'Total%':>10}{'CAGR%':>8}{'Sharpe':>8}{'MaxDD%':>9}{'Final$':>16}")
    for k, v in strategies.items():
        t, cg, s, d, w = summary(v)
        print(f"{k:<24}{t*100:>9.0f}{cg*100:>8.1f}{s:>8.2f}{d*100:>9.1f}{w:>16,.0f}")


if __name__ == "__main__":
    main()
