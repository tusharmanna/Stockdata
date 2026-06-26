"""Tushar v2 — visual chart: yearly gains, drawdown, and rolling volatility.

Reuses all computation from tushar_v2_backtest.py.  Run:
    python tushar_v2_chart.py
Saves PDF to charts/tushar_v2_analysis.pdf and opens it.
"""

import os
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER
from tushar_v2_backtest import (
    vol_target_exposure, strat_returns, annual_returns,
    TARGET_VOL, LEV_CAP, VOL_WINDOW, TRADING_DAYS,
)

# ── Palette ────────────────────────────────────────────────────────────────────
C_QQQ  = "#7f8c8d"
C_V1   = "#e67e22"
C_V2   = "#2980b9"
C_TQQQ = "#c0392b"
C_NEG  = "#e74c3c"
C_POS  = "#27ae60"

OUT_DIR  = "charts"
OUT_FILE = os.path.join(OUT_DIR, "tushar_v2_analysis.pdf")


def _drawdown(ret: pd.Series) -> pd.Series:
    eq = (1.0 + ret).cumprod()
    return eq / eq.cummax() - 1.0


def _rolling_ann_vol(ret: pd.Series, window: int = 63) -> pd.Series:
    return ret.rolling(window).std() * np.sqrt(TRADING_DAYS)


def main():
    print("Loading QQQ and TQQQ (live)...")
    qqq_df  = _load(QQQ_TICKER)
    tqqq_df = _load(TQQQ_TICKER)

    sig        = compute_signal_v1(qqq_df)
    regime_pos = (sig["regime"] == "BUY_TQQQ").astype(float)

    idx        = qqq_df.index.intersection(tqqq_df.index)
    regime_pos = regime_pos.loc[idx]
    tqqq_ret   = tqqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    qqq_ret    = qqq_df.loc[idx, "close"].pct_change().fillna(0.0)
    dates      = pd.Series(idx, index=idx)

    exposure  = vol_target_exposure(regime_pos, tqqq_ret)
    v1        = strat_returns(regime_pos, tqqq_ret, dates)
    v2c       = strat_returns(exposure, tqqq_ret, dates, costs=True)

    # ── Annual returns ─────────────────────────────────────────────────────────
    ann = {
        "QQQ B&H": annual_returns(dates, qqq_ret),
        "v1":      annual_returns(dates, v1),
        "v2":      annual_returns(dates, v2c),
    }
    years = ann["v1"].index.tolist()
    n     = len(years)
    x     = np.arange(n)
    w     = 0.26

    # ── Drawdown series ────────────────────────────────────────────────────────
    dd_v1  = _drawdown(v1)
    dd_v2  = _drawdown(v2c)
    dd_qqq = _drawdown(qqq_ret)

    # ── Rolling volatility (63-day / quarterly) ────────────────────────────────
    vol_tqqq = _rolling_ann_vol(tqqq_ret)
    vol_v1   = _rolling_ann_vol(v1)
    vol_v2   = _rolling_ann_vol(v2c)

    # ── Figure ─────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 14))
    fig.patch.set_facecolor("#0f1117")

    gs = GridSpec(3, 1, figure=fig, hspace=0.42,
                  top=0.92, bottom=0.06, left=0.07, right=0.97)

    axes = [fig.add_subplot(gs[i]) for i in range(3)]
    for ax in axes:
        ax.set_facecolor("#1a1d27")
        ax.tick_params(colors="#aaaaaa", labelsize=9)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333344")
        ax.grid(axis="y", color="#2a2d3a", linewidth=0.6, linestyle="--")
        ax.grid(axis="x", visible=False)

    # ─── Panel 1 — Yearly Returns ─────────────────────────────────────────────
    ax1 = axes[0]
    bars_qqq = ann["QQQ B&H"].values
    bars_v1  = ann["v1"].values
    bars_v2  = ann["v2"].values

    def bar_colors(vals):
        return [C_POS if v >= 0 else C_NEG for v in vals]

    ax1.bar(x - w, bars_qqq, width=w, color=bar_colors(bars_qqq),
            alpha=0.55, label="QQQ B&H")
    ax1.bar(x,     bars_v1,  width=w, color=C_V1, alpha=0.80, label="v1 baseline")
    ax1.bar(x + w, bars_v2,  width=w, color=C_V2, alpha=0.90, label="v2 after-cost")

    ax1.axhline(0, color="#555566", linewidth=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(y) for y in years], fontsize=8, color="#aaaaaa")
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))
    ax1.set_title("Yearly Returns — QQQ B&H vs v1 vs v2 (after cost)",
                  color="#e0e0e0", fontsize=11, pad=8)
    ax1.legend(loc="upper left", framealpha=0.2, fontsize=8,
               labelcolor="#cccccc", facecolor="#222233")

    # annotate v2 bars with value
    for xi, val in zip(x + w, bars_v2):
        va = "bottom" if val >= 0 else "top"
        offset = 0.004 if val >= 0 else -0.004
        ax1.text(xi, val + offset, f"{val:.0%}", ha="center", va=va,
                 fontsize=6.5, color="#aaccff")

    # ─── Panel 2 — Drawdown ───────────────────────────────────────────────────
    ax2 = axes[1]
    ax2.fill_between(idx, dd_v2 * 100, 0,   alpha=0.55, color=C_V2,   label="v2 after-cost")
    ax2.fill_between(idx, dd_v1 * 100, 0,   alpha=0.35, color=C_V1,   label="v1 baseline")
    ax2.fill_between(idx, dd_qqq * 100, 0,  alpha=0.20, color=C_QQQ,  label="QQQ B&H")
    ax2.set_xlim(idx[0], idx[-1])
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax2.set_title("Drawdown from Peak", color="#e0e0e0", fontsize=11, pad=8)
    ax2.legend(loc="lower left", framealpha=0.2, fontsize=8,
               labelcolor="#cccccc", facecolor="#222233")

    # label worst drawdowns
    for dd_s, col, label in [(dd_v2, C_V2, "v2"), (dd_v1, C_V1, "v1")]:
        worst_idx = dd_s.idxmin()
        worst_val = dd_s.min() * 100
        ax2.annotate(f"{label} worst\n{worst_val:.1f}%",
                     xy=(worst_idx, worst_val),
                     xytext=(20, 14), textcoords="offset points",
                     color=col, fontsize=7.5,
                     arrowprops=dict(arrowstyle="->", color=col, lw=0.9))

    # ─── Panel 3 — Rolling Volatility ─────────────────────────────────────────
    ax3 = axes[2]
    ax3.plot(idx, vol_tqqq * 100, color=C_TQQQ, linewidth=0.9,
             alpha=0.75, label="TQQQ realized vol (63d)")
    ax3.plot(idx, vol_v1 * 100,   color=C_V1,   linewidth=1.0,
             alpha=0.85, label="v1 equity vol (63d)")
    ax3.plot(idx, vol_v2 * 100,   color=C_V2,   linewidth=1.1,
             label="v2 equity vol (63d)")
    ax3.axhline(TARGET_VOL * 100, color="#aaaaff", linewidth=0.8, linestyle="--",
                label=f"Target vol {TARGET_VOL:.0%}")
    ax3.set_xlim(idx[0], idx[-1])
    ax3.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax3.set_title("Rolling 63-Day Annualised Volatility", color="#e0e0e0",
                  fontsize=11, pad=8)
    ax3.legend(loc="upper right", framealpha=0.2, fontsize=8,
               labelcolor="#cccccc", facecolor="#222233")

    # ── Title ──────────────────────────────────────────────────────────────────
    date_range = f"{idx[0].strftime('%b %Y')} – {idx[-1].strftime('%b %Y')}"
    fig.suptitle(f"Tushar v2 Strategy Analysis  ·  {date_range}",
                 color="#ffffff", fontsize=13, fontweight="bold")

    # ── Save ───────────────────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(OUT_FILE, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved: {OUT_FILE}")
    plt.show()


if __name__ == "__main__":
    main()
