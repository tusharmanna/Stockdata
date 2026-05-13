"""
US Stock Data Downloader
========================
First run  → downloads 750 days of OHLCV history for every US-listed stock.
Later runs → appends only today's bar and recomputes indicators.

Usage:
    python main.py            # auto-detect first run vs daily update
    python main.py --history  # force a fresh 750-day history download
    python main.py --today    # force re-download of today's data (overrides dedup)
"""

import sys
import database
import indicators
from ticker_list import get_all_us_tickers
from downloader import download_history, download_today


def is_first_run() -> bool:
    """True when the prices table has no data yet."""
    return len(database.get_all_tickers()) == 0


def _get_arg(flag: str) -> str | None:
    """Return the value after `flag` in sys.argv, or None."""
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main():
    force_history = "--history" in sys.argv
    force_today   = "--today"   in sys.argv
    target_date   = _get_arg("--date")   # e.g. --date 2026-04-17

    print("=== US Stock Data Downloader ===")
    database.init_db()
    tickers = get_all_us_tickers()

    failed = database.get_failed_tickers()
    if failed:
        before = len(tickers)
        tickers = [t for t in tickers if t not in failed]
        print(f"Skipping {before - len(tickers)} known failed/delisted tickers ({len(tickers)} remaining)")

    if force_history or is_first_run():
        if force_history:
            print("\n--history flag set — re-downloading 750-day history.")
        else:
            print("\nFirst run detected — downloading 750-day history.")
        download_history(tickers, days=750)
    elif target_date:
        print(f"\n--date flag set — downloading data for {target_date}.")
        download_today(tickers, force=True, date=target_date)
    elif force_today:
        print("\n--today flag set — force re-downloading today's data.")
        download_today(tickers, force=True)
    else:
        existing = len(database.get_all_tickers())
        print(f"\nDatabase has {existing} tickers — running daily update.")
        download_today(tickers)

    indicators.recompute_all()
    print("\nDone.")


if __name__ == "__main__":
    main()
