"""
oliver_scan_all.py — Oliver Kell Price Cycle scan across all US stocks in stockdata.db

Reads OHLCV data from the local database (populated by main.py / downloader.py),
computes Oliver Kell indicators for every ticker, and outputs actionable signals
grouped by stage: BUY (Wedge Pop), ADD (EMA Crossback), SELL (Wedge Drop),
REDUCE (Extension 2+).

Prerequisites:
    python main.py          # download / update all stocks first

Usage:
    python oliver_scan_all.py                   # scan with default ADX>=15 filter
    python oliver_scan_all.py --adx-min 0       # no ADX filter
    python oliver_scan_all.py --adx-min 20      # stricter trend filter
    python oliver_scan_all.py --action BUY      # only BUY signals
    python oliver_scan_all.py --min-price 10    # skip stocks below $10
    python oliver_scan_all.py --min-rs 0        # only show market leaders
    python oliver_scan_all.py --workers 16      # more parallel threads
"""

import argparse
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from oliver_stock_strategy import (
    compute_indicators,
    compute_extension_count,
    detect_stage,
    relative_strength,
    market_regime,
    _load,
    REGIME_TICKER,
    ADX_TREND_MIN,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH      = Path("stockdata.db")
DEFAULT_ADX  = 15.0
MIN_PRICE    = 5.0
MIN_AVG_VOL  = 200_000   # 200k avg daily volume minimum
MIN_BARS     = 100       # need enough history for reliable EMAs
MAX_WORKERS  = 12


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_tickers(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    # Only tickers active in the last 5 calendar days, not in failed list
    cur.execute("""
        SELECT DISTINCT ticker FROM prices
        WHERE date >= (SELECT DATE(MAX(date), '-5 days') FROM prices)
          AND ticker NOT IN (SELECT ticker FROM failed_tickers)
        ORDER BY ticker
    """)
    tickers = [r[0] for r in cur.fetchall()]
    conn.close()
    return tickers


def load_price_df(db_path: Path, ticker: str) -> pd.DataFrame | None:
    conn = sqlite3.connect(db_path)
    df   = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume "
        "FROM prices WHERE ticker = ? ORDER BY date",
        conn, params=(ticker,),
    )
    conn.close()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.index.name = "date"
    return df


# ---------------------------------------------------------------------------
# Per-ticker processing
# ---------------------------------------------------------------------------

def scan_ticker(ticker: str, db_path: Path, qqq_ind: pd.DataFrame,
                adx_min: float, min_price: float, min_vol: float,
                rs_min: float = 0.0, high_52w_max_pct: float = 0.25) -> dict | None:
    try:
        df = load_price_df(db_path, ticker)
        if df is None or len(df) < MIN_BARS:
            return None

        close   = float(df["close"].iloc[-1])
        avg_vol = float(df["volume"].rolling(20, min_periods=5).mean().iloc[-1])
        if close < min_price or avg_vol < min_vol or np.isnan(close):
            return None

        df_ind  = compute_indicators(df)
        ext_cnt = compute_extension_count(df_ind)
        result  = detect_stage(df_ind, ext_cnt)

        rs       = relative_strength(df_ind, qqq_ind) if not qqq_ind.empty else None
        row      = df_ind.iloc[-1]
        stop     = result["stop"]
        risk_pct = ((close - stop) / close * 100) if stop and stop < close else 0.0
        adx_val  = float(row["adx"])
        di_plus  = float(row["di_plus"])
        di_minus = float(row["di_minus"])
        trending = (adx_min == 0) or (adx_val >= adx_min and di_plus > di_minus)

        # 52-week high proximity
        high_252     = df_ind["close"].rolling(252, min_periods=50).max().iloc[-1]
        pct_from_52w = float((high_252 - close) / high_252) if high_252 > 0 else 1.0

        # Quality filters — gate entries only, exits always pass
        rs_ok      = (rs is None) or (rs >= rs_min)
        near_high  = pct_from_52w <= high_52w_max_pct
        quality_ok = rs_ok and near_high

        return {
            "ticker":       ticker,
            "close":        close,
            "stage":        result["stage"],
            "action":       result["action"],
            "stop":         stop,
            "risk_pct":     risk_pct,
            "ext_cnt":      result["ext_cnt"],
            "rs":           rs,
            "adx":          adx_val,
            "di_plus":      di_plus,
            "di_minus":     di_minus,
            "vol_flag":     result["vol_flag"],
            "avg_vol":      avg_vol,
            "trending":     trending,
            "quality_ok":   quality_ok,
            "pct_from_52w": pct_from_52w * 100,
            "notes":        result["notes"][0] if result["notes"] else "",
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_group(label: str, group: list[dict], min_rs: float | None) -> None:
    if not group:
        return

    # Apply RS filter if specified
    if min_rs is not None:
        group = [r for r in group if r["rs"] is not None and r["rs"] >= min_rs]
    if not group:
        return

    # Sort: volume spike first, then by relative strength desc
    group.sort(key=lambda r: (not r["vol_flag"], -(r["rs"] or -999)))

    action_label = {
        "BUY":    "BUY -- Wedge Pop (just crossed above 20 EMA)",
        "ADD":    "ADD -- EMA Crossback (pulled back to 10/20 EMA in uptrend)",
        "SELL":   "SELL -- Wedge Drop (lost 20 EMA)",
        "REDUCE": "REDUCE -- Exhaustion Extension #2+ (take profits)",
    }.get(label, label)

    print(f"\n  {'-'*96}")
    print(f"  {action_label}  [{len(group)} stocks]")
    print(f"  {'-'*96}")
    print(f"  {'Ticker':<7}  {'Close':>8}  {'Stop':>8}  {'Risk%':>6}  "
          f"{'RS20d':>6}  {'Frm52w':>7}  {'ADX':>5}  {'AvgVol':>8}  {'Vol':>3}  Notes")
    print(f"  {'.'*94}")

    for r in group:
        stop_s   = f"${r['stop']:.2f}" if r["stop"] else "     N/A"
        rs_s     = f"{r['rs']:>+.1f}%"  if r["rs"] is not None else "   N/A"
        vol_s    = f"{r['avg_vol']/1e6:.1f}M"
        vol_tag  = "***" if r["vol_flag"] else "   "
        frm52w_s = f"{r.get('pct_from_52w', 0):.1f}%"
        note     = r["notes"][:40]
        print(f"  {r['ticker']:<7}  ${r['close']:>7.2f}  {stop_s:>8}  "
              f"{r['risk_pct']:>5.1f}%  {rs_s:>6}  {frm52w_s:>7}  {r['adx']:>5.1f}  "
              f"{vol_s:>7}  {vol_tag}  {note}")


def print_results(results: list[dict], adx_min: float,
                  action_filter: str | None, min_rs: float | None,
                  regime: dict, rs_min: float = 0.0,
                  high_52w_max_pct: float = 0.25) -> None:
    today = date.today()

    # BUY/ADD: require trending + quality filters (RS, 52w proximity)
    buys    = [r for r in results if r["action"] == "BUY" and r["trending"] and r["quality_ok"]]
    adds    = [r for r in results if r["action"] == "ADD" and r["trending"] and r["quality_ok"]]
    # SELL/REDUCE: always show — exits are never filtered
    sells   = [r for r in results if r["action"] == "SELL"]
    reduces = [r for r in results if r["action"] == "REDUCE"]
    holds   = [r for r in results if r["action"] == "HOLD"]
    cash    = [r for r in results if r["action"] == "CASH"]
    watches = [r for r in results if r["action"] == "WATCH"]

    adx_note = (f"ADX >= {adx_min:.0f} + +DI > -DI required for entries"
                if adx_min > 0 else "No ADX filter")
    quality_note = f"RS >= {rs_min:+.0f}%  |  within {high_52w_max_pct*100:.0f}% of 52w high"

    print(f"\n{'='*96}")
    print(f"  OLIVER KELL FULL MARKET SCAN  --  {today.strftime('%A, %B %d, %Y')}")
    print(f"  Market: {regime['label']}  (QQQ ${regime['close']:,.2f}  "
          f"{'above' if regime['above_20'] else 'BELOW'} 20 EMA)  |  {adx_note}")
    print(f"  Quality filters (entries only): {quality_note}")
    print(f"{'='*96}")
    print(f"  {len(results):,} stocks passed price/volume filters")

    counts = {
        "BUY":    len(buys),
        "ADD":    len(adds),
        "SELL":   len(sells),
        "REDUCE": len(reduces),
        "HOLD":   len(holds),
        "CASH":   len(cash),
        "WATCH":  len(watches),
    }
    print(f"\n  Stage distribution (after quality filters):")
    for action, cnt in counts.items():
        bar = "#" * (cnt * 40 // max(counts.values(), default=1))
        print(f"    {action:<7} {cnt:>5}  {bar}")

    groups_to_show = (
        [action_filter] if action_filter
        else ["BUY", "ADD", "SELL", "REDUCE"]
    )
    for label in groups_to_show:
        g = {"BUY": buys, "ADD": adds, "SELL": sells, "REDUCE": reduces}.get(label, [])
        print_group(label, g, min_rs)

    print(f"\n{'='*96}")
    print(f"  TOTALS:  BUY {counts['BUY']}  |  ADD {counts['ADD']}  |  "
          f"SELL {counts['SELL']}  |  REDUCE {counts['REDUCE']}  |  "
          f"HOLD {counts['HOLD']}  |  CASH {counts['CASH']}  |  WATCH {counts['WATCH']}")
    print(f"{'='*96}\n")


def save_csv(results: list[dict]) -> str:
    today = date.today().strftime("%Y-%m-%d")
    fname = f"oliver_scan_{today}.csv"
    rows  = []
    for r in results:
        rows.append({
            "Date":         today,
            "Ticker":       r["ticker"],
            "Stage":        r["stage"],
            "Action":       r["action"],
            "QualityOK":    r["quality_ok"],
            "Close":        round(r["close"], 2),
            "Stop":         round(r["stop"], 2) if r["stop"] else "",
            "Risk_Pct":     round(r["risk_pct"], 1),
            "RS20d":        r["rs"],
            "Pct_From_52w": round(r["pct_from_52w"], 1),
            "ADX":          round(r["adx"], 1),
            "DI_Plus":      round(r["di_plus"], 1),
            "DI_Minus":     round(r["di_minus"], 1),
            "Trending":     r["trending"],
            "VolSpike":     r["vol_flag"],
            "AvgVol":       int(r["avg_vol"]),
            "ExtCount":     r["ext_cnt"],
            "Notes":        r["notes"],
        })
    rows.sort(key=lambda r: (
        {"BUY": 0, "ADD": 1, "SELL": 2, "REDUCE": 3}.get(r["Action"], 9),
        not r["QualityOK"],
        -(r["RS20d"] or -999)
    ))
    pd.DataFrame(rows).to_csv(fname, index=False)
    return fname


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Oliver Kell scan — all US stocks from stockdata.db",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--adx-min",   type=float, default=DEFAULT_ADX,
                    help=f"ADX threshold (default {DEFAULT_ADX}, 0=off)")
    ap.add_argument("--rs-min",    type=float, default=0.0,
                    help="Min RS vs QQQ (20d) for BUY/ADD entries (default 0 = outperforming)")
    ap.add_argument("--high-52w",  type=float, default=0.25,
                    help="Max %% below 52-week high for entries (default 0.25 = 25%%)")
    ap.add_argument("--action",    choices=["BUY", "ADD", "SELL", "REDUCE"],
                    help="Show only this action type")
    ap.add_argument("--min-price", type=float, default=MIN_PRICE,
                    help=f"Skip stocks below this price (default ${MIN_PRICE})")
    ap.add_argument("--min-vol",   type=float, default=MIN_AVG_VOL,
                    help=f"Min avg daily volume (default {MIN_AVG_VOL:,.0f})")
    ap.add_argument("--min-rs",    type=float, default=None,
                    help="Display filter: only show stocks with RS20d >= this value")
    ap.add_argument("--workers",   type=int, default=MAX_WORKERS,
                    help=f"Parallel threads (default {MAX_WORKERS})")
    ap.add_argument("--no-csv",    action="store_true",
                    help="Skip saving CSV output")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"Error: {DB_PATH} not found.")
        print("Run 'python main.py' first to download stock data.")
        sys.exit(1)

    # ── Load QQQ for regime + relative strength ──────────────────────────────
    print("Loading QQQ data for market regime...")
    try:
        qqq_raw = _load(REGIME_TICKER, "2023-01-01")
        qqq_ind = compute_indicators(qqq_raw)
        regime  = market_regime(qqq_ind)
        print(f"Market regime: {regime['label']}  "
              f"(QQQ ${regime['close']:,.2f}  "
              f"{'above' if regime['above_20'] else 'BELOW'} 20 EMA)")
    except Exception as e:
        print(f"Warning: could not load QQQ ({e}). Relative strength will be N/A.")
        qqq_ind = pd.DataFrame()
        regime  = {"label": "UNKNOWN", "close": 0, "above_20": False}

    # ── Get ticker list ──────────────────────────────────────────────────────
    tickers = get_tickers(DB_PATH)
    print(f"Found {len(tickers):,} active tickers in {DB_PATH.name}")
    print(f"Scanning with {args.workers} threads  "
          f"|  price >= ${args.min_price}  "
          f"|  vol >= {args.min_vol/1e3:.0f}k  "
          f"|  ADX >= {args.adx_min}")
    print(f"Entry quality filters  "
          f"|  RS >= {args.rs_min:+.0f}%  "
          f"|  within {args.high_52w*100:.0f}% of 52w high  "
          f"|  (exits always shown)")
    print("Processing...", flush=True)

    # ── Parallel scan ────────────────────────────────────────────────────────
    t0      = time.time()
    results = []
    done    = 0
    errors  = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                scan_ticker, t, DB_PATH, qqq_ind,
                args.adx_min, args.min_price, args.min_vol,
                args.rs_min, args.high_52w
            ): t
            for t in tickers
        }
        for fut in as_completed(futures):
            done += 1
            if done % 500 == 0 or done == len(tickers):
                elapsed = time.time() - t0
                pct     = done / len(tickers) * 100
                print(f"  {done:>5,}/{len(tickers):,}  ({pct:.0f}%)  "
                      f"{elapsed:.0f}s elapsed  "
                      f"{len(results)} passed filters",
                      end="\r", flush=True)
            r = fut.result()
            if r:
                results.append(r)
            else:
                errors += 1

    elapsed = time.time() - t0
    print(f"\nDone: {len(tickers):,} tickers in {elapsed:.1f}s  "
          f"|  {len(results):,} passed filters  |  "
          f"{errors:,} skipped (low price/vol/data)")

    # ── Display ──────────────────────────────────────────────────────────────
    print_results(results, args.adx_min, args.action, args.min_rs, regime,
                  rs_min=args.rs_min, high_52w_max_pct=args.high_52w)

    # ── Save CSV ─────────────────────────────────────────────────────────────
    if not args.no_csv:
        fname = save_csv(results)
        buys  = sum(1 for r in results if r["action"] in ("BUY", "ADD")
                    and r["trending"] and r["quality_ok"])
        sells = sum(1 for r in results if r["action"] == "SELL")
        print(f"  Saved: {fname}  ({buys} quality buy/add + {sells} sell signals)")


if __name__ == "__main__":
    main()
