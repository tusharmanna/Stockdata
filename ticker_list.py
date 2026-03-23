"""
Fetches the list of all US-listed stocks.
Sources (tried in order):
  1. GitHub: rreichel3/US-Stock-Symbols  — comprehensive all-exchange list
  2. GitHub: datasets/s-and-p-500-companies — S&P 500 fallback
"""

import requests

# ~10 000 US tickers across NYSE, NASDAQ, AMEX, OTC
PRIMARY_URL = (
    "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols"
    "/main/all/all_tickers.txt"
)

# Fallback: S&P 500 CSV
FALLBACK_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/main/data/constituents.csv"
)


def _clean(symbols: list[str]) -> list[str]:
    """Remove symbols yfinance can't handle (spaces, $, /)."""
    return [
        s.strip()
        for s in symbols
        if s.strip() and not any(c in s for c in ("$", "/", " "))
    ]


def _fetch_primary() -> list[str]:
    resp = requests.get(PRIMARY_URL, timeout=30)
    resp.raise_for_status()
    symbols = resp.text.splitlines()
    return _clean(symbols)


def _fetch_fallback() -> list[str]:
    import io, pandas as pd
    resp = requests.get(FALLBACK_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    return _clean(df["Symbol"].dropna().tolist())


def get_all_us_tickers() -> list[str]:
    """Return a deduplicated, clean list of US stock tickers."""
    try:
        print("Fetching US ticker list from GitHub (rreichel3/US-Stock-Symbols)…")
        tickers = _fetch_primary()
        print(f"  {len(tickers)} symbols loaded")
        return tickers
    except Exception as e:
        print(f"  Primary source failed ({e}), trying S&P 500 fallback…")

    try:
        tickers = _fetch_fallback()
        print(f"  {len(tickers)} S&P 500 symbols loaded (fallback)")
        return tickers
    except Exception as e:
        raise RuntimeError(f"All ticker sources failed: {e}")
