"""
Fetches the list of all US-listed stocks.
Sources (tried in order — optimized for daily/frequent use):
  1. NASDAQ Screener API     — ~7 000 NYSE/NASDAQ/AMEX tickers (primary: fast, reliable)
  2. GitHub: rreichel3/US-Stock-Symbols  — comprehensive all-exchange fallback
  3. SEC company_tickers.json — Official US-listed company tickers (fallback: rate-limited)
  4. GitHub: datasets/s-and-p-500-companies — S&P 500 last-resort fallback
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

SEC_URL = "https://www.sec.gov/files/company_tickers.json"

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
    """Fetch tickers from NASDAQ Screener API (primary source for daily use)."""
    resp = requests.get(NASDAQ_URL, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    rows = resp.json()["data"]["rows"]
    symbols = [r["symbol"] for r in rows if r.get("symbol")]
    return _clean(symbols)


def _fetch_github_all() -> list[str]:
    """Fetch from GitHub comprehensive ticker list."""
    resp = requests.get(GITHUB_ALL_URL, timeout=30)
    resp.raise_for_status()
    return _clean(resp.text.splitlines())


def _fetch_sec() -> list[str]:
    """Fetch tickers from SEC's official company_tickers.json (fallback: rate-limited).

    Note: SEC endpoint has strict rate limiting. Use only as fallback when primary
    sources fail. For one-time comprehensive list, this is authoritative. For daily
    updates, NASDAQ API is recommended.
    """
    resp = requests.get(
        SEC_URL,
        headers={**_HEADERS, "Accept": "application/json"},
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    symbols = [entry["ticker"] for entry in data.values() if entry.get("ticker")]
    return _clean(symbols)


def _fetch_fallback() -> list[str]:
    """Fetch S&P 500 symbols (last-resort fallback)."""
    import io, pandas as pd
    resp = requests.get(FALLBACK_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    return _clean(df["Symbol"].dropna().tolist())


def get_all_us_tickers() -> list[str]:
    """Return a deduplicated, clean list of US stock tickers (pinned tickers always included).

    Optimized for daily/frequent use: tries NASDAQ first (fast, reliable),
    then GitHub, then SEC (official but rate-limited), then S&P 500 CSV.
    """
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
            print(f"  GitHub fallback failed ({e}), trying SEC company_tickers.json...")
            try:
                tickers = _fetch_sec()
                print(f"  {len(tickers)} symbols loaded (SEC official source)")
            except Exception as e:
                print(f"  SEC source failed ({e}), trying S&P 500 fallback...")
                try:
                    tickers = _fetch_fallback()
                    print(f"  {len(tickers)} S&P 500 symbols loaded (last-resort fallback)")
                except Exception as e:
                    raise RuntimeError(f"All ticker sources failed: {e}")

    merged = sorted(set(tickers) | set(PINNED_TICKERS))
    print(f"  Pinned tickers added: {PINNED_TICKERS}")
    return merged
