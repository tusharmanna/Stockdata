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

Output:
  - masterlist.txt (deduped, sorted alphabetically, one per line)
  - masterlist_with_sources.txt (shows which scanner(s) found each ticker)

Usage:
    python generate_masterlist.py
"""

import os
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).parent

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


def main():
    print("=" * 60)
    print("Consolidating scanner outputs into masterlist...")
    print("=" * 60)
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

    # Sort tickers
    sorted_tickers = sorted(ticker_sources.keys())

    # Write simple masterlist (one ticker per line)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# Masterlist — consolidated from all scanners\n")
        f.write(f"# Total: {len(sorted_tickers)} ticker(s)\n")
        f.write(f"# Generated: {Path.cwd().name}\n\n")
        for ticker in sorted_tickers:
            f.write(f"{ticker}\n")

    print(f"[OK] Masterlist saved to: {OUTPUT_FILE.name}")
    print(f"  {len(sorted_tickers)} unique ticker(s)")
    print()

    # Write masterlist with sources
    with open(OUTPUT_WITH_SOURCES, "w", encoding="utf-8") as f:
        f.write("# Masterlist with sources — which scanner(s) found each ticker\n")
        f.write(f"# Total: {len(sorted_tickers)} ticker(s)\n\n")
        for ticker in sorted_tickers:
            sources = sorted(ticker_sources[ticker])
            source_str = " + ".join(sources)
            f.write(f"{ticker:8}  ({source_str})\n")

    print(f"[OK] Masterlist with sources saved to: {OUTPUT_WITH_SOURCES.name}")
    print()

    # Summary by source
    print("Breakdown by scanner:")
    for source_name in sorted(SOURCES.keys()):
        count = sum(1 for sources in ticker_sources.values() if source_name in sources)
        print(f"  {source_name:20}  {count:4d} ticker(s)")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
