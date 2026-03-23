"""
Charting: plots candlestick charts with volume and moving averages
for all tickers returned by the scanner.

Each chart shows the last LOOKBACK trading days with:
  - Candlestick OHLC bars
  - Volume bars (subplot)
  - MA10 (blue), MA20 (orange), MA50 (green), MA200 (red)
  - Entry line (current day high), Stop line (current day low)
  - Position sizing box: Entry, Stop, Risk=$100, Shares, Cost Basis

Filters applied before charting:
  - Entry price must be >= MIN_PRICE ($5)
  - Risk per share (high - low) must be >= MIN_RISK_PER_SHARE ($0.05)

All charts are saved into a single PDF: charts/YYYY-MM-DD/scan_results.pdf
Pass show=True to auto-open the PDF after saving.
"""

import os
import datetime
import sqlite3
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import database

LOOKBACK          = 60    # trading days of history to display
RISK_DOLLARS      = 100   # fixed risk per trade in $
MIN_PRICE         = 5.0   # skip tickers with entry below this price
MIN_RISK_PER_SHARE = 0.05 # skip tickers with high-low spread below this (absolute)
MIN_RANGE_PCT     = 0.005 # skip tickers where (high-low)/price < 0.5%
CHARTS_DIR = os.path.join(os.path.dirname(__file__), "charts")


def _fetch(ticker: str) -> pd.DataFrame:
    """Return the last LOOKBACK rows of OHLCV + MAs for a ticker."""
    conn = sqlite3.connect(database.DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT p.date, p.open, p.high, p.low, p.close, p.volume,
               i.ma10, i.ma20, i.ma50, i.ma200
        FROM prices p
        JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
        WHERE p.ticker = ?
        ORDER BY p.date DESC
        LIMIT ?
        """,
        conn,
        params=(ticker, LOOKBACK),
    )
    conn.close()

    if df.empty:
        return df

    df = df.sort_values("date").reset_index(drop=True)
    df.index = pd.DatetimeIndex(df["date"])
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    return df


def _position_size(entry: float, stop: float) -> dict:
    """Calculate position sizing given entry=day high, stop=day low."""
    risk_per_share = entry - stop
    shares         = int(RISK_DOLLARS / risk_per_share)
    cost_basis     = shares * entry
    return {
        "entry":      entry,
        "stop":       stop,
        "risk":       RISK_DOLLARS,
        "shares":     shares,
        "cost_basis": cost_basis,
    }


def plot_results(inside_bar_tickers: list[str], doji_tickers: list[str], show: bool = True):
    """
    Save candlestick charts for all scan results into a single PDF.
    Skips tickers below MIN_PRICE or with too-narrow a range.
    If show=True, opens the PDF with the default viewer when done.
    """
    all_tickers = (
        [(t, "Inside Bar") for t in inside_bar_tickers] +
        [(t, "Doji-NR near MA") for t in doji_tickers]
    )

    if not all_tickers:
        print("No tickers to chart.")
        return

    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    out_dir   = os.path.join(CHARTS_DIR, scan_date)
    os.makedirs(out_dir, exist_ok=True)
    pdf_path  = os.path.join(out_dir, "scan_results.pdf")

    style      = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":")
    chart_count = 0
    skipped     = []

    with PdfPages(pdf_path) as pdf:
        for ticker, scan_type in all_tickers:
            df = _fetch(ticker)
            if df.empty:
                skipped.append((ticker, "no data"))
                continue

            last           = df.iloc[-1]
            entry          = last["High"]
            stop           = last["Low"]
            risk_per_share = entry - stop

            if entry < MIN_PRICE:
                skipped.append((ticker, f"price ${entry:.2f} < ${MIN_PRICE}"))
                continue
            if risk_per_share < MIN_RISK_PER_SHARE:
                skipped.append((ticker, f"range ${risk_per_share:.3f} < ${MIN_RISK_PER_SHARE}"))
                continue
            if risk_per_share / entry < MIN_RANGE_PCT:
                skipped.append((ticker, f"range% {risk_per_share/entry*100:.2f}% < {MIN_RANGE_PCT*100:.1f}%"))
                continue

            pos = _position_size(entry, stop)

            ap = [
                mpf.make_addplot(df["ma10"],  color="#1f77b4", width=0.9, label="MA10"),
                mpf.make_addplot(df["ma20"],  color="#ff7f0e", width=0.9, label="MA20"),
                mpf.make_addplot(df["ma50"],  color="#2ca02c", width=1.2, label="MA50"),
                mpf.make_addplot(df["ma200"], color="#d62728", width=1.5, label="MA200"),
            ]

            fig, axes = mpf.plot(
                df,
                type="candle",
                style=style,
                volume=True,
                addplot=ap,
                title=f"\n[{scan_type}]  {ticker}",
                figsize=(14, 8),
                tight_layout=True,
                returnfig=True,
            )

            ax = axes[0]

            ax.legend(
                ["MA10", "MA20", "MA50", "MA200"],
                loc="upper left",
                fontsize=8,
                framealpha=0.7,
            )

            ax.axhline(pos["entry"], color="#00aa00", linewidth=1.2,
                       linestyle="--", alpha=0.85)
            ax.axhline(pos["stop"],  color="#cc0000", linewidth=1.2,
                       linestyle="--", alpha=0.85)

            info = (
                f"  Shares : {pos['shares']:,}\n"
                f"  Entry  : ${pos['entry']:.2f}\n"
                f"  Stop   : ${pos['stop']:.2f}\n"
                f"  Risk   : ${pos['risk']:.0f}\n"
                f"  Cost   : ${pos['cost_basis']:,.0f}"
            )
            ax.text(
                0.01, 0.03, info,
                transform=ax.transAxes,
                fontsize=9,
                verticalalignment="bottom",
                horizontalalignment="left",
                fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow",
                          edgecolor="gray", alpha=0.9),
            )

            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)

            print(f"  [chart] {ticker} ({scan_type})  "
                  f"entry=${pos['entry']:.2f}  stop=${pos['stop']:.2f}  "
                  f"shares={pos['shares']}  cost=${pos['cost_basis']:,.0f}")
            chart_count += 1

    if skipped:
        print(f"  Skipped {len(skipped)}: {', '.join(t for t, _ in skipped)}")

    print(f"  PDF saved ({chart_count} charts): {pdf_path}")

    if show and chart_count > 0:
        os.startfile(pdf_path)


if __name__ == "__main__":
    conn = sqlite3.connect(database.DB_PATH)
    inside_tickers = [r[0] for r in conn.execute(
        "SELECT ticker FROM scan_results ORDER BY ticker"
    ).fetchall()]
    doji_tickers = [r[0] for r in conn.execute(
        "SELECT ticker FROM doji_scan_results ORDER BY ticker"
    ).fetchall()]
    conn.close()

    print(f"Inside bar tickers : {inside_tickers or 'none'}")
    print(f"Doji/NR tickers    : {doji_tickers or 'none'}")
    print()
    plot_results(inside_tickers, doji_tickers, show=True)
