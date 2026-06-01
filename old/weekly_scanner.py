"""
weekly_scanner.py — Weekly scans (run once per week, typically on Sunday).

Scans:
  1. Momentum          — extended stocks >15% above MA50 with strong 20-day return
  2. StockbeeMomentum  — range-expansion breakout day after volatility contraction
  3. Double Trouble    — stocks that doubled off 52-week lows, quiet ±1% day
  4. TI65              — 7-day avg >5% above 65-day avg, quiet ±1% day
  5. Parabolic         — explosive stocks 50%+ above MA50, still running

Results are written to the DB, individual CSVs under charts/YYYY-MM-DD/,
a combined WeeklyWatchlist.txt, and a PDF chart.

Usage:
    python weekly_scanner.py
    python weekly_scanner.py --no-display
"""

import argparse
import datetime
import os
import sqlite3
import pandas as pd
import database
import chart


# ---------------------------------------------------------------------------
# Scan 1 — Momentum
# ---------------------------------------------------------------------------

_MOMENTUM_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
prev20 AS (
    SELECT p.ticker, p.close AS close_20d_ago
    FROM prices p, latest
    WHERE p.date = (
        SELECT p2.date FROM prices p2
        WHERE p2.ticker = p.ticker
          AND p2.date   <= DATE(latest.max_date, '-28 days')
        ORDER BY p2.date DESC
        LIMIT 1
    )
),
recent AS (
    SELECT p.ticker, p.date,
           LAG(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_high,
           LAG(p.low)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_low
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-30 days')
)
SELECT
    p.ticker,
    p.date                                                           AS price_date,
    p.open,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND((p.close - i.ma20)  / i.ma20  * 100, 2)                  AS dist_ma20_pct,
    ROUND((p.close - i.ma50)  / i.ma50  * 100, 2)                  AS dist_ma50_pct,
    ROUND((p.close - prev20.close_20d_ago) / prev20.close_20d_ago * 100, 2) AS ret_20d_pct,
    ROUND((p.high  - p.low)   / p.close * 100, 2)                  AS range_pct
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest        ON p.date   = latest.max_date
JOIN prev20        ON p.ticker = prev20.ticker
JOIN recent r      ON p.ticker = r.ticker AND p.date = r.date
WHERE
    p.close   > i.ma20
    AND p.close   > i.ma50
    AND i.ma20    > i.ma50
    AND (p.close - i.ma50)  / i.ma50  > 0.15
    AND (p.close - i.ma50)  / i.ma50  < 2.0
    AND (p.close - prev20.close_20d_ago) / prev20.close_20d_ago > 0.15
    AND p.volume  >= 50000
    AND i.vol_avg30 >= 50000
    AND r.prev_high IS NOT NULL
    AND (
        (p.high < r.prev_high AND p.low > r.prev_low)
        OR (p.high - p.low) / p.close < 0.015
    )
ORDER BY ret_20d_pct DESC
"""


def run_momentum_scan() -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    df = pd.read_sql_query(_MOMENTUM_SCAN_SQL, conn)
    if df.empty:
        print("Momentum scan complete — no stocks matched.")
        conn.close()
        return df
    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM momentum_scan_results")
    rows = [
        (scan_date, row.ticker, row.price_date, row.open, row.close, row.high, row.low,
         int(row.volume), row.ma20, row.ma50, row.ma200, row.vol_avg30,
         row.dist_ma20_pct, row.dist_ma50_pct, row.ret_20d_pct, row.range_pct)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO momentum_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, dist_ma20_pct, dist_ma50_pct, ret_20d_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "momentum_scan_results.csv")
    print(f"Momentum scan complete — {len(df)} stock(s) matched:")
    _print_momentum_results(df)
    return df


# ---------------------------------------------------------------------------
# Scan 2 — StockbeeMomentum
# ---------------------------------------------------------------------------

_STOCKBEE_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        p.high - p.low                                                         AS day_range,
        LAG(p.high,  1) OVER w                                                 AS prev_high,
        LAG(p.low,   1) OVER w                                                 AS prev_low,
        LAG(p.close, 1) OVER w                                                 AS prev_close,
        LAG(p.open,  1) OVER w                                                 AS prev_open,
        LAG(p.volume,1) OVER w                                                 AS prev_volume,
        LAG(p.high - p.low, 1) OVER w                                          AS prev_range,
        AVG(p.high - p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                                  ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)    AS avg_range_5d,
        AVG(p.high - p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                                  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING)   AS avg_range_10d,
        MAX(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date
                          ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)            AS max_high_5d,
        MAX(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date
                          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)           AS max_high_20d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-35 days')
    WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
)
SELECT
    w.ticker,
    w.date                                                    AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    CAST(w.prev_volume AS INTEGER)                            AS prev_volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND(w.day_range / w.close * 100, 2)                    AS range_pct,
    ROUND(w.day_range / w.avg_range_5d, 2)                   AS range_expansion,
    ROUND((w.close - w.high) / w.high * 100, 2)              AS close_vs_high_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest       ON w.date   = latest.max_date
WHERE
    w.day_range > w.avg_range_5d * 1.5
    AND w.close >= w.high * 0.95
    AND w.volume > w.prev_volume
    AND w.volume   >= 100000
    AND i.vol_avg30 >= 50000
    AND (w.prev_range < w.avg_range_5d OR w.prev_close <= w.prev_open)
    AND w.high > w.max_high_5d
    AND w.max_high_20d <= w.high * 1.15
    AND w.avg_range_5d <= w.avg_range_10d
    AND (i.ma50 IS NULL OR w.close < i.ma50 * 1.50)
    AND w.prev_high IS NOT NULL
    AND w.avg_range_5d > 0
    AND w.avg_range_10d > 0
ORDER BY range_expansion DESC
"""


def run_stockbee_scan() -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    df = pd.read_sql_query(_STOCKBEE_SCAN_SQL, conn)
    if df.empty:
        print("StockbeeMomentum scan complete — no stocks matched.")
        conn.close()
        return df
    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM stockbee_scan_results")
    rows = [
        (scan_date, row.ticker, row.price_date, row.open, row.close, row.high, row.low,
         int(row.volume), int(row.prev_volume), row.ma20, row.ma50, row.ma200, row.vol_avg30,
         row.range_pct, row.range_expansion, row.close_vs_high_pct)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO stockbee_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume, prev_volume,
            ma20, ma50, ma200, vol_avg30, range_pct, range_expansion, close_vs_high_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "stockbee_scan_results.csv")
    print(f"StockbeeMomentum scan complete — {len(df)} stock(s) matched:")
    _print_stockbee_results(df)
    return df


# ---------------------------------------------------------------------------
# Scan 3 — Double Trouble
# ---------------------------------------------------------------------------

_DOUBLE_TROUBLE_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date)  AS prev_close,
        MIN(p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                         ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)  AS low_252d,
        AVG(p.volume) OVER (PARTITION BY p.ticker ORDER BY p.date
                            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS avg_vol_3d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-400 days')
)
SELECT
    w.ticker,
    w.date                                                         AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND(w.close / w.low_252d, 2)                                 AS close_vs_52wk_low,
    ROUND((w.close - w.prev_close) / w.prev_close * 100, 2)        AS change_pct,
    ROUND((w.high - w.low) / w.close * 100, 2)                     AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest       ON w.date   = latest.max_date
WHERE
    w.close / w.low_252d >= 1.8
    AND w.avg_vol_3d >= 100000
    AND i.vol_avg30 >= 500000
    AND w.close > i.ma50
    AND i.ma50  > i.ma200
    AND w.prev_close IS NOT NULL
    AND (w.close - w.prev_close) / w.prev_close * 100 BETWEEN -1.0 AND 1.0
ORDER BY close_vs_52wk_low DESC
"""


def run_double_trouble_scan() -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    df = pd.read_sql_query(_DOUBLE_TROUBLE_SCAN_SQL, conn)
    if df.empty:
        print("Double Trouble scan complete — no stocks matched.")
        conn.close()
        return df
    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM double_trouble_scan_results")
    rows = [
        (scan_date, row.ticker, row.price_date, row.open, row.close, row.high, row.low,
         int(row.volume), row.ma20, row.ma50, row.ma200, row.vol_avg30,
         row.close_vs_52wk_low, row.change_pct, row.range_pct)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO double_trouble_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, close_vs_52wk_low, change_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "double_trouble_scan_results.csv")
    print(f"Double Trouble scan complete — {len(df)} stock(s) matched:")
    _print_double_trouble_results(df)
    return df


# ---------------------------------------------------------------------------
# Scan 4 — TI65
# ---------------------------------------------------------------------------

_TI65_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date)  AS prev_close,
        AVG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)  AS avgc7,
        AVG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 64 PRECEDING AND CURRENT ROW) AS avgc65,
        AVG(p.volume) OVER (PARTITION BY p.ticker ORDER BY p.date
                            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS avg_vol_3d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-120 days')
)
SELECT
    w.ticker,
    w.date                                                         AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND(w.avgc7,  4)                                             AS avgc7,
    ROUND(w.avgc65, 4)                                             AS avgc65,
    ROUND(w.avgc7 / w.avgc65, 4)                                   AS ti65_ratio,
    ROUND((w.close - w.prev_close) / w.prev_close * 100, 2)        AS change_pct,
    ROUND((w.high - w.low) / w.close * 100, 2)                     AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest       ON w.date   = latest.max_date
WHERE
    w.avgc7 / w.avgc65 > 1.05
    AND w.avg_vol_3d >= 100000
    AND i.vol_avg30 >= 500000
    AND w.close > i.ma50
    AND i.ma50  > i.ma200
    AND w.prev_close IS NOT NULL
    AND (w.close - w.prev_close) / w.prev_close * 100 BETWEEN -1.0 AND 1.0
    AND w.avgc65 > 0
ORDER BY ti65_ratio DESC
"""


def run_ti65_scan() -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    df = pd.read_sql_query(_TI65_SCAN_SQL, conn)
    if df.empty:
        print("TI65 scan complete — no stocks matched.")
        conn.close()
        return df
    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM ti65_scan_results")
    rows = [
        (scan_date, row.ticker, row.price_date, row.open, row.close, row.high, row.low,
         int(row.volume), row.ma50, row.ma200, row.vol_avg30,
         row.avgc7, row.avgc65, row.ti65_ratio, row.change_pct, row.range_pct)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO ti65_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma50, ma200, vol_avg30, avgc7, avgc65, ti65_ratio, change_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "ti65_scan_results.csv")
    print(f"TI65 scan complete — {len(df)} stock(s) matched:")
    _print_ti65_results(df)
    return df


# ---------------------------------------------------------------------------
# Scan 5 — Parabolic
# ---------------------------------------------------------------------------

_PARABOLIC_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 20) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_20d_ago,
        LAG(p.close,  5) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_5d_ago,
        MIN(p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                         ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)   AS low_60d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-90 days')
)
SELECT
    w.ticker,
    w.date                                                                  AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND((w.close - w.close_20d_ago) / w.close_20d_ago * 100, 2)         AS ret_20d_pct,
    ROUND((w.close - w.close_5d_ago)  / w.close_5d_ago  * 100, 2)         AS ret_5d_pct,
    ROUND((w.close - w.low_60d)       / w.low_60d        * 100, 2)         AS rise_60d_pct,
    ROUND((w.close - i.ma50)          / i.ma50            * 100, 2)         AS dist_ma50_pct,
    ROUND((w.high  - w.low)           / w.close           * 100, 2)         AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest       ON w.date   = latest.max_date
WHERE
    w.close > i.ma20
    AND w.close > i.ma50
    AND (w.close - i.ma50) / i.ma50 >= 0.50
    AND w.close_20d_ago IS NOT NULL
    AND (w.close - w.close_20d_ago) / w.close_20d_ago >= 0.50
    AND w.close_5d_ago IS NOT NULL
    AND w.close > w.close_5d_ago
    AND w.low_60d > 0
    AND (w.close - w.low_60d) / w.low_60d >= 0.50
    AND w.volume   >= 50000
    AND i.vol_avg30 >= 50000
ORDER BY ret_20d_pct DESC
"""


def run_parabolic_scan() -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    df = pd.read_sql_query(_PARABOLIC_SCAN_SQL, conn)
    if df.empty:
        print("Parabolic scan complete — no stocks matched.")
        conn.close()
        return df
    scan_date = datetime.date.today().strftime("%Y-%m-%d")
    conn.execute("DELETE FROM parabolic_scan_results")
    rows = [
        (scan_date, row.ticker, row.price_date, row.open, row.close, row.high, row.low,
         int(row.volume), row.ma20, row.ma50, row.ma200, row.vol_avg30,
         row.ret_20d_pct, row.ret_5d_pct, row.rise_60d_pct, row.dist_ma50_pct, row.range_pct)
        for row in df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO parabolic_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, ret_20d_pct, ret_5d_pct,
            rise_60d_pct, dist_ma50_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "parabolic_scan_results.csv")
    print(f"Parabolic scan complete — {len(df)} stock(s) matched:")
    _print_parabolic_results(df)
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_csv(df: pd.DataFrame, scan_date: str, filename: str):
    folder = os.path.join("charts", scan_date)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    df.to_csv(path, index=False)
    print(f"  CSV saved to {path}")


def _print_momentum_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 140)
    cols = ["ticker", "price_date", "close", "ma20", "ma50", "ma200",
            "vol_avg30", "dist_ma20_pct", "dist_ma50_pct", "ret_20d_pct", "range_pct"]
    print(df[cols].to_string(index=False))


def _print_stockbee_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 150)
    cols = ["ticker", "price_date", "close", "high", "low", "volume", "prev_volume",
            "ma50", "vol_avg30", "range_pct", "range_expansion", "close_vs_high_pct"]
    print(df[cols].to_string(index=False))


def _print_double_trouble_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 150)
    cols = ["ticker", "price_date", "close", "ma50", "ma200",
            "vol_avg30", "close_vs_52wk_low", "change_pct", "range_pct"]
    print(df[cols].to_string(index=False))


def _print_ti65_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.4f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 150)
    cols = ["ticker", "price_date", "close", "ma50", "ma200",
            "vol_avg30", "avgc7", "avgc65", "ti65_ratio", "change_pct", "range_pct"]
    print(df[cols].to_string(index=False))


def _print_parabolic_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)
    cols = ["ticker", "price_date", "close", "ma20", "ma50",
            "vol_avg30", "ret_5d_pct", "ret_20d_pct", "rise_60d_pct", "dist_ma50_pct", "range_pct"]
    print(df[cols].to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly scanner — Momentum / Stockbee / Double Trouble / TI65 / Parabolic")
    parser.add_argument("--no-display", action="store_true",
                        help="Save charts to files only, do not open GUI windows")
    args = parser.parse_args()

    database.init_db()

    df_momentum       = run_momentum_scan()
    df_stockbee       = run_stockbee_scan()
    df_double_trouble = run_double_trouble_scan()
    df_ti65           = run_ti65_scan()
    df_parabolic      = run_parabolic_scan()

    momentum_tickers       = df_momentum["ticker"].tolist()       if not df_momentum.empty       else []
    stockbee_tickers       = df_stockbee["ticker"].tolist()       if not df_stockbee.empty       else []
    double_trouble_tickers = df_double_trouble["ticker"].tolist() if not df_double_trouble.empty else []
    ti65_tickers           = df_ti65["ticker"].tolist()           if not df_ti65.empty           else []
    parabolic_tickers      = df_parabolic["ticker"].tolist()      if not df_parabolic.empty      else []

    all_weekly = sorted(set(momentum_tickers + stockbee_tickers
                            + double_trouble_tickers + ti65_tickers + parabolic_tickers))

    # Write WeeklyWatchlist.txt — read by intraday_scanner.py all week
    watchlist_path = os.path.join(os.path.dirname(__file__), "WeeklyWatchlist.txt")
    with open(watchlist_path, "w") as f:
        f.write(f"# Generated by weekly_scanner.py on {datetime.date.today()}\n")
        f.write(f"# Momentum:{len(momentum_tickers)}  Stockbee:{len(stockbee_tickers)}  "
                f"DoubleTrouble:{len(double_trouble_tickers)}  TI65:{len(ti65_tickers)}  "
                f"Parabolic:{len(parabolic_tickers)}\n")
        for ticker in all_weekly:
            f.write(f"{ticker}\n")
    print(f"\n  WeeklyWatchlist.txt updated: {len(all_weekly)} ticker(s) -> {watchlist_path}")

    chart.plot_results(
        [], [],
        momentum_tickers=momentum_tickers,
        stockbee_tickers=stockbee_tickers,
        double_trouble_tickers=double_trouble_tickers,
        ti65_tickers=ti65_tickers,
        parabolic_tickers=parabolic_tickers,
        show=not args.no_display,
    )
