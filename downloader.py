"""
Handles downloading OHLCV data from Yahoo Finance (via yfinance).
Data is stored in SQLite via database.py.
"""

import time
import datetime
import yfinance as yf
import pandas as pd
from typing import Sequence
import database

BATCH_SIZE = 100    # tickers per yfinance group_by batch
BATCH_PAUSE = 1     # seconds between batches to be polite to the API


def _today_str() -> str:
    return datetime.date.today().strftime("%Y-%m-%d")


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse MultiIndex columns to just the field name.

    yfinance returns two different layouts depending on how many tickers
    are in the batch:
      multi-ticker : (field, ticker)  e.g. ('Open', 'AAPL')  → use col[0]
      single-ticker: (ticker, field)  e.g. ('AAPL', 'Open')  → use col[1]
    """
    if isinstance(df.columns, pd.MultiIndex):
        _FIELDS = {"Open", "High", "Low", "Close", "Volume", "Adj Close"}
        if df.columns[0][0] in _FIELDS:
            df.columns = [col[0] for col in df.columns]  # (field, ticker)
        else:
            df.columns = [col[1] for col in df.columns]  # (ticker, field)
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
            threads=False,
        )
    except Exception as e:
        print(f"  [batch error] {e}")
        return {}

    if raw is None or (hasattr(raw, "empty") and raw.empty):
        return {}

    results = {}
    if len(tickers) == 1:
        t = tickers[0]
        if not raw.empty:
            results[t] = raw
    else:
        for t in tickers:
            try:
                df = raw[t].dropna(how="all")
                if not df.empty:
                    results[t] = df
            except (KeyError, TypeError):
                pass
    return results


def _process_batch(tickers: list[str], start: str, end: str) -> tuple[list[str], list[str]]:
    """Download one batch and upsert; returns (saved_tickers, skipped_tickers)."""
    data = _download_batch(tickers, start, end)
    saved = []
    skipped = []
    for ticker in tickers:
        if ticker in data and not data[ticker].empty:
            database.upsert_prices(ticker, _flatten_columns(data[ticker]))
            saved.append(ticker)
        else:
            skipped.append(ticker)
    time.sleep(BATCH_PAUSE)
    return saved, skipped


def download_history(tickers: Sequence[str], days: int = 300):
    """First-run: download `days` days of history for all tickers."""
    end   = datetime.date.today() + datetime.timedelta(days=1)
    start = datetime.date.today() - datetime.timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str   = end.strftime("%Y-%m-%d")

    tickers = list(tickers)
    total = len(tickers)
    num_batches = (total - 1) // BATCH_SIZE + 1
    print(f"\nDownloading {days}-day history for {total} tickers ({start_str} -> {end_str})")

    saved_total = skipped_total = 0
    all_skipped: list[str] = []

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        saved, skipped = _process_batch(batch, start_str, end_str)
        saved_total += len(saved)
        skipped_total += len(skipped)
        all_skipped.extend(skipped)
        completed = i // BATCH_SIZE + 1
        print(f"  Batch {completed}/{num_batches} done — {len(saved)} saved, {len(skipped)} skipped")

    if all_skipped:
        print(f"  Marking {len(all_skipped)} tickers as failed (no data in {days}-day window)")
        database.mark_failed_many(all_skipped, f"no_data_{days}d")

    print(f"\nHistory download complete: {saved_total} saved, {skipped_total} failed/delisted")


def download_today(tickers: Sequence[str], force: bool = False, date: str | None = None):
    """Append one day's bar for each ticker.

    date  — target date as 'YYYY-MM-DD'; defaults to today.
    force — re-download even if the date is already stored.
    """
    if date:
        today = datetime.date.fromisoformat(date)
    else:
        today = datetime.date.today()
    start_str = today.strftime("%Y-%m-%d")
    end_str   = (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    if today.weekday() >= 5:
        print(f"{start_str} is a weekend — US markets are closed. Nothing to download.")
        return

    tickers = list(tickers)
    pending = tickers if force else [t for t in tickers if not database.has_date(t, start_str)]
    if force:
        print(f"\nForce re-downloading today's data ({start_str}) for {len(pending)} tickers")
    print(f"\nUpdating {len(pending)} tickers with today's data ({start_str})")
    if not pending:
        print("All tickers already up to date.")
        return

    total = len(pending)
    num_batches = (total - 1) // BATCH_SIZE + 1
    saved_total = skipped_total = 0
    all_skipped: list[str] = []

    for i in range(0, total, BATCH_SIZE):
        batch = pending[i:i + BATCH_SIZE]
        saved, skipped = _process_batch(batch, start_str, end_str)
        saved_total += len(saved)
        skipped_total += len(skipped)
        all_skipped.extend(skipped)
        completed = i // BATCH_SIZE + 1
        print(f"  Batch {completed}/{num_batches} done — {len(saved)} saved, {len(skipped)} skipped")

    # Only mark as failed if they have absolutely no history in the DB.
    existing_set = set(database.get_all_tickers())
    newly_failed = [t for t in all_skipped if t not in existing_set]
    if newly_failed:
        print(f"  Marking {len(newly_failed)} tickers as failed (no data ever returned)")
        database.mark_failed_many(newly_failed, "no_data_daily")

    print(f"\nToday's update complete: {saved_total} appended, {skipped_total} skipped (no data yet / market closed)")
