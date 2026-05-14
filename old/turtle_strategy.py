"""
turtle_strategy.py — Classic Turtle Trading adapted for QQQ/PSQ.

System 1 (S1): 20-day breakout entry, 10-day exit  (shorter-term)
System 2 (S2): 55-day breakout entry, 20-day exit  (longer-term)
N            : 20-day ATR (Wilder's smoothing)
Unit size    : floor(capital × 1% / N)  — same dollar risk on every trade
Pyramid      : up to 4 units, add 1 unit per ½N move in your favour
Stop         : 2N from the most recent unit entry (trails up as you pyramid)
S1 filter    : skip S1 entry if the last S1 trade was a winner

Bull = long QQQ  |  Bear = long PSQ (inverse, instead of shorting)

Usage:
    python turtle_strategy.py
    python turtle_strategy.py --lookback 40
    python turtle_strategy.py --backtest --year 2025
    python turtle_strategy.py --capital 100000 --risk-pct 1.0
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
BULL_ETF = "QQQ"
BEAR_ETF = "PSQ"

S1_ENTRY = 20;  S1_EXIT = 10
S2_ENTRY = 55;  S2_EXIT = 20
ATR_PERIOD   = 20
MAX_UNITS    = 4
PYRAMID_STEP = 0.5   # add 1 unit per this many N
STOP_N       = 2.0   # stop = 2N from latest entry

DEFAULT_CAPITAL = 100_000.0
DEFAULT_RISK    = 0.01          # 1 % of capital per unit
MIN_BARS        = S2_ENTRY + ATR_PERIOD + 5


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

def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    hi, lo, pc = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def build_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["atr"] = _atr(df, ATR_PERIOD)

    # Donchian channels — shift(1) so today's bar is NOT included in the lookback
    out["s1_high"]      = df["high"].rolling(S1_ENTRY).max().shift(1)
    out["s1_low"]       = df["low"].rolling(S1_ENTRY).min().shift(1)
    out["s1_exit_low"]  = df["low"].rolling(S1_EXIT).min().shift(1)
    out["s1_exit_high"] = df["high"].rolling(S1_EXIT).max().shift(1)

    out["s2_high"]      = df["high"].rolling(S2_ENTRY).max().shift(1)
    out["s2_low"]       = df["low"].rolling(S2_ENTRY).min().shift(1)
    out["s2_exit_low"]  = df["low"].rolling(S2_EXIT).min().shift(1)
    out["s2_exit_high"] = df["high"].rolling(S2_EXIT).max().shift(1)
    return out


# ── Unit sizing ───────────────────────────────────────────────────────────────

def _unit_shares(capital: float, risk_pct: float,
                 atr: float, etf_price: float,
                 qqq_price: float, direction: str) -> int:
    """
    Risk 1 % of capital on each unit.
    For QQQ (bull):  shares = capital × risk / atr_qqq
    For PSQ (bear):  same dollar risk but expressed in PSQ shares.
                     PSQ moves roughly 1× QQQ in absolute dollar terms scaled
                     by the price ratio, so we normalise:
                     psq_atr_equiv = atr_qqq × (psq_price / qqq_price)
    """
    risk_dollars = capital * risk_pct
    if direction == "BULL":
        n_per_share = atr
    else:
        n_per_share = atr * (etf_price / qqq_price)  # PSQ equivalent of 1N
    if n_per_share <= 0:
        return 0
    return max(0, math.floor(risk_dollars / n_per_share))


# ── Backtest simulation ───────────────────────────────────────────────────────

def run_backtest(ind: pd.DataFrame, psq_df: pd.DataFrame,
                 capital: float, risk_pct: float) -> list[dict]:
    etf_map = {"BULL": ind, "BEAR": psq_df}

    trades        = []
    position      = None      # active position dict
    last_s1_win   = None      # True/False/None — S1 filter

    for date, row in ind.iterrows():
        close  = float(row["close"])
        atr    = float(row["atr"])
        if pd.isna(atr) or pd.isna(row["s2_high"]):
            continue

        psq_close = float(psq_df.loc[date, "close"]) if date in psq_df.index else None

        # ── Manage open position ─────────────────────────────────────────────
        if position is not None:
            direction = position["direction"]
            sys_num   = position["system"]
            stop      = position["stop"]
            units     = position["units"]
            N         = position["n"]

            # Exit price = today's close (simulate fill at close)
            exit_etf  = close if direction == "BULL" else psq_close
            if exit_etf is None:
                continue

            exit_reason = None

            # 1. Stop hit (in QQQ terms)
            if direction == "BULL" and close <= stop:
                exit_reason = "stop"
            elif direction == "BEAR" and close >= stop:
                exit_reason = "stop"

            # 2. System exit (Donchian opposite)
            if exit_reason is None:
                if direction == "BULL":
                    exit_lvl = row[f"s{sys_num}_exit_low"]
                    if not pd.isna(exit_lvl) and close < float(exit_lvl):
                        exit_reason = f"s{sys_num}_exit"
                else:
                    exit_lvl = row[f"s{sys_num}_exit_high"]
                    if not pd.isna(exit_lvl) and close > float(exit_lvl):
                        exit_reason = f"s{sys_num}_exit"

            if exit_reason:
                pnl, rec = _close_position(position, exit_etf, date, exit_reason)
                trades.append(rec)
                if sys_num == 1:
                    last_s1_win = pnl > 0
                position = None
                # Fall through to check for new entry on same bar

            # 3. Pyramid (only if still in position)
            if position is not None:
                next_pyr = position["next_pyramid"]
                if (direction == "BULL" and close >= next_pyr and len(units) < MAX_UNITS) or \
                   (direction == "BEAR" and psq_close is not None and
                    psq_close >= next_pyr and len(units) < MAX_UNITS):

                    etf_p  = close if direction == "BULL" else psq_close
                    shares = _unit_shares(capital, risk_pct, atr, etf_p, close, direction)
                    if shares > 0:
                        units.append({
                            "entry_date":  date,
                            "qqq_ref":     close,
                            "etf_price":   etf_p,
                            "shares":      shares,
                        })
                        # Update stop and next pyramid level
                        if direction == "BULL":
                            position["stop"]          = close - STOP_N * N
                            position["next_pyramid"]  = close + PYRAMID_STEP * N
                        else:
                            position["stop"]          = close + STOP_N * N
                            position["next_pyramid"]  = psq_close + PYRAMID_STEP * \
                                                        (N * psq_close / close)

        # ── Check for new entry ───────────────────────────────────────────────
        if position is None and not pd.isna(row["s2_high"]) and psq_close is not None:
            new_dir, new_sys = None, None

            # S2 (priority)
            if close > float(row["s2_high"]):
                new_dir, new_sys = "BULL", 2
            elif close < float(row["s2_low"]):
                new_dir, new_sys = "BEAR", 2
            # S1 (only if last S1 was not a winner)
            elif last_s1_win is not True:
                if close > float(row["s1_high"]):
                    new_dir, new_sys = "BULL", 1
                elif close < float(row["s1_low"]):
                    new_dir, new_sys = "BEAR", 1

            if new_dir is not None:
                etf_p  = close if new_dir == "BULL" else psq_close
                shares = _unit_shares(capital, risk_pct, atr, etf_p, close, new_dir)
                if shares > 0:
                    if new_dir == "BULL":
                        stop     = close - STOP_N * atr
                        nxt_pyr  = close + PYRAMID_STEP * atr
                    else:
                        psq_n    = atr * psq_close / close
                        stop     = close + STOP_N * atr      # QQQ level (bear stop)
                        nxt_pyr  = psq_close + PYRAMID_STEP * psq_n

                    position = {
                        "direction":      new_dir,
                        "system":         new_sys,
                        "n":              atr,
                        "stop":           stop,
                        "next_pyramid":   nxt_pyr,
                        "units": [{
                            "entry_date":  date,
                            "qqq_ref":     close,
                            "etf_price":   etf_p,
                            "shares":      shares,
                        }],
                    }

    # Close open position at end of data
    if position is not None:
        direction = position["direction"]
        last_row  = ind.iloc[-1]
        last_date = ind.index[-1]
        etf_p = float(last_row["close"]) if direction == "BULL" \
                else float(psq_df["close"].iloc[-1])
        _, rec = _close_position(position, etf_p, last_date, "open_mtm")
        trades.append(rec)

    return trades


def _close_position(pos: dict, etf_price: float, exit_date, reason: str) -> tuple[float, dict]:
    total_pnl  = 0.0
    total_cost = 0.0
    total_sh   = 0
    entry_prices = []

    for u in pos["units"]:
        pnl         = (etf_price - u["etf_price"]) * u["shares"]
        total_pnl  += pnl
        total_cost += u["etf_price"] * u["shares"]
        total_sh   += u["shares"]
        entry_prices.append(u["etf_price"])

    avg_entry = total_cost / total_sh if total_sh else 0
    pct_pnl   = (etf_price - avg_entry) / avg_entry * 100 if avg_entry else 0
    cal_days  = (exit_date - pos["units"][0]["entry_date"]).days

    rec = {
        "direction":   pos["direction"],
        "instrument":  BULL_ETF if pos["direction"] == "BULL" else BEAR_ETF,
        "system":      pos["system"],
        "entry_date":  pos["units"][0]["entry_date"],
        "exit_date":   exit_date,
        "avg_entry":   round(avg_entry, 2),
        "exit_price":  round(etf_price, 2),
        "total_shares": total_sh,
        "units_max":   len(pos["units"]),
        "total_cost":  round(total_cost, 2),
        "pnl":         round(total_pnl, 2),
        "pct_pnl":     round(pct_pnl, 2),
        "cal_days":    cal_days,
        "exit_reason": reason,
        "is_open":     reason == "open_mtm",
        "n":           round(pos["n"], 2),
        "stop":        round(pos["stop"], 2),
    }
    return round(total_pnl, 2), rec


# ── Print helpers ─────────────────────────────────────────────────────────────

def print_backtest(trades: list[dict], year: int, capital: float, risk_pct: float) -> float:
    relevant = [t for t in trades
                if t["entry_date"].year <= year <= t["exit_date"].year]

    SEP = "=" * 158
    print(SEP)
    print(f"  TURTLE TRADING BACKTEST {year}  |  Capital: ${capital:,.0f}  |  "
          f"Risk: {risk_pct*100:.1f}%/unit  |  S1=20/10  S2=55/20  |  "
          f"N=ATR20  Stop=2N  Pyramid=0.5N×4")
    print(SEP)
    print(f"{'#':<4} {'Entry':<12} {'Sys':<4} {'Dir':<5} {'Instr':<5} "
          f"{'AvgEntry':>9} {'Exit':<12} {'ExitPx':>8} "
          f"{'Shs':>6} {'Units':>5} {'Cost':>10} "
          f"{'P&L':>11} {'%':>8} {'Days':>5} {'N':>6} "
          f"{'Exit Reason':<16} Result")
    print("-" * 158)

    total_pnl = 0.0
    winners   = 0
    losers    = 0

    for i, t in enumerate(relevant, 1):
        pnl_s  = f"${t['pnl']:+,.2f}"
        pct_s  = f"{t['pct_pnl']:+.2f}%"
        result = "OPEN" if t["is_open"] else ("WIN" if t["pnl"] >= 0 else "LOSS")
        sys_s  = f"S{t['system']}"

        if not t["is_open"]:
            total_pnl += t["pnl"]
            if t["pnl"] >= 0: winners += 1
            else:              losers  += 1

        print(f"{i:<4} {t['entry_date'].strftime('%Y-%m-%d'):<12} {sys_s:<4} "
              f"{t['direction']:<5} {t['instrument']:<5} "
              f"{t['avg_entry']:>9.2f} "
              f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['exit_price']:>8.2f} "
              f"{t['total_shares']:>6} {t['units_max']:>5} {t['total_cost']:>10,.2f} "
              f"{pnl_s:>11} {pct_s:>8} {t['cal_days']:>5} {t['n']:>6.2f} "
              f"{t['exit_reason']:<16} {result}")

    print("-" * 158)
    closed   = [t for t in relevant if not t["is_open"]]
    win_rate = winners / len(closed) * 100 if closed else 0
    avg_win  = sum(t["pnl"] for t in closed if t["pnl"] >= 0) / winners if winners else 0
    avg_loss = sum(t["pnl"] for t in closed if t["pnl"] < 0)  / losers  if losers  else 0
    rr       = abs(avg_win / avg_loss) if avg_loss else 0
    ret_pct  = total_pnl / capital * 100

    print(f"\n  Trades: {len(relevant)}  |  Winners: {winners}  |  "
          f"Losers: {losers}  |  Win rate: {win_rate:.0f}%  |  "
          f"Avg win: ${avg_win:+,.2f}  |  Avg loss: ${avg_loss:+,.2f}  |  R:R: {rr:.1f}x")
    print(f"  Total P&L: ${total_pnl:+,.2f}  |  Return on ${capital:,.0f}: {ret_pct:+.2f}%")
    print(SEP)
    print()
    return total_pnl


# ── Daily signal output ───────────────────────────────────────────────────────

def print_table(ind: pd.DataFrame, lookback: int) -> None:
    recent = ind.tail(lookback)
    W = 128
    print("=" * W)
    print(f"  TURTLE SIGNAL LEVELS — last {lookback} trading days")
    print("=" * W)
    print(f"{'Date':<12} {'Close':>8} {'ATR':>6}  "
          f"{'S1 Hi':>8} {'S1 Lo':>8} {'S2 Hi':>8} {'S2 Lo':>8}  "
          f"{'S1 XLo':>8} {'S2 XLo':>8}")
    print("-" * W)
    for date, row in recent.iterrows():
        print(f"{date.strftime('%Y-%m-%d'):<12} {row['close']:>8.2f} {row['atr']:>6.2f}  "
              f"{row['s1_high']:>8.2f} {row['s1_low']:>8.2f} "
              f"{row['s2_high']:>8.2f} {row['s2_low']:>8.2f}  "
              f"{row['s1_exit_low']:>8.2f} {row['s2_exit_low']:>8.2f}")
    print("-" * W)
    print()


def build_json(ind: pd.DataFrame, trades: list[dict],
               psq_price: float, capital: float, risk_pct: float) -> dict:
    row  = ind.iloc[-1]
    date = ind.index[-1].strftime("%Y-%m-%d")

    # Current open position (last trade if is_open)
    open_trade = trades[-1] if trades and trades[-1]["is_open"] else None

    atr     = float(row["atr"])
    close   = float(row["close"])
    s1h     = float(row["s1_high"])
    s1l     = float(row["s1_low"])
    s2h     = float(row["s2_high"])
    s2l     = float(row["s2_low"])

    # Next action levels
    bull_unit = _unit_shares(capital, risk_pct, atr, close, close, "BULL")
    bear_unit = _unit_shares(capital, risk_pct, atr, psq_price, close, "BEAR")

    status = "FLAT"
    if open_trade:
        status = f"{open_trade['direction']} S{open_trade['system']} ({open_trade['units_max']} units)"

    return {
        "date":             date,
        "strategy":         "Turtle",
        "status":           status,
        "close":            round(close, 2),
        "atr_20":           round(atr, 2),
        "s1_buy_above":     round(s1h, 2),
        "s1_sell_below":    round(s1l, 2),
        "s2_buy_above":     round(s2h, 2),
        "s2_sell_below":    round(s2l, 2),
        "s1_exit_long_below":  round(float(row["s1_exit_low"]), 2),
        "s2_exit_long_below":  round(float(row["s2_exit_low"]), 2),
        "bull_unit_shares": bull_unit,
        "bull_unit_cost":   round(bull_unit * close, 2),
        "bear_unit_shares": bear_unit,
        "bear_unit_cost":   round(bear_unit * psq_price, 2),
        "two_n":            round(2 * atr, 2),
        "half_n":           round(0.5 * atr, 2),
        "capital":          capital,
        "risk_per_unit":    round(capital * risk_pct, 2),
    }


def write_signal_file(payload: dict) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "turtle_signal.txt")
    with open(path, "w") as fh:
        fh.write("\n".join(f"{k}={v}" for k, v in payload.items()) + "\n")
    return path


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Turtle Trading QQQ/PSQ")
    ap.add_argument("--lookback",  type=int,   default=30)
    ap.add_argument("--capital",   type=float, default=DEFAULT_CAPITAL)
    ap.add_argument("--risk-pct",  type=float, default=1.0,
                    help="Risk %% of capital per unit (default 1.0)")
    ap.add_argument("--backtest",  action="store_true")
    ap.add_argument("--year",      type=int,   default=2025)
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    capital  = args.capital
    risk_pct = args.risk_pct / 100.0

    qqq = _load_ohlcv("QQQ")
    psq = _load_ohlcv("PSQ")

    if len(qqq) < MIN_BARS:
        print(f"ERROR: need {MIN_BARS} bars, have {len(qqq)}", file=sys.stderr)
        sys.exit(1)

    ind    = build_indicators(qqq)
    trades = run_backtest(ind, psq, capital, risk_pct)

    if args.backtest:
        print(f"\n=== Turtle Trading Backtest — {args.year} ===\n")
        print_backtest(trades, year=args.year, capital=capital, risk_pct=risk_pct)
        return

    psq_price = float(psq["close"].iloc[-1])
    payload   = build_json(ind, trades, psq_price, capital, risk_pct)

    if args.json_only:
        print(json.dumps(payload, indent=2))
        return

    print(f"\n=== Turtle Trading Strategy — {datetime.date.today()} ===\n")
    print_table(ind, args.lookback)

    print("=" * 70)
    print("  TODAY'S SIGNAL")
    print("=" * 70)
    for k, v in payload.items():
        print(f"  {k:<26}: {v}")
    print("=" * 70)
    print()

    path = write_signal_file(payload)
    print(f"  Signal written to: {path}\n")


if __name__ == "__main__":
    main()
