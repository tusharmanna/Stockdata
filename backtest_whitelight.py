"""
backtest_whitelight.py — Enhanced Whitelight strategy backtest with all 6 improvements:
  1. ADX-scaled risk ($100/$150/$200 by ADX band)
  2. Pyramid into winners when ADX crosses 30
  3. Re-entry at ADX 17 after forced exits
  4. Compound profits (20% of cumulative P&L added to base risk)
  5. ADX entry threshold lowered to 18
  6. 12% trailing stop from highest close since entry

Usage:
    python backtest_whitelight.py               # backtest 2025
    python backtest_whitelight.py --year 2024
    python backtest_whitelight.py --compare     # side-by-side original vs enhanced
"""

import argparse
from math import floor

import pandas as pd

from whitelight_strategy import (
    _load_ohlcv, build_indicators, compute_signals, position_size,
    BULL_ETF, BEAR_ETF,
    RISK_DOLLARS, TRAILING_STOP_PCT, PYRAMID_ADX,
    COMPOUND_PCT, ADX_RISK_SCALE,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _etf_price_on(etf_df: pd.DataFrame, date) -> float | None:
    if date in etf_df.index:
        return float(etf_df.loc[date, "close"])
    avail = etf_df.index[etf_df.index <= date]
    return float(etf_df.loc[avail[-1], "close"]) if not avail.empty else None


def _adx_risk_scale(adx: float) -> float:
    for threshold, multiplier in ADX_RISK_SCALE:
        if adx >= threshold:
            return multiplier
    return 1.0


def _dynamic_risk(base: float, cumulative_pnl: float) -> float:
    return max(base, base + COMPOUND_PCT * cumulative_pnl)


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def run_backtest(sig_df: pd.DataFrame, tqqq: pd.DataFrame, sqqq: pd.DataFrame,
                 base_risk: float = RISK_DOLLARS) -> list[dict]:
    etf_map        = {BULL_ETF: tqqq, BEAR_ETF: sqqq}
    trades         = []
    cumulative_pnl = 0.0
    position       = None

    for date, row in sig_df.iterrows():
        signal = row["signal"]
        adx    = float(row["adx"])
        instr  = BULL_ETF if signal == "BUY_TQQQ" else (BEAR_ETF if signal == "BUY_SQQQ" else None)

        # ── Manage open position ───────────────────────────────────────────
        if position is not None:
            etf_df    = etf_map[position["instrument"]]
            etf_close = _etf_price_on(etf_df, date)
            if etf_close is None:
                continue

            # Update trailing high
            if etf_close > position["highest_close"]:
                position["highest_close"] = etf_close

            # Pyramid: ADX crosses 30, not yet done
            if adx >= PYRAMID_ADX and not position["pyramided"]:
                pyra_shares = max(1, position["shares"] // 2)
                position["pyramided"]      = True
                position["pyramid_shares"] = pyra_shares
                position["pyramid_price"]  = etf_close

            # Trailing stop (12% from highest close)
            stop_price = position["highest_close"] * (1 - TRAILING_STOP_PCT)
            if etf_close <= stop_price:
                pnl, _ = _close_position(position, etf_close)
                cumulative_pnl += pnl
                trades.append(_trade_record(position, date, etf_close, pnl, "trailing_stop"))
                position = None
                continue

            # Signal changed — exit
            pos_sig = "BUY_TQQQ" if position["instrument"] == BULL_ETF else "BUY_SQQQ"
            if signal != pos_sig:
                pnl, _ = _close_position(position, etf_close)
                cumulative_pnl += pnl
                reason = "forced_exit" if signal == "NO_TRADE" else "signal_flip"
                trades.append(_trade_record(position, date, etf_close, pnl, reason))
                position = None

        # ── Open new position ─────────────────────────────────────────────
        if position is None and instr is not None and signal != "NO_TRADE":
            etf_df    = etf_map[instr]
            etf_close = _etf_price_on(etf_df, date)
            if not etf_close or etf_close <= 0:
                continue

            dyn_risk    = _dynamic_risk(base_risk, cumulative_pnl)
            risk_scaled = dyn_risk * _adx_risk_scale(adx)
            sz = position_size(float(row["close"]), float(row["ema_20"]),
                               etf_close, risk_scaled)
            if sz["shares"] == 0:
                continue

            position = {
                "instrument":     instr,
                "entry_date":     date,
                "entry_price":    etf_close,
                "shares":         sz["shares"],
                "cost":           sz["estimated_cost"],
                "risk_used":      round(risk_scaled, 2),
                "risk_per_share": sz["risk_per_share"],
                "highest_close":  etf_close,
                "pyramided":      False,
                "pyramid_shares": 0,
                "pyramid_price":  0.0,
                "entry_adx":      adx,
            }

    # Close open position at end of data
    if position is not None:
        etf_df    = etf_map[position["instrument"]]
        etf_close = float(etf_df["close"].iloc[-1])
        last_date = etf_df.index[-1]
        pnl, _    = _close_position(position, etf_close)
        trades.append(_trade_record(position, last_date, etf_close, pnl, "open_mtm"))

    return trades


def _close_position(pos: dict, exit_price: float) -> tuple[float, float]:
    pnl  = (exit_price - pos["entry_price"]) * pos["shares"]
    cost = pos["shares"] * exit_price
    if pos["pyramid_shares"] > 0:
        pnl  += (exit_price - pos["pyramid_price"]) * pos["pyramid_shares"]
        cost += pos["pyramid_shares"] * exit_price
    return round(pnl, 2), round(cost, 2)


def _trade_record(pos: dict, exit_date, exit_price: float,
                  pnl: float, exit_reason: str) -> dict:
    pct_pnl  = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100
    cal_days = (exit_date - pos["entry_date"]).days
    return {
        "entry_date":     pos["entry_date"],
        "instrument":     pos["instrument"],
        "entry_price":    pos["entry_price"],
        "exit_date":      exit_date,
        "exit_price":     exit_price,
        "shares":         pos["shares"],
        "pyramid_shares": pos["pyramid_shares"],
        "cost":           pos["cost"],
        "risk_used":      pos["risk_used"],
        "risk_per_share": pos["risk_per_share"],
        "entry_adx":      pos["entry_adx"],
        "pnl":            pnl,
        "pct_pnl":        round(pct_pnl, 2),
        "cal_days":       cal_days,
        "exit_reason":    exit_reason,
        "is_open":        exit_reason == "open_mtm",
    }


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_trades(trades: list[dict], label: str, year: int) -> float:
    trades = [t for t in trades
              if t["entry_date"].year == year or t["exit_date"].year == year]

    SEP = "=" * 152
    print(SEP)
    print(f"  {label}")
    print(SEP)
    hdr = (f"{'#':<4} {'Entry':<12} {'Instr':<6} {'Entry$':>8} "
           f"{'Exit':<12} {'Exit$':>8} {'Shs':>5} {'Pyr':>4} {'Cost':>9} "
           f"{'Risk$':>7} {'Rk/Sh':>6} {'P&L':>11} {'%':>8} "
           f"{'Days':>5} {'ADX@En':>7}  Exit Reason        Result")
    print(hdr)
    print("-" * 152)

    total_pnl = 0.0
    winners   = 0
    losers    = 0
    trailing  = 0
    pyramided = 0

    for i, t in enumerate(trades, 1):
        entry_s = t["entry_date"].strftime("%Y-%m-%d")
        exit_s  = t["exit_date"].strftime("%Y-%m-%d")
        pnl_s   = f"${t['pnl']:+,.2f}"
        pct_s   = f"{t['pct_pnl']:+.2f}%"
        pyr_s   = str(t["pyramid_shares"]) if t["pyramid_shares"] > 0 else "-"
        result  = "OPEN" if t["is_open"] else ("WIN" if t["pnl"] > 0 else "LOSS")

        if not t["is_open"]:
            total_pnl += t["pnl"]
            if t["pnl"] > 0: winners += 1
            else:             losers  += 1
        if t["exit_reason"] == "trailing_stop": trailing  += 1
        if t["pyramid_shares"] > 0:             pyramided += 1

        print(f"{i:<4} {entry_s:<12} {t['instrument']:<6} {t['entry_price']:>8.2f} "
              f"{exit_s:<12} {t['exit_price']:>8.2f} {t['shares']:>5} {pyr_s:>4} "
              f"{t['cost']:>9,.2f} {t['risk_used']:>7.0f} {t['risk_per_share']:>6.2f} "
              f"{pnl_s:>11} {pct_s:>8} {t['cal_days']:>5} {t['entry_adx']:>7.1f}  "
              f"{t['exit_reason']:<18} {result}")

    print("-" * 152)
    closed   = [t for t in trades if not t["is_open"]]
    win_rate = winners / len(closed) * 100 if closed else 0
    avg_win  = (sum(t["pnl"] for t in closed if t["pnl"] > 0) / winners) if winners else 0
    avg_loss = (sum(t["pnl"] for t in closed if t["pnl"] <= 0) / losers)  if losers  else 0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss else 0

    print(f"\n  Trades: {len(trades)}  |  Winners: {winners}  |  Losers: {losers}  |  "
          f"Win rate: {win_rate:.0f}%  |  Avg win: ${avg_win:+,.2f}  |  "
          f"Avg loss: ${avg_loss:+,.2f}  |  R:R ratio: {rr_ratio:.1f}x")
    print(f"  Trailing stops triggered: {trailing}  |  Positions pyramided: {pyramided}  |  "
          f"Total P&L: ${total_pnl:+,.2f}")
    print(SEP)
    print()
    return total_pnl


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Whitelight enhanced backtest")
    ap.add_argument("--year",    type=int,  default=2025)
    ap.add_argument("--compare", action="store_true",
                    help="Show original (flat $100, no enhancements) side by side")
    args = ap.parse_args()
    year = args.year

    print(f"\n=== Whitelight Enhanced Backtest — {year} ===\n")
    print("Loading data from DB...")

    qqq  = _load_ohlcv("QQQ")
    tqqq = _load_ohlcv(BULL_ETF)
    sqqq = _load_ohlcv(BEAR_ETF)

    ind    = build_indicators(qqq)
    sig_df = compute_signals(ind)
    print(f"  {len(qqq)} QQQ bars  |  signal flips: "
          f"{sig_df['signal'].ne(sig_df['signal'].shift(1)).sum()}\n")

    enhanced_trades = run_backtest(sig_df, tqqq, sqqq, base_risk=RISK_DOLLARS)
    enhanced_pnl = print_trades(
        enhanced_trades,
        f"ENHANCED BACKTEST {year}  |  Base risk $100  |  "
        f"ADX scaling + Pyramid + Trailing stop + Compounding  |  ADX entry=18  |  Re-entry=17",
        year=year,
    )

    if args.compare:
        # Original: flat $100, ADX=20, no trailing/pyramid/compound
        # Simulate using plain signal flips (signal_flip only exits, no extras)
        orig_trades = []
        prev_sig    = None
        position    = None

        for date, row in sig_df.iterrows():
            signal = row["signal"]
            instr  = BULL_ETF if signal == "BUY_TQQQ" else (BEAR_ETF if signal == "BUY_SQQQ" else None)

            if position is not None:
                etf_df    = etf_map = {BULL_ETF: tqqq, BEAR_ETF: sqqq}[position["instrument"]]
                etf_close = _etf_price_on(etf_df, date)
                if etf_close and signal != ("BUY_TQQQ" if position["instrument"] == BULL_ETF else "BUY_SQQQ"):
                    pnl = round((etf_close - position["entry_price"]) * position["shares"], 2)
                    reason = "forced_exit" if signal == "NO_TRADE" else "signal_flip"
                    orig_trades.append(_trade_record(position, date, etf_close, pnl, reason))
                    position = None

            if position is None and instr and signal != "NO_TRADE":
                etf_df    = {BULL_ETF: tqqq, BEAR_ETF: sqqq}[instr]
                etf_close = _etf_price_on(etf_df, date)
                if etf_close and etf_close > 0:
                    sz = position_size(float(row["close"]), float(row["ema_20"]),
                                       etf_close, RISK_DOLLARS)
                    if sz["shares"] > 0:
                        position = {
                            "instrument": instr, "entry_date": date,
                            "entry_price": etf_close, "shares": sz["shares"],
                            "cost": sz["estimated_cost"], "risk_used": RISK_DOLLARS,
                            "risk_per_share": sz["risk_per_share"],
                            "highest_close": etf_close, "pyramided": False,
                            "pyramid_shares": 0, "pyramid_price": 0.0,
                            "entry_adx": float(row["adx"]),
                        }

        if position is not None:
            etf_df    = {BULL_ETF: tqqq, BEAR_ETF: sqqq}[position["instrument"]]
            etf_close = float(etf_df["close"].iloc[-1])
            pnl = round((etf_close - position["entry_price"]) * position["shares"], 2)
            orig_trades.append(_trade_record(position, etf_df.index[-1], etf_close, pnl, "open_mtm"))

        orig_pnl = print_trades(
            orig_trades,
            f"ORIGINAL BACKTEST {year}  |  Flat $100 risk  |  No enhancements",
            year=year,
        )

        print(f"  IMPROVEMENT: ${enhanced_pnl - orig_pnl:+,.2f}  "
              f"({(enhanced_pnl/orig_pnl-1)*100:+.1f}% gain vs original)"
              if orig_pnl else "")


if __name__ == "__main__":
    main()
