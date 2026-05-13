"""
refresh_whitelight_data.py — Download today's QQQ/TQQQ/SQQQ and recompute indicators.
Called by run_whitelight.bat before whitelight_strategy.py runs.
"""
import sqlite3
import sys
import pandas as pd
import yfinance as yf
import database
import indicators

TICKERS = ["PSQ", "QQQ", "SQQQ", "TQQQ"]


def main():
    database.init_db()
    print(f"Downloading latest data for {TICKERS}...")

    df = yf.download(TICKERS, period="5d", auto_adjust=True,
                     group_by="ticker", progress=False)

    if df.empty:
        print("ERROR: yfinance returned no data.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(database.DB_PATH)

    for ticker in TICKERS:
        try:
            sub = df[ticker].dropna()
            if sub.empty:
                print(f"  {ticker}: no data returned")
                continue
            database.upsert_prices(ticker, sub)

            prices = pd.read_sql_query(
                "SELECT * FROM prices WHERE ticker=? ORDER BY date",
                conn, params=(ticker,)
            )
            ind = indicators.compute_indicators(prices)
            database.upsert_indicators(ticker, ind)
            print(f"  {ticker}: {len(sub)} row(s) refreshed, indicators updated")
        except Exception as e:
            print(f"  {ticker}: ERROR — {e}", file=sys.stderr)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
