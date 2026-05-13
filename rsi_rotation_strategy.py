"""
rsi_rotation_strategy.py — RSI-driven TQQQ/QQQ/PSQ/SQQQ rotation strategy.

Signal  : RSI(14) of QQQ close (Wilder's EWM)
Zones (with hysteresis on TQQQ):
  Enter TQQQ when RSI rises above RSI_TQQQ_ENTRY; stay until RSI drops below RSI_TQQQ_EXIT
  RSI between exit and 50 => 100% QQQ
  RSI < 50 => QQQ%=RSI/50, bear_pct=1-RSI/50  (bear = PSQ or SQQQ depending on --lever)

Usage:
    python rsi_rotation_strategy.py                          # today's signal
    python rsi_rotation_strategy.py --backtest --year 2025
    python rsi_rotation_strategy.py --backtest --compare     # all years
    python rsi_rotation_strategy.py --lever tqqq             # lower TQQQ threshold only
    python rsi_rotation_strategy.py --lever sqqq             # SQQQ bear side only
    python rsi_rotation_strategy.py --lever both             # both levers
    python rsi_rotation_strategy.py --lever compare          # all 4 configs side by side
    python rsi_rotation_strategy.py --capital 100000
    python rsi_rotation_strategy.py --json-only
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
RSI_PERIOD      = 14
TQQQ_ETF        = "TQQQ"
BULL_ETF        = "QQQ"
BEAR_ETF        = "PSQ"
SQQQ_ETF        = "SQQQ"
RSI_BULL_THRESH = 50.0    # below this -> hedge zone

# Baseline TQQQ hysteresis thresholds
BASELINE_TQQQ_ENTRY = 70.0
BASELINE_TQQQ_EXIT  = 60.0

# Lever 1 (lower threshold = more TQQQ time)
LEVER1_TQQQ_ENTRY   = 65.0
LEVER1_TQQQ_EXIT    = 55.0

DEFAULT_CAPITAL = 100_000.0
MIN_BARS        = 30


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

def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0.0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(50.0)


def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rsi14"] = _rsi(df["close"])
    return out


# ── Signal / allocation engine ────────────────────────────────────────────────

def compute_signals(ind: pd.DataFrame,
                    tqqq_entry: float = BASELINE_TQQQ_ENTRY,
                    tqqq_exit:  float = BASELINE_TQQQ_EXIT,
                    use_sqqq:   bool  = False) -> pd.DataFrame:
    """
    Returns DataFrame with columns: tqqq_pct, qqq_pct, psq_pct, sqqq_pct, zone.
    use_sqqq=True: replace PSQ with SQQQ in the hedge zone.
    """
    out     = ind.copy()
    rsi     = out["rsi14"].clip(0, 100)
    in_tqqq = False

    tqqq_col = []; qqq_col  = []; psq_col  = []
    sqqq_col = []; zone_col = []

    for r in rsi:
        if not in_tqqq and r > tqqq_entry:
            in_tqqq = True
        elif in_tqqq and r <= tqqq_exit:
            in_tqqq = False

        if in_tqqq:
            tqqq_col.append(1.0); qqq_col.append(0.0)
            psq_col.append(0.0);  sqqq_col.append(0.0)
            zone_col.append("TQQQ")
        elif r > RSI_BULL_THRESH:
            tqqq_col.append(0.0); qqq_col.append(1.0)
            psq_col.append(0.0);  sqqq_col.append(0.0)
            zone_col.append("QQQ")
        else:
            q    = round(r / RSI_BULL_THRESH, 4)
            bear = round(1.0 - q, 4)
            tqqq_col.append(0.0); qqq_col.append(q)
            if use_sqqq:
                psq_col.append(0.0); sqqq_col.append(bear)
                zone_col.append("SQQQ")
            else:
                psq_col.append(bear); sqqq_col.append(0.0)
                zone_col.append("HEDGE")

    out["tqqq_pct"] = tqqq_col
    out["qqq_pct"]  = qqq_col
    out["psq_pct"]  = psq_col
    out["sqqq_pct"] = sqqq_col
    out["zone"]     = zone_col
    return out


# ── Price helper ──────────────────────────────────────────────────────────────

def _price_on(etf_df: pd.DataFrame, date) -> float | None:
    if etf_df is None:
        return None
    if date in etf_df.index:
        return float(etf_df.loc[date, "close"])
    avail = etf_df.index[etf_df.index <= date]
    return float(etf_df.loc[avail[-1], "close"]) if not avail.empty else None


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(sig_df:  pd.DataFrame,
                 tqqq_df: pd.DataFrame,
                 qqq_df:  pd.DataFrame,
                 psq_df:  pd.DataFrame,
                 capital: float,
                 sqqq_df: pd.DataFrame | None = None) -> list[dict]:
    tqqq_sh = qqq_sh = psq_sh = sqqq_sh = 0
    cash    = capital
    daily   = []

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        qp = _price_on(qqq_df,  date)
        pp = _price_on(psq_df,  date)
        sp = _price_on(sqqq_df, date) if sqqq_df is not None else None
        if qp is None:
            continue

        port = (tqqq_sh * (tp or 0) + qqq_sh * qp +
                psq_sh  * (pp or 0) + sqqq_sh * (sp or 0) + cash)

        tpct = float(row["tqqq_pct"])
        qpct = float(row["qqq_pct"])
        ppct = float(row["psq_pct"])
        spct = float(row["sqqq_pct"])

        new_tqqq = math.floor(port * tpct / tp) if tp and tpct > 0 else 0
        new_qqq  = math.floor(port * qpct / qp) if qpct > 0 else 0
        new_psq  = math.floor(port * ppct / pp) if pp and ppct > 0 else 0
        new_sqqq = math.floor(port * spct / sp) if sp and spct > 0 else 0

        if tp: cash += (tqqq_sh - new_tqqq) * tp
        cash += (qqq_sh  - new_qqq)  * qp
        if pp: cash += (psq_sh  - new_psq)  * pp
        if sp: cash += (sqqq_sh - new_sqqq) * sp

        tqqq_sh = new_tqqq; qqq_sh = new_qqq
        psq_sh  = new_psq;  sqqq_sh = new_sqqq

        port = round(tqqq_sh * (tp or 0) + qqq_sh * qp +
                     psq_sh  * (pp or 0) + sqqq_sh * (sp or 0) + cash, 2)

        daily.append({
            "date":       date,
            "qqq_close":  round(qp, 2),
            "rsi":        round(float(row["rsi14"]), 1),
            "zone":       row["zone"],
            "tqqq_pct":   tpct, "qqq_pct": qpct,
            "psq_pct":    ppct, "sqqq_pct": spct,
            "tqqq_sh":    tqqq_sh, "qqq_sh": qqq_sh,
            "psq_sh":     psq_sh,  "sqqq_sh": sqqq_sh,
            "portfolio":  port,
        })

    return daily


# ── Print helpers ─────────────────────────────────────────────────────────────

def _year_stats(daily: list[dict], qqq_df: pd.DataFrame, year: int) -> dict:
    yr = [d for d in daily if d["date"].year == year]
    if not yr:
        return {}
    start_port = yr[0]["portfolio"]
    end_port   = yr[-1]["portfolio"]
    yr_ret     = round((end_port - start_port) / start_port * 100, 2) if start_port else 0.0

    yr_dates = [d for d in qqq_df.index if d.year == year]
    qqq_hold = 0.0
    if yr_dates:
        qqq_hold = round((float(qqq_df.loc[yr_dates[-1], "close"]) /
                          float(qqq_df.loc[yr_dates[0],  "close"]) - 1) * 100, 2)

    return {
        "year":       year,
        "start":      start_port,
        "end":        end_port,
        "pnl":        round(end_port - start_port, 2),
        "ret":        yr_ret,
        "qqq_hold":   qqq_hold,
        "alpha":      round(yr_ret - qqq_hold, 2),
        "tqqq_days":  sum(1 for d in yr if d["zone"] == "TQQQ"),
        "qqq_days":   sum(1 for d in yr if d["zone"] == "QQQ"),
        "hedge_days": sum(1 for d in yr if d["zone"] in ("HEDGE", "SQQQ")),
    }


def print_backtest(daily: list[dict], qqq_df: pd.DataFrame,
                   capital: float, year: int, label: str = "") -> None:
    yr = [d for d in daily if d["date"].year == year]
    if not yr:
        print(f"  No data for {year}"); return

    snapshots = {}
    for d in yr:
        snapshots[(d["date"].year, d["date"].month)] = d
    snaps = sorted(snapshots.values(), key=lambda x: x["date"])

    SEP = "=" * 130
    hdr = label or f"RSI ROTATION BACKTEST {year}"
    print(SEP)
    print(f"  {hdr}  |  Capital: ${capital:,.0f}")
    print(SEP)
    print(f"{'#':<4} {'Date':<12} {'QQQ$':>8} {'RSI':>6} {'Zone':<6} "
          f"{'TQQQ%':>6} {'QQQ%':>5} {'PSQ%':>5} {'SQQQ%':>6} "
          f"{'TQQQsh':>7} {'QQQsh':>6} {'PSQsh':>6} {'SQQQsh':>7} {'Portfolio':>13}")
    print("-" * 130)

    for i, s in enumerate(snaps, 1):
        print(f"{i:<4} {s['date'].strftime('%Y-%m-%d'):<12} {s['qqq_close']:>8.2f} "
              f"{s['rsi']:>6.1f} {s['zone']:<6} "
              f"{s['tqqq_pct']*100:>5.0f}% {s['qqq_pct']*100:>4.0f}% "
              f"{s['psq_pct']*100:>4.0f}% {s['sqqq_pct']*100:>5.0f}% "
              f"{s['tqqq_sh']:>7} {s['qqq_sh']:>6} {s['psq_sh']:>6} {s['sqqq_sh']:>7} "
              f"${s['portfolio']:>12,.2f}")

    st = _year_stats(daily, qqq_df, year)
    print("-" * 130)
    print(f"\n  {year}: ${st['start']:,.2f} => ${st['end']:,.2f}  |  "
          f"P&L: ${st['pnl']:+,.2f} ({st['ret']:+.2f}%)  |  "
          f"QQQ B&H: {st['qqq_hold']:+.2f}%  |  Alpha: {st['alpha']:+.2f} pp")
    print(f"  Days — TQQQ: {st['tqqq_days']}  QQQ: {st['qqq_days']}  Hedge/SQQQ: {st['hedge_days']}")
    print(SEP); print()


def print_comparison(configs: list[tuple], qqq_df: pd.DataFrame,
                     capital: float) -> None:
    """configs = list of (label, daily_list)"""
    all_years = sorted({d["date"].year for _, dl in configs for d in dl})

    SEP = "=" * 120
    print(f"\n{SEP}")
    print(f"  LEVER COMPARISON — all years  |  Capital: ${capital:,.0f}")
    print(SEP)

    col = 22
    hdr = f"{'Config':<{col}}"
    for yr in all_years:
        hdr += f"{'  '+str(yr):>14}"
    hdr += f"{'  Compounded':>14}  Alpha/yr"
    print(hdr)
    print("-" * 120)

    # QQQ B&H row
    qqq_comp = 1.0
    qqq_row  = f"{'QQQ Buy-and-Hold':<{col}}"
    for yr in all_years:
        yr_dates = [d for d in qqq_df.index if d.year == yr]
        if yr_dates:
            r = (float(qqq_df.loc[yr_dates[-1], "close"]) /
                 float(qqq_df.loc[yr_dates[0],  "close"]) - 1) * 100
            qqq_comp *= (1 + r / 100)
            qqq_row  += f"{r:>+13.2f}%"
        else:
            qqq_row  += f"{'  N/A':>14}"
    qqq_comp_pct = round((qqq_comp - 1) * 100, 2)
    qqq_row += f"{qqq_comp_pct:>+13.2f}%  —"
    print(qqq_row)
    print()

    for label, daily in configs:
        row  = f"{label:<{col}}"
        comp = 1.0
        alphas = []
        for yr in all_years:
            st = _year_stats(daily, qqq_df, yr)
            if not st:
                row += f"{'  N/A':>14}"; continue
            comp   *= (1 + st["ret"] / 100)
            alphas.append(st["alpha"])
            row    += f"{st['ret']:>+13.2f}%"
        comp_pct  = round((comp - 1) * 100, 2)
        avg_alpha = round(sum(alphas) / len(alphas), 2) if alphas else 0
        row += f"{comp_pct:>+13.2f}%  {avg_alpha:+.2f}pp"
        print(row)

    print(SEP); print()


# ── Daily signal output ───────────────────────────────────────────────────────

def print_table(sig_df: pd.DataFrame, lookback: int) -> None:
    recent = sig_df.tail(lookback)
    SEP = "=" * 110
    print(SEP)
    print(f"  RSI ROTATION — last {lookback} trading days")
    print(SEP)
    print(f"{'Date':<12} {'Close':>8} {'RSI':>7} {'TQQQ%':>7} {'QQQ%':>6} "
          f"{'PSQ%':>6} {'SQQQ%':>7}  Zone")
    print("-" * 110)
    for date, row in recent.iterrows():
        print(f"{date.strftime('%Y-%m-%d'):<12} {float(row['close']):>8.2f} "
              f"{float(row['rsi14']):>7.1f} "
              f"{row['tqqq_pct']*100:>6.0f}% {row['qqq_pct']*100:>5.0f}% "
              f"{row['psq_pct']*100:>5.0f}% {row['sqqq_pct']*100:>6.0f}%  {row['zone']}")
    print("-" * 110); print()


def build_json(sig_df: pd.DataFrame, tqqq_price: float, qqq_price: float,
               psq_price: float, sqqq_price: float, capital: float) -> dict:
    row   = sig_df.iloc[-1]
    date  = sig_df.index[-1].strftime("%Y-%m-%d")
    rsi   = round(float(row["rsi14"]), 1)
    tpct  = float(row["tqqq_pct"]); qpct = float(row["qqq_pct"])
    ppct  = float(row["psq_pct"]);  spct = float(row["sqqq_pct"])

    tqqq_sh = math.floor(capital * tpct / tqqq_price) if tqqq_price > 0 and tpct > 0 else 0
    qqq_sh  = math.floor(capital * qpct / qqq_price)  if qqq_price  > 0 and qpct > 0 else 0
    psq_sh  = math.floor(capital * ppct / psq_price)  if psq_price  > 0 and ppct > 0 else 0
    sqqq_sh = math.floor(capital * spct / sqqq_price) if sqqq_price > 0 and spct > 0 else 0

    return {
        "date":        date, "strategy": "RSI_Rotation_TQQQ",
        "zone":        row["zone"], "rsi14": rsi,
        "tqqq_pct":   round(tpct*100,1), "qqq_pct": round(qpct*100,1),
        "psq_pct":    round(ppct*100,1), "sqqq_pct": round(spct*100,1),
        "tqqq_price": round(tqqq_price,2), "qqq_price": round(qqq_price,2),
        "psq_price":  round(psq_price,2),  "sqqq_price": round(sqqq_price,2),
        "tqqq_shares": tqqq_sh, "tqqq_cost": round(tqqq_sh*tqqq_price,2),
        "qqq_shares":  qqq_sh,  "qqq_cost":  round(qqq_sh*qqq_price,2),
        "psq_shares":  psq_sh,  "psq_cost":  round(psq_sh*psq_price,2),
        "sqqq_shares": sqqq_sh, "sqqq_cost": round(sqqq_sh*sqqq_price,2),
        "cash":    round(capital - tqqq_sh*tqqq_price - qqq_sh*qqq_price
                         - psq_sh*psq_price - sqqq_sh*sqqq_price, 2),
        "capital": capital,
    }


def write_signal_file(payload: dict) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "rsi_rotation_signal.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(f"{k}={v}" for k, v in payload.items()) + "\n")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="RSI Rotation TQQQ/QQQ/PSQ/SQQQ strategy")
    ap.add_argument("--lookback", type=int,   default=30)
    ap.add_argument("--capital",  type=float, default=DEFAULT_CAPITAL)
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--year",     type=int,   default=2025)
    ap.add_argument("--compare",  action="store_true", help="All available years")
    ap.add_argument("--lever",    choices=["none", "tqqq", "sqqq", "both", "compare"],
                    default="none",
                    help="none=baseline 70/60 PSQ | tqqq=65/55 PSQ | "
                         "sqqq=70/60 SQQQ | both=65/55 SQQQ | compare=all 4")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    tqqq = _load_ohlcv(TQQQ_ETF)
    qqq  = _load_ohlcv(BULL_ETF)
    psq  = _load_ohlcv(BEAR_ETF)
    sqqq = _load_ohlcv(SQQQ_ETF)

    if len(qqq) < MIN_BARS:
        print(f"ERROR: need at least {MIN_BARS} bars", file=sys.stderr); sys.exit(1)

    ind = build_indicators(qqq)

    # ── Lever compare mode ────────────────────────────────────────────────────
    if args.lever == "compare":
        configs = [
            ("Baseline (70/60, PSQ)",  compute_signals(ind, BASELINE_TQQQ_ENTRY, BASELINE_TQQQ_EXIT, False)),
            ("Lever1  (65/55, PSQ)",   compute_signals(ind, LEVER1_TQQQ_ENTRY,   LEVER1_TQQQ_EXIT,   False)),
            ("Lever2  (70/60, SQQQ)",  compute_signals(ind, BASELINE_TQQQ_ENTRY, BASELINE_TQQQ_EXIT, True)),
            ("Both    (65/55, SQQQ)",  compute_signals(ind, LEVER1_TQQQ_ENTRY,   LEVER1_TQQQ_EXIT,   True)),
        ]
        backtests = [
            (lbl, run_backtest(sig, tqqq, qqq, psq, args.capital,
                               sqqq if "SQQQ" in lbl else None))
            for lbl, sig in configs
        ]
        print(f"\n=== RSI Rotation — Lever Comparison ===")
        print_comparison(backtests, qqq, args.capital)

        # Also print detailed backtest for each config
        years = sorted({d["date"].year for _, dl in backtests for d in dl})
        for lbl, daily in backtests:
            for yr in years:
                print_backtest(daily, qqq, args.capital, yr,
                               label=f"{lbl} — {yr}")
        return

    # ── Single config backtest ────────────────────────────────────────────────
    use_sqqq   = args.lever in ("sqqq", "both")
    entry      = LEVER1_TQQQ_ENTRY if args.lever in ("tqqq", "both") else BASELINE_TQQQ_ENTRY
    exit_      = LEVER1_TQQQ_EXIT  if args.lever in ("tqqq", "both") else BASELINE_TQQQ_EXIT
    sqqq_data  = sqqq if use_sqqq else None
    sig_df     = compute_signals(ind, entry, exit_, use_sqqq)

    if args.backtest:
        daily = run_backtest(sig_df, tqqq, qqq, psq, args.capital, sqqq_data)
        lever_lbl = {"none": "Baseline (70/60, PSQ)", "tqqq": "Lever1 (65/55, PSQ)",
                     "sqqq": "Lever2 (70/60, SQQQ)", "both": "Both (65/55, SQQQ)"}[args.lever]
        if args.compare:
            print(f"\n=== {lever_lbl} — Year-by-Year ===\n")
            for yr in sorted({d["date"].year for d in daily}):
                print_backtest(daily, qqq, args.capital, yr, label=f"{lever_lbl} — {yr}")
        else:
            print(f"\n=== {lever_lbl} — {args.year} ===\n")
            print_backtest(daily, qqq, args.capital, args.year,
                           label=f"{lever_lbl} — {args.year}")
        return

    # ── Daily signal mode ─────────────────────────────────────────────────────
    tqqq_price = float(tqqq["close"].iloc[-1])
    qqq_price  = float(qqq["close"].iloc[-1])
    psq_price  = float(psq["close"].iloc[-1])
    sqqq_price = float(sqqq["close"].iloc[-1])

    payload = build_json(sig_df, tqqq_price, qqq_price, psq_price, sqqq_price, args.capital)

    if args.json_only:
        print(json.dumps(payload, indent=2)); return

    print(f"\n=== RSI Rotation Strategy — {datetime.date.today()} ===\n")
    print_table(sig_df, args.lookback)
    print("=" * 72)
    print("  TODAY'S ALLOCATION")
    print("=" * 72)
    for k, v in payload.items():
        print(f"  {k:<22}: {v}")
    print("=" * 72); print()
    path = write_signal_file(payload)
    print(f"  Signal written to: {path}\n")


if __name__ == "__main__":
    main()
