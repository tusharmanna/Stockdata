"""
whitelight_strategy.py — Whitelight TQQQ/SQQQ momentum switching strategy.

Signal engine: EMA(5) / EMA(20) cross + ADX(14) strength filter + RSI(14) confirmation.

Usage:
    python whitelight_strategy.py                   # signal for today
    python whitelight_strategy.py --lookback 20     # show last N days in table
    python whitelight_strategy.py --json-only       # print JSON signal and exit
"""

import argparse
import datetime
import json
import os
import sqlite3
import sys

import pandas as pd

import database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BULL_ETF    = "TQQQ"
BEAR_ETF    = "SQQQ"
SIGNAL_TKR  = "QQQ"

EMA_FAST     = 5
EMA_SLOW     = 20
ADX_PERIOD   = 14
RSI_PERIOD   = 14
MIN_BARS     = 26          # minimum history required
MIN_HOLD     = 3           # whipsaw filter: min days before exit allowed
ADX_TRADE    = 18.0        # ADX threshold to enter (lowered from 20)
ADX_REENTRY  = 17.0        # ADX threshold to re-enter after a forced exit
ADX_FORCE    = 15.0        # ADX threshold for forced exit
RISK_DOLLARS = 100.0       # base risk per trade for position sizing
LEVERAGE     = 3.0         # TQQQ/SQQQ are 3x QQQ
TRAILING_STOP_PCT = 0.12   # 12% trailing stop from highest close
PYRAMID_ADX  = 30.0        # ADX level to add 50% to winning position
COMPOUND_PCT = 0.20        # reinvest 20% of cumulative P&L into risk budget

# Risk scaling by ADX strength
ADX_RISK_SCALE = [
    (30.0, 2.0),   # ADX >= 30 → 2x risk
    (25.0, 1.5),   # ADX >= 25 → 1.5x risk
    (0.0,  1.0),   # ADX <  25 → 1x risk
]

# ── Dual Strategy position sizing ─────────────────────────────────────────────
DEFAULT_CAPITAL = 100_000.0
HIGH_PERIOD     = 252        # rolling window for PercentHigh (1-year high)
RSI_AVG_PERIOD  = 14         # period for RSI average

# Stage bands: (max_pct_below_high, tqqq_stage_factor)
# QQQ near 52-week high → full position; deeper drawdown → smaller position
STAGE_BANDS = [
    ( 5.0, 1.00),   # 0–5%   below high → 100% TQQQ
    (10.0, 0.70),   # 5–10%  below high →  70% TQQQ
    (15.0, 0.30),   # 10–15% below high →  30% TQQQ
    (float("inf"), 0.00),  # >15%  below high →   0% TQQQ
]


# ---------------------------------------------------------------------------
# Data loader (reads from local DB)
# ---------------------------------------------------------------------------

def _load_ohlcv(ticker: str) -> pd.DataFrame:
    conn = sqlite3.connect(database.DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker = ? ORDER BY date",
        conn, params=(ticker,)
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    return df


# ---------------------------------------------------------------------------
# Indicator calculations
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(50)


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    up   = high - high.shift(1)
    down = low.shift(1) - low
    dm_p = up.where((up > down)   & (up   > 0), 0.0)
    dm_m = down.where((down > up) & (down > 0), 0.0)

    alpha = 1 / period
    atr   = tr.ewm(alpha=alpha,   adjust=False, min_periods=period).mean()
    smp   = dm_p.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    smm   = dm_m.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    di_p  = 100 * smp / atr.replace(0, float("nan"))
    di_m  = 100 * smm / atr.replace(0, float("nan"))
    denom = (di_p + di_m).replace(0, float("nan"))
    dx    = 100 * (di_p - di_m).abs() / denom
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def build_indicators(qqq: pd.DataFrame) -> pd.DataFrame:
    df = qqq.copy()
    df["ema_5"]  = _ema(df["close"], EMA_FAST)
    df["ema_20"] = _ema(df["close"], EMA_SLOW)
    df["adx"]    = _adx(df)
    df["rsi"]    = _rsi(df["close"])
    return df


# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------

def compute_signals(ind: pd.DataFrame) -> pd.DataFrame:
    """
    Apply EMA cross + ADX + RSI rules row-by-row, tracking hold days
    and whipsaw filter. Adds columns:
        ema_dir, adx_valid, rsi_confirms, raw_signal,
        signal, hold_days, whipsaw_filtered, filter_reason
    """
    df = ind.copy()

    df["ema_dir"]     = (df["ema_5"] > df["ema_20"]).map({True: "BULLISH", False: "BEARISH"})
    df["adx_valid"]   = df["adx"] >= ADX_TRADE
    df["rsi_confirms"] = (
        ((df["ema_dir"] == "BULLISH") & (df["rsi"] >= 50)) |
        ((df["ema_dir"] == "BEARISH") & (df["rsi"] <= 50))
    )

    # Raw desired signal from EMA direction alone
    df["raw_signal"] = df["ema_dir"].map({"BULLISH": "BUY_TQQQ", "BEARISH": "BUY_SQQQ"})

    signals      = []
    hold_days    = []
    filtered     = []
    filter_rsns  = []

    current_sig       = None
    hold_count        = 0
    post_forced_exit  = False   # use lower ADX_REENTRY threshold after forced flat

    for i, row in df.iterrows():
        desired   = row["raw_signal"]
        adx       = row["adx"]
        # Entry threshold: lower after a forced exit to re-engage sooner
        adx_entry = ADX_REENTRY if post_forced_exit else ADX_TRADE

        # First bar — initialise without filters
        if current_sig is None:
            if adx >= adx_entry and row["rsi_confirms"]:
                current_sig      = desired
                post_forced_exit = False
            else:
                current_sig = "NO_TRADE"
            hold_count = 0
            signals.append(current_sig)
            hold_days.append(hold_count)
            filtered.append(False)
            filter_rsns.append(None)
            hold_count += 1
            continue

        # Forced exit if ADX collapses below hard floor
        if adx < ADX_FORCE and current_sig != "NO_TRADE":
            current_sig      = "NO_TRADE"
            hold_count       = 0
            post_forced_exit = True
            signals.append(current_sig)
            hold_days.append(hold_count)
            filtered.append(False)
            filter_rsns.append(f"Forced exit: ADX={adx:.1f} < {ADX_FORCE}")
            hold_count += 1
            continue

        want_change = (desired != current_sig and current_sig != "NO_TRADE") or \
                      (current_sig == "NO_TRADE" and adx >= adx_entry and row["rsi_confirms"])

        if not want_change:
            signals.append(current_sig)
            hold_days.append(hold_count)
            filtered.append(False)
            filter_rsns.append(None)
            hold_count += 1
            continue

        # A change is desired — run whipsaw checks
        reason = None
        if adx < adx_entry:
            reason = f"ADX={adx:.1f} < {adx_entry} — chop, no new trades"
        elif not row["rsi_confirms"]:
            reason = f"RSI={row['rsi']:.1f} does not confirm {row['ema_dir']} EMA — skipping"
        elif hold_count < MIN_HOLD and current_sig != "NO_TRADE":
            reason = f"Whipsaw filter: held only {hold_count} day(s) (min {MIN_HOLD})"

        if reason:
            signals.append(current_sig)
            hold_days.append(hold_count)
            filtered.append(True)
            filter_rsns.append(reason)
            hold_count += 1
        else:
            current_sig      = desired
            post_forced_exit = False
            hold_count       = 0
            signals.append(current_sig)
            hold_days.append(hold_count)
            filtered.append(False)
            filter_rsns.append(None)
            hold_count += 1

    df["signal"]           = signals
    df["hold_days"]        = hold_days
    df["whipsaw_filtered"] = filtered
    df["filter_reason"]    = filter_rsns
    return df


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def position_size(qqq_close: float, ema_20: float, etf_price: float,
                  risk: float = RISK_DOLLARS) -> dict:
    """
    Stop level = QQQ EMA20 (the signal flip level).
    Risk/share on the ETF = (QQQ distance to EMA20 / QQQ price) * leverage * ETF price.
    Shares      = floor(risk / risk_per_share).
    """
    from math import floor
    qqq_stop_dist   = abs(qqq_close - ema_20)
    qqq_stop_pct    = qqq_stop_dist / qqq_close if qqq_close > 0 else 0
    risk_per_share  = round(qqq_stop_pct * LEVERAGE * etf_price, 4)
    shares          = floor(risk / risk_per_share) if risk_per_share > 0 else 0
    cost            = round(shares * etf_price, 2)
    return {
        "etf_price":       round(etf_price, 2),
        "qqq_stop_level":  round(ema_20, 2),
        "qqq_stop_dist":   round(qqq_stop_dist, 2),
        "risk_per_share":  risk_per_share,
        "shares":          shares,
        "estimated_cost":  cost,
        "risk_dollars":    risk,
    }


# ---------------------------------------------------------------------------
# Dual Strategy position sizing (% of portfolio)
# ---------------------------------------------------------------------------

def compute_dual_position(sig_df: pd.DataFrame,
                          capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Computes TQQQ and SQQQ position sizes as % of portfolio.

    Algorithm (matches screenshot from Aug 5 2025):
      1. PercentHigh  = (rolling-252-day-high - close) / rolling-high × 100
      2. StageFactor  = from STAGE_BANDS lookup
      3. Reduction factors (each in 0..1, multiplied together):
           breakoutFailureFactor  — placeholder, always 1.0 for now
           currRSIBreakFactor     — reduces if RSI_Today << RSI_Average
           currMADownFactor       — placeholder, always 1.0 for now
           currRSIROCFactor       — placeholder, always 1.0 for now
      4. Result (TQQQ%) = StageFactor × all factors × 100  (integer)
      5. SQQQ%:  0 when signal is BUY_TQQQ; equals Result when BUY_SQQQ
    """
    row     = sig_df.iloc[-1]
    signal  = row["signal"]
    close   = float(row["close"])

    # PercentHigh
    rolling_high = float(
        sig_df["close"].rolling(HIGH_PERIOD, min_periods=1).max().iloc[-1]
    )
    percent_high = round((rolling_high - close) / rolling_high * 100, 2) \
                   if rolling_high > 0 else 0.0

    # RSI values
    rsi_today = round(float(row["rsi"]), 2)
    rsi_avg   = round(
        float(sig_df["rsi"].rolling(RSI_AVG_PERIOD, min_periods=1).mean().iloc[-1]), 2
    )

    # StageFactor
    stage_factor = 0.0
    for max_pct, factor in STAGE_BANDS:
        if percent_high < max_pct:
            stage_factor = factor
            break

    # Reduction factors
    breakout_failure_factor = 1.0
    # currRSIBreakFactor: reduce when RSI_Today is meaningfully below RSI_Average
    rsi_ratio = rsi_today / rsi_avg if rsi_avg > 0 else 1.0
    curr_rsi_break_factor = round(min(1.0, max(0.0, rsi_ratio)), 2) \
                            if rsi_ratio < 0.85 else 1.0
    curr_ma_down_factor  = 1.0   # future: reduce when QQQ below key MAs
    curr_rsi_roc_factor  = 1.0   # future: reduce when RSI momentum falling

    combined = (stage_factor * breakout_failure_factor *
                curr_rsi_break_factor * curr_ma_down_factor * curr_rsi_roc_factor)
    result = int(round(combined * 100))   # position size as integer %

    tqqq_pct  = result if signal == "BUY_TQQQ" else 0
    sqqq_pct  = result if signal == "BUY_SQQQ" else 0

    tqqq_dollars = round(capital * tqqq_pct / 100, 2)
    sqqq_dollars = round(capital * sqqq_pct / 100, 2)

    return {
        "strategy":               "Dual",
        "tqqq_position_size":     tqqq_pct,
        "sqqq_position_size":     sqqq_pct,
        "percent_high":           percent_high,
        "rsi_today":              rsi_today,
        "rsi_average":            rsi_avg,
        "result":                 result,
        "stage_factor":           stage_factor,
        "breakout_failure_factor": breakout_failure_factor,
        "curr_rsi_break_factor":  curr_rsi_break_factor,
        "curr_ma_down_factor":    curr_ma_down_factor,
        "curr_rsi_roc_factor":    curr_rsi_roc_factor,
        "capital":                capital,
        "tqqq_dollars":           tqqq_dollars,
        "sqqq_dollars":           sqqq_dollars,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _confidence(row: pd.Series) -> str:
    if not row["adx_valid"] or not row["rsi_confirms"]:
        return "LOW"
    adx = row["adx"]
    rsi = row["rsi"]
    rsi_margin = abs(rsi - 50)
    if adx >= 30 and rsi_margin >= 5:
        return "HIGH"
    if adx >= 20:
        return "MEDIUM"
    return "LOW"


def build_json(sig_df: pd.DataFrame, etf_prices: dict) -> dict:
    row  = sig_df.iloc[-1]
    date = sig_df.index[-1].strftime("%Y-%m-%d")
    sig  = row["signal"]

    if sig == "BUY_TQQQ":
        action, instrument = "ENTER_LONG", BULL_ETF
    elif sig == "BUY_SQQQ":
        action, instrument = "ENTER_SHORT", BEAR_ETF
    elif sig == "NO_TRADE":
        action, instrument = "HOLD", "NONE"
    else:
        action, instrument = "HOLD", "NONE"

    all_met = (row["adx_valid"] and row["rsi_confirms"] and
               not row["whipsaw_filtered"] and sig != "NO_TRADE")

    prev_sig = sig_df["signal"].iloc[-2] if len(sig_df) > 1 else sig
    if sig != prev_sig and sig != "NO_TRADE":
        action = "ENTER_LONG" if sig == "BUY_TQQQ" else "ENTER_SHORT"
    elif sig != "NO_TRADE" and row["hold_days"] > 0:
        action = "HOLD"

    rsi_confirms = bool(row["rsi_confirms"])
    notes = _generate_notes(row, sig, prev_sig)

    etf_price = etf_prices.get(instrument, 0.0)
    sizing = position_size(float(row["close"]), float(row["ema_20"]), etf_price)

    return {
        "date":               date,
        "signal":             sig,
        "action":             action,
        "instrument":         instrument,
        "ema_5":              round(float(row["ema_5"]),  4),
        "ema_20":             round(float(row["ema_20"]), 4),
        "ema_direction":      row["ema_dir"],
        "adx_14":             round(float(row["adx"]),   2),
        "adx_valid":          bool(row["adx_valid"]),
        "rsi_14":             round(float(row["rsi"]),   2),
        "rsi_confirms":       rsi_confirms,
        "all_conditions_met": all_met,
        "whipsaw_filtered":   bool(row["whipsaw_filtered"]),
        "filter_reason":      row["filter_reason"],
        "confidence":         _confidence(row),
        "hold_days_current":  int(row["hold_days"]),
        "etf_price":          sizing["etf_price"],
        "qqq_stop_level":     sizing["qqq_stop_level"],
        "risk_per_share":     sizing["risk_per_share"],
        "shares":             sizing["shares"],
        "estimated_cost":     sizing["estimated_cost"],
        "risk_dollars":       sizing["risk_dollars"],
        "notes":              notes,
    }


def _generate_notes(row, sig, prev_sig) -> str:
    parts = []
    parts.append(f"5-EMA={row['ema_5']:.2f} {'>' if row['ema_dir']=='BULLISH' else '<'} "
                 f"20-EMA={row['ema_20']:.2f} ({row['ema_dir']}).")
    parts.append(f"ADX={row['adx']:.1f} "
                 f"({'valid' if row['adx_valid'] else 'INVALID — below ' + str(ADX_TRADE)}).")
    parts.append(f"RSI={row['rsi']:.1f} "
                 f"({'confirms' if row['rsi_confirms'] else 'CONFLICTS'}).")
    if row["whipsaw_filtered"]:
        parts.append(f"Signal filtered: {row['filter_reason']}.")
    elif sig != prev_sig and sig != "NO_TRADE":
        parts.append(f"NEW SIGNAL — switch to {sig}.")
    elif sig == "NO_TRADE":
        parts.append("No trade: conditions not met.")
    else:
        parts.append(f"Hold {sig} ({int(row['hold_days'])} day(s)).")
    return " ".join(parts)


def print_table(sig_df: pd.DataFrame, lookback: int, etf_prices: dict) -> None:
    recent = sig_df.tail(lookback)
    print("=" * 128)
    print(f"  WHITELIGHT SIGNAL TABLE — last {lookback} trading days")
    print("=" * 128)
    print(f"{'Date':<12} {'QQQ':>8} {'EMA5':>8} {'EMA20':>8} {'ADX':>6} "
          f"{'RSI':>6} {'Dir':<9} {'Signal':<11} {'Hold':>5} "
          f"{'ETF Px':>8} {'Shs':>5} {'~Cost':>8} {'Filtered'}")
    print("-" * 128)
    prev = sig_df["signal"].shift(1)
    for date, row in recent.iterrows():
        flip = " <<" if row["signal"] != prev.loc[date] and row["signal"] != "NO_TRADE" else ""
        filt = "YES" if row["whipsaw_filtered"] else ""
        sig  = row["signal"]
        instr = BULL_ETF if sig == "BUY_TQQQ" else (BEAR_ETF if sig == "BUY_SQQQ" else "NONE")
        ep    = etf_prices.get(instr, 0.0)
        sz    = position_size(float(row["close"]), float(row["ema_20"]), ep) if ep > 0 else {}
        ep_s  = f"{ep:.2f}"          if ep   > 0 else "N/A"
        sh_s  = str(sz.get("shares", "N/A"))
        cost_s = f"${sz['estimated_cost']:,.0f}" if sz.get("estimated_cost") else "N/A"
        print(f"{date.strftime('%Y-%m-%d'):<12} {row['close']:>8.2f} "
              f"{row['ema_5']:>8.2f} {row['ema_20']:>8.2f} "
              f"{row['adx']:>6.1f} {row['rsi']:>6.1f} "
              f"{row['ema_dir']:<9} {(sig + flip):<11} "
              f"{int(row['hold_days']):>5} "
              f"{ep_s:>8} {sh_s:>5} {cost_s:>8}  {filt}")
    print("-" * 128)
    print()


def write_signal_file(payload: dict) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whitelight_signal.txt")
    lines = [f"{k}={v}" for k, v in payload.items()]
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Whitelight EMA/ADX/RSI signal engine")
    ap.add_argument("--lookback",  type=int,    default=30,            help="Days to show in table (default 30)")
    ap.add_argument("--capital",   type=float,  default=DEFAULT_CAPITAL, help="Portfolio capital for position sizing")
    ap.add_argument("--json-only", action="store_true",                help="Print JSON signal only and exit")
    args = ap.parse_args()

    # Load QQQ from DB
    try:
        qqq = _load_ohlcv(SIGNAL_TKR)
    except Exception as e:
        print(json.dumps({"error": f"Could not load {SIGNAL_TKR} from DB: {e}"}))
        sys.exit(1)

    if len(qqq) < MIN_BARS:
        print(json.dumps({"error": f"Insufficient data — minimum {MIN_BARS} daily closes required"}))
        sys.exit(1)

    # Load latest ETF close prices for position sizing
    etf_prices = {}
    for etf in (BULL_ETF, BEAR_ETF):
        try:
            etf_df = _load_ohlcv(etf)
            etf_prices[etf] = float(etf_df["close"].iloc[-1])
        except Exception:
            etf_prices[etf] = 0.0

    ind     = build_indicators(qqq)
    sig_df  = compute_signals(ind)
    payload = build_json(sig_df, etf_prices)
    dual    = compute_dual_position(sig_df, args.capital)

    if args.json_only:
        print(json.dumps({**payload, **dual}, indent=2))
        return

    # Human-readable output
    print(f"\n=== Whitelight Strategy — {datetime.date.today()} ===\n")
    print_table(sig_df, args.lookback, etf_prices)

    print("=" * 66)
    print("  TODAY'S SIGNAL")
    print("=" * 66)
    for k, v in payload.items():
        print(f"  {k:<22}: {v}")
    print("=" * 66)
    print()

    print("=" * 66)
    print("  DUAL STRATEGY POSITION SIZING")
    print("=" * 66)
    print(f"  Strategy               : {dual['strategy']}")
    print(f"  TQQQ Position Size     : {dual['tqqq_position_size']}%  (${dual['tqqq_dollars']:,.0f})")
    print(f"  SQQQ Position Size     : {dual['sqqq_position_size']}%  (${dual['sqqq_dollars']:,.0f})")
    print()
    print(f"  Extra Info :")
    print(f"  PercentHigh            : {dual['percent_high']}")
    print(f"  RSI_Today              : {dual['rsi_today']}")
    print(f"  RSI_Average            : {dual['rsi_average']}")
    print(f"  Result                 : {dual['result']}")
    print(f"  StageFactor            : {dual['stage_factor']}")
    print(f"  breakoutFailureFactor  : {dual['breakout_failure_factor']}")
    print(f"  currRSIBreakFactor     : {dual['curr_rsi_break_factor']}")
    print(f"  currMADownFactor       : {dual['curr_ma_down_factor']}")
    print(f"  currRSIROCFactor       : {dual['curr_rsi_roc_factor']}")
    print(f"  Capital                : ${dual['capital']:,.0f}")
    print("=" * 66)
    print()

    path = write_signal_file(payload)
    print(f"  Signal written to: {path}")
    print()


if __name__ == "__main__":
    main()
