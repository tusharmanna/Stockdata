"""
Backfill recent data for tickers that are behind the latest date in the DB.

Finds every ticker whose most recent price row is older than the DB-wide
latest date, then re-downloads the last 14 calendar days (~7 trading days)
for all of them, and recomputes indicators when done.

Usage:
    python backfill_recent.py
"""

import datetime
import sqlite3
import database
import indicators
from downloader import _process_batch, BATCH_SIZE


def get_stale_tickers(conn: sqlite3.Connection, latest_date: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT ticker
        FROM prices
        GROUP BY ticker
        HAVING MAX(date) < ?
        ORDER BY ticker
        """,
        (latest_date,),
    ).fetchall()
    return [r[0] for r in rows]


def main():
    database.init_db()

    conn = sqlite3.connect(database.DB_PATH)
    latest_date = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    if not latest_date:
        print("No data in database.")
        conn.close()
        return

    stale = get_stale_tickers(conn, latest_date)
    conn.close()

    if not stale:
        print("All tickers are up to date.")
        return

    failed = database.get_failed_tickers()
    before = len(stale)
    stale = [t for t in stale if t not in failed]
    if before - len(stale):
        print(f"Skipping {before - len(stale)} known failed/delisted tickers")

    if not stale:
        print("All remaining tickers are known failed/delisted.")
        return

    print(f"Latest date in DB : {latest_date}")
    print(f"Tickers to backfill: {len(stale)}")

    end   = datetime.date.today() + datetime.timedelta(days=1)
    start = datetime.date.today() - datetime.timedelta(days=14)
    start_str = start.strftime("%Y-%m-%d")
    end_str   = end.strftime("%Y-%m-%d")
    print(f"Date range        : {start_str} -> {end_str}\n")

    total = len(stale)
    num_batches = (total - 1) // BATCH_SIZE + 1
    saved_total = skipped_total = 0
    all_skipped: list[str] = []

    for i in range(0, total, BATCH_SIZE):
        batch = stale[i:i + BATCH_SIZE]
        saved, skipped = _process_batch(batch, start_str, end_str)
        saved_total += len(saved)
        skipped_total += len(skipped)
        all_skipped.extend(skipped)
        completed = i // BATCH_SIZE + 1
        done = min((i + BATCH_SIZE), total)
        print(f"  {done}/{total} done — {len(saved)} saved, {len(skipped)} skipped")

    if all_skipped:
        print(f"  Marking {len(all_skipped)} tickers as failed/delisted (no data in backfill window)")
        database.mark_failed_many(all_skipped, "no_data_backfill")

    print(f"\nBackfill complete: {saved_total} updated, {skipped_total} marked as failed/delisted")

    print("\nRecomputing indicators...")
    indicators.recompute_all()
    print("Done.")


if __name__ == "__main__":
    main()
