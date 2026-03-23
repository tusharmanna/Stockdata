"""
SQLite storage layer for stock OHLCV data and computed indicators.
"""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "stockdata.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
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


def get_all_tickers() -> list[str]:
    """Return list of distinct tickers in the prices table."""
    conn = _connect()
    cur = conn.execute("SELECT DISTINCT ticker FROM prices ORDER BY ticker")
    tickers = [row[0] for row in cur.fetchall()]
    conn.close()
    return tickers


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
