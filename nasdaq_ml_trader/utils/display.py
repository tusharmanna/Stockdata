from __future__ import annotations
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box

console = Console()

_SIGNAL_COLOR = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}


def print_signal_table(signals: list[dict]) -> None:
    table = Table(title="Signal History", box=box.SIMPLE_HEAVY)
    table.add_column("Date", style="dim")
    table.add_column("Signal", justify="center")
    table.add_column("Conf", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Models", style="dim")

    for s in signals:
        sig = s.get("signal", "HOLD")
        color = _SIGNAL_COLOR.get(sig, "white")
        table.add_row(
            s.get("date", ""),
            f"[{color}]{sig}[/{color}]",
            f"{s.get('confidence', 0):.1%}",
            f"{s.get('close', 0):.2f}",
            ", ".join(s.get("models_active", [])),
        )
    console.print(table)


def print_backtest_summary(metrics: dict, title: str = "Backtest Metrics") -> None:
    lines = [
        f"CAGR:          [green]{metrics.get('cagr', 0):.2%}[/green]",
        f"Sharpe:        {metrics.get('sharpe', 0):.2f}",
        f"Sortino:       {metrics.get('sortino', 0):.2f}",
        f"Calmar:        {metrics.get('calmar', 0):.2f}",
        f"Max Drawdown:  [red]{metrics.get('max_drawdown', 0):.2%}[/red]",
        f"Win Rate:      {metrics.get('win_rate', 0):.1%}",
        f"Profit Factor: {metrics.get('profit_factor', 0):.2f}",
        f"Avg Win:       {metrics.get('avg_win', 0):.3%}",
        f"Avg Loss:      {metrics.get('avg_loss', 0):.3%}",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold]{title}[/bold]", box=box.ROUNDED))


def print_model_weights(weights: dict) -> None:
    table = Table(title="Ensemble Weights", box=box.SIMPLE)
    table.add_column("Model")
    table.add_column("Weight", justify="right")
    for model, w in weights.items():
        table.add_row(model.upper(), f"{w:.3f}")
    console.print(table)


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total} folds"),
    )


def plot_cumulative_returns(
    strategy_equity: "pd.Series",
    benchmark_equity: "pd.Series",
    strategy_metrics: dict,
    benchmark_metrics: dict,
    title: str = "Cumulative Returns",
    save_path: Path | None = None,
) -> Path:
    """
    Three-panel chart:
      Top    — cumulative return lines, strategy vs buy-and-hold (normalised to 100)
      Middle — drawdown (strategy red fill, benchmark grey line)
      Bottom — calendar-year bar chart side by side

    Saves PNG to save_path (auto-generated if None).
    Returns the path where the file was saved.
    """
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")           # non-interactive backend — safe on Windows without display
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import matplotlib.dates as mdates
    import numpy as np

    # ── Align both series to the same date range ────────────────────────────
    # Deduplicate both series defensively before any slicing
    strategy_equity  = strategy_equity[~strategy_equity.index.duplicated(keep="last")].sort_index()
    benchmark_equity = benchmark_equity[~benchmark_equity.index.duplicated(keep="last")].sort_index()

    start = max(strategy_equity.index[0], benchmark_equity.index[0])
    end   = min(strategy_equity.index[-1], benchmark_equity.index[-1])
    strat = strategy_equity[(strategy_equity.index >= start) & (strategy_equity.index <= end)]
    bench = benchmark_equity[(benchmark_equity.index >= start) & (benchmark_equity.index <= end)]

    # Normalise both to start at 100
    strat_norm = strat / strat.iloc[0] * 100
    bench_norm = bench / bench.iloc[0] * 100

    # Drawdowns
    def _drawdown(equity: "pd.Series") -> "pd.Series":
        roll_max = equity.cummax()
        return (equity - roll_max) / roll_max * 100   # in percent

    strat_dd = _drawdown(strat_norm)
    bench_dd = _drawdown(bench_norm)

    # Annual returns (calendar year)
    def _annual_rets(equity: "pd.Series") -> "pd.Series":
        rets = equity.pct_change().dropna()
        return rets.groupby(rets.index.year).apply(lambda x: (1 + x).prod() - 1) * 100

    strat_annual = _annual_rets(strat_norm)
    bench_annual = _annual_rets(bench_norm)
    years = sorted(set(strat_annual.index) | set(bench_annual.index))

    # ── Layout ───────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 10))
    fig.patch.set_facecolor("#0e1117")
    gs  = fig.add_gridspec(3, 1, height_ratios=[3, 1.2, 1.6], hspace=0.08)

    ax_cum = fig.add_subplot(gs[0])
    ax_dd  = fig.add_subplot(gs[1], sharex=ax_cum)
    ax_bar = fig.add_subplot(gs[2])

    for ax in (ax_cum, ax_dd, ax_bar):
        ax.set_facecolor("#0e1117")
        ax.tick_params(colors="#aaaaaa", labelsize=9)
        ax.spines[:].set_color("#333333")
        ax.yaxis.label.set_color("#aaaaaa")

    # ── Top: cumulative returns ───────────────────────────────────────────────
    ax_cum.plot(strat_norm.index, strat_norm.values, color="#4c9be8",
                linewidth=1.8, label="ML Strategy", zorder=3)
    ax_cum.plot(bench_norm.index, bench_norm.values, color="#f0a500",
                linewidth=1.4, linestyle="--", label="Buy & Hold ^IXIC", zorder=2)

    ax_cum.fill_between(strat_norm.index, 100, strat_norm.values,
                        where=(strat_norm.values >= 100),
                        alpha=0.12, color="#4c9be8", zorder=1)

    ax_cum.axhline(100, color="#444444", linewidth=0.7, linestyle=":")
    ax_cum.set_ylabel("Growth of 100", fontsize=10)
    ax_cum.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    ax_cum.legend(loc="upper left", facecolor="#1a1a2e", edgecolor="#333",
                  labelcolor="white", fontsize=9)

    # Stats annotation box
    strat_tot  = strat_norm.iloc[-1] - 100
    bench_tot  = bench_norm.iloc[-1] - 100
    stats_text = (
        f"Strategy:   +{strat_tot:.1f}%  CAGR {strategy_metrics.get('cagr', 0):.1%}"
        f"  Sharpe {strategy_metrics.get('sharpe', 0):.2f}"
        f"  MaxDD {strategy_metrics.get('max_drawdown', 0):.1%}\n"
        f"Buy & Hold: +{bench_tot:.1f}%  CAGR {benchmark_metrics.get('cagr', 0):.1%}"
        f"  Sharpe {benchmark_metrics.get('sharpe', 0):.2f}"
        f"  MaxDD {benchmark_metrics.get('max_drawdown', 0):.1%}"
    )
    ax_cum.text(0.01, 0.97, stats_text, transform=ax_cum.transAxes,
                fontsize=8.5, verticalalignment="top", color="#cccccc",
                bbox=dict(facecolor="#1a1a2e", edgecolor="#333", alpha=0.9, pad=5))

    ax_cum.set_title(title, color="white", fontsize=13, pad=10)
    plt.setp(ax_cum.get_xticklabels(), visible=False)

    # ── Middle: drawdown ──────────────────────────────────────────────────────
    ax_dd.fill_between(strat_dd.index, strat_dd.values, 0,
                       alpha=0.55, color="#e84c4c", label="Strategy DD")
    ax_dd.plot(bench_dd.index, bench_dd.values, color="#f0a500",
               linewidth=0.9, linestyle="--", alpha=0.7, label="B&H DD")
    ax_dd.axhline(0, color="#444444", linewidth=0.6)
    ax_dd.set_ylabel("Drawdown %", fontsize=9)
    ax_dd.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_dd.legend(loc="lower left", facecolor="#1a1a2e", edgecolor="#333",
                 labelcolor="white", fontsize=8)
    plt.setp(ax_dd.get_xticklabels(), visible=False)

    # ── Bottom: annual bar chart ──────────────────────────────────────────────
    x    = np.arange(len(years))
    w    = 0.38
    s_vals = [strat_annual.get(yr, 0) for yr in years]
    b_vals = [bench_annual.get(yr, 0) for yr in years]

    bars_s = ax_bar.bar(x - w/2, s_vals, w, label="Strategy",
                        color=["#4c9be8" if v >= 0 else "#e84c4c" for v in s_vals],
                        alpha=0.85)
    bars_b = ax_bar.bar(x + w/2, b_vals, w, label="Buy & Hold",
                        color=["#f0a500" if v >= 0 else "#cc8800" for v in b_vals],
                        alpha=0.55)

    ax_bar.axhline(0, color="#666666", linewidth=0.7)
    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels([str(y) for y in years], fontsize=8)
    ax_bar.set_ylabel("Annual Return %", fontsize=9)
    ax_bar.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax_bar.legend(loc="upper left", facecolor="#1a1a2e", edgecolor="#333",
                  labelcolor="white", fontsize=8)

    # Value labels on bars
    for bar in list(bars_s) + list(bars_b):
        h = bar.get_height()
        if abs(h) > 1:
            ax_bar.text(
                bar.get_x() + bar.get_width() / 2,
                h + (0.5 if h >= 0 else -1.5),
                f"{h:.0f}%", ha="center", va="bottom" if h >= 0 else "top",
                fontsize=6.5, color="#cccccc",
            )

    # x-axis date formatting on top panel (visible through sharex)
    ax_cum.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_cum.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # ── Save ──────────────────────────────────────────────────────────────────
    if save_path is None:
        from config import BASE_DIR
        import datetime
        out_dir  = BASE_DIR / "backtest_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        save_path = out_dir / f"cumulative_returns_{datetime.date.today()}.png"

    fig.savefig(save_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return Path(save_path)


def print_annual_table(
    strategy_equity: "pd.Series",
    benchmark_equity: "pd.Series",
) -> None:
    """Print a year-by-year return comparison table in the terminal."""
    import pandas as pd

    def _annual(equity: "pd.Series") -> dict:
        r = equity.pct_change().dropna()
        return {yr: (1 + g).prod() - 1
                for yr, g in r.groupby(r.index.year)}

    sa = _annual(strategy_equity)
    ba = _annual(benchmark_equity)
    years = sorted(set(sa) | set(ba))

    table = Table(title="Annual Returns", box=box.SIMPLE_HEAVY)
    table.add_column("Year", style="dim")
    table.add_column("ML Strategy", justify="right")
    table.add_column("Buy & Hold", justify="right")
    table.add_column("Alpha", justify="right")

    for yr in years:
        s = sa.get(yr, 0.0)
        b = ba.get(yr, 0.0)
        a = s - b
        s_color = "green" if s >= 0 else "red"
        b_color = "green" if b >= 0 else "red"
        a_color = "green" if a >= 0 else "red"
        table.add_row(
            str(yr),
            f"[{s_color}]{s:+.1%}[/{s_color}]",
            f"[{b_color}]{b:+.1%}[/{b_color}]",
            f"[{a_color}]{a:+.1%}[/{a_color}]",
        )

    console.print(table)
