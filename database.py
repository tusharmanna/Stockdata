"""
SQLite storage layer for stock OHLCV data and computed indicators.
"""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "stockdata.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prices (
            ticker   TEXT    NOT NULL,
            date     TEXT    NOT NULL,
            open     REAL,
            high     REAL,
            low      REAL,
            close    REAL,
            volume   INTEGER,
            PRIMARY KEY (ticker, date)
        );

        CREATE TABLE IF NOT EXISTS indicators (
            ticker    TEXT  NOT NULL,
            date      TEXT  NOT NULL,
            ma10      REAL,
            ma20      REAL,
            ma50      REAL,
            ma200     REAL,
            vol_avg30 REAL,
            PRIMARY KEY (ticker, date)
        );

        CREATE TABLE IF NOT EXISTS scan_results (
            scan_date  TEXT NOT NULL,
            ticker     TEXT NOT NULL,
            price_date TEXT NOT NULL,
            close      REAL,
            high       REAL,
            low        REAL,
            volume     INTEGER,
            ma10       REAL,
            ma20       REAL,
            ma50       REAL,
            ma200      REAL,
            vol_avg30  REAL,
            prev_high  REAL,
            prev_low   REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS doji_scan_results (
            scan_date  TEXT NOT NULL,
            ticker     TEXT NOT NULL,
            price_date TEXT,
            open       REAL,
            close      REAL,
            high       REAL,
            low        REAL,
            volume     INTEGER,
            ma10       REAL,
            ma20       REAL,
            ma50       REAL,
            ma200      REAL,
            vol_avg30  REAL,
            body_pct   REAL,
            range_pct  REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS red_candle_scan_results (
            scan_date  TEXT NOT NULL,
            ticker     TEXT NOT NULL,
            price_date TEXT,
            open       REAL,
            close      REAL,
            high       REAL,
            low        REAL,
            volume     INTEGER,
            ma20       REAL,
            ma50       REAL,
            ma200      REAL,
            vol_avg30  REAL,
            body_pct   REAL,
            range_pct  REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS stockbee_scan_results (
            scan_date        TEXT NOT NULL,
            ticker           TEXT NOT NULL,
            price_date       TEXT,
            open             REAL,
            close            REAL,
            high             REAL,
            low              REAL,
            volume           INTEGER,
            prev_volume      INTEGER,
            ma20             REAL,
            ma50             REAL,
            ma200            REAL,
            vol_avg30        REAL,
            range_pct        REAL,
            range_expansion  REAL,
            close_vs_high_pct REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ibd_scan_results (
            scan_date      TEXT NOT NULL,
            ticker         TEXT NOT NULL,
            price_date     TEXT,
            open           REAL,
            close          REAL,
            high           REAL,
            low            REAL,
            volume         INTEGER,
            ma20           REAL,
            ma50           REAL,
            ma200          REAL,
            vol_avg30      REAL,
            dist_ma50_pct  REAL,
            dist_ma200_pct REAL,
            range_pct      REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS momentum_scan_results (
            scan_date     TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            price_date    TEXT,
            open          REAL,
            close         REAL,
            high          REAL,
            low           REAL,
            volume        INTEGER,
            ma20          REAL,
            ma50          REAL,
            ma200         REAL,
            vol_avg30     REAL,
            dist_ma20_pct REAL,
            dist_ma50_pct REAL,
            ret_20d_pct   REAL,
            range_pct     REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS double_trouble_scan_results (
            scan_date          TEXT NOT NULL,
            ticker             TEXT NOT NULL,
            price_date         TEXT,
            open               REAL,
            close              REAL,
            high               REAL,
            low                REAL,
            volume             INTEGER,
            ma20               REAL,
            ma50               REAL,
            ma200              REAL,
            vol_avg30          REAL,
            close_vs_52wk_low  REAL,
            change_pct         REAL,
            range_pct          REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ti65_scan_results (
            scan_date   TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            price_date  TEXT,
            open        REAL,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      INTEGER,
            ma50        REAL,
            ma200       REAL,
            vol_avg30   REAL,
            avgc7       REAL,
            avgc65      REAL,
            ti65_ratio  REAL,
            change_pct  REAL,
            range_pct   REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ma_cross_up_results (
            scan_date   TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            price_date  TEXT,
            open        REAL,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      INTEGER,
            ma20        REAL,
            ma50        REAL,
            ma200       REAL,
            vol_avg30   REAL,
            body_pct    REAL,
            range_pct   REAL,
            crossed_ma  TEXT,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ma_cross_down_results (
            scan_date   TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            price_date  TEXT,
            open        REAL,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      INTEGER,
            ma20        REAL,
            ma50        REAL,
            ma200       REAL,
            vol_avg30   REAL,
            body_pct    REAL,
            range_pct   REAL,
            crossed_ma  TEXT,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS parabolic_scan_results (
            scan_date     TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            price_date    TEXT,
            open          REAL,
            close         REAL,
            high          REAL,
            low           REAL,
            volume        INTEGER,
            ma20          REAL,
            ma50          REAL,
            ma200         REAL,
            vol_avg30     REAL,
            ret_20d_pct   REAL,
            ret_5d_pct    REAL,
            rise_60d_pct  REAL,
            dist_ma50_pct REAL,
            range_pct     REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS near_ma50_below_results (
            scan_date      TEXT NOT NULL,
            ticker         TEXT NOT NULL,
            price_date     TEXT,
            open           REAL,
            close          REAL,
            high           REAL,
            low            REAL,
            volume         INTEGER,
            ma20           REAL,
            ma50           REAL,
            ma200          REAL,
            vol_avg30      REAL,
            pct_below_ma50 REAL,
            range_pct      REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ma50_cross_up_results (
            scan_date   TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            price_date  TEXT,
            open        REAL,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      INTEGER,
            ma20        REAL,
            ma50        REAL,
            ma200       REAL,
            vol_avg30   REAL,
            change_pct  REAL,
            range_pct   REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS higher_lows_scan_results (
            scan_date   TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            price_date  TEXT,
            close       REAL,
            high        REAL,
            low         REAL,
            volume      INTEGER,
            ma20        REAL,
            ma50        REAL,
            ma200       REAL,
            vol_avg30   REAL,
            low_10d     REAL,
            low_20d     REAL,
            high_10d    REAL,
            high_20d    REAL,
            pattern     TEXT,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS ma_pullback_scan_results (
            scan_date      TEXT NOT NULL,
            ticker         TEXT NOT NULL,
            price_date     TEXT,
            close          REAL,
            high           REAL,
            low            REAL,
            volume         INTEGER,
            ma20           REAL,
            ma50           REAL,
            ma200          REAL,
            vol_avg30      REAL,
            pct_from_ma20  REAL,
            pct_from_ma50  REAL,
            support_ma     TEXT,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS large_volume_scan_results (
            scan_date      TEXT NOT NULL,
            ticker         TEXT NOT NULL,
            price_date     TEXT,
            close          REAL,
            high           REAL,
            low            REAL,
            volume         INTEGER,
            ma20           REAL,
            ma50           REAL,
            ma200          REAL,
            vol_avg30      REAL,
            vol_avg_15d    REAL,
            volume_ratio   REAL,
            PRIMARY KEY (scan_date, ticker)
        );

        CREATE TABLE IF NOT EXISTS failed_tickers (
            ticker    TEXT PRIMARY KEY,
            fail_date TEXT NOT NULL,
            reason    TEXT
        );
    """)
    conn.commit()
    conn.close()


def upsert_prices(ticker: str, df: pd.DataFrame):
    """Insert or replace OHLCV rows for a ticker from a DataFrame."""
    if df is None or df.empty:
        return
    conn = _connect()
    rows = []
    for idx, row in df.iterrows():
        date_str = str(idx)[:10]
        try:
            rows.append((
                ticker,
                date_str,
                round(float(row["Open"]), 4),
                round(float(row["High"]), 4),
                round(float(row["Low"]), 4),
                round(float(row["Close"]), 4),
                int(row["Volume"]),
            ))
        except (KeyError, ValueError):
            pass
    conn.executemany(
        "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def upsert_indicators(ticker: str, df: pd.DataFrame):
    """Insert or replace indicator rows for a ticker from a DataFrame."""
    if df is None or df.empty:
        return
    conn = _connect()
    rows = []
    for _, row in df.iterrows():
        rows.append((
            ticker,
            str(row["date"]),
            row.get("ma10"),
            row.get("ma20"),
            row.get("ma50"),
            row.get("ma200"),
            row.get("vol_avg30"),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO indicators (ticker, date, ma10, ma20, ma50, ma200, vol_avg30) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_prices(ticker: str) -> pd.DataFrame:
    """Return all price rows for a ticker as a DataFrame sorted by date."""
    conn = _connect()
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date",
        conn,
        params=(ticker,),
    )
    conn.close()
    return df


def get_all_prices_bulk() -> dict:
    """Return all prices grouped by ticker as {ticker: DataFrame}. Much faster than per-ticker queries."""
    conn = _connect()
    df = pd.read_sql_query(
        "SELECT ticker, date, open, high, low, close, volume FROM prices ORDER BY ticker, date",
        conn,
    )
    conn.close()
    return {ticker: group.reset_index(drop=True) for ticker, group in df.groupby("ticker")}


def upsert_indicators_bulk(rows: list):
    """Insert or replace many indicator rows in a single transaction."""
    if not rows:
        return
    conn = _connect()
    conn.executemany(
        "INSERT OR REPLACE INTO indicators (ticker, date, ma10, ma20, ma50, ma200, vol_avg30) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def get_all_tickers() -> list[str]:
    """Return list of distinct tickers in the prices table."""
    conn = _connect()
    cur = conn.execute("SELECT DISTINCT ticker FROM prices ORDER BY ticker")
    tickers = [row[0] for row in cur.fetchall()]
    conn.close()
    return tickers


def mark_failed(ticker: str, reason: str):
    """Record a ticker as failed/delisted so future runs skip it."""
    mark_failed_many([ticker], reason)


def mark_failed_many(tickers: list, reason: str):
    """Record multiple tickers as failed in a single transaction."""
    import datetime
    if not tickers:
        return
    today = datetime.date.today().strftime("%Y-%m-%d")
    conn = _connect()
    conn.executemany(
        "INSERT OR REPLACE INTO failed_tickers (ticker, fail_date, reason) VALUES (?, ?, ?)",
        [(t, today, reason) for t in tickers],
    )
    conn.commit()
    conn.close()


def get_failed_tickers() -> set:
    """Return the set of tickers marked as failed."""
    conn = _connect()
    cur = conn.execute("SELECT ticker FROM failed_tickers")
    result = {row[0] for row in cur.fetchall()}
    conn.close()
    return result


def has_date(ticker: str, date_str: str) -> bool:
    """Return True if the prices table already has a row for (ticker, date)."""
    conn = _connect()
    cur = conn.execute(
        "SELECT 1 FROM prices WHERE ticker=? AND date=? LIMIT 1",
        (ticker, date_str),
    )
    found = cur.fetchone() is not None
    conn.close()
    return found
