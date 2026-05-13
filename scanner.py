"""
scanner.py — All end-of-day scans. Run via daily.bat after market close.

Scans:
  1.  Inside Bar          — uptrend stock, inside-bar day on low volume
  2.  Doji / Narrow Range near MA — indecision candle at a key MA
  3.  Red Candle near MA  — pullback to MA in uptrend
  4.  IBD Leader          — institutional quality, MA50 > MA200, tight day
  5.  Momentum            — extended stocks >15% above MA50, strong 20-day return
  6.  StockbeeMomentum    — range-expansion breakout after volatility contraction
  7.  Double Trouble      — doubled off 52-week lows, quiet day
  8.  TI65                — 7-day avg >5% above 65-day avg, quiet day
  9.  Parabolic           — 50%+ above MA50, still running
  10. MA Cross-Up         — narrow green candle crossing above MA20/50/200
  11. MA Cross-Down       — narrow red candle crossing below MA20/50/200
  12. Near MA50 Below     — within 2% below MA50
  13. MA50 Cross-Up       — any close above MA50 from below

All scan results are combined into ActionList.txt.
The intraday scanner reads ActionList.txt to populate buynow.txt.

Usage:
    python scanner.py
    python scanner.py --no-display
"""

import argparse
import datetime
import os
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
recent AS (
    -- Last 30 days only, with previous day's high/low/close via LAG
    SELECT p.ticker, p.date, p.high, p.low,
           LAG(p.high)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_high,
           LAG(p.low)   OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_low,
           LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
           LAG(i.ma200) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma200
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date, latest
    WHERE p.date >= DATE(latest.max_date, '-30 days')
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
    r.prev_high,
    r.prev_low
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN recent r     ON p.ticker = r.ticker  AND p.date = r.date
JOIN latest       ON p.date  = latest.max_date
WHERE
    p.close  > 5
    AND p.close  > i.ma50
    AND p.close  > i.ma200

    AND r.prev_close > r.prev_ma200          -- prev day also above ma200 (filters spike-through)
    AND p.volume >= 100000
    AND p.volume < i.vol_avg30
    AND i.vol_avg30 > 1000000
    AND p.high   < r.prev_high
    AND p.low    > r.prev_low
    AND r.prev_high  IS NOT NULL
    AND r.prev_close IS NOT NULL
    AND r.prev_ma200 IS NOT NULL
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

    _save_csv(df, scan_date, "inside_bar_scan_results.csv")
    print(f"Scan complete — {len(df)} stock(s) matched (saved to scan_results for {scan_date}):")
    _print_results(df)
    return df


_DOJI_MA_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
recent AS (
    -- Previous day's high via LAG
    SELECT p.ticker, p.date,
           LAG(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_high
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-30 days')
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
JOIN recent r     ON p.ticker = r.ticker AND p.date = r.date
WHERE
    p.close >= 5
    AND p.volume >= 100000
    AND i.vol_avg30 > 1000000
    AND p.close > i.ma200

    AND (p.high - p.low) > 0
    AND p.high < r.prev_high                   -- high below previous day's high
    AND r.prev_high IS NOT NULL
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

    _save_csv(df, scan_date, "doji_scan_results.csv")
    print(f"Doji/NR scan complete — {len(df)} stock(s) matched (saved to doji_scan_results for {scan_date}):")
    _print_doji_results(df)
    return df


_RED_CANDLE_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
recent AS (
    -- Previous day's high via LAG
    SELECT p.ticker, p.date,
           LAG(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_high
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-30 days')
)
SELECT
    p.ticker,
    p.date        AS price_date,
    p.open,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ABS(p.close - p.open) / (p.high - p.low)  AS body_pct,
    (p.high - p.low) / p.close                 AS range_pct
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest       ON p.date = latest.max_date
JOIN recent r     ON p.ticker = r.ticker AND p.date = r.date
WHERE
    p.close >= 5
    AND p.volume >= 100000
    AND i.vol_avg30 > 1000000
    AND p.close > i.ma200

    AND (p.high - p.low) > 0
    AND p.close < p.open                       -- red candle
    AND p.high < r.prev_high                   -- high below previous day's high
    AND r.prev_high IS NOT NULL
    AND (
        -- Close within 2% of ma20, ma50, or ma200
        ABS(p.close - i.ma20)  / i.ma20  < 0.02
        OR ABS(p.close - i.ma50)  / i.ma50  < 0.02
        OR ABS(p.close - i.ma200) / i.ma200 < 0.02
    )
ORDER BY p.ticker
"""


def run_red_candle_scan() -> pd.DataFrame:
    """
    Scan for red candles (close < open) near a key moving average,
    with the high below the previous day's high.
    Results saved to red_candle_scan_results.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_RED_CANDLE_SCAN_SQL, conn)

    if df.empty:
        print("Red candle scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM red_candle_scan_results")

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
        """INSERT OR REPLACE INTO red_candle_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, body_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "red_candle_scan_results.csv")
    print(f"Red candle scan complete — {len(df)} stock(s) matched (saved to red_candle_scan_results for {scan_date}):")
    _print_doji_results(df)
    return df


_IBD_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
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
    p.date                                                   AS price_date,
    p.open,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND((p.close - i.ma50)  / i.ma50  * 100, 2)          AS dist_ma50_pct,
    ROUND((p.close - i.ma200) / i.ma200 * 100, 2)          AS dist_ma200_pct,
    ROUND((p.high  - p.low)   / p.close * 100, 2)          AS range_pct
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest       ON p.date   = latest.max_date
JOIN recent r     ON p.ticker = r.ticker AND p.date = r.date
WHERE
    p.close    > 5
    AND p.close    > i.ma200                         -- above 200-day MA (long-term uptrend)
    AND i.ma50 > i.ma200                         -- MA50 above MA200 (confirmed sustained uptrend)
    AND p.close > i.ma50 * 0.85                  -- not more than 15% below MA50

    AND i.vol_avg30 > 1000000                    -- institutional-grade liquidity
    AND p.volume   >= 100000
    AND r.prev_high IS NOT NULL
    AND (
        -- Inside bar: today's range is inside yesterday's range
        (p.high < r.prev_high AND p.low > r.prev_low)
        OR
        -- Narrow range: today's range < 1.5% of price
        (p.high - p.low) / p.close < 0.015
    )
ORDER BY dist_ma50_pct ASC
"""


def run_ibd_scan() -> pd.DataFrame:
    """
    Scan for IBD-style leader stocks:
      - Close above MA200 (long-term uptrend)
      - MA50 above MA200 (confirmed, sustained uptrend — not just a bounce)
      - Close within 15% below MA50 (consolidating in uptrend, not broken down)
      - vol_avg30 > 500k (institutional liquidity)
    Results sorted by distance from MA50 (closest = best entry proximity).
    Saved to ibd_scan_results.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_IBD_SCAN_SQL, conn)

    if df.empty:
        print("IBD scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM ibd_scan_results")

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
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.dist_ma50_pct,
            row.dist_ma200_pct,
            row.range_pct,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO ibd_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, dist_ma50_pct, dist_ma200_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "ibd_scan_results.csv")
    print(f"IBD scan complete — {len(df)} stock(s) matched (saved to ibd_scan_results for {scan_date}):")
    _print_ibd_results(df)
    return df


# ---------------------------------------------------------------------------
# Scan 5 — Momentum
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
    p.open, p.close, p.high, p.low, p.volume,
    i.ma20, i.ma50, i.ma200, i.vol_avg30,
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
    p.close > 5
    AND p.close > i.ma20 AND p.close > i.ma50
    AND i.ma20 > i.ma50
    AND (p.close - i.ma50) / i.ma50 > 0.15
    AND (p.close - i.ma50) / i.ma50 < 2.0
    AND (p.close - prev20.close_20d_ago) / prev20.close_20d_ago > 0.15
    AND p.volume >= 50000 AND i.vol_avg30 >= 50000
    AND r.prev_high IS NOT NULL
    AND ((p.high < r.prev_high AND p.low > r.prev_low)
         OR (p.high - p.low) / p.close < 0.015)
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
    rows = [(scan_date, r.ticker, r.price_date, r.open, r.close, r.high, r.low,
             int(r.volume), r.ma20, r.ma50, r.ma200, r.vol_avg30,
             r.dist_ma20_pct, r.dist_ma50_pct, r.ret_20d_pct, r.range_pct)
            for r in df.itertuples(index=False)]
    conn.executemany(
        """INSERT OR REPLACE INTO momentum_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, dist_ma20_pct, dist_ma50_pct, ret_20d_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "momentum_scan_results.csv")
    print(f"Momentum scan complete — {len(df)} stock(s) matched:")
    pd.set_option("display.float_format", "{:.2f}".format)
    print(df[["ticker","price_date","close","ma50","ret_20d_pct","dist_ma50_pct","range_pct"]].to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# Scan 6 — StockbeeMomentum
# ---------------------------------------------------------------------------

_STOCKBEE_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        p.high - p.low AS day_range,
        LAG(p.high,  1) OVER w AS prev_high,
        LAG(p.close, 1) OVER w AS prev_close,
        LAG(p.open,  1) OVER w AS prev_open,
        LAG(p.volume,1) OVER w AS prev_volume,
        LAG(p.high - p.low, 1) OVER w AS prev_range,
        AVG(p.high - p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                                  ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS avg_range_5d,
        AVG(p.high - p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                                  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS avg_range_10d,
        MAX(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date
                          ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS max_high_5d,
        MAX(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date
                          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS max_high_20d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-35 days')
    WINDOW w AS (PARTITION BY p.ticker ORDER BY p.date)
)
SELECT w.ticker, w.date AS price_date, w.open, w.close, w.high, w.low, w.volume,
    CAST(w.prev_volume AS INTEGER) AS prev_volume,
    i.ma20, i.ma50, i.ma200, i.vol_avg30,
    ROUND(w.day_range / w.close * 100, 2) AS range_pct,
    ROUND(w.day_range / w.avg_range_5d, 2) AS range_expansion,
    ROUND((w.close - w.high) / w.high * 100, 2) AS close_vs_high_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest ON w.date = latest.max_date
WHERE w.close >= 5
    AND w.day_range > w.avg_range_5d * 1.5
    AND w.close >= w.high * 0.95
    AND w.volume > w.prev_volume
    AND w.volume >= 100000 AND i.vol_avg30 >= 50000
    AND (w.prev_range < w.avg_range_5d OR w.prev_close <= w.prev_open)
    AND w.high > w.max_high_5d
    AND w.max_high_20d <= w.high * 1.15
    AND w.avg_range_5d <= w.avg_range_10d
    AND (i.ma50 IS NULL OR w.close < i.ma50 * 1.50)
    AND w.prev_high IS NOT NULL AND w.avg_range_5d > 0 AND w.avg_range_10d > 0
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
    rows = [(scan_date, r.ticker, r.price_date, r.open, r.close, r.high, r.low,
             int(r.volume), int(r.prev_volume), r.ma20, r.ma50, r.ma200, r.vol_avg30,
             r.range_pct, r.range_expansion, r.close_vs_high_pct)
            for r in df.itertuples(index=False)]
    conn.executemany(
        """INSERT OR REPLACE INTO stockbee_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume, prev_volume,
            ma20, ma50, ma200, vol_avg30, range_pct, range_expansion, close_vs_high_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "stockbee_scan_results.csv")
    print(f"StockbeeMomentum scan complete — {len(df)} stock(s) matched:")
    pd.set_option("display.float_format", "{:.2f}".format)
    print(df[["ticker","price_date","close","volume","prev_volume","range_pct","range_expansion"]].to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# Scan 7 — Double Trouble
# ---------------------------------------------------------------------------

_DOUBLE_TROUBLE_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
        MIN(p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                         ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_252d,
        AVG(p.volume) OVER (PARTITION BY p.ticker ORDER BY p.date
                            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS avg_vol_3d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-400 days')
)
SELECT w.ticker, w.date AS price_date, w.open, w.close, w.high, w.low, w.volume,
    i.ma20, i.ma50, i.ma200, i.vol_avg30,
    ROUND(w.close / w.low_252d, 2) AS close_vs_52wk_low,
    ROUND((w.close - w.prev_close) / w.prev_close * 100, 2) AS change_pct,
    ROUND((w.high - w.low) / w.close * 100, 2) AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest ON w.date = latest.max_date
WHERE w.close >= 5
    AND w.close / w.low_252d >= 1.8
    AND w.avg_vol_3d >= 100000 AND i.vol_avg30 >= 500000
    AND w.close > i.ma50 AND i.ma50 > i.ma200
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
    rows = [(scan_date, r.ticker, r.price_date, r.open, r.close, r.high, r.low,
             int(r.volume), r.ma20, r.ma50, r.ma200, r.vol_avg30,
             r.close_vs_52wk_low, r.change_pct, r.range_pct)
            for r in df.itertuples(index=False)]
    conn.executemany(
        """INSERT OR REPLACE INTO double_trouble_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, close_vs_52wk_low, change_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "double_trouble_scan_results.csv")
    print(f"Double Trouble scan complete — {len(df)} stock(s) matched:")
    pd.set_option("display.float_format", "{:.2f}".format)
    print(df[["ticker","price_date","close","ma50","ma200","close_vs_52wk_low","change_pct"]].to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# Scan 8 — TI65
# ---------------------------------------------------------------------------

_TI65_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
        AVG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS avgc7,
        AVG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date
                           ROWS BETWEEN 64 PRECEDING AND CURRENT ROW) AS avgc65,
        AVG(p.volume) OVER (PARTITION BY p.ticker ORDER BY p.date
                            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS avg_vol_3d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-120 days')
)
SELECT w.ticker, w.date AS price_date, w.open, w.close, w.high, w.low, w.volume,
    i.ma50, i.ma200, i.vol_avg30,
    ROUND(w.avgc7,  4) AS avgc7,
    ROUND(w.avgc65, 4) AS avgc65,
    ROUND(w.avgc7 / w.avgc65, 4) AS ti65_ratio,
    ROUND((w.close - w.prev_close) / w.prev_close * 100, 2) AS change_pct,
    ROUND((w.high - w.low) / w.close * 100, 2) AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest ON w.date = latest.max_date
WHERE w.close >= 5
    AND w.avgc7 / w.avgc65 > 1.05
    AND w.avg_vol_3d >= 100000 AND i.vol_avg30 >= 500000
    AND w.close > i.ma50 AND i.ma50 > i.ma200
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
    rows = [(scan_date, r.ticker, r.price_date, r.open, r.close, r.high, r.low,
             int(r.volume), r.ma50, r.ma200, r.vol_avg30,
             r.avgc7, r.avgc65, r.ti65_ratio, r.change_pct, r.range_pct)
            for r in df.itertuples(index=False)]
    conn.executemany(
        """INSERT OR REPLACE INTO ti65_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma50, ma200, vol_avg30, avgc7, avgc65, ti65_ratio, change_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "ti65_scan_results.csv")
    print(f"TI65 scan complete — {len(df)} stock(s) matched:")
    pd.set_option("display.float_format", "{:.4f}".format)
    print(df[["ticker","price_date","close","ma50","avgc7","avgc65","ti65_ratio","change_pct"]].to_string(index=False))
    return df


# ---------------------------------------------------------------------------
# Scan 9 — Parabolic
# ---------------------------------------------------------------------------

_PARABOLIC_SCAN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT p.ticker, p.date, p.open, p.high, p.low, p.close, p.volume,
        LAG(p.close, 20) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_20d_ago,
        LAG(p.close,  5) OVER (PARTITION BY p.ticker ORDER BY p.date) AS close_5d_ago,
        MIN(p.low) OVER (PARTITION BY p.ticker ORDER BY p.date
                         ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS low_60d
    FROM prices p, latest
    WHERE p.date >= DATE(latest.max_date, '-90 days')
)
SELECT w.ticker, w.date AS price_date, w.open, w.close, w.high, w.low, w.volume,
    i.ma20, i.ma50, i.ma200, i.vol_avg30,
    ROUND((w.close - w.close_20d_ago) / w.close_20d_ago * 100, 2) AS ret_20d_pct,
    ROUND((w.close - w.close_5d_ago)  / w.close_5d_ago  * 100, 2) AS ret_5d_pct,
    ROUND((w.close - w.low_60d)       / w.low_60d        * 100, 2) AS rise_60d_pct,
    ROUND((w.close - i.ma50)          / i.ma50            * 100, 2) AS dist_ma50_pct,
    ROUND((w.high  - w.low)           / w.close           * 100, 2) AS range_pct
FROM windowed w
JOIN indicators i ON w.ticker = i.ticker AND w.date = i.date
JOIN latest ON w.date = latest.max_date
WHERE w.close >= 5
    AND w.close > i.ma20 AND w.close > i.ma50
    AND (w.close - i.ma50) / i.ma50 >= 0.50
    AND w.close_20d_ago IS NOT NULL
    AND (w.close - w.close_20d_ago) / w.close_20d_ago >= 0.50
    AND w.close_5d_ago IS NOT NULL AND w.close > w.close_5d_ago
    AND w.low_60d > 0 AND (w.close - w.low_60d) / w.low_60d >= 0.50
    AND w.volume >= 50000 AND i.vol_avg30 >= 50000
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
    rows = [(scan_date, r.ticker, r.price_date, r.open, r.close, r.high, r.low,
             int(r.volume), r.ma20, r.ma50, r.ma200, r.vol_avg30,
             r.ret_20d_pct, r.ret_5d_pct, r.rise_60d_pct, r.dist_ma50_pct, r.range_pct)
            for r in df.itertuples(index=False)]
    conn.executemany(
        """INSERT OR REPLACE INTO parabolic_scan_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, ret_20d_pct, ret_5d_pct,
            rise_60d_pct, dist_ma50_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    conn.commit()
    conn.close()
    _save_csv(df, scan_date, "parabolic_scan_results.csv")
    print(f"Parabolic scan complete — {len(df)} stock(s) matched:")
    pd.set_option("display.float_format", "{:.2f}".format)
    print(df[["ticker","price_date","close","ma50","ret_20d_pct","rise_60d_pct","dist_ma50_pct"]].to_string(index=False))
    return df


_MA_CROSS_DOWN_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date,
        p.open, p.close, p.high, p.low, p.volume,
        LAG(p.close,  1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
        LAG(i.ma20,   1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma20,
        LAG(i.ma50,   1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma50,
        LAG(i.ma200,  1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma200,
        i.ma20, i.ma50, i.ma200, i.vol_avg30
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date, latest
    WHERE p.date >= DATE(latest.max_date, '-10 days')
)
SELECT
    w.ticker,
    w.date          AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    w.ma20,
    w.ma50,
    w.ma200,
    w.vol_avg30,
    ROUND((w.close - w.open)  / w.open  * 100, 2)  AS body_pct,
    ROUND((w.high  - w.low)   / w.close * 100, 2)  AS range_pct,
    CASE
        WHEN w.prev_close > w.prev_ma200 AND w.close < w.ma200 THEN 'MA200'
        WHEN w.prev_close > w.prev_ma50  AND w.close < w.ma50  THEN 'MA50'
        WHEN w.prev_close > w.prev_ma20  AND w.close < w.ma20  THEN 'MA20'
    END AS crossed_ma
FROM windowed w
JOIN latest ON w.date = latest.max_date
WHERE
    w.close >= 5
    AND w.close < w.open                                    -- red candle
    AND w.volume   >= 100000
    AND w.vol_avg30 >= 200000
    AND w.prev_close IS NOT NULL
    AND (w.high - w.low) / w.close < 0.01                  -- very narrow range (< 1% of price)
    AND (
        (w.prev_close > w.prev_ma20  AND w.close < w.ma20)
        OR (w.prev_close > w.prev_ma50  AND w.close < w.ma50)
        OR (w.prev_close > w.prev_ma200 AND w.close < w.ma200)
    )
ORDER BY crossed_ma DESC, w.ticker
"""


_MA_CROSS_UP_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date,
        p.open, p.close, p.high, p.low, p.volume,
        LAG(p.close,  1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
        LAG(i.ma20,   1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma20,
        LAG(i.ma50,   1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma50,
        LAG(i.ma200,  1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma200,
        i.ma20, i.ma50, i.ma200, i.vol_avg30
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date, latest
    WHERE p.date >= DATE(latest.max_date, '-10 days')
)
SELECT
    w.ticker,
    w.date          AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    w.ma20,
    w.ma50,
    w.ma200,
    w.vol_avg30,
    ROUND((w.close - w.open)  / w.open  * 100, 2)  AS body_pct,
    ROUND((w.high  - w.low)   / w.close * 100, 2)  AS range_pct,
    CASE
        WHEN w.prev_close < w.prev_ma200 AND w.close > w.ma200 THEN 'MA200'
        WHEN w.prev_close < w.prev_ma50  AND w.close > w.ma50  THEN 'MA50'
        WHEN w.prev_close < w.prev_ma20  AND w.close > w.ma20  THEN 'MA20'
    END AS crossed_ma
FROM windowed w
JOIN latest ON w.date = latest.max_date
WHERE
    w.close >= 5
    AND w.close > w.open                                    -- green candle
    AND w.volume   >= 100000
    AND w.vol_avg30 >= 200000
    AND w.prev_close IS NOT NULL
    AND (w.high - w.low) / w.close < 0.015             -- narrow range (< 1.5% of price)
    AND (
        (w.prev_close < w.prev_ma20  AND w.close > w.ma20)
        OR (w.prev_close < w.prev_ma50  AND w.close > w.ma50)
        OR (w.prev_close < w.prev_ma200 AND w.close > w.ma200)
    )
ORDER BY crossed_ma DESC, w.ticker
"""


def run_ma_cross_up_scan() -> pd.DataFrame:
    """
    Scan for narrow-range green candles that closed above a MA they were previously below.
    Detects crosses above MA20, MA50, and MA200.
    Results saved to ma_cross_up_results and directly added to ActionList.txt.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_MA_CROSS_UP_SQL, conn)

    if df.empty:
        print("MA cross-up scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM ma_cross_up_results")

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
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.body_pct,
            row.range_pct,
            row.crossed_ma,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO ma_cross_up_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, body_pct, range_pct, crossed_ma)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "ma_cross_up_results.csv")
    print(f"MA cross-up scan complete — {len(df)} stock(s) matched "
          f"(saved to ma_cross_up_results for {scan_date}):")
    _print_ma_cross_down_results(df)   # same column layout
    return df


def run_ma_cross_down_scan() -> pd.DataFrame:
    """
    Scan for red candles that closed below a moving average they were previously above.
    Detects crosses below MA20, MA50, and MA200.
    Results saved to ma_cross_down_results and directly added to ActionList.txt.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_MA_CROSS_DOWN_SQL, conn)

    if df.empty:
        print("MA cross-down scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM ma_cross_down_results")

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
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.body_pct,
            row.range_pct,
            row.crossed_ma,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO ma_cross_down_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, body_pct, range_pct, crossed_ma)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "ma_cross_down_results.csv")
    print(f"MA cross-down scan complete — {len(df)} stock(s) matched "
          f"(saved to ma_cross_down_results for {scan_date}):")
    _print_ma_cross_down_results(df)
    return df


_NEAR_MA50_BELOW_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
)
SELECT
    p.ticker,
    p.date          AS price_date,
    p.open,
    p.close,
    p.high,
    p.low,
    p.volume,
    i.ma20,
    i.ma50,
    i.ma200,
    i.vol_avg30,
    ROUND((i.ma50 - p.close) / i.ma50 * 100, 2) AS pct_below_ma50,
    ROUND((p.high - p.low)   / p.close * 100, 2) AS range_pct
FROM prices p
JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
JOIN latest       ON p.date = latest.max_date
WHERE
    p.close >= 5
    AND p.close < i.ma50                    -- price is below MA50
    AND p.close >= i.ma50 * 0.98        -- but within 2% below
    AND p.volume   >= 100000
    AND i.vol_avg30 >= 200000
ORDER BY pct_below_ma50 ASC            -- closest to MA50 first
"""


def run_near_ma50_below_scan() -> pd.DataFrame:
    """
    Scan for stocks trading just below their 50-day MA (within 2%).
    Condition: close < ma50 AND close >= ma50 * 0.98.
    Results saved to near_ma50_below_results and force-included in ActionList.txt.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_NEAR_MA50_BELOW_SQL, conn)

    if df.empty:
        print("Near-MA50-below scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM near_ma50_below_results")

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
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.pct_below_ma50,
            row.range_pct,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO near_ma50_below_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, pct_below_ma50, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "near_ma50_below_results.csv")
    print(f"Near-MA50-below scan complete — {len(df)} stock(s) within 2% below MA50 "
          f"(saved to near_ma50_below_results for {scan_date}):")
    _print_near_ma50_below_results(df)
    return df


_MA50_CROSS_UP_SQL = """
WITH latest AS (
    SELECT MAX(p.date) AS max_date
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
),
windowed AS (
    SELECT
        p.ticker, p.date,
        p.open, p.close, p.high, p.low, p.volume,
        LAG(p.close, 1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
        LAG(i.ma50,  1) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_ma50,
        i.ma20, i.ma50, i.ma200, i.vol_avg30
    FROM prices p
    JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date, latest
    WHERE p.date >= DATE(latest.max_date, '-10 days')
)
SELECT
    w.ticker,
    w.date          AS price_date,
    w.open,
    w.close,
    w.high,
    w.low,
    w.volume,
    w.ma20,
    w.ma50,
    w.ma200,
    w.vol_avg30,
    ROUND((w.close - w.prev_close) / w.prev_close * 100, 2) AS change_pct,
    ROUND((w.high  - w.low)        / w.close       * 100, 2) AS range_pct
FROM windowed w
JOIN latest ON w.date = latest.max_date
WHERE
    w.close >= 5
    AND w.prev_close < w.prev_ma50          -- was below MA50 yesterday
    AND w.close  > w.ma50               -- closed above MA50 today
    AND w.volume   >= 100000
    AND w.vol_avg30 >= 200000
    AND w.prev_close IS NOT NULL
    AND w.prev_ma50  IS NOT NULL
ORDER BY w.ticker
"""


def run_ma50_cross_up_scan() -> pd.DataFrame:
    """
    Scan for stocks whose close crossed above their 50-day MA today
    (prev_close < prev_ma50 AND close > ma50).
    No candle-shape filter — any crossover day qualifies.
    Results saved to ma50_cross_up_results and force-included in ActionList.txt.
    """
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    df = pd.read_sql_query(_MA50_CROSS_UP_SQL, conn)

    if df.empty:
        print("MA50 cross-up scan complete — no stocks matched.")
        conn.close()
        return df

    scan_date = datetime.date.today().strftime("%Y-%m-%d")

    conn.execute("DELETE FROM ma50_cross_up_results")

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
            row.ma20,
            row.ma50,
            row.ma200,
            row.vol_avg30,
            row.change_pct,
            row.range_pct,
        )
        for row in df.itertuples(index=False)
    ]

    conn.executemany(
        """INSERT OR REPLACE INTO ma50_cross_up_results
           (scan_date, ticker, price_date, open, close, high, low, volume,
            ma20, ma50, ma200, vol_avg30, change_pct, range_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()

    _save_csv(df, scan_date, "ma50_cross_up_results.csv")
    print(f"MA50 cross-up scan complete — {len(df)} stock(s) crossed above MA50 "
          f"(saved to ma50_cross_up_results for {scan_date}):")
    _print_ma50_cross_up_results(df)
    return df


def create_action_list(tickers: list, force_include: list = None) -> list:
    """
    From the given ticker list, return those whose latest day is a narrow range
    (high-low)/close < 1.5%) OR an inside bar (high < prev_high AND low > prev_low).
    Writes matching tickers to ActionList.txt and returns the list.
    """
    if not tickers:
        return []

    placeholders = ",".join("?" * len(tickers))
    sql = f"""
    WITH latest AS (
        SELECT MAX(date) AS max_date FROM prices
    ),
    recent AS (
        SELECT p.ticker, p.date,
               LAG(p.high) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_high,
               LAG(p.low)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_low
        FROM prices p, latest
        WHERE p.ticker IN ({placeholders})
          AND p.date >= DATE(latest.max_date, '-10 days')
    )
    SELECT p.ticker
    FROM prices p
    JOIN recent r ON p.ticker = r.ticker AND p.date = r.date
    JOIN latest   ON p.date = latest.max_date
    WHERE p.ticker IN ({placeholders})
      AND r.prev_high IS NOT NULL
      AND (
          (p.high < r.prev_high AND p.low > r.prev_low)
          OR (p.high - p.low) / p.close < 0.015
      )
    ORDER BY p.ticker
    """

    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.execute(sql, tickers + tickers)
    action_tickers = [row[0] for row in cur.fetchall()]
    conn.close()

    # Merge in any force-included tickers (e.g. MA cross-down — direct signals)
    if force_include:
        action_tickers = sorted(set(action_tickers) | set(force_include))

    action_path = os.path.join(os.path.dirname(__file__), "ActionList.txt")
    with open(action_path, "w") as f:
        f.write(f"# ActionList (narrow range / inside bar / MA cross-up / MA50 cross-up / near MA50 below) — {datetime.date.today()}\n")
        for ticker in action_tickers:
            f.write(f"{ticker}\n")
    print(f"  ActionList.txt updated: {len(action_tickers)} ticker(s)")
    return action_tickers


def _save_csv(df: pd.DataFrame, scan_date: str, filename: str):
    folder = os.path.join("charts", scan_date)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    df.to_csv(path, index=False)
    print(f"  CSV saved to {path}")


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


def _print_ibd_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 140)
    cols = ["ticker", "price_date", "close", "ma20", "ma50", "ma200",
            "vol_avg30", "dist_ma50_pct", "dist_ma200_pct", "range_pct"]
    print(df[cols].to_string(index=False))


def _print_ma_cross_down_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)
    cols = ["ticker", "price_date", "open", "close", "high", "low", "volume",
            "ma20", "ma50", "ma200", "vol_avg30", "body_pct", "range_pct", "crossed_ma"]
    print(df[cols].to_string(index=False))


def _print_near_ma50_below_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)
    cols = ["ticker", "price_date", "open", "close", "high", "low", "volume",
            "ma20", "ma50", "ma200", "vol_avg30", "pct_below_ma50", "range_pct"]
    print(df[cols].to_string(index=False))


def _print_ma50_cross_up_results(df: pd.DataFrame):
    pd.set_option("display.float_format", "{:.2f}".format)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 160)
    cols = ["ticker", "price_date", "open", "close", "high", "low", "volume",
            "ma20", "ma50", "ma200", "vol_avg30", "change_pct", "range_pct"]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-display", action="store_true",
                        help="Save charts to files only, do not open GUI windows")
    args = parser.parse_args()

    database.init_db()
    df_inside          = run_scan()
    df_doji            = run_doji_scan()
    df_red_candle      = run_red_candle_scan()
    df_ibd             = run_ibd_scan()
    df_momentum        = run_momentum_scan()
    df_stockbee        = run_stockbee_scan()
    df_double_trouble  = run_double_trouble_scan()
    df_ti65            = run_ti65_scan()
    df_parabolic       = run_parabolic_scan()
    df_ma_cross_up     = run_ma_cross_up_scan()
    df_ma_cross_down   = run_ma_cross_down_scan()
    df_ma50_cross_up   = run_ma50_cross_up_scan()
    df_near_ma50_below = run_near_ma50_below_scan()

    inside_tickers          = df_inside["ticker"].tolist()          if not df_inside.empty          else []
    doji_tickers            = df_doji["ticker"].tolist()            if not df_doji.empty            else []
    red_candle_tickers      = df_red_candle["ticker"].tolist()      if not df_red_candle.empty      else []
    ibd_tickers             = df_ibd["ticker"].tolist()             if not df_ibd.empty             else []
    momentum_tickers        = df_momentum["ticker"].tolist()        if not df_momentum.empty        else []
    stockbee_tickers        = df_stockbee["ticker"].tolist()        if not df_stockbee.empty        else []
    double_trouble_tickers  = df_double_trouble["ticker"].tolist()  if not df_double_trouble.empty  else []
    ti65_tickers            = df_ti65["ticker"].tolist()            if not df_ti65.empty            else []
    parabolic_tickers       = df_parabolic["ticker"].tolist()       if not df_parabolic.empty       else []
    ma_cross_up_tickers     = df_ma_cross_up["ticker"].tolist()     if not df_ma_cross_up.empty     else []
    ma_cross_down_tickers   = df_ma_cross_down["ticker"].tolist()   if not df_ma_cross_down.empty   else []
    ma50_cross_up_tickers   = df_ma50_cross_up["ticker"].tolist()   if not df_ma50_cross_up.empty   else []
    near_ma50_below_tickers = df_near_ma50_below["ticker"].tolist() if not df_near_ma50_below.empty else []

    # Load custom watchlist (always included)
    custom_path = os.path.join(os.path.dirname(__file__), "custom_watchlist.txt")
    custom_tickers = []
    if os.path.exists(custom_path):
        with open(custom_path) as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    custom_tickers.append(t)
        if custom_tickers:
            print(f"  custom_watchlist.txt: {len(custom_tickers)} ticker(s) force-included")

    # Union all scan results into a single ActionList.txt
    all_tickers = sorted(set(
        inside_tickers + doji_tickers + red_candle_tickers
        + ibd_tickers + momentum_tickers + stockbee_tickers
        + double_trouble_tickers + ti65_tickers + parabolic_tickers
        + ma_cross_up_tickers + ma_cross_down_tickers
        + ma50_cross_up_tickers + near_ma50_below_tickers
        + custom_tickers
    ))
    action_path = os.path.join(os.path.dirname(__file__), "ActionList.txt")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(f"# ActionList generated by scanner.py on {datetime.date.today()}\n")
        for ticker in all_tickers:
            f.write(f"{ticker}\n")
    print(f"  ActionList.txt updated: {len(all_tickers)} ticker(s)")

    # Generate FilteredActionList.txt from setup-focused scans only
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.execute("""
        SELECT DISTINCT ticker FROM scan_results
        UNION
        SELECT DISTINCT ticker FROM doji_scan_results
        UNION
        SELECT DISTINCT ticker FROM red_candle_scan_results
        UNION
        SELECT DISTINCT ticker FROM ma_cross_up_results
        UNION
        SELECT DISTINCT ticker FROM ma_cross_down_results
        UNION
        SELECT DISTINCT ticker FROM ma50_cross_up_results
        UNION
        SELECT DISTINCT ticker FROM near_ma50_below_results
        ORDER BY ticker
    """)
    filtered_tickers = [r[0] for r in cur.fetchall()]
    conn.close()
    filtered_path = os.path.join(os.path.dirname(__file__), "FilteredActionList.txt")
    with open(filtered_path, "w", encoding="utf-8") as f:
        f.write(f"# FilteredActionList (Inside Bar / Doji-NR / Red Candle / MA Cross-Up / MA Cross-Down / MA50 Cross-Up / Near-MA50-Below) — {datetime.date.today()}\n")
        for ticker in filtered_tickers:
            f.write(f"{ticker}\n")
    print(f"  FilteredActionList.txt updated: {len(filtered_tickers)} ticker(s)")

    # Generate MAInsideRange.txt — tickers where any MA lies within the candle's high-low
    conn = sqlite3.connect(database.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.execute("""
        WITH latest AS (
            SELECT MAX(p.date) AS max_date
            FROM prices p
            JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
        ),
        filtered AS (
            SELECT DISTINCT ticker FROM scan_results
            UNION SELECT DISTINCT ticker FROM doji_scan_results
            UNION SELECT DISTINCT ticker FROM red_candle_scan_results
            UNION SELECT DISTINCT ticker FROM ma_cross_up_results
            UNION SELECT DISTINCT ticker FROM ma_cross_down_results
            UNION SELECT DISTINCT ticker FROM ma50_cross_up_results
            UNION SELECT DISTINCT ticker FROM near_ma50_below_results
        )
        SELECT p.ticker
        FROM prices p
        JOIN indicators i ON p.ticker = i.ticker AND p.date = i.date
        JOIN latest ON p.date = latest.max_date
        JOIN filtered f ON p.ticker = f.ticker
        WHERE (i.ma10  BETWEEN p.low AND p.high)
           OR (i.ma20  BETWEEN p.low AND p.high)
           OR (i.ma50  BETWEEN p.low AND p.high)
           OR (i.ma200 BETWEEN p.low AND p.high)
        ORDER BY p.ticker
    """)
    ma_inside_tickers = [r[0] for r in cur.fetchall()]
    conn.close()
    ma_inside_path = os.path.join(os.path.dirname(__file__), "MAInsideRange.txt")
    with open(ma_inside_path, "w", encoding="utf-8") as f:
        f.write(f"# MAInsideRange — MA lies within candle high-low — {datetime.date.today()}\n")
        for ticker in ma_inside_tickers:
            f.write(f"{ticker}\n")
    print(f"  MAInsideRange.txt updated: {len(ma_inside_tickers)} ticker(s)")

    chart.plot_results(inside_tickers, doji_tickers, red_candle_tickers,
                       ibd_tickers=ibd_tickers,
                       momentum_tickers=momentum_tickers,
                       stockbee_tickers=stockbee_tickers,
                       double_trouble_tickers=double_trouble_tickers,
                       ti65_tickers=ti65_tickers,
                       parabolic_tickers=parabolic_tickers,
                       show=not args.no_display)
