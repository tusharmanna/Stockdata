"""
Nasdaq ML Trading Signal System
Usage:
    python main.py fetch              — Download/update ^IXIC parquet cache
    python main.py fetch --refresh    — Force full re-download
    python main.py features           — Show feature engineering stats
    python main.py train              — Walk-forward training (RF + XGB + LSTM)
    python main.py train --skip-lstm  — RF + XGB only (~15 min on CPU)
    python main.py backtest           — Walk-forward backtest
    python main.py backtest --benchmark  — Include buy-and-hold comparison
    python main.py signal             — Generate today's signal
    python main.py signal --capital 50000
    python main.py signal --history 20  — Show last 20 signals
    python main.py status             — Show which model files exist
"""

import argparse
import sys
from pathlib import Path

# Ensure the project root is on the path so imports work from any working directory
sys.path.insert(0, str(Path(__file__).parent))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_fetch(args) -> None:
    from data.fetcher import get_ohlcv
    from utils.display import console

    with console.status("[bold green]Fetching ^IXIC data..."):
        df = get_ohlcv(force_refresh=args.refresh)

    console.print(
        f"[green]Data loaded:[/green] {len(df):,} rows "
        f"({df.index[0].date()} to {df.index[-1].date()})"
    )


def cmd_features(args) -> None:
    from data.fetcher import get_ohlcv
    from data.features import build_ml_dataset
    from utils.display import console
    from rich.table import Table
    from rich import box

    with console.status("Computing features..."):
        df     = get_ohlcv()
        X, y   = build_ml_dataset(df)

    table = Table(title="Feature Statistics", box=box.SIMPLE_HEAVY)
    table.add_column("Feature")
    table.add_column("Mean",   justify="right")
    table.add_column("Std",    justify="right")
    table.add_column("Min",    justify="right")
    table.add_column("Max",    justify="right")

    for col in X.columns:
        s = X[col]
        table.add_row(col, f"{s.mean():.4f}", f"{s.std():.4f}",
                      f"{s.min():.4f}", f"{s.max():.4f}")
    console.print(table)

    dist = y.value_counts().sort_index()
    console.print(
        f"\nSamples: {len(X):,}   Features: {X.shape[1]}\n"
        f"Labels:  HOLD(0)={dist.get(0,0):,}  "
        f"BUY(1)={dist.get(1,0):,}  "
        f"SELL(2)={dist.get(2,0):,}"
    )


def cmd_train(args) -> None:
    from data.fetcher import get_ohlcv
    from data.features import build_ml_dataset
    from models.trainer import generate_folds, train_final_models
    from models.ensemble import EnsembleModel
    from backtest.engine import run_walk_forward
    from utils.display import console, make_progress, print_model_weights

    console.print("[bold]Starting walk-forward training...[/bold]")
    if args.skip_lstm:
        console.print("[yellow]--skip-lstm: RF + XGB only[/yellow]")

    ohlcv = get_ohlcv()
    X, y  = build_ml_dataset(ohlcv)
    folds = generate_folds(X.index)

    with make_progress() as progress:
        task = progress.add_task("Walk-forward folds", total=len(folds))

        def update(n, total):
            progress.update(task, completed=n)

        results = run_walk_forward(ohlcv, skip_lstm=args.skip_lstm,
                                   progress_callback=update)

    if results["val_results"]:
        console.print("\n[bold]Optimizing ensemble weights...[/bold]")
        ensemble = EnsembleModel()
        ensemble._available = (
            ["rf", "xgb"] + ([] if args.skip_lstm else ["lstm"])
        )
        ensemble._rebalance_weights()
        opt = ensemble.optimize_weights(results["val_results"])
        print_model_weights({"rf": opt[0], "xgb": opt[1], "lstm": opt[2]})

    console.print("\n[bold]Retraining final models on full history...[/bold]")
    train_final_models(X, y)
    console.print("[green]Training complete. Models saved to saved_models/[/green]")

    from utils.display import print_backtest_summary
    print_backtest_summary(results["metrics"], "Walk-Forward Backtest Metrics")


def cmd_backtest(args) -> None:
    import pandas as pd
    from data.fetcher import get_ohlcv
    from data.features import build_ml_dataset
    from models.trainer import generate_folds
    from backtest.engine import run_walk_forward, benchmark_buyhold
    from utils.display import (print_backtest_summary, console, make_progress,
                                plot_cumulative_returns, print_annual_table)

    # Determine window start date
    years      = getattr(args, "years", None) or 5
    capital    = getattr(args, "capital", None) or 100_000.0
    start_date = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)

    console.print(
        f"[bold]Backtesting last {years} years[/bold] "
        f"(from {start_date.date()})  |  Capital: ${capital:,.0f}"
    )

    ohlcv = get_ohlcv()

    # Count only the folds that fall in the requested window for the progress bar
    X_all, _ = build_ml_dataset(ohlcv)
    all_folds = generate_folds(X_all.index)
    active_folds = [f for f in all_folds if f.test_end > start_date]

    with make_progress() as progress:
        task = progress.add_task(
            f"Walk-forward ({len(active_folds)} folds)", total=len(active_folds)
        )

        def update(n, total):
            progress.update(task, completed=n)

        results = run_walk_forward(
            ohlcv,
            skip_lstm=args.skip_lstm,
            progress_callback=update,
            start_date=start_date,
            initial_capital=capital,
        )

    if not results["folds"]:
        console.print("[red]No backtest data -- run training first: python main.py train[/red]")
        return

    # Trim equity curve to the requested window start
    equity = results["equity_curve"]
    equity = equity[equity.index >= start_date]

    # Benchmark over the same window
    bh = benchmark_buyhold(ohlcv, capital=capital, start_date=start_date)

    # ── Terminal output ───────────────────────────────────────────────────────
    print_backtest_summary(results["metrics"], f"ML Strategy -- Last {years} Years")
    console.print()
    print_backtest_summary(bh["metrics"], "Buy & Hold ^IXIC (Benchmark)")
    console.print()
    print_annual_table(equity, bh["equity"])

    # ── Chart ─────────────────────────────────────────────────────────────────
    chart_path = plot_cumulative_returns(
        strategy_equity=equity,
        benchmark_equity=bh["equity"],
        strategy_metrics=results["metrics"],
        benchmark_metrics=bh["metrics"],
        title=f"Nasdaq ML Strategy vs Buy & Hold -- Last {years} Years",
    )
    console.print(f"\n[green]Chart saved:[/green] {chart_path}")

    # Open the chart automatically on Windows
    import subprocess, os
    try:
        os.startfile(str(chart_path))
    except Exception:
        pass


def cmd_signal(args) -> None:
    from signals.generator import generate_signal, get_signal_history
    from utils.display import print_signal_table, console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    if args.history:
        signals = get_signal_history(args.history)
        if not signals:
            console.print("[yellow]No signal history found.[/yellow]")
        else:
            print_signal_table(signals)
        return

    capital = args.capital or 100_000.0

    with console.status("[bold green]Generating signal..."):
        sig = generate_signal(capital=capital)

    signal  = sig["signal"]
    color   = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(signal, "white")
    models  = sig.get("models_active", [])
    weights = sig.get("weights", {})

    # Signal panel
    panel_lines = [
        f"[{color} bold]{signal}[/{color} bold]  "
        f"Confidence: [{color}]{sig['confidence']:.1%}[/{color}]"
        + (" [dim](filtered below threshold)[/dim]" if sig.get("confidence_filtered") else ""),
        "",
        f"P(HOLD)={sig['p_hold']:.3f}   P(BUY)={sig['p_buy']:.3f}   P(SELL)={sig['p_sell']:.3f}",
        f"Models: {' | '.join(m.upper() for m in models)}",
        f"Weights: RF={weights.get('rf',0):.3f}  XGB={weights.get('xgb',0):.3f}  "
        f"LSTM={weights.get('lstm',0):.3f}",
        f"^IXIC close: {sig['close']:,.2f}  |  Date: {sig['date']}",
    ]
    console.print(Panel("\n".join(panel_lines),
                        title="[bold]NASDAQ ML Signal Engine[/bold]",
                        box=box.DOUBLE_EDGE))

    # Position sizing table
    sizing = sig.get("sizing", {})
    st = Table(title=f"Position Sizing (Capital: ${capital:,.0f})", box=box.SIMPLE_HEAVY)
    st.add_column("Method")
    st.add_column("Allocation ($)", justify="right")
    st.add_column("% Capital", justify="right")

    ff  = sizing.get("fixed_fractional", {})
    atr = sizing.get("atr_based", {})
    kel = sizing.get("kelly", {})

    if ff:
        st.add_row(
            "Fixed Fractional",
            f"${ff.get('allocation', 0):,.0f}",
            f"{ff.get('pct_of_capital', 0):.1%}",
        )
    if atr:
        shares = atr.get("shares", 0)
        st.add_row(
            f"ATR-Based ({shares} shares)",
            f"${atr.get('allocation', 0):,.0f}",
            f"{atr.get('pct_of_capital', 0):.1%}",
        )
    if kel:
        st.add_row(
            f"Kelly (f*={kel.get('kelly_f', 0):.3f}, half-Kelly)",
            f"${kel.get('allocation', 0):,.0f}",
            f"{kel.get('pct_of_capital', 0):.1%}",
        )
    console.print(st)


def cmd_status(args) -> None:
    from config import MODEL_DIR
    from utils.display import console
    from rich.table import Table
    from rich import box

    table = Table(title="Model Status", box=box.SIMPLE_HEAVY)
    table.add_column("File")
    table.add_column("Size", justify="right")
    table.add_column("Status", justify="center")

    expected = [
        "rf_final.joblib",
        "xgb_final.ubj",
        "lstm_final.pt",
        "scaler_final.joblib",
        "ensemble_weights.joblib",
    ]
    for fname in expected:
        p = MODEL_DIR / fname
        if p.exists():
            kb = p.stat().st_size / 1024
            size = f"{kb:.0f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
            table.add_row(fname, size, "[green]OK[/green]")
        else:
            table.add_row(fname, "--", "[red]MISSING[/red]")

    # Count fold-level files
    if MODEL_DIR.exists():
        fold_counts = {
            "rf folds":   len(list(MODEL_DIR.glob("rf_fold*.joblib"))),
            "xgb folds":  len(list(MODEL_DIR.glob("xgb_fold*.ubj"))),
            "lstm folds": len(list(MODEL_DIR.glob("lstm_fold*.pt"))),
        }
        console.print(table)
        console.print(
            "\nFold cache: "
            + "  ".join(f"{k}={v}" for k, v in fold_counts.items())
        )
    else:
        console.print(table)
        console.print(f"\n[yellow]Model directory does not exist: {MODEL_DIR}[/yellow]")
        console.print("Run: [bold]python main.py train[/bold]")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="nasdaq_ml_trader",
        description="Nasdaq ML Trading Signal System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="Download/update ^IXIC data")
    p_fetch.add_argument("--refresh", action="store_true",
                         help="Force full re-download (ignore cache)")

    sub.add_parser("features", help="Display feature engineering statistics")

    p_train = sub.add_parser("train", help="Run walk-forward training")
    p_train.add_argument("--skip-lstm", action="store_true",
                         help="Skip LSTM (RF+XGB only; ~15 min on CPU)")

    p_bt = sub.add_parser("backtest", help="Run walk-forward backtest")
    p_bt.add_argument("--skip-lstm", action="store_true")
    p_bt.add_argument("--years", type=int, default=5,
                      help="Number of years to backtest (default: 5)")
    p_bt.add_argument("--capital", type=float, default=100_000.0,
                      help="Starting capital in USD (default: 100,000)")
    p_bt.add_argument("--benchmark", action="store_true",
                      help="Include buy-and-hold ^IXIC benchmark (always shown)")

    p_sig = sub.add_parser("signal", help="Generate today's trading signal")
    p_sig.add_argument("--capital", type=float, default=None,
                       help="Portfolio capital in USD (default: 100,000)")
    p_sig.add_argument("--history", type=int, default=0, metavar="N",
                       help="Show last N signals from log instead of generating new")

    sub.add_parser("status", help="Show which model files exist")

    args = ap.parse_args()
    dispatch = {
        "fetch":    cmd_fetch,
        "features": cmd_features,
        "train":    cmd_train,
        "backtest": cmd_backtest,
        "signal":   cmd_signal,
        "status":   cmd_status,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
