#!/usr/bin/env python3
"""
Sync account_transactions.json to signals/account_data.js
Fetches live prices from yfinance so the dashboard always shows current values.
Run this after modifying account_transactions.json to update the dashboard.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf


def _fetch_price(ticker: str) -> float:
    """Return the latest closing price for ticker, or 0.0 on failure."""
    try:
        data = yf.download(ticker, period="5d", progress=False, auto_adjust=True)
        if data is None or data.empty:
            return 0.0
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return float(data["Close"].dropna().iloc[-1])
    except Exception:
        return 0.0


def _latest_signal(signals_dir: Path) -> dict:
    """Read the most recent row from tushar_v2_history.csv. Returns {} on failure."""
    try:
        csv = signals_dir / "tushar_v2_history.csv"
        if not csv.exists():
            return {}
        df = pd.read_csv(csv, dtype={"date": str})
        row = df.sort_values("date").iloc[-1]
        return {
            "date":         str(row["date"]),
            "regime":       str(row["regime"]),
            "exposure":     round(float(row["exposure"]), 2),
            "exposure_pct": round(float(row["exposure"]) * 100, 1),
            "tqqq_vol_pct": round(float(row["tqqq_vol"]) * 100, 1),
            "pcthi":        round(float(row["pcthi"]), 1),
        }
    except Exception:
        return {}


def sync_account_data():
    """Generate account_data.js from account_transactions.json with live prices."""
    accounts_file = Path(__file__).parent / "account_transactions.json"
    data = json.loads(accounts_file.read_text())

    signals_dir = Path(__file__).parent / "signals"
    signals_dir.mkdir(exist_ok=True)

    # Fetch live prices for each unique ETF
    etfs = {a["etf"] for a in data.get("accounts", []) if "etf" in a}
    prices = {etf: _fetch_price(etf) for etf in etfs}

    # Inject live price into each account
    for account in data.get("accounts", []):
        etf = account.get("etf")
        if etf and prices.get(etf, 0.0) > 0:
            account["current_price"] = round(prices[etf], 2)

    # Embed latest v2 signal so the dashboard can auto-set target exposure
    sig = _latest_signal(signals_dir)
    if sig:
        data["latest_signal"] = sig

    js_content = (
        "// Auto-generated account data\n"
        "// Source: account_transactions.json\n"
        f"// Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"window.ACCOUNT_DATA = {json.dumps(data, indent=2)};\n"
    )

    out = signals_dir / "account_data.js"
    out.write_text(js_content)

    for etf, price in prices.items():
        print(f"  {etf}: ${price:.2f}")
    if sig:
        print(f"  Signal ({sig['date']}): {sig['regime']} {sig['exposure_pct']}% exposure")
    print(f"Synced account_transactions.json -> {out}")
    return True


if __name__ == "__main__":
    sync_account_data()
