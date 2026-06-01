"""
higher_lows_strategy.py -- Higher Lows Breakout Strategy vs Tushar v1

STRATEGY RULES
--------------
Entry (all must be true on the same day):
  1. Higher lows: TQQQ 20-day rolling minimum is ascending over 3 consecutive
     20-day periods  (roll_min[today] > roll_min[today-20] > roll_min[today-40]).
  2. TQQQ closes above 50-day MA (fresh crossover -- was below 50d within past 10 days).
  3. TQQQ closes above 20-day MA (white-line resistance broken).

Exit (either condition):
  (TQQQ close < 20-day MA  OR  TQQQ close < 50-day MA)
  AND  TQQQ daily change <= -2%   (large red candle)

COMPARISON
----------
  Columns: QQQ Buy&Hold | TQQQ Buy&Hold | Tushar v1 | Higher Lows Breakout

USAGE
-----
  python higher_lows_strategy.py               # current year
  python higher_lows_strategy.py --all         # all years since DATA_START
  python higher_lows_strategy.py --capital 50000 --all
"""

import argparse
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

# -- Constants -----------------------------------------------------------------
QQQ_TICKER       = "QQQ"
TQQQ_TICKER      = "TQQQ"
DEFAULT_CAPITAL  = 100_000.0
HIGH_PERIOD      = 252        # Tushar v1: 252-day rolling high
SIGNAL_THRESHOLD = 15.0       # Tushar v1: % below that high -> CASH
REENTRY_DAYS     = 3          # Tushar v1: consecutive days < 15% -> re-enter
DATA_START       = "2015-01-01"

MA_MEDIUM        = 20         # 20-day MA (white line / resistance)
MA_SHORT         = 50         # 50-day MA (yellow line)
HL_WINDOW        = 20         # rolling window for higher-lows detection
CROSSOVER_LOOKBACK = 10       # "fresh" if below 50d within this many days
EXIT_DROP        = -0.02      # -2% daily drop triggers exit

MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# -- Data loading --------------------------------------------------------------

def _load(ticker: str, start: str = DATA_START) -> pd.DataFrame:
    try:
        raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            raise ValueError("empty")
    except Exception:
        raw = yf.Ticker(ticker).history(start=start, auto_adjust=True)
    df = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


# -- Tushar v1 (embedded) ------------------------------------------------------

def compute_signal_v1(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """Original TusharStrategy: QQQ 15%-below-252d-high rule."""
    df = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100

    regime_list, action_list = [], []
    days_below = 0
    in_tqqq    = True
    prev_in    = False

    for pcthi in df["pcthi"]:
        if pcthi >= SIGNAL_THRESHOLD:
            days_below = 0
            in_tqqq    = False
        else:
            days_below += 1
            if days_below >= REENTRY_DAYS:
                in_tqqq = True

        act = "BUY" if (in_tqqq and not prev_in) else "SELL" if (not in_tqqq and prev_in) else "HOLD"
        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        prev_in = in_tqqq

    df["regime"] = regime_list
    df["action"] = action_list
    return df


# -- Higher Lows Breakout Strategy ---------------------------------------------

def compute_signal_hl(tqqq_df: pd.DataFrame) -> pd.DataFrame:
    """
    Higher Lows Breakout: enter on ascending 20d-min pattern + 50d-MA crossover.
    Exit on large red candle (< -2%) closing below 20d or 50d MA.
    """
    df = tqqq_df.copy()
    df["ma20"] = df["close"].rolling(MA_MEDIUM, min_periods=1).mean()
    df["ma50"] = df["close"].rolling(MA_SHORT,  min_periods=1).mean()
    df["ret"]  = df["close"].pct_change().fillna(0.0)

    # Higher lows: ascending rolling minimums across 3 consecutive HL_WINDOW periods
    roll_min = df["close"].rolling(HL_WINDOW, min_periods=HL_WINDOW).min()
    rm1 = roll_min.shift(HL_WINDOW)
    rm2 = roll_min.shift(2 * HL_WINDOW)
    df["hl"] = (roll_min > rm1) & (rm1 > rm2) & roll_min.notna() & rm1.notna() & rm2.notna()

    # Fresh 50d crossover: currently above ma50, was below within past CROSSOVER_LOOKBACK days
    above50 = df["close"] >= df["ma50"]
    below50_recent = (~above50).rolling(CROSSOVER_LOOKBACK, min_periods=1).max().astype(bool)
    df["fresh_cross"] = above50 & below50_recent

    # Precompute arrays for fast loop
    hl_arr    = df["hl"].values
    fc_arr    = df["fresh_cross"].values
    close_arr = df["close"].values
    ma20_arr  = df["ma20"].values
    ma50_arr  = df["ma50"].values
    ret_arr   = df["ret"].values

    regime_list = []
    action_list = []
    entry_list  = []
    exit_list   = []
    in_tqqq = False
    prev_in = False

    for i in range(len(df)):
        hl    = bool(hl_arr[i])
        fc    = bool(fc_arr[i])
        close = float(close_arr[i])
        ma20  = float(ma20_arr[i])
        ma50  = float(ma50_arr[i])
        ret   = float(ret_arr[i])

        # Exit: large red candle AND close below 20d or 50d MA
        exit_sig = in_tqqq and (close < ma20 or close < ma50) and (ret <= EXIT_DROP)

        # Entry: higher lows + fresh 50d crossover + close above 20d MA
        entry_sig = (not in_tqqq) and hl and fc and (close >= ma20)

        if exit_sig:
            in_tqqq = False
        if entry_sig:
            in_tqqq = True

        act = "BUY" if (in_tqqq and not prev_in) else "SELL" if (not in_tqqq and prev_in) else "HOLD"
        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        action_list.append(act)
        entry_list.append(entry_sig)
        exit_list.append(exit_sig)
        prev_in = in_tqqq

    df["regime"] = regime_list
    df["action"] = action_list
    df["entry"]  = entry_list
    df["exit"]   = exit_list
    return df


# -- Backtest engine -----------------------------------------------------------

def _price_on(df: pd.DataFrame, dt) -> float | None:
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest(sig_df: pd.DataFrame, price_df: pd.DataFrame,
                 capital: float) -> list[dict]:
    shares  = 0
    cash    = capital
    daily   = []
    prev_in = False

    for dt, row in sig_df.iterrows():
        p = _price_on(price_df, dt)
        if p is None:
            continue
        in_pos = (row["regime"] == "BUY_TQQQ")

        if in_pos and not prev_in:
            ns     = math.floor(cash / p) if p > 0 else 0
            cash  -= ns * p
            shares = ns
        elif not in_pos and prev_in:
            cash  += shares * p
            shares = 0

        prev_in = in_pos
        port    = round(shares * p + cash, 2)
        daily.append({
            "date":      dt,
            "portfolio": port,
            "regime":    row["regime"],
            "action":    row["action"],
            "close":     p,
            "entry":     bool(row.get("entry", False)),
            "exit":      bool(row.get("exit",  False)),
            "pcthi":     float(row.get("pcthi", 0.0)),
        })
    return daily


def run_buyhold(price_df: pd.DataFrame, capital: float) -> list[dict]:
    """Simple buy-and-hold from first available date."""
    shares = 0
    cash   = capital
    daily  = []

    for i, (dt, row) in enumerate(price_df.iterrows()):
        p = float(row["close"])
        if i == 0:
            shares = math.floor(cash / p) if p > 0 else 0
            cash  -= shares * p
        port = round(shares * p + cash, 2)
        daily.append({
            "date":      dt,
            "portfolio": port,
            "regime":    "BUY",
            "action":    "HOLD",
            "close":     p,
            "entry":     False,
            "exit":      False,
            "pcthi":     0.0,
        })
    return daily


# -- Reporting helpers ---------------------------------------------------------

def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _ticker_monthly_rets(df: pd.DataFrame) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d, row in df.iterrows():
        bm[(d.year, d.month)].append(float(row["close"]))
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(v: float | None, w: int = 8) -> str:
    if v is None:
        return "  N/A  ".rjust(w)
    s = "+" if v >= 0 else ""
    return f"{s}{v:.1f}%".rjust(w)


def _diff(a: float | None, b: float | None, w: int = 9) -> str:
    if a is None or b is None:
        return "  N/A".rjust(w)
    v = a - b
    return (("+" if v >= 0 else "") + f"{v:.1f}%").rjust(w)


# -- Main comparison printer ---------------------------------------------------

def print_comparison(
    daily_v1:  list[dict],
    daily_hl:  list[dict],
    daily_tbh: list[dict],
    qqq_df:    pd.DataFrame,
    years:     list[int],
    capital:   float,
) -> None:
    r_v1  = _monthly_rets(daily_v1)
    r_hl  = _monthly_rets(daily_hl)
    r_tbh = _monthly_rets(daily_tbh)
    r_q   = _ticker_monthly_rets(qqq_df)

    W   = 98
    SEP = "=" * W
    DIV = "-" * W

    cum_q   = capital
    cum_tbh = capital
    cum_v1  = capital
    cum_hl  = capital

    print(f"\n{SEP}")
    print(f"  COMPARISON: QQQ B&H  |  TQQQ B&H  |  Tushar v1  |  Higher Lows Breakout")
    print(f"  Entry: ascending 20d-min x3 + close > 50d MA (fresh cross) + close > 20d MA")
    print(f"  Exit:  close < 20d or 50d MA  AND  daily change <= -2%")
    print(f"  Capital: ${capital:,.0f}")
    print(SEP)

    yr_totals = []
    all_years = sorted(set(ym[0] for ym in r_v1 if ym[0] in years))

    for year in all_years:
        months = sorted(ym for ym in r_v1 if ym[0] == year)
        if not months:
            continue

        yq0   = cum_q
        ytbh0 = cum_tbh
        yv10  = cum_v1
        yhl0  = cum_hl

        yr_entries = sum(1 for d in daily_hl if d.get("entry") and d["date"].year == year)
        yr_exits   = sum(1 for d in daily_hl if d.get("exit")  and d["date"].year == year)

        print(f"\n  -- {year} {'-'*74}")
        print(f"  {'Month':<7} {'QQQ B&H':>8}  {'TQQQ B&H':>9}  {'Tushar v1':>10}  {'HigherLows':>11}  {'HL vs v1':>9}  Notes")
        print(DIV)

        for ym in months:
            m   = ym[1]
            q   = r_q.get(ym)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)
            hl  = r_hl.get(ym)

            if q:   cum_q   *= 1 + q   / 100
            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100
            if hl:  cum_hl  *= 1 + hl  / 100

            notes = ""
            m_e = sum(1 for d in daily_hl if d.get("entry") and d["date"].year == ym[0] and d["date"].month == ym[1])
            m_x = sum(1 for d in daily_hl if d.get("exit")  and d["date"].year == ym[0] and d["date"].month == ym[1])
            if m_e: notes += f" E{m_e}"
            if m_x: notes += f" X{m_x}"

            print(f"  {MONTHS[m]:<7} {_fmt(q):>8}  {_fmt(tbh):>9}  {_fmt(v1):>10}  "
                  f"{_fmt(hl):>11}  {_diff(hl, v1):>9}  {notes}")

        fy_q   = round((cum_q   / yq0   - 1) * 100, 1)
        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        fy_hl  = round((cum_hl  / yhl0  - 1) * 100, 1)
        yr_totals.append((year, fy_q, fy_tbh, fy_v1, fy_hl, yr_entries, yr_exits))

        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_q):>8}  {_fmt(fy_tbh):>9}  {_fmt(fy_v1):>10}  "
              f"{_fmt(fy_hl):>11}  {_diff(fy_hl, fy_v1):>9}  E{yr_entries} X{yr_exits}")

    if len(all_years) > 1:
        print(f"\n{SEP}")
        print(f"  ANNUAL SUMMARY")
        print(DIV)
        print(f"  {'Year':<7} {'QQQ B&H':>8}  {'TQQQ B&H':>9}  {'Tushar v1':>10}  {'HigherLows':>11}  {'HL vs v1':>9}")
        print(DIV)
        for y, q, tbh, v1, hl, e, x in yr_totals:
            print(f"  {str(y):<7} {_fmt(q):>8}  {_fmt(tbh):>9}  {_fmt(v1):>10}  "
                  f"{_fmt(hl):>11}  {_diff(hl, v1):>9}  E{e} X{x}")
        print(DIV)

        n_yrs = (date.today().year - all_years[0]) + \
                (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr  = lambda x: round(((x / capital) ** (1 / n_yrs) - 1) * 100, 1) if n_yrs > 0 and x > 0 else 0.0

        ov_q   = round((cum_q   / capital - 1) * 100, 1)
        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)
        ov_hl  = round((cum_hl  / capital - 1) * 100, 1)
        cg_q   = cagr(cum_q)
        cg_tbh = cagr(cum_tbh)
        cg_v1  = cagr(cum_v1)
        cg_hl  = cagr(cum_hl)

        t_entries = sum(1 for d in daily_hl if d.get("entry"))
        t_exits   = sum(1 for d in daily_hl if d.get("exit"))

        print(f"  {'Total %':<7} {_fmt(ov_q):>8}  {_fmt(ov_tbh):>9}  {_fmt(ov_v1):>10}  "
              f"{_fmt(ov_hl):>11}  {_diff(ov_hl, ov_v1):>9}  E{t_entries} X{t_exits}")
        print(f"  {'CAGR':<7} {_fmt(cg_q):>8}  {_fmt(cg_tbh):>9}  {_fmt(cg_v1):>10}  "
              f"{_fmt(cg_hl):>11}  {_diff(cg_hl, cg_v1):>9}")
        print(SEP)

    # Entry / exit event log
    events = []
    for d in daily_hl:
        if d.get("entry"):
            events.append((d["date"], "ENTRY", d["close"]))
        if d.get("exit"):
            events.append((d["date"], "EXIT",  d["close"]))

    if events:
        n_e = sum(1 for _, t, _ in events if t == "ENTRY")
        n_x = sum(1 for _, t, _ in events if t == "EXIT")
        print(f"\n  HIGHER LOWS BREAKOUT EVENTS  ({n_e} entries, {n_x} exits)")
        print(f"  {'Date':<12}  {'Type':<7}  {'TQQQ Close':>10}")
        print(f"  {'-'*35}")
        for dt, typ, p in sorted(events):
            print(f"  {str(dt.date()):<12}  {typ:<7}  ${p:>9.2f}")
    print()


# -- CLI -----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Higher Lows Breakout strategy vs Tushar v1"
    )
    ap.add_argument("--all",     action="store_true",
                    help="Show all years since DATA_START (default: current year only)")
    ap.add_argument("--capital", type=float, default=DEFAULT_CAPITAL,
                    help=f"Starting capital (default: {DEFAULT_CAPITAL:,.0f})")
    ap.add_argument("--start",   default=DATA_START,
                    help=f"Data start date (default: {DATA_START})")
    args = ap.parse_args()

    print("Loading data...")
    qqq_df  = _load(QQQ_TICKER,  args.start)
    tqqq_df = _load(TQQQ_TICKER, args.start)

    print("Computing signals...")
    sig_v1 = compute_signal_v1(qqq_df)
    sig_hl = compute_signal_hl(tqqq_df)

    # Align to common date range
    common   = sig_v1.index.intersection(sig_hl.index)
    sig_v1   = sig_v1.loc[common]
    sig_hl   = sig_hl.loc[common]
    qqq_algn = qqq_df.loc[qqq_df.index.intersection(common)]
    tqqq_alg = tqqq_df.loc[tqqq_df.index.intersection(common)]

    print("Running backtests...")
    daily_v1  = run_backtest(sig_v1, tqqq_alg, args.capital)   # v1 signal -> TQQQ position
    daily_hl  = run_backtest(sig_hl, tqqq_alg, args.capital)   # HL signal -> TQQQ position
    daily_tbh = run_buyhold(tqqq_alg, args.capital)            # TQQQ buy-and-hold

    if args.all:
        years = list(range(int(args.start[:4]), date.today().year + 1))
    else:
        years = [date.today().year]

    print_comparison(daily_v1, daily_hl, daily_tbh, qqq_algn, years, args.capital)


if __name__ == "__main__":
    main()
