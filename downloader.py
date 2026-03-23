"""
Handles downloading OHLCV data from Yahoo Finance (via yfinance).
Data is stored in SQLite via database.py.
"""

import time
import threading
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
import pandas as pd
from typing import Sequence
import database

BATCH_SIZE = 100        # tickers per yfinance group_by batch
BATCH_PAUSE = 2         # seconds between batches to be polite to the API
MAX_WORKERS = 4         # parallel batch workers


def _today_str() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse MultiIndex columns like ('Open', 'AAPL') → 'Open'."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df


def _download_batch(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Download a batch and return {ticker: DataFrame}."""
    joined = " ".join(tickers)
    try:
        raw = yf.download(
            joined,
            start=start,
            end=end,
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"  [batch error] {e}")
        return {}

    results = {}
    if len(tickers) == 1:
        # Single ticker: yfinance returns a flat DataFrame
        t = tickers[0]
        if not raw.empty:
            results[t] = raw
    else:
        for t in tickers:
            try:
                df = raw[t].dropna(how="all")
                if not df.empty:
                    results[t] = df
            except KeyError:
                pass
    return results


def _process_batch(tickers: list[str], start: str, end: str) -> tuple[int, int]:
    """Download one batch and upsert; returns (saved, skipped) counts."""
    data = _download_batch(tickers, start, end)
    saved = skipped = 0
    for ticker in tickers:
        if ticker in data and not data[ticker].empty:
            database.upsert_prices(ticker, _flatten_columns(data[ticker]))
            saved += 1
        else:
            skipped += 1
    time.sleep(BATCH_PAUSE)
    return saved, skipped


def download_history(tickers: Sequence[str], days: int = 300):
    """First-run: download `days` days of history for all tickers."""
    end   = datetime.date.today() + datetime.timedelta(days=1)
    start = datetime.date.today() - datetime.timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str   = end.strftime("%Y-%m-%d")

    tickers = list(tickers)
    total   = len(tickers)
    num_batches = (total - 1) // BATCH_SIZE + 1
    print(f"\nDownloading {days}-day history for {total} tickers ({start_str} → {end_str})")

    lock = threading.Lock()
    saved_total = skipped_total = completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_batch, tickers[i:i + BATCH_SIZE], start_str, end_str): i
            for i in range(0, total, BATCH_SIZE)
        }
        for future in as_completed(futures):
            saved, skipped = future.result()
            with lock:
                saved_total += saved
                skipped_total += skipped
                completed += 1
                print(f"  Batch {completed}/{num_batches} done — {saved} saved, {skipped} skipped")

    print(f"\nHistory download complete: {saved_total} saved, {skipped_total} skipped (no data)")


def download_today(tickers: Sequence[str], force: bool = False):
    """Append today's bar for each ticker. Pass force=True to re-download even if already stored."""
    today     = datetime.date.today()
    start_str = today.strftime("%Y-%m-%d")
    end_str   = (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    if today.weekday() >= 5:
        print("Today is a weekend — US markets are closed. Nothing to download.")
        return

    tickers = list(tickers)
    # Skip tickers that already have today's data (unless force=True)
    pending = tickers if force else [t for t in tickers if not database.has_date(t, start_str)]
    if force:
        print(f"\nForce re-downloading today's data ({start_str}) for {len(pending)} tickers")
    print(f"\nUpdating {len(pending)} tickers with today's data ({start_str})")
    if not pending:
        print("All tickers already up to date.")
        return

    total = len(pending)
    num_batches = (total - 1) // BATCH_SIZE + 1

    lock = threading.Lock()
    saved_total = skipped_total = completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_batch, pending[i:i + BATCH_SIZE], start_str, end_str): i
            for i in range(0, total, BATCH_SIZE)
        }
        for future in as_completed(futures):
            saved, skipped = future.result()
            with lock:
                saved_total += saved
                skipped_total += skipped
                completed += 1
                print(f"  Batch {completed}/{num_batches} done — {saved} saved, {skipped} skipped")

    print(f"\nToday's update complete: {saved_total} appended, {skipped_total} skipped (no data yet / market closed)")
