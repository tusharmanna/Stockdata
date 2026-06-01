"""
patternscan.py — Pattern-based stock scans (higher lows, lower highs, squeeze).

Detects structural patterns over 20 trading days:
  - Higher Lows: bullish accumulation, buyers stepping in at progressively higher levels
  - Lower Highs: bearish distribution, sellers rejecting at lower levels
  - Squeeze: both patterns simultaneously (converging triangle / VCP)

Results are saved to patternscan_results.csv and patternscan_tickers.txt.

Usage:
    python patternscan.py
    python patternscan.py --no-display
"""

import argparse
import datetime
import os
import sqlite3
import pandas as pd
import database


_HIGHER_LOWS_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date, p.close, p.high, p.low, p.volume,
        LAG(p.low,  10) OVER (PARTITION BY p.ticker ORDER BY p.date) AS low_10d,
        LAG(p.low,  20) OVER (PARTITION BY p.ticker ORDER BY p.date) AS low_20d,
        LAG(p.high, 10) OVER (PARTITION BY p.ticker ORDER BY p.date) AS high_10d,
        LAG(p.high, 20) OVER (PARTITION BY p.ticker ORDER BY p.date) AS high_20d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-60 days')
)
SELECT
    w.ticker,
    w.date      AS price_date,
    w.close, w.high, w.low, w.volume,
    i.ma20, i.ma50, i.ma200, i.vol_avg30,
    ROUND(w.low_10d,  4) AS low_10d,
    ROUND(w.low_20d,  4) AS low_20d,
    ROUND(w.high_10d, 4) AS high_10d,
    ROUND(w.high_20d, 4) AS high_20d,
    CASE
        WHEN (w.low > w.low_10d AND w.low_10d > w.low_20d)
         AND (w.high < w.high_10d AND w.high_10d < w.high_20d) THEN 'Squeeze'
        WHEN  w.low > w.low_10d AND w.low_10d > w.low_20d      THEN 'Higher Lows'
        WHEN  w.high < w.high_10d AND w.high_10d < w.high_20d  THEN 'Lower Highs'
    END AS pattern
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest ON w.date = latest.max_date
WHERE
    w.close     >= 5
    AND w.volume    >= 100000
    AND i.vol_avg30 >= 200000
    AND w.low_10d   IS NOT NULL
    AND w.low_20d   IS NOT NULL
    AND w.high_10d  IS NOT NULL
    AND w.high_20d  IS NOT NULL
    AND (
        (w.low > w.low_10d AND w.low_10d > w.low_20d)
        OR
        (w.high < w.high_10d AND w.high_10d < w.high_20d)
    )
ORDER BY pattern, w.ticker
"""


def run_higher_lows_scan() -> pd.DataFrame:
    """
    Scan for higher lows, lower highs, or squeeze (both) over 20 trading days.
    3-point check at 10-day intervals: today / 10d ago / 20d ago.
    """
    conn = database._connect()

    df = pd.read_sql_query(_HIGHER_LOWS_SCAN_SQL, conn)

    if df.empty:
        print("Higher Lows/Lower Highs scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM higher_lows_scan_results")

    rows = [
        (
            scan_date,
            row.ticker,
            row.price_date,
            row.close,
            row.high,
            row.low,
            int(row.volume),
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.low_10d,
            row.low_20d,
            row.high_10d,
            row.high_20d,
            row.pattern,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO higher_lows_scan_results
           (scan_date, ticker, price_date, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30,
            low_10d, low_20d, high_10d, high_20d, pattern)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "patternscan_results.csv")
    print(f"Higher Lows/Lower Highs scan complete — {len(df)} stock(s) matched (saved to higher_lows_scan_results for {scan_date}):")
    _print_higher_lows_results(df)
    return df


def _save_csv(df: pd.DataFrame, scan_date: str, filename: str):
    folder = os.path.join("charts", scan_date)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    df.to_csv(path, index=False)
    print(f"  CSV saved to {path}")


def _print_higher_lows_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 180)
    cols = ["ticker", "price_date", "close", "high", "low", "volume",
            "ma20", "ma50", "vol_avg30",
            "low_10d", "low_20d", "high_10d", "high_20d", "pattern"]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-display", action="store_true",
                        help="Save results only, do not display in console")
    args = parser.parse_args()

    database.init_db()
    df = run_higher_lows_scan()

    if not df.empty:
        # Write ticker list by pattern (organized)
        scan_date = datetime.date.today().strftime("%Y-%m-%d")
        tickers_path = os.path.join(os.path.dirname(__file__), "patternscan_tickers.txt")

        with open(tickers_path, "w", encoding="utf-8") as f:
            f.write(f"# Pattern Scan Results — {scan_date}\n")
            f.write(f"# Total: {len(df)} stock(s)\n\n")

            for pattern in ["Squeeze", "Higher Lows", "Lower Highs"]:
                pattern_df = df[df["pattern"] == pattern]
                if not pattern_df.empty:
                    f.write(f"## {pattern} ({len(pattern_df)})\n")
                    for ticker in sorted(pattern_df["ticker"].unique()):
                        f.write(f"{ticker}\n")
                    f.write("\n")

        print(f"  Ticker list saved to {tickers_path}")

        # Write flat ticker list (one per line)
        flat_tickers_path = os.path.join(os.path.dirname(__file__), "patternscan_all_tickers.txt")
        with open(flat_tickers_path, "w", encoding="utf-8") as f:
            f.write(f"# Pattern Scan Flat List — {scan_date}\n")
            for ticker in sorted(df["ticker"].unique()):
                f.write(f"{ticker}\n")

        print(f"  Flat ticker list saved to {flat_tickers_path}")
