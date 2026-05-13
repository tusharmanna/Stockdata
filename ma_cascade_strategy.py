"""
ma_cascade_strategy.py — MA Cascade QQQ/PSQ hedge strategy.

Start : 100% QQQ, 0% PSQ
Rules :
  Close crosses BELOW any MA  →  QQQ -15%,  PSQ +15%
  Close crosses ABOVE any MA  →  QQQ +15%,  PSQ -15%
MAs tracked : 100, 150, 200, 250

With 4 MAs the worst-case (all broken) gives:
  QQQ = 100% − 4×15% = 40%
  PSQ = 0%   + 4×15% = 60%

Usage:
    python ma_cascade_strategy.py                        # today's signal
    python ma_cascade_strategy.py --lookback 30
    python ma_cascade_strategy.py --backtest --year 2025
    python ma_cascade_strategy.py --capital 100000
"""

import argparse
import datetime
import json
import math
import os
import sqlite3
import sys

import pandas as pd

import database

# ── Constants ─────────────────────────────────────────────────────────────────
MAS       = [100, 150, 200, 250]
BULL_ETF  = "QQQ"
BEAR_ETF  = "PSQ"

QQQ_BREAK   = -0.15   # per MA break
PSQ_BREAK   = +0.15
QQQ_RECLAIM = +0.15   # per MA reclaim
PSQ_RECLAIM = -0.15

QQQ_FLOOR = 0.00
PSQ_FLOOR = 0.00
QQQ_CAP   = 1.00      # never lever above 100% — pure hedge/reduction strategy
PSQ_CAP   = 1.50

DEFAULT_CAPITAL = 100_000.0
MIN_BARS        = 260


# ── Data loader ───────────────────────────────────────────────────────────────

def _load_ohlcv(ticker: str) -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    df   = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker=? ORDER BY date",
        conn, params=(ticker,),
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df          = df.set_index("date")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    return df


# ── Indicators ────────────────────────────────────────────────────────────────

def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for ma in MAS:
        out[f"ma{ma}"] = df["close"].rolling(ma, min_periods=1).mean()
    return out


# ── Signal / allocation engine ────────────────────────────────────────────────

def compute_signals(ind: pd.DataFrame) -> pd.DataFrame:
    """
    State machine. Adds columns:
      qqq_pct, psq_pct   — target allocations after today's events
      breaks             — list of MAs broken today
      reclaims           — list of MAs reclaimed today
      above_mask         — dict {ma: bool} whether close is above each MA
    """
    df = ind.copy()

    qqq_pct = 1.0
    psq_pct = 0.0
    prev    = {ma: None for ma in MAS}

    qqq_col    = []
    psq_col    = []
    break_col  = []
    reclaim_col = []
    above_col  = []

    for date, row in df.iterrows():
        close  = float(row["close"])
        breaks = []
        reclaims = []

        for ma in MAS:
            ma_val = float(row[f"ma{ma}"])
            above  = close > ma_val

            if prev[ma] is not None:
                if prev[ma] and not above:          # crossed below
                    breaks.append(ma)
                    qqq_pct = max(QQQ_FLOOR, qqq_pct + QQQ_BREAK)
                    psq_pct = min(PSQ_CAP,   psq_pct + PSQ_BREAK)
                elif not prev[ma] and above:        # crossed above
                    reclaims.append(ma)
                    qqq_pct = min(QQQ_CAP,   qqq_pct + QQQ_RECLAIM)
                    psq_pct = max(PSQ_FLOOR, psq_pct + PSQ_RECLAIM)

            prev[ma] = above

        qqq_col.append(round(qqq_pct, 4))
        psq_col.append(round(psq_pct, 4))
        break_col.append(breaks)
        reclaim_col.append(reclaims)
        above_col.append({ma: close > float(row[f"ma{ma}"]) for ma in MAS})

    df["qqq_pct"]  = qqq_col
    df["psq_pct"]  = psq_col
    df["breaks"]   = break_col
    df["reclaims"] = reclaim_col
    df["above"]    = above_col
    return df


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(sig_df: pd.DataFrame, qqq_df: pd.DataFrame, psq_df: pd.DataFrame,
                 capital: float, year: int) -> tuple[list[dict], dict]:
    """
    Simulate the full history, rebalancing whenever breaks/reclaims occur.
    Returns (events_list, year_summary).
    """
    # ── Initialise ────────────────────────────────────────────────────────────
    first_date = sig_df.index[0]
    qqq_start  = float(qqq_df.loc[first_date, "close"]) if first_date in qqq_df.index \
                 else float(qqq_df["close"].iloc[0])

    qqq_sh = math.floor(capital / qqq_start)
    psq_sh = 0
    cash   = round(capital - qqq_sh * qqq_start, 2)

    events = []

    def _price(etf_df, date):
        if date in etf_df.index:
            return float(etf_df.loc[date, "close"])
        avail = etf_df.index[etf_df.index <= date]
        return float(etf_df.loc[avail[-1], "close"]) if not avail.empty else None

    for date, row in sig_df.iterrows():
        brks  = row["breaks"]
        rcls  = row["reclaims"]
        if not brks and not rcls:
            continue

        qp = _price(qqq_df, date)
        pp = _price(psq_df, date)
        if qp is None or pp is None:
            continue

        qqq_pct = float(row["qqq_pct"])
        psq_pct = float(row["psq_pct"])

        # Target shares
        new_qqq = math.floor(capital * qqq_pct / qp)
        new_psq = math.floor(capital * psq_pct / pp)

        # Cash flows from rebalancing
        cash += (qqq_sh - new_qqq) * qp   # sell (+) or buy (-) QQQ
        cash += (psq_sh - new_psq) * pp   # sell (+) or buy (-) PSQ

        qqq_sh = new_qqq
        psq_sh = new_psq

        port = round(qqq_sh * qp + psq_sh * pp + cash, 2)

        for ma in brks:
            events.append({
                "date":       date,
                "event":      "BREAK",
                "ma":         ma,
                "close":      round(float(row["close"]), 2),
                "qqq_pct":    qqq_pct,
                "psq_pct":    psq_pct,
                "qqq_sh":     qqq_sh,
                "psq_sh":     psq_sh,
                "qqq_price":  round(qp, 2),
                "psq_price":  round(pp, 2),
                "portfolio":  port,
            })
        for ma in rcls:
            events.append({
                "date":       date,
                "event":      "RECLAIM",
                "ma":         ma,
                "close":      round(float(row["close"]), 2),
                "qqq_pct":    qqq_pct,
                "psq_pct":    psq_pct,
                "qqq_sh":     qqq_sh,
                "psq_sh":     psq_sh,
                "qqq_price":  round(qp, 2),
                "psq_price":  round(pp, 2),
                "portfolio":  port,
            })

    # ── Year summary ──────────────────────────────────────────────────────────
    def _year_val(target_year):
        dates_in_year = [d for d in qqq_df.index if d.year == target_year]
        if not dates_in_year:
            return None, None, None
        start_d = dates_in_year[0]
        end_d   = dates_in_year[-1]

        # Reconstruct portfolio at start and end of year by replaying
        # Easier: use the events to find state at those dates
        # We'll just find the last event before each date
        def _state_at(d):
            ev_before = [e for e in events if e["date"] <= d]
            if ev_before:
                last = ev_before[-1]
                return last["qqq_sh"], last["psq_sh"]
            return qqq_sh, psq_sh  # fallback to current (end)

        # Start-of-year portfolio value
        qs, ps = _state_at(start_d)
        # Find cash at start of year (approximate: cash doesn't change without events)
        ev_before_start = [e for e in events if e["date"] < start_d]
        if ev_before_start:
            # Recompute cash by replaying events up to start_d
            pass  # handled in final summary

        qp_start = float(qqq_df.loc[start_d, "close"]) if start_d in qqq_df.index else float(qqq_df["close"].iloc[0])
        pp_start = float(psq_df.loc[start_d, "close"]) if start_d in psq_df.index else float(psq_df["close"].iloc[0])
        qp_end   = float(qqq_df.loc[end_d, "close"])
        pp_end   = float(psq_df.loc[end_d, "close"])
        return start_d, end_d, (qp_start, pp_start, qp_end, pp_end)

    # Final portfolio value (at last available date)
    last_qp = float(qqq_df["close"].iloc[-1])
    last_pp = float(psq_df["close"].iloc[-1])
    final_val = round(qqq_sh * last_qp + psq_sh * last_pp + cash, 2)

    summary = {
        "capital":       capital,
        "final_value":   final_val,
        "total_pnl":     round(final_val - capital, 2),
        "total_ret_pct": round((final_val - capital) / capital * 100, 2),
        "qqq_sh":        qqq_sh,
        "psq_sh":        psq_sh,
        "cash":          round(cash, 2),
        "qqq_pct":       round(float(sig_df["qqq_pct"].iloc[-1]) * 100, 1),
        "psq_pct":       round(float(sig_df["psq_pct"].iloc[-1]) * 100, 1),
    }
    return events, summary


def print_backtest(events: list[dict], sig_df: pd.DataFrame,
                   qqq_df: pd.DataFrame, psq_df: pd.DataFrame,
                   capital: float, year: int) -> None:

    yr_events = [e for e in events if e["date"].year == year]

    SEP = "=" * 140
    print(SEP)
    print(f"  MA CASCADE BACKTEST {year}  |  Capital: ${capital:,.0f}  |  "
          f"QQQ -15% / PSQ +15% per break  |  QQQ +15% / PSQ -15% per reclaim")
    print(SEP)
    print(f"{'#':<4} {'Date':<12} {'Event':<8} {'MA':>5} {'Close':>8} "
          f"{'QQQ%':>6} {'PSQ%':>6} "
          f"{'QQQ$':>8} {'QQQshs':>7} {'PSQ$':>7} {'PSQshs':>8} "
          f"{'Portfolio':>12}")
    print("-" * 140)

    # Find year start portfolio value
    yr_dates = [d for d in qqq_df.index if d.year == year]
    if yr_dates:
        start_d  = yr_dates[0]
        end_d    = yr_dates[-1]
        qp_start = float(qqq_df.loc[start_d, "close"])
        qp_end   = float(qqq_df.loc[end_d, "close"])
        qqq_hold = round((qp_end / qp_start - 1) * 100, 2)

        # State at start of year: find last event before year start
        ev_before = [e for e in events if e["date"] < start_d]
        if ev_before:
            last = ev_before[-1]
            start_port = last["portfolio"]
            # Revalue at year-start prices
            pp_start = float(psq_df.loc[start_d, "close"]) if start_d in psq_df.index \
                       else float(psq_df["close"].iloc[0])
            start_port = round(last["qqq_sh"] * qp_start + last["psq_sh"] * pp_start, 2)
        else:
            start_port = capital

        end_port = yr_events[-1]["portfolio"] if yr_events else start_port
        yr_pnl   = round(end_port - start_port, 2)
        yr_ret   = round(yr_pnl / start_port * 100, 2) if start_port else 0
    else:
        start_port = capital
        qqq_hold   = 0
        yr_pnl     = 0
        yr_ret     = 0

    for i, e in enumerate(yr_events, 1):
        evt_lbl = "v BREAK  " if e["event"] == "BREAK" else "^ RECLAIM"
        print(f"{i:<4} {e['date'].strftime('%Y-%m-%d'):<12} {evt_lbl:<8} "
              f"MA{e['ma']:>3} {e['close']:>8.2f} "
              f"{e['qqq_pct']*100:>5.0f}% {e['psq_pct']*100:>5.0f}% "
              f"{e['qqq_price']:>8.2f} {e['qqq_sh']:>7} "
              f"{e['psq_price']:>7.2f} {e['psq_sh']:>8} "
              f"${e['portfolio']:>11,.2f}")

    print("-" * 140)
    print(f"\n  {year} portfolio start: ${start_port:,.2f}  =>  end: ${end_port:,.2f}  |  "
          f"P&L: ${yr_pnl:+,.2f}  ({yr_ret:+.2f}%)")
    print(f"  QQQ buy-and-hold {year}: {qqq_hold:+.2f}%  |  "
          f"Events this year: {len(yr_events)} "
          f"({sum(1 for e in yr_events if e['event']=='BREAK')} breaks, "
          f"{sum(1 for e in yr_events if e['event']=='RECLAIM')} reclaims)")
    print(SEP)
    print()


# ── Daily signal output ───────────────────────────────────────────────────────

def print_table(sig_df: pd.DataFrame, lookback: int,
                qqq_price: float, psq_price: float, capital: float) -> None:
    recent = sig_df.tail(lookback)
    print("=" * 130)
    print(f"  MA CASCADE — last {lookback} trading days")
    print("=" * 130)
    # MA header
    ma_hdr = " ".join(f"{'MA'+str(m):>5}" for m in MAS)
    print(f"{'Date':<12} {'Close':>8}  {ma_hdr}  {'QQQ%':>6} {'PSQ%':>6}  {'Events'}")
    print("-" * 130)

    for date, row in recent.iterrows():
        close   = float(row["close"])
        above   = row["above"]
        brks    = row["breaks"]
        rcls    = row["reclaims"]
        ma_vals = " ".join(
            ("  ^  " if above[m] else "  v  ") for m in MAS
        )
        evts = ""
        if brks:   evts += f"BREAK MA{','.join(str(m) for m in brks)}"
        if rcls:   evts += f"{'  ' if evts else ''}RECLAIM MA{','.join(str(m) for m in rcls)}"
        print(f"{date.strftime('%Y-%m-%d'):<12} {close:>8.2f}  {ma_vals}  "
              f"{row['qqq_pct']*100:>5.0f}% {row['psq_pct']*100:>5.0f}%  {evts}")
    print("-" * 130)
    print()


def build_json(sig_df: pd.DataFrame, qqq_price: float, psq_price: float,
               capital: float) -> dict:
    row   = sig_df.iloc[-1]
    date  = sig_df.index[-1].strftime("%Y-%m-%d")
    qpct  = float(row["qqq_pct"])
    ppct  = float(row["psq_pct"])
    above = row["above"]

    qqq_sh = math.floor(capital * qpct / qqq_price) if qqq_price > 0 else 0
    psq_sh = math.floor(capital * ppct / psq_price) if psq_price > 0 else 0
    qqq_cost = round(qqq_sh * qqq_price, 2)
    psq_cost = round(psq_sh * psq_price, 2)
    cash     = round(capital - qqq_cost - psq_cost, 2)

    brks = row["breaks"]
    rcls = row["reclaims"]
    action = "HOLD"
    if brks:   action = f"REDUCE_QQQ / ADD_PSQ (MA {','.join(str(m) for m in brks)} broke)"
    elif rcls: action = f"ADD_QQQ / REDUCE_PSQ (MA {','.join(str(m) for m in rcls)} reclaimed)"

    ma_status = {f"ma{m}": ("above" if above[m] else "below") for m in MAS}
    mas_above = sum(1 for m in MAS if above[m])

    return {
        "date":           date,
        "strategy":       "MA_Cascade",
        "action":         action,
        "qqq_pct":        round(qpct * 100, 1),
        "psq_pct":        round(ppct * 100, 1),
        "mas_above":      mas_above,
        "mas_below":      len(MAS) - mas_above,
        "qqq_price":      round(qqq_price, 2),
        "psq_price":      round(psq_price, 2),
        "qqq_shares":     qqq_sh,
        "qqq_cost":       qqq_cost,
        "psq_shares":     psq_sh,
        "psq_cost":       psq_cost,
        "cash":           cash,
        "capital":        capital,
        **ma_status,
    }


def write_signal_file(payload: dict) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "ma_cascade_signal.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(f"{k}={v}" for k, v in payload.items()) + "\n")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="MA Cascade QQQ/PSQ strategy")
    ap.add_argument("--lookback",  type=int,   default=30)
    ap.add_argument("--capital",   type=float, default=DEFAULT_CAPITAL)
    ap.add_argument("--backtest",  action="store_true")
    ap.add_argument("--year",      type=int,   default=2025)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    qqq = _load_ohlcv("QQQ")
    psq = _load_ohlcv("PSQ")

    if len(qqq) < MIN_BARS:
        print(f"ERROR: need at least {MIN_BARS} bars, have {len(qqq)}", file=sys.stderr)
        sys.exit(1)

    ind    = build_indicators(qqq)
    sig_df = compute_signals(ind)

    # ── Backtest mode ────────────────────────────────────────────────────────
    if args.backtest:
        print(f"\n=== MA Cascade Backtest — {args.year} ===\n")
        events, summary = run_backtest(sig_df, qqq, psq, args.capital, args.year)
        print_backtest(events, sig_df, qqq, psq, args.capital, args.year)
        return

    # ── Daily signal mode ────────────────────────────────────────────────────
    qqq_price = float(qqq["close"].iloc[-1])
    psq_price = float(psq["close"].iloc[-1])

    payload = build_json(sig_df, qqq_price, psq_price, args.capital)

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return

    print(f"\n=== MA Cascade Strategy — {datetime.date.today()} ===\n")
    print_table(sig_df, args.lookback, qqq_price, psq_price, args.capital)

    print("=" * 72)
    print("  TODAY'S ALLOCATION")
    print("=" * 72)
    for k, v in payload.items():
        print(f"  {k:<20}: {v}")
    print("=" * 72)
    print()

    path = write_signal_file(payload)
    print(f"  Signal written to: {path}\n")


if __name__ == "__main__":
    main()
