"""
Scanner: two scans run against the latest trading day.

Scan 1 — Inside Bar:
  1. Close is above ma50 and ma200
  2. Volume is below the 30-day average (and >= 100k)
  3. The day is an inside bar (high < prev_day_high AND low > prev_day_low)

Scan 2 — Doji / Narrow Range near Key MA:
  1. Volume >= 100k
  2. Doji: |close - open| < 10% of (high - low)
     OR Narrow range: (high - low) / close < 1.5%
  3. Close is within 2% of ma20, ma50, or ma200

Results are saved to scan_results and doji_scan_results tables.

Usage:
    python scanner.py
"""

import argparse
import datetime
import sqlite3
import pandas as pd
import database
import chart


_SCAN_SQL = """
WITH latest AS (
    -- Most recent date that exists in both prices and indicators
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
prev AS (
    -- For each ticker, the trading day immediately before max_date
    SELECT p.ticker, p.date AS prev_date, p.high AS prev_high, p.low AS prev_low
    FROM prices p, latest
    WHERE p.date = (
        SELECT MAX(p2.date)
        FROM prices p2
        WHERE p2.ticker = p.ticker
          AND p2.date < latest.max_date
    )
)
SELECT
    p.ticker,
    p.date        AS price_date,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma10,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    prev.prev_high,
    prev.prev_low
FROM prices p
JOIN indicators i  ON p.ticker = i.ticker AND p.date = i.date
JOIN prev          ON p.ticker = prev.ticker
JOIN latest        ON p.date  = latest.max_date
WHERE
    p.close  > i.ma50
    AND p.close  > i.ma200
    AND p.volume >= 100000
    AND p.volume < i.vol_avg30
    AND p.high   < prev.prev_high
    AND p.low    > prev.prev_low
ORDER BY p.ticker
"""


def run_scan() -> pd.DataFrame:
    """
    Execute the scan against the database and return a DataFrame of matches.
    Also persists the results to scan_results (keyed by today's run date).
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_SCAN_SQL, conn)

    if df.empty:
        print("Scan complete — no stocks matched all criteria.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    # Wipe all previous results before inserting fresh ones
    conn.execute("DELETE FROM scan_results")

    rows = [
        (
            scan_date,
            row.ticker,
            row.price_date,
            row.close,
            row.high,
            row.low,
            int(row.volume),
            row.ma10,
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.prev_high,
            row.prev_low,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO scan_results
           (scan_date, ticker, price_date, close, high, low, volume,
            ma10, ma20, ma50, ma200, vol_avg30, prev_high, prev_low)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    print(f"Scan complete — {len(df)} stock(s) matched (saved to scan_results for {scan_date}):")
    _print_results(df)
    return df


_DOJI_MA_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
)
SELECT
    p.ticker,
    p.date        AS price_date,
    p.open,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma10,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ABS(p.close - p.open) / (p.high - p.low)  AS body_pct,
    (p.high - p.low) / p.close                 AS range_pct
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest       ON p.date = latest.max_date
WHERE
    p.volume >= 100000
    AND (p.high - p.low) > 0
    AND (
        -- Doji: body is less than 10% of candle range
        ABS(p.close - p.open) / (p.high - p.low) < 0.10
        OR
        -- Narrow range: total range less than 1.5% of price
        (p.high - p.low) / p.close < 0.015
    )
    AND (
        -- Within 2% of ma20, ma50, or ma200
        ABS(p.close - i.ma20)  / i.ma20  < 0.02
        OR ABS(p.close - i.ma50)  / i.ma50  < 0.02
        OR ABS(p.close - i.ma200) / i.ma200 < 0.02
    )
ORDER BY p.ticker
"""


def run_doji_scan() -> pd.DataFrame:
    """
    Scan for doji / narrow-range bars sitting near a key moving average.
    Results are saved to doji_scan_results keyed by (scan_date, ticker).
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_DOJI_MA_SCAN_SQL, conn)

    if df.empty:
        print("Doji/NR scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM doji_scan_results")

    rows = [
        (
            scan_date,
            row.ticker,
            row.price_date,
            row.open,
            row.close,
            row.high,
            row.low,
            int(row.volume),
            row.ma10,
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.body_pct,
            row.range_pct,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO doji_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma10, ma20, ma50, ma200, vol_avg30, body_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    print(f"Doji/NR scan complete — {len(df)} stock(s) matched (saved to doji_scan_results for {scan_date}):")
    _print_doji_results(df)
    return df


def _print_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 120)
    cols = ["ticker", "price_date", "close", "high", "low", "volume",
            "ma10", "ma20", "ma50", "ma200", "vol_avg30", "prev_high", "prev_low"]
    print(df[cols].to_string(index=False))


def _print_doji_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 140)
    cols = ["ticker", "price_date", "open", "close", "high", "low", "volume",
            "ma20", "ma50", "ma200", "body_pct", "range_pct"]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-display", action="store_true",
                        help="Save charts to files only, do not open GUI windows")
    args = parser.parse_args()

    database.init_db()
    df_inside = run_scan()
    print()
    df_doji = run_doji_scan()

    inside_tickers = df_inside["ticker"].tolist() if not df_inside.empty else []
    doji_tickers   = df_doji["ticker"].tolist()   if not df_doji.empty   else []

    print()
    chart.plot_results(inside_tickers, doji_tickers, show=not args.no_display)
