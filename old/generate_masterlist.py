"""
generate_masterlist.py — Consolidate all scanner outputs into a single masterlist.

Reads from all available scanner/watchlist files:
  - patternscan_all_tickers.txt (Higher Lows/Lower Highs/Squeeze)
  - ma_pullback_all_tickers.txt (MA pullback opportunities)
  - FilteredActionList.txt (Combined scan results from scanner.py)
  - ActionList.txt (Inside bar + Doji-NR + Red Candle + MA crosses)
  - DailyWatchlist.txt (Manual daily watchlist)
  - custom_watchlist.txt (Custom watchlist)
  - buynow.txt (Intraday breakout scanner)

Filters by MA200: Only includes stocks trading above their 200-day moving average (uptrend filter).

Output:
  - masterlist.txt (deduped, sorted alphabetically, one per line, MA200 filtered)
  - masterlist_with_sources.txt (shows which scanner(s) found each ticker)

Usage:
    python generate_masterlist.py
"""

import os
import sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import pandas as pd

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "stockdata.db"

MA_PERIOD = 200

# Define all scanner sources
SOURCES = {
    "patternscan": BASE_DIR / "patternscan_all_tickers.txt",
    "ma_pullback": BASE_DIR / "ma_pullback_all_tickers.txt",
    "filtered_action": BASE_DIR / "FilteredActionList.txt",
    "action_list": BASE_DIR / "ActionList.txt",
    "daily_watchlist": BASE_DIR / "DailyWatchlist.txt",
    "custom_watchlist": BASE_DIR / "custom_watchlist.txt",
    "buynow": BASE_DIR / "buynow.txt",
}

OUTPUT_FILE = BASE_DIR / "masterlist.txt"
OUTPUT_WITH_SOURCES = BASE_DIR / "masterlist_with_sources.txt"


def load_tickers(filepath: Path, source_name: str) -> set[str]:
    """Load tickers from a file, skipping comments and empty lines."""
    tickers = set()
    if not filepath.exists():
        print(f"  [--] {source_name:20} — file not found")
        return tickers

    try:
        with open(filepath) as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    tickers.add(t)
        print(f"  [OK] {source_name:20} — {len(tickers):4d} tickers loaded")
    except Exception as e:
        print(f"  [XX] {source_name:20} — error: {e}")

    return tickers


def filter_by_ma200(tickers):
    """Filter tickers using existing database: keep only those above MA200."""
    if not DB_PATH.exists():
        print("\nWarning: stockdata.db not found. Skipping MA200 filter.")
        print("Run 'python main.py' first to download market data.")
        return tickers, []

    above_ma200 = []
    below_ma200 = []

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")

        # Get latest date in database
        cursor = conn.execute(
            "SELECT MAX(date) FROM prices WHERE ticker IN ({})".format(
                ','.join(['?'] * len(tickers))
            ),
            tickers
        )
        latest_date = cursor.fetchone()[0]

        if not latest_date:
            print("\nWarning: No price data found in database for these tickers.")
            conn.close()
            return tickers, []

        print(f"\nFiltering {len(tickers)} tickers by MA200 (as of {latest_date})...")
        print("-" * 80)

        # Query database for latest close and MA200 for each ticker
        placeholders = ','.join(['?'] * len(tickers))
        query = f"""
        SELECT p.ticker, p.close, i.ma200
        FROM prices p
        JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
        WHERE p.ticker IN ({placeholders})
        AND p.date = ?
        ORDER BY p.ticker
        """

        cursor = conn.execute(query, tickers + [latest_date])
        results = cursor.fetchall()

        for i, (ticker, close, ma200) in enumerate(results, 1):
            print(f"[{i:3d}/{len(tickers)}] {ticker:8} ", end="", flush=True)

            if close is None or ma200 is None:
                print("SKIP (no indicators)")
                continue

            if close > ma200:
                pct_above = ((close - ma200) / ma200 * 100) if ma200 > 0 else 0
                print(f"ABOVE  (${close:.2f} vs MA200 ${ma200:.2f}, +{pct_above:.1f}%)")
                above_ma200.append(ticker)
            else:
                pct_below = ((ma200 - close) / ma200 * 100) if ma200 > 0 else 0
                print(f"BELOW  (${close:.2f} vs MA200 ${ma200:.2f}, -{pct_below:.1f}%)")
                below_ma200.append(ticker)

        conn.close()

    except Exception as e:
        print(f"\nError querying database: {e}")
        print("Returning all tickers without MA200 filter.")
        return tickers, []

    return above_ma200, below_ma200


def main():
    print("=" * 80)
    print("Consolidating scanner outputs into masterlist (with MA200 filter)...")
    print("=" * 80)
    print()

    # Load all tickers with source tracking
    ticker_sources = defaultdict(set)
    total_loaded = 0

    for source_name, filepath in SOURCES.items():
        tickers = load_tickers(filepath, source_name)
        for ticker in tickers:
            ticker_sources[ticker].add(source_name)
        total_loaded += len(tickers)

    print()
    print(f"Total records loaded: {total_loaded}")
    print(f"Unique tickers: {len(ticker_sources)}")
    print()

    # Sort tickers for MA200 filtering
    sorted_tickers = sorted(ticker_sources.keys())

    # Apply MA200 filter
    above_ma200, below_ma200 = filter_by_ma200(sorted_tickers)

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Tickers:      {len(sorted_tickers)}")
    print(f"Above MA200:        {len(above_ma200)} ({len(above_ma200)/len(sorted_tickers)*100:.1f}%)")
    print(f"Below MA200:        {len(below_ma200)} ({len(below_ma200)/len(sorted_tickers)*100:.1f}%)")
    print("=" * 80)
    print()

    # Use only tickers above MA200
    filtered_tickers = sorted(above_ma200)

    # Write simple masterlist (one ticker per line, MA200 filtered)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Masterlist — consolidated from all scanners, MA200 filtered (uptrend only)\n")
        f.write(f"# Total: {len(filtered_tickers)} ticker(s)\n")
        f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for ticker in filtered_tickers:
            f.write(f"{ticker}\n")

    print(f"[OK] Masterlist saved to: {OUTPUT_FILE.name}")
    print(f"  {len(filtered_tickers)} unique ticker(s) (above MA200)")
    print()

    # Write masterlist with sources (also MA200 filtered)
    with open(OUTPUT_WITH_SOURCES, "w", encoding="utf-8") as f:
        f.write("# Masterlist with sources — which scanner(s) found each ticker (MA200 filtered)\n")
        f.write(f"# Total: {len(filtered_tickers)} ticker(s)\n\n")
        for ticker in filtered_tickers:
            sources = sorted(ticker_sources[ticker])
            source_str = " + ".join(sources)
            f.write(f"{ticker:8}  ({source_str})\n")

    print(f"[OK] Masterlist with sources saved to: {OUTPUT_WITH_SOURCES.name}")
    print()

    # Summary by source
    print("Breakdown by scanner (before MA200 filter):")
    for source_name in sorted(SOURCES.keys()):
        count = sum(1 for sources in ticker_sources.values() if source_name in sources)
        print(f"  {source_name:20}  {count:4d} ticker(s)")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
