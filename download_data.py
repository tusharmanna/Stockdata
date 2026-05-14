"""
download_data.py  --  Download and cache market data (QQQ, TQQQ, SQQQ, NDX)

This script downloads current and historical data for key indices/ETFs
and saves them to CSV files in the data/ directory with timestamps.

USAGE
-----
  python download_data.py                # download all tickers
  python download_data.py --history      # force full re-download from 2015
  python download_data.py --tickers QQQ TQQQ  # specific tickers only
"""

import argparse
import os
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

# Data directory
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Tickers to download
TICKERS = ["QQQ", "TQQQ", "SQQQ", "PSQ", "^NDX"]  # ^NDX is Nasdaq-100 (NDX)
TICKER_NAMES = {
    "QQQ": "QQQ",
    "TQQQ": "TQQQ",
    "SQQQ": "SQQQ",
    "PSQ": "PSQ",
    "^NDX": "NDX"
}

DATA_START = "2015-01-01"


def get_csv_path(ticker: str) -> str:
    """Get CSV file path for a ticker."""
    name = TICKER_NAMES.get(ticker, ticker.replace("^", ""))
    return os.path.join(DATA_DIR, f"{name}_history.csv")


def load_existing_data(ticker: str) -> pd.DataFrame | None:
    """Load existing CSV data if it exists."""
    path = get_csv_path(ticker)
    if os.path.exists(path):
        try:
            df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
            return df
        except Exception as e:
            print(f"  [warn] Could not load {path}: {e}")
    return None


def download_ticker(ticker: str, force_history: bool = False) -> pd.DataFrame | None:
    """Download data for a single ticker."""
    print(f"  Downloading {ticker}...", end=" ", flush=True)

    # Load existing data
    existing = load_existing_data(ticker)

    # Determine download range
    if force_history or existing is None:
        start_date = DATA_START
        print(f"(full history from {start_date})", end=" ", flush=True)
    else:
        # Download only last 30 days to get recent data
        last_date = existing.index[-1]
        start_date = (last_date - timedelta(days=30)).strftime("%Y-%m-%d")
        print(f"(since {start_date})", end=" ", flush=True)

    try:
        # Download data
        raw = yf.download(ticker, start=start_date, auto_adjust=True, progress=False)

        if raw is None or raw.empty:
            print("[no data]")
            return existing

        # Clean up columns
        raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
        raw.index = pd.to_datetime(raw.index).tz_localize(None)
        raw.index.name = "Date"

        # Keep only OHLCV
        raw = raw[["open", "high", "low", "close", "volume"]]

        # Merge with existing if available
        if existing is not None:
            # Combine and remove duplicates, keeping newest
            combined = pd.concat([existing, raw])
            raw = combined[~combined.index.duplicated(keep="last")]
            raw = raw.sort_index()

        # Save to CSV
        path = get_csv_path(ticker)
        raw.to_csv(path)

        print(f"[OK] Saved {len(raw)} rows")
        return raw

    except Exception as e:
        print(f"[ERROR] {e}")
        return existing


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", action="store_true",
                    help="Force full re-download from 2015")
    ap.add_argument("--tickers", nargs="+", default=TICKERS,
                    help="Specific tickers to download (default: all)")
    args = ap.parse_args()

    print(f"\n{'='*70}")
    print(f"  Downloading market data  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    results = {}
    for ticker in args.tickers:
        df = download_ticker(ticker, force_history=args.history)
        if df is not None:
            results[ticker] = df

    print(f"\n{'='*70}")
    print(f"  Data saved to: {os.path.abspath(DATA_DIR)}/")
    print(f"{'='*70}\n")

    return results


if __name__ == "__main__":
    main()
