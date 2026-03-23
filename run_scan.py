"""
Run main.py then scanner.py, then print all tickers from scan_results space-separated.
"""

import subprocess
import sys
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run(script):
    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, script)],
        cwd=BASE_DIR,
    )
    if result.returncode != 0:
        print(f"\n[ERROR] {script} exited with code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    run("main.py")
    run("scanner.py")

    db_path = os.path.join(BASE_DIR, "stockdata.db")
    conn = sqlite3.connect(db_path)
    tickers = [row[0] for row in conn.execute(
        "SELECT ticker FROM scan_results ORDER BY ticker"
    ).fetchall()]
    doji_tickers = [row[0] for row in conn.execute(
        "SELECT ticker FROM doji_scan_results ORDER BY ticker"
    ).fetchall()]
    conn.close()

    if tickers:
        print("\nInside bar results: " + " ".join(tickers))
    else:
        print("\nNo tickers matched the inside bar criteria.")

    if doji_tickers:
        print("Doji/NR results:    " + " ".join(doji_tickers))
    else:
        print("No tickers matched the doji/NR criteria.")
