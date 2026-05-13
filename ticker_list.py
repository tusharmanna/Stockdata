"""
Fetches the list of all US-listed stocks.
Sources (tried in order):
  1. NASDAQ Screener API  — ~7 000 NYSE/NASDAQ/AMEX tickers with metadata
  2. GitHub: rreichel3/US-Stock-Symbols  — comprehensive all-exchange fallback
  3. GitHub: datasets/s-and-p-500-companies — S&P 500 last-resort fallback
"""

import requests

NASDAQ_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=10000&download=true"
)

GITHUB_ALL_URL = (
    "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols"
    "/main/all/all_tickers.txt"
)

FALLBACK_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies"
    "/main/data/constituents.csv"
)

# Always included regardless of what the API returns
PINNED_TICKERS = ["PSQ", "QQQ", "SQQQ", "TQQQ"]

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _clean(symbols: list[str]) -> list[str]:
    """Remove symbols yfinance can't handle (spaces, $, /)."""
    return [
        s.strip()
        for s in symbols
        if s.strip() and not any(c in s for c in ("$", "/", " "))
    ]


def _fetch_nasdaq() -> list[str]:
    resp = requests.get(NASDAQ_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    rows = resp.json()["data"]["rows"]
    symbols = [r["symbol"] for r in rows if r.get("symbol")]
    return _clean(symbols)


def _fetch_github_all() -> list[str]:
    resp = requests.get(GITHUB_ALL_URL, timeout=30)
    resp.raise_for_status()
    return _clean(resp.text.splitlines())


def _fetch_fallback() -> list[str]:
    import io, pandas as pd
    resp = requests.get(FALLBACK_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    return _clean(df["Symbol"].dropna().tolist())


def get_all_us_tickers() -> list[str]:
    """Return a deduplicated, clean list of US stock tickers (pinned tickers always included)."""
    try:
        print("Fetching US ticker list from NASDAQ Screener API...")
        tickers = _fetch_nasdaq()
        print(f"  {len(tickers)} symbols loaded")
    except Exception as e:
        print(f"  NASDAQ API failed ({e}), trying GitHub fallback...")
        try:
            tickers = _fetch_github_all()
            print(f"  {len(tickers)} symbols loaded (GitHub fallback)")
        except Exception as e:
            print(f"  GitHub fallback failed ({e}), trying S&P 500 fallback...")
            try:
                tickers = _fetch_fallback()
                print(f"  {len(tickers)} S&P 500 symbols loaded (last-resort fallback)")
            except Exception as e:
                raise RuntimeError(f"All ticker sources failed: {e}")

    merged = sorted(set(tickers) | set(PINNED_TICKERS))
    print(f"  Pinned tickers added: {PINNED_TICKERS}")
    return merged
