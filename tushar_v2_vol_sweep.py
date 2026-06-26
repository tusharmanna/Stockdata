"""Tushar v2 — volatility sweep analysis.

Tests every target_vol from 0.15 to 1.50 and reports CAGR, Max Drawdown,
Sharpe, and a blended score. Produces a 4-panel chart and prints a ranked table.

    python tushar_v2_vol_sweep.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.cm as cm
from matplotlib.gridspec import GridSpec

from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER
from tushar_v2_backtest import strat_returns, annual_returns, TRADING_DAYS
from tushar_v2_backtest import RATE_SPLIT_YEARS, TBILL_EARLY, TBILL_LATE  # for reference

VOL_WINDOW  = 20
LEV_CAP     = 1.5
CURRENT_VOL = 0.45   # currently configured setting

OUT_DIR  = "charts"
OUT_FILE = os.path.join(OUT_DIR, "tushar_v2_vol_sweep.pdf")


def vol_exposure(regime_pos, tqqq_ret, target_vol, cap=LEV_CAP):
    rv = (tqqq_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)).bfill()
    lev = (target_vol / rv).clip(0, cap)
    return (regime_pos * lev).clip(0, cap)


def compute_metrics(ret, capital=100_000):
    eq     = (1.0 + ret).cumprod()
    n_yr   = len(ret) / TRADING_DAYS
    cagr   = eq.iloc[-1] ** (1 / n_yr) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(TRADING_DAYS) if ret.std() > 0 else np.nan
    max_dd = (eq / eq.cummax() - 1.0).min()
    final  = eq.iloc[-1] * capital
    return dict(cagr=cagr, sharpe=sharpe, max_dd=max_dd, final=final)


def yearly(dates, ret):
    df = pd.DataFrame({"date": dates.values, "ret": ret.values}).set_index("date")
    df["year"] = pd.DatetimeIndex(df.index).year
    return df.groupby("year")["ret"].apply(lambda x: (1.0 + x).prod() - 1.0)


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

    # ── Sweep ─────────────────────────────────────────────────────────────────
    vols = np.round(np.arange(0.15, 1.55, 0.05), 3)
    rows = []
    for tv in vols:
        exp = vol_exposure(regime_pos, tqqq_ret, tv)
        ret = strat_returns(exp, tqqq_ret, dates, costs=True)
        m   = compute_metrics(ret)
        m["target_vol"] = tv
        # blended score: Sharpe × CAGR / abs(MaxDD)  — rewards high return+Sharpe, penalises DD
        m["score"] = m["sharpe"] * m["cagr"] / abs(m["max_dd"])
        rows.append(m)

    df = pd.DataFrame(rows).set_index("target_vol")

    # ── Benchmarks ────────────────────────────────────────────────────────────
    tqqq_m = compute_metrics(tqqq_ret)
    qqq_m  = compute_metrics(qqq_ret)

    # ── Find optima ───────────────────────────────────────────────────────────
    best_cagr   = df["cagr"].idxmax()
    best_sharpe = df["sharpe"].idxmax()
    best_score  = df["score"].idxmax()
    least_dd    = df["max_dd"].idxmax()   # closest to 0

    # ── Print table ───────────────────────────────────────────────────────────
    print(f"\n{'TargVol':>8}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Final $':>14}{'Score':>9}")
    print("-" * 60)
    for tv, row in df.iterrows():
        flag = ""
        if tv == best_score:    flag += " <-- BEST OVERALL"
        elif tv == best_cagr:   flag += " <-- BEST CAGR"
        elif tv == best_sharpe: flag += " <-- BEST SHARPE"
        elif tv == least_dd:    flag += " <-- LEAST DRAWDOWN"
        elif tv == CURRENT_VOL: flag += " <-- CURRENT"
        print(f"{tv:>7.2f}  {row['cagr']:>8.1%}  {row['sharpe']:>7.2f}  "
              f"{row['max_dd']:>8.1%}  {row['final']:>13,.0f}  {row['score']:>8.3f}{flag}")
    print("-" * 60)
    print(f"{'TQQQ B&H':>8}  {tqqq_m['cagr']:>8.1%}  {tqqq_m['sharpe']:>7.2f}  "
          f"{tqqq_m['max_dd']:>8.1%}  {tqqq_m['final']:>13,.0f}")
    print(f"{'QQQ B&H':>8}  {qqq_m['cagr']:>8.1%}  {qqq_m['sharpe']:>7.2f}  "
          f"{qqq_m['max_dd']:>8.1%}  {qqq_m['final']:>13,.0f}")

    print(f"\nBest CAGR:          target_vol = {best_cagr:.2f}  "
          f"({df.loc[best_cagr,'cagr']:.1%} CAGR, {df.loc[best_cagr,'max_dd']:.1%} MaxDD)")
    print(f"Best Sharpe:        target_vol = {best_sharpe:.2f}  "
          f"({df.loc[best_sharpe,'sharpe']:.2f} Sharpe)")
    print(f"Least Drawdown:     target_vol = {least_dd:.2f}  "
          f"({df.loc[least_dd,'max_dd']:.1%} MaxDD)")
    print(f"Best Overall Score: target_vol = {best_score:.2f}  "
          f"({df.loc[best_score,'cagr']:.1%} CAGR, {df.loc[best_score,'sharpe']:.2f} Sharpe, "
          f"{df.loc[best_score,'max_dd']:.1%} MaxDD)")

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(16, 14))
    fig.patch.set_facecolor("#0f1117")
    gs  = GridSpec(2, 2, figure=fig, hspace=0.40, wspace=0.32,
                   top=0.91, bottom=0.07, left=0.08, right=0.97)

    ax_cagr   = fig.add_subplot(gs[0, 0])
    ax_dd     = fig.add_subplot(gs[0, 1])
    ax_sharpe = fig.add_subplot(gs[1, 0])
    ax_front  = fig.add_subplot(gs[1, 1])

    axes = [ax_cagr, ax_dd, ax_sharpe, ax_front]
    for ax in axes:
        ax.set_facecolor("#1a1d27")
        ax.tick_params(colors="#aaaaaa", labelsize=9)
        for spine in ax.spines.values():
            spine.set_edgecolor("#333344")
        ax.grid(color="#2a2d3a", linewidth=0.6, linestyle="--")

    tv_vals = df.index.values

    def vline(ax, tv, color, label):
        ax.axvline(tv, color=color, linewidth=1.0, linestyle=":", alpha=0.85, label=label)

    # ── Panel 1: CAGR vs target_vol ──────────────────────────────────────────
    ax_cagr.plot(tv_vals, df["cagr"] * 100, color="#2980b9", linewidth=2)
    ax_cagr.fill_between(tv_vals, df["cagr"] * 100, alpha=0.15, color="#2980b9")
    vline(ax_cagr, CURRENT_VOL, "#aaaaff", f"Current ({CURRENT_VOL:.2f})")
    vline(ax_cagr, best_cagr,   "#27ae60", f"Best CAGR ({best_cagr:.2f})")
    vline(ax_cagr, best_score,  "#f39c12", f"Best Overall ({best_score:.2f})")
    ax_cagr.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_cagr.set_xlabel("Target Volatility", color="#aaaaaa", fontsize=9)
    ax_cagr.set_title("CAGR (after cost)", color="#e0e0e0", fontsize=11)
    ax_cagr.legend(fontsize=7.5, framealpha=0.2, labelcolor="#cccccc",
                   facecolor="#222233")

    # ── Panel 2: Max Drawdown vs target_vol ──────────────────────────────────
    ax_dd.plot(tv_vals, df["max_dd"] * 100, color="#e74c3c", linewidth=2)
    ax_dd.fill_between(tv_vals, df["max_dd"] * 100, alpha=0.15, color="#e74c3c")
    vline(ax_dd, CURRENT_VOL, "#aaaaff", f"Current ({CURRENT_VOL:.2f})")
    vline(ax_dd, least_dd,    "#27ae60", f"Least DD ({least_dd:.2f})")
    vline(ax_dd, best_score,  "#f39c12", f"Best Overall ({best_score:.2f})")
    ax_dd.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_dd.set_xlabel("Target Volatility", color="#aaaaaa", fontsize=9)
    ax_dd.set_title("Max Drawdown (after cost)", color="#e0e0e0", fontsize=11)
    ax_dd.legend(fontsize=7.5, framealpha=0.2, labelcolor="#cccccc",
                 facecolor="#222233")

    # ── Panel 3: Sharpe vs target_vol ────────────────────────────────────────
    ax_sharpe.plot(tv_vals, df["sharpe"], color="#9b59b6", linewidth=2)
    ax_sharpe.fill_between(tv_vals, df["sharpe"], alpha=0.15, color="#9b59b6")
    vline(ax_sharpe, CURRENT_VOL, "#aaaaff", f"Current ({CURRENT_VOL:.2f})")
    vline(ax_sharpe, best_sharpe, "#27ae60", f"Best Sharpe ({best_sharpe:.2f})")
    vline(ax_sharpe, best_score,  "#f39c12", f"Best Overall ({best_score:.2f})")
    ax_sharpe.set_xlabel("Target Volatility", color="#aaaaaa", fontsize=9)
    ax_sharpe.set_title("Sharpe Ratio (after cost)", color="#e0e0e0", fontsize=11)
    ax_sharpe.legend(fontsize=7.5, framealpha=0.2, labelcolor="#cccccc",
                     facecolor="#222233")

    # ── Panel 4: Efficient Frontier scatter (MaxDD vs CAGR) ──────────────────
    norm   = plt.Normalize(tv_vals.min(), tv_vals.max())
    colors = cm.plasma(norm(tv_vals))
    sc = ax_front.scatter(df["max_dd"] * 100, df["cagr"] * 100,
                          c=tv_vals, cmap="plasma", s=55, zorder=3)

    # annotate a few key points
    for tv, label, color in [
        (CURRENT_VOL, f"Current\n({CURRENT_VOL:.2f})", "#aaaaff"),
        (best_score,  f"Best Overall\n({best_score:.2f})",  "#f39c12"),
        (best_cagr,   f"Best CAGR\n({best_cagr:.2f})",     "#27ae60"),
        (least_dd,    f"Least DD\n({least_dd:.2f})",        "#e74c3c"),
    ]:
        if tv not in df.index:
            continue
        px = df.loc[tv, "max_dd"] * 100
        py = df.loc[tv, "cagr"]   * 100
        ax_front.annotate(label, xy=(px, py),
                          xytext=(12, 8), textcoords="offset points",
                          color=color, fontsize=7.5,
                          arrowprops=dict(arrowstyle="->", color=color, lw=0.8))
        ax_front.scatter([px], [py], s=90, color=color, zorder=4)

    # benchmarks
    ax_front.scatter([tqqq_m["max_dd"] * 100], [tqqq_m["cagr"] * 100],
                     marker="^", s=90, color="#c0392b", zorder=4)
    ax_front.annotate("TQQQ B&H", xy=(tqqq_m["max_dd"]*100, tqqq_m["cagr"]*100),
                      xytext=(-50, -14), textcoords="offset points",
                      color="#c0392b", fontsize=7.5,
                      arrowprops=dict(arrowstyle="->", color="#c0392b", lw=0.8))

    cbar = fig.colorbar(sc, ax=ax_front, pad=0.02)
    cbar.set_label("Target Volatility", color="#aaaaaa", fontsize=8)
    cbar.ax.yaxis.set_tick_params(color="#aaaaaa", labelsize=8)
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="#aaaaaa")

    ax_front.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_front.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_front.set_xlabel("Max Drawdown", color="#aaaaaa", fontsize=9)
    ax_front.set_ylabel("CAGR", color="#aaaaaa", fontsize=9)
    ax_front.set_title("Efficient Frontier: CAGR vs Drawdown", color="#e0e0e0", fontsize=11)

    date_range = f"{idx[0].strftime('%b %Y')} - {idx[-1].strftime('%b %Y')}"
    fig.suptitle(f"Target Volatility Sweep  |  v2 after cost  |  {date_range}",
                 color="#ffffff", fontsize=13, fontweight="bold")

    os.makedirs(OUT_DIR, exist_ok=True)
    fig.savefig(OUT_FILE, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"\nSaved: {OUT_FILE}")
    plt.show()


if __name__ == "__main__":
    main()
