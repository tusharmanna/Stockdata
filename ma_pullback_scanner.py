"""
ma_pullback_scanner.py — Identify pullback opportunities to moving averages in uptrends.

Strategy: Find stocks trading near their 20/50-day MA (within 5%) while above the 200-day MA.
This identifies potential entry points where price is testing support in a confirmed uptrend.

Criteria:
  - Close within 5% of MA20 OR MA50 (pullback to support)
  - Close above MA200 (confirmed uptrend)
  - Volume >= 100k, vol_avg30 >= 200k (liquidity filter)

Results saved to ma_pullback_tickers.txt and ma_pullback_all_tickers.txt

Usage:
    python ma_pullback_scanner.py
    python ma_pullback_scanner.py --no-display
"""

import argparse
import datetime
import os
import sqlite3
import pandas as pd
import database


_MA_PULLBACK_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
)
SELECT
    p.ticker,
    p.date      AS price_date,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND(ABS(p.close - i.ma20) / i.ma20 * 100, 2) AS pct_from_ma20,
    ROUND(ABS(p.close - i.ma50) / i.ma50 * 100, 2) AS pct_from_ma50,
    CASE
        WHEN ABS(p.close - i.ma20) / i.ma20 < 0.05 THEN 'MA20'
        WHEN ABS(p.close - i.ma50) / i.ma50 < 0.05 THEN 'MA50'
    END AS support_ma
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest ON p.date = latest.max_date
WHERE
    p.close >= 5
    AND p.volume >= 100000
    AND i.vol_avg30 >= 200000
    AND p.close > i.ma200
    AND (
        ABS(p.close - i.ma20) / i.ma20 < 0.05
        OR ABS(p.close - i.ma50) / i.ma50 < 0.05
    )
ORDER BY support_ma, p.ticker
"""


def run_ma_pullback_scan() -> pd.DataFrame:
    """
    Scan for stocks in pullback to 20/50-day MA while above 200-day MA.
    Identifies potential entry points in confirmed uptrends.
    """
    conn = database._connect()

    df = pd.read_sql_query(_MA_PULLBACK_SQL, conn)

    if df.empty:
        print("MA Pullback scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM ma_pullback_scan_results")

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
            row.pct_from_ma20,
            row.pct_from_ma50,
            row.support_ma,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO ma_pullback_scan_results
           (scan_date, ticker, price_date, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30,
            pct_from_ma20, pct_from_ma50, support_ma)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "ma_pullback_results.csv")
    print(f"MA Pullback scan complete — {len(df)} stock(s) matched (saved to ma_pullback_scan_results for {scan_date}):")
    _print_ma_pullback_results(df)
    return df


def _save_csv(df: pd.DataFrame, scan_date: str, filename: str):
    folder = os.path.join("charts", scan_date)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    df.to_csv(path, index=False)
    print(f"  CSV saved to {path}")


def _print_ma_pullback_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 180)
    cols = ["ticker", "price_date", "close", "high", "low", "volume",
            "ma20", "ma50", "ma200", "vol_avg30",
            "pct_from_ma20", "pct_from_ma50", "support_ma"]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-display", action="store_true",
                        help="Save results only, do not display in console")
    args = parser.parse_args()

    database.init_db()
    df = run_ma_pullback_scan()

    if not df.empty:
        scan_date = datetime.date.today().strftime("%Y-%m-%d")

        # Write ticker list by MA (organized)
        tickers_path = os.path.join(os.path.dirname(__file__), "ma_pullback_tickers.txt")
        with open(tickers_path, "w", encoding="utf-8") as f:
            f.write(f"# MA Pullback Opportunities — {scan_date}\n")
            f.write(f"# Pullback to 20/50-day MA in confirmed uptrend (above MA200)\n")
            f.write(f"# Total: {len(df)} stock(s)\n\n")

            for ma in ["MA20", "MA50"]:
                ma_df = df[df["support_ma"] == ma]
                if not ma_df.empty:
                    f.write(f"## {ma} Support ({len(ma_df)})\n")
                    for ticker in sorted(ma_df["ticker"].unique()):
                        ticker_data = ma_df[ma_df["ticker"] == ticker].iloc[0]
                        pct = ticker_data["pct_from_ma20"] if ma == "MA20" else ticker_data["pct_from_ma50"]
                        f.write(f"{ticker}  ({pct:.2f}% from {ma})\n")
                    f.write("\n")

        print(f"  Ticker list saved to {tickers_path}")

        # Write flat ticker list (one per line)
        flat_tickers_path = os.path.join(os.path.dirname(__file__), "ma_pullback_all_tickers.txt")
        with open(flat_tickers_path, "w", encoding="utf-8") as f:
            f.write(f"# MA Pullback Flat List — {scan_date}\n")
            for ticker in sorted(df["ticker"].unique()):
                f.write(f"{ticker}\n")

        print(f"  Flat ticker list saved to {flat_tickers_path}")
