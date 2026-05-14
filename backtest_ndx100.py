"""
backtest_ndx100.py — Batch Oliver Kell backtest for Nasdaq 100 stocks

Runs the Oliver Kell strategy backtest on all NDX 100 components in parallel,
then prints a summary table sorted by a chosen year's return.

Usage:
    python backtest_ndx100.py                    # 2025 returns, default ADX filter
    python backtest_ndx100.py --year 2024        # 2024 returns
    python backtest_ndx100.py --adx-min 0        # no ADX filter
    python backtest_ndx100.py --sort bh          # sort by buy-and-hold return
    python backtest_ndx100.py --min-price 10     # skip stocks below $10
"""

import argparse
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from oliver_stock_strategy import (
    _load, compute_indicators, run_backtest, BACKTEST_START
)

DB_PATH = Path("stockdata.db")


def load_from_db(ticker: str, start: str) -> pd.DataFrame | None:
    """Load OHLCV from stockdata.db, fall back to yfinance if not found or too short."""
    if not DB_PATH.exists():
        return _load(ticker, start)
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker = ? AND date >= ? ORDER BY date",
            conn, params=(ticker, start),
        )
        conn.close()
        if len(df) < 50:
            return _load(ticker, start)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.index.name = "date"
        # Fall back to yfinance if DB doesn't cover the requested start date
        start_dt = pd.to_datetime(start)
        if df.index[0] > start_dt + pd.Timedelta(days=90):
            return _load(ticker, start)
        return df
    except Exception:
        return _load(ticker, start)

# ---------------------------------------------------------------------------
# Nasdaq 100 components (as of May 2026)
# ---------------------------------------------------------------------------
NDX100 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "GOOG",
    "AVGO", "COST", "NFLX", "AMD", "QCOM", "ADBE", "INTU", "TXN",
    "AMAT", "ISRG", "CSCO", "HON", "LRCX", "AMGN", "BKNG", "PDD",
    "MU", "PANW", "KLAC", "ADI", "REGN", "GILD", "SNPS", "CDNS",
    "MELI", "CRWD", "CTAS", "SBUX", "ORLY", "PCAR", "FTNT", "MDLZ",
    "PAYX", "ROST", "NXPI", "AEP", "IDXX", "MCHP", "KDP", "FAST",
    "CEG", "CPRT", "DXCM", "WDAY", "MNST", "DLTR", "TEAM", "VRSK",
    "ZS", "BIIB", "CTSH", "EXC", "ANSS", "ILMN", "TTD", "DDOG",
    "ON", "EA", "XEL", "ULTA", "CSX", "ODFL", "LULU", "ABNB",
    "GFS", "GEHC", "KHC", "ALGN", "MRNA", "FANG", "WBD", "SMCI",
    "ARM", "ROP", "MRVL", "PYPL", "CHTR", "TMUS", "ASML", "APP",
    "TTWO", "VRNS", "AZN", "DASH", "CDW", "DKNG", "EXPE", "NTAP",
    "MSTR", "COIN",
]

START     = "2013-01-01"   # load from here (gives ~500-bar warmup before 2015)
WORKERS   = 12
START_CAP = 10_000.0


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def prefetch_all(tickers: list, start: str) -> dict:
    """Download all ticker data sequentially to avoid yfinance thread-safety issues."""
    data = {}
    for i, ticker in enumerate(tickers):
        print(f"  Fetching {ticker:<6} ({i+1:>3}/{len(tickers)})...", end="\r", flush=True)
        df = load_from_db(ticker, start)
        if df is not None and len(df) >= 120:
            data[ticker] = df
    print()
    return data


def backtest_one(ticker: str, df, adx_min: float,
                 qqq_df, rs_min: float, high_52w: float,
                 vol_confirm: bool) -> dict | None:
    try:
        if df is None or len(df) < 120:
            return None
        r = run_backtest(ticker, df, start_capital=START_CAP, adx_min=adx_min,
                         qqq_df=qqq_df, rs_min=rs_min,
                         high_52w_max_pct=high_52w, vol_confirm=vol_confirm)
        return r if r else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], year: int) -> None:
    rows = []
    for r in results:
        ok_yr  = r["annual"].get(year)
        bh_yr  = r["annual_bh"].get(year)
        if ok_yr is None and bh_yr is None:
            continue
        rows.append({
            "Ticker":    r["ticker"],
            "OK_year":   ok_yr,
            "BH_year":   bh_yr,
            "Diff":      (ok_yr - bh_yr) if (ok_yr is not None and bh_yr is not None) else None,
            "OK_CAGR":   r["cagr"] * 100,
            "BH_CAGR":   r["bh_cagr"] * 100,
            "Max_DD":    r["max_dd"] * 100,
            "BH_DD":     r["bh_max_dd"] * 100,
            "Trades":    r["n_trades"],
            "WinRate":   r["win_rate"] * 100,
            "PF":        r["profit_fac"],
        })

    if not rows:
        print(f"No data for year {year}.")
        return

    df = pd.DataFrame(rows).sort_values("OK_year", ascending=False)

    adx_str = f"ADX filter: {results[0].get('adx_min', 0)}" if results else ""
    print(f"\n{'='*90}")
    print(f"  OLIVER KELL NDX 100 BACKTEST  --  {year} Annual Returns")
    print(f"  {len(df)} stocks  |  {adx_str}")
    print(f"{'='*90}")
    print(f"  {'Ticker':<6}  {'OK ':>8}  {'B&H':>8}  {'Diff':>7}  "
          f"{'OK CAGR':>8}  {'BH CAGR':>8}  {'Max DD':>7}  "
          f"{'Trades':>6}  {'WinR':>5}  {'PF':>5}")
    print(f"  {'-'*86}")

    beats_bh  = 0
    ok_total  = 0
    bh_total  = 0
    count     = 0

    for _, row in df.iterrows():
        ok  = row["OK_year"]
        bh  = row["BH_year"]
        diff = row["Diff"]
        ok_s  = f"{ok:>+.1f}%" if ok  is not None else "   N/A"
        bh_s  = f"{bh:>+.1f}%" if bh  is not None else "   N/A"
        diff_s = f"{diff:>+.1f}%" if diff is not None else "   N/A"
        tag   = " +" if (diff is not None and diff > 0) else "  "
        print(f"  {row['Ticker']:<6}  {ok_s:>8}  {bh_s:>8}  {diff_s:>7}{tag} "
              f"{row['OK_CAGR']:>7.1f}%  {row['BH_CAGR']:>7.1f}%  "
              f"{row['Max_DD']:>6.1f}%  "
              f"{int(row['Trades']):>6}  {row['WinRate']:>4.0f}%  {row['PF']:>5.2f}")
        if diff is not None and diff > 0:
            beats_bh += 1
        if ok is not None:
            ok_total += ok
            count += 1
        if bh is not None:
            bh_total += bh

    avg_ok = ok_total / count if count else 0
    avg_bh = bh_total / count if count else 0
    print(f"  {'-'*86}")
    print(f"  {'AVERAGE':<6}  {avg_ok:>+7.1f}%  {avg_bh:>+7.1f}%  "
          f"{avg_ok - avg_bh:>+6.1f}%")
    print(f"\n  Beats B&H: {beats_bh}/{count} stocks  "
          f"({beats_bh/count*100:.0f}%)")

    # Drawdown comparison
    avg_ok_dd = df["Max_DD"].mean()
    avg_bh_dd = df["BH_DD"].mean()
    print(f"  Avg Max DD: Oliver {avg_ok_dd:.1f}%  vs  B&H {avg_bh_dd:.1f}%  "
          f"(saved {avg_bh_dd - avg_ok_dd:.1f}%)")
    print(f"{'='*90}\n")


def print_full_period(results: list[dict]) -> None:
    """Full-period CAGR and drawdown summary."""
    rows = []
    for r in results:
        rows.append({
            "Ticker":  r["ticker"],
            "OK_CAGR": r["cagr"] * 100,
            "BH_CAGR": r["bh_cagr"] * 100,
            "Diff":    (r["cagr"] - r["bh_cagr"]) * 100,
            "Max_DD":  r["max_dd"] * 100,
            "BH_DD":   r["bh_max_dd"] * 100,
            "Trades":  r["n_trades"],
            "WinRate": r["win_rate"] * 100,
            "PF":      r["profit_fac"],
        })
    df = pd.DataFrame(rows).sort_values("OK_CAGR", ascending=False)
    print(f"\n  Full-period CAGR summary ({results[0]['years']:.1f} years):")
    print(f"  {'Ticker':<6}  {'OK CAGR':>8}  {'BH CAGR':>8}  {'Diff':>7}  "
          f"{'Max DD':>7}  {'BH DD':>7}  {'Trades':>6}")
    print(f"  {'-'*68}")
    for _, row in df.iterrows():
        tag = " +" if row["Diff"] > 0 else "  "
        print(f"  {row['Ticker']:<6}  {row['OK_CAGR']:>7.1f}%  {row['BH_CAGR']:>7.1f}%  "
              f"{row['Diff']:>+6.1f}%{tag}  {row['Max_DD']:>6.1f}%  "
              f"{row['BH_DD']:>6.1f}%  {int(row['Trades']):>6}")
    avg = df.mean(numeric_only=True)
    print(f"  {'-'*68}")
    print(f"  {'AVERAGE':<6}  {avg['OK_CAGR']:>7.1f}%  {avg['BH_CAGR']:>7.1f}%  "
          f"{avg['Diff']:>+6.1f}%    {avg['Max_DD']:>6.1f}%  {avg['BH_DD']:>6.1f}%")


# ---------------------------------------------------------------------------
# Yearly comparison
# ---------------------------------------------------------------------------

def compute_qqq_annual(qqq_df: pd.DataFrame) -> dict:
    """Annual returns for QQQ, keyed by year."""
    annual = {}
    qqq_df = qqq_df.copy()
    qqq_df["year"] = qqq_df.index.year
    for yr, grp in qqq_df.groupby("year"):
        yr_start = float(grp["close"].iloc[0])
        yr_end   = float(grp["close"].iloc[-1])
        annual[yr] = (yr_end - yr_start) / yr_start * 100
    return annual


def print_yearly_comparison(results: list[dict], qqq_annual: dict,
                             start_year: int = 2015) -> None:
    """Year-by-year Oliver Kell average vs QQQ, from start_year onward."""
    all_years = sorted(
        yr for r in results for yr in r["annual"]
        if yr >= start_year
    )
    all_years = sorted(set(all_years))
    if not all_years:
        print("No yearly data available.")
        return

    n_stocks = len(results)
    W = 88
    print(f"\n{'='*W}")
    print(f"  OLIVER KELL NDX 100 -- YEARLY RETURNS vs QQQ  ({start_year}-{all_years[-1]})")
    print(f"  Equal-weighted average across {n_stocks} stocks  |  "
          f"Filters: RS>=0%  within 25% of 52w high")
    print(f"{'='*W}")
    print(f"  {'Year':<5}  {'Oliver Avg':>11}  {'NDX B&H Avg':>12}  {'QQQ':>8}  "
          f"{'vs QQQ':>8}  {'Beats QQQ':>12}  {'# Stocks':>9}")
    print(f"  {'-'*82}")

    ok_cumulative  = 1.0
    qqq_cumulative = 1.0

    for yr in all_years:
        ok_rets  = [r["annual"][yr]    for r in results if yr in r["annual"]]
        bh_rets  = [r["annual_bh"][yr] for r in results if yr in r["annual_bh"]]
        n        = len(ok_rets)
        if n == 0:
            continue

        avg_ok  = sum(ok_rets)  / n
        avg_bh  = sum(bh_rets)  / len(bh_rets) if bh_rets else 0.0
        qqq_ret = qqq_annual.get(yr)
        vs_qqq  = avg_ok - qqq_ret if qqq_ret is not None else None
        beats   = sum(1 for ret in ok_rets if qqq_ret is not None and ret > qqq_ret)

        ok_cumulative  *= (1 + avg_ok  / 100)
        if qqq_ret is not None:
            qqq_cumulative *= (1 + qqq_ret / 100)

        qqq_s  = f"{qqq_ret:>+.1f}%"  if qqq_ret  is not None else "    N/A"
        vs_s   = f"{vs_qqq:>+.1f}%"   if vs_qqq   is not None else "    N/A"
        tag    = " +" if vs_qqq is not None and vs_qqq > 0 else "  "

        print(f"  {yr:<5}  {avg_ok:>+10.1f}%  {avg_bh:>+11.1f}%  {qqq_s:>8}  "
              f"{vs_s:>8}{tag}  {beats:>4}/{n:<4}  {n:>8}")

    # Summary row
    n_years       = len(all_years)
    ok_cagr       = (ok_cumulative  ** (1 / n_years) - 1) * 100
    qqq_cagr      = (qqq_cumulative ** (1 / n_years) - 1) * 100
    ok_total_ret  = (ok_cumulative  - 1) * 100
    qqq_total_ret = (qqq_cumulative - 1) * 100

    print(f"  {'-'*82}")
    print(f"  {'CAGR':<5}  {ok_cagr:>+10.1f}%  {'':>12}  {qqq_cagr:>+7.1f}%  "
          f"{ok_cagr - qqq_cagr:>+8.1f}%")
    print(f"  {'Total':<5}  {ok_total_ret:>+10.1f}%  {'':>12}  {qqq_total_ret:>+7.1f}%  "
          f"{ok_total_ret - qqq_total_ret:>+8.1f}%")
    print(f"{'='*W}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Oliver Kell NDX 100 batch backtest")
    ap.add_argument("--year",        type=int,   default=2025,
                    help="Year to highlight in summary (default 2025)")
    ap.add_argument("--start",       default=START,
                    help=f"Data start date (default {START})")
    ap.add_argument("--adx-min",     type=float, default=0.0,
                    help="ADX threshold + DI filter (default 0=off)")
    ap.add_argument("--rs-min",      type=float, default=0.0,
                    help="Min RS vs QQQ (20d) at entry (default 0 = outperforming)")
    ap.add_argument("--high-52w",    type=float, default=0.15,
                    help="Max %% below 52-week high to allow entry (default 0.15 = 15%%)")
    ap.add_argument("--vol-confirm", action="store_true",
                    help="Require entry bar volume >= 1.2x average")
    ap.add_argument("--no-filters",  action="store_true",
                    help="Disable all quality filters (RS, 52w high, volume)")
    ap.add_argument("--workers",     type=int,   default=WORKERS)
    ap.add_argument("--full",        action="store_true",
                    help="Also show full-period CAGR table")
    args = ap.parse_args()

    # Load QQQ for RS calculation + annual benchmark
    print("Loading QQQ data...")
    try:
        qqq_df     = _load("QQQ", args.start)
        qqq_annual = compute_qqq_annual(qqq_df)
        print(f"QQQ: {len(qqq_df)} bars loaded  "
              f"({qqq_df.index[0].year}-{qqq_df.index[-1].year})")
    except Exception as e:
        print(f"Warning: could not load QQQ ({e}). RS filter and QQQ benchmark disabled.")
        qqq_df     = None
        qqq_annual = {}

    rs_min      = 0.0         if args.no_filters else args.rs_min
    high_52w    = 1.0         if args.no_filters else args.high_52w
    vol_confirm = False       if args.no_filters else args.vol_confirm

    tickers = NDX100
    filters_str = (
        "no filters" if args.no_filters else
        f"RS>={rs_min:+.0f}%  |  within {high_52w*100:.0f}% of 52w high"
        + ("  |  vol>=1.2x" if vol_confirm else "")
    )
    print(f"Oliver Kell backtest -- {len(tickers)} NDX 100 stocks")
    print(f"Data from {args.start}  |  ADX >= {args.adx_min}  |  {filters_str}")
    print(f"Highlighting year {args.year}")

    # Pre-fetch all data sequentially (avoids yfinance thread-safety issues)
    print(f"Pre-fetching price data from {args.start}...")
    stock_data = prefetch_all(tickers, args.start)
    print(f"Loaded {len(stock_data)}/{len(tickers)} tickers  |  "
          f"Running backtest on {args.workers} threads...")

    results = []
    errors  = []
    done    = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(backtest_one, t, stock_data.get(t), args.adx_min,
                        qqq_df, rs_min, high_52w, vol_confirm): t
            for t in tickers
        }
        for fut in as_completed(futures):
            done += 1
            ticker = futures[fut]
            r = fut.result()
            if r:
                results.append(r)
                status = f"ok  ({r['annual'].get(args.year, 0):>+.1f}%)"
            else:
                errors.append(ticker)
                status = "skip"
            print(f"  [{done:>3}/{len(tickers)}] {ticker:<6}  {status}",
                  end="\r", flush=True)

    print(f"\nDone: {len(results)} succeeded, {len(errors)} failed"
          + (f" ({', '.join(errors)})" if errors else ""))

    if not results:
        print("No results.")
        sys.exit(1)

    print_yearly_comparison(results, qqq_annual, start_year=2015)

    print_summary(results, args.year)

    if args.full:
        print_full_period(results)


if __name__ == "__main__":
    main()
