"""
intraday_scanner.py — Intraday breakout scanner.

Reads tickers from DailyWatchlist.txt and ActionList.txt.
For each ticker, fetches the current live price via yfinance and flags it if:

  Condition 1 — Prev-High Breakout:  current_price > yesterday's high
  Condition 2 — MA Crossover:        yesterday's close was below an MA and
                                     current_price has crossed above it
                                     (checks MA10, MA20, MA50, MA200)

Results are written to buynow.txt with separate sections for each condition.
A ticker can appear in both sections.

Run manually or via Task Scheduler every hour, 10:15 AM - 2:15 PM ET.
"""

import datetime
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE_DIR    = Path(__file__).parent
ACTION_LIST = BASE_DIR / "ActionList.txt"
BUY_NOW     = BASE_DIR / "buynow.txt"
DB_PATH     = BASE_DIR / "stockdata.db"

BATCH_SIZE      = 100   # tickers per yfinance multi-download call
MAX_BREAKOUT_PCT = 25.0  # cap to exclude stale-DB false positives


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_tickers(filepath: Path) -> list[str]:
    """Return non-comment, non-empty ticker lines from a watchlist file."""
    if not filepath.exists():
        print(f"  Warning: {filepath.name} not found - skipping")
        return []
    tickers = []
    for line in filepath.read_text().splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            tickers.append(t.upper())
    return tickers


def get_db_data(tickers: list[str]) -> dict[str, dict]:
    """
    Return per-ticker DB data needed for both scan conditions.

    Keys per ticker: prev_high, prev_close, ma10, ma20, ma50, ma200
    Only tickers with at least prev_high and prev_close are included.
    """
    if not DB_PATH.exists():
        print(f"  Error: {DB_PATH} not found - run main.py first")
        return {}

    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    result: dict[str, dict] = {}
    for ticker in tickers:
        # Most recent price row (yesterday's OHLCV)
        cur = conn.execute(
            "SELECT date, high, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (ticker,),
        )
        price_row = cur.fetchone()
        if not price_row or price_row[1] is None or price_row[2] is None:
            continue

        ref_date, prev_high, prev_close = price_row

        # Indicators for the same date
        cur = conn.execute(
            "SELECT ma10, ma20, ma50, ma200 FROM indicators WHERE ticker=? AND date=?",
            (ticker, ref_date),
        )
        ind_row = cur.fetchone()
        ma10 = ma20 = ma50 = ma200 = None
        if ind_row:
            ma10, ma20, ma50, ma200 = ind_row

        result[ticker] = {
            "prev_high":  float(prev_high),
            "prev_close": float(prev_close),
            "ma10":  float(ma10)  if ma10  is not None else None,
            "ma20":  float(ma20)  if ma20  is not None else None,
            "ma50":  float(ma50)  if ma50  is not None else None,
            "ma200": float(ma200) if ma200 is not None else None,
        }

    conn.close()
    return result


def _flatten_multi(raw: pd.DataFrame, batch: list[str]) -> dict[str, float]:
    """Extract the latest 1m close from a multi-ticker yfinance download.

    yfinance multi-ticker downloads use (ticker, field) MultiIndex column order.
    """
    prices: dict[str, float] = {}
    for ticker in batch:
        try:
            sub = raw[ticker]["Close"].dropna()
            if not sub.empty:
                prices[ticker] = float(sub.iloc[-1])
        except Exception:
            pass
    return prices


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """
    Fetch the most recent 1-minute bar close for every ticker.
    Uses batched multi-ticker downloads (100 tickers per call).
    """
    prices: dict[str, float] = {}
    total = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"    Batch {batch_num}/{total} ({len(batch)} tickers)...")
        try:
            if len(batch) == 1:
                df = yf.download(
                    batch[0], period="1d", interval="1m",
                    progress=False, auto_adjust=True,
                )
                if not df.empty:
                    prices[batch[0]] = float(df["Close"].iloc[-1])
            else:
                raw = yf.download(
                    batch, period="1d", interval="1m",
                    group_by="ticker", progress=False, auto_adjust=True,
                )
                prices.update(_flatten_multi(raw, batch))
        except Exception as exc:
            print(f"  Warning: batch {batch_num} download failed: {exc}")

    return prices


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.datetime.now()
    print(f"[{now:%Y-%m-%d %H:%M:%S}] Intraday breakout scanner starting...")

    # --- Load tickers -------------------------------------------------------
    all_tickers = sorted(set(load_tickers(ACTION_LIST)))
    print(f"  Tickers: {len(all_tickers)} (from ActionList.txt)")

    if not all_tickers:
        print("  No tickers loaded - exiting.")
        sys.exit(0)

    # --- DB data (prev high, prev close, MAs) -------------------------------
    db = get_db_data(all_tickers)
    missing = len(all_tickers) - len(db)
    print(f"  DB rows found: {len(db)}  (no DB row: {missing})")

    fetch_list = sorted(db.keys())
    if not fetch_list:
        print("  No tickers with DB data - exiting.")
        sys.exit(0)

    # --- Current prices from yfinance ---------------------------------------
    total_batches = (len(fetch_list) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  Fetching live 1m prices for {len(fetch_list)} tickers ({total_batches} batch(es))...")
    current = get_current_prices(fetch_list)
    print(f"  Prices received: {len(current)}")

    # --- Condition 1: current price > yesterday's high ----------------------
    prev_high_breakouts: list[tuple] = []
    for ticker in sorted(current):
        price    = current[ticker]
        ref_high = db[ticker]["prev_high"]
        if price > ref_high:
            diff = price - ref_high
            pct  = diff / ref_high * 100
            if pct <= MAX_BREAKOUT_PCT:
                prev_high_breakouts.append((ticker, price, ref_high, diff, pct))

    prev_high_breakouts.sort(key=lambda x: x[4], reverse=True)

    # --- Condition 2: price crossed above a moving average ------------------
    MA_NAMES = ["ma10", "ma20", "ma50", "ma200"]
    MA_LABELS = {"ma10": "MA10", "ma20": "MA20", "ma50": "MA50", "ma200": "MA200"}

    ma_crossovers: list[tuple] = []  # (ticker, price, ma_label, ma_value, diff, pct)
    for ticker in sorted(current):
        price      = current[ticker]
        prev_close = db[ticker]["prev_close"]
        for ma_key in MA_NAMES:
            ma_val = db[ticker].get(ma_key)
            if ma_val is None:
                continue
            # Crossover: was below MA yesterday, now above it
            if prev_close < ma_val <= price:
                diff = price - ma_val
                pct  = diff / ma_val * 100
                if pct <= MAX_BREAKOUT_PCT:
                    ma_crossovers.append((ticker, price, MA_LABELS[ma_key], ma_val, diff, pct))

    # One entry per (ticker, MA) pair; sort by % above MA descending
    ma_crossovers.sort(key=lambda x: x[5], reverse=True)

    # --- Build buynow.txt ---------------------------------------------------
    timestamp  = now.strftime("%Y-%m-%d %H:%M:%S")

    # Union all matched tickers (a ticker can appear in both conditions)
    all_buy_tickers = sorted(set(
        [t for t, *_ in prev_high_breakouts] +
        [t for t, *_ in ma_crossovers]
    ))

    lines = [f"# BuyNow - {timestamp}"]
    lines += all_buy_tickers if all_buy_tickers else ["# (none)"]

    BUY_NOW.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- Console summary ----------------------------------------------------
    print(f"\n  Prev-High Breakouts: {len(prev_high_breakouts)}  |  MA Crossovers: {len(ma_crossovers)}")
    print(f"  buynow.txt: {len(all_buy_tickers)} unique ticker(s)")
    if all_buy_tickers:
        print("  " + "  ".join(all_buy_tickers))
    print(f"\n  buynow.txt written -> {BUY_NOW}")


if __name__ == "__main__":
    main()
