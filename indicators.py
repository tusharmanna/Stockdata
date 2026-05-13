"""
Computes moving average indicators from stored price data.
"""

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import database


def compute_indicators(prices_df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes a prices DataFrame (columns: date, open, high, low, close, volume)
    and returns an indicators DataFrame with columns:
        date, ma10, ma20, ma50, ma200, vol_avg30
    Uses min_periods=1 so partial MAs are always computed (no NaN gaps).
    """
    if prices_df is None or prices_df.empty:
        return pd.DataFrame()

    close = prices_df["close"]
    volume = prices_df["volume"]

    result = pd.DataFrame()
    result["date"] = prices_df["date"].values
    result["ma10"] = close.rolling(window=10, min_periods=1).mean().values
    result["ma20"] = close.rolling(window=20, min_periods=1).mean().values
    result["ma50"] = close.rolling(window=50, min_periods=1).mean().values
    result["ma200"] = close.rolling(window=200, min_periods=1).mean().values
    result["vol_avg30"] = volume.rolling(window=30, min_periods=1).mean().values

    return result


def _compute_rows(ticker: str, prices_df: pd.DataFrame) -> list:
    """Compute indicators for one ticker and return a list of DB row tuples."""
    ind_df = compute_indicators(prices_df)
    if ind_df.empty:
        return []
    return [
        (ticker, str(row["date"]), row.get("ma10"), row.get("ma20"),
         row.get("ma50"), row.get("ma200"), row.get("vol_avg30"))
        for _, row in ind_df.iterrows()
    ]


def recompute_all():
    """Load all prices in one query, compute indicators in parallel, write in one batch."""
    print("\nLoading all prices from DB...")
    all_prices = database.get_all_prices_bulk()
    total = len(all_prices)
    print(f"Computing indicators for {total} tickers using parallel threads...")

    all_rows = []
    completed = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_compute_rows, ticker, df): ticker
            for ticker, df in all_prices.items()
        }
        for future in as_completed(futures):
            all_rows.extend(future.result())
            completed += 1
            if completed % 500 == 0 or completed == total:
                print(f"  {completed}/{total} computed")

    print(f"  Writing {len(all_rows):,} indicator rows...")
    database.upsert_indicators_bulk(all_rows)
    print("Indicators recompute complete.")
