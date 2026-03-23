"""
Computes moving average indicators from stored price data.
"""

import pandas as pd
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


def recompute_all():
    """Iterate all tickers in prices table, compute and save indicators."""
    tickers = database.get_all_tickers()
    total = len(tickers)
    print(f"\nRecomputing indicators for {total} tickers...")
    for i, ticker in enumerate(tickers, 1):
        prices_df = database.get_prices(ticker)
        if prices_df.empty:
            continue
        ind_df = compute_indicators(prices_df)
        database.upsert_indicators(ticker, ind_df)
        if i % 100 == 0 or i == total:
            print(f"  {i}/{total} done")
    print("Indicators recompute complete.")
