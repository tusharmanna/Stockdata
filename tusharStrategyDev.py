"""
tusharStrategyDev.py  --  Trading Strategies: v1

STRATEGIES
----------
v1 (TusharStrategy):
  - Watch QQQ distance from its rolling 189-day high.
  - QQQ within 15% of that high  -> hold TQQQ  (bull regime)
  - QQQ falls > 15% below that high -> go to CASH
  - Re-entry: 3 consecutive days back below 15% threshold.

"""

import argparse
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

# -- Constants -----------------------------------------------------------------
QQQ_TICKER        = "QQQ"
TQQQ_TICKER       = "TQQQ"
SQQQ_TICKER       = "SQQQ"        # 3x inverse QQQ for hedging
DEFAULT_CAPITAL   = 100_000.0

# v1 constants
HIGH_PERIOD       = 189           # proven period from tushar_strategy.py
SIGNAL_THRESHOLD  = 15.0
REENTRY_DAYS      = 3


DATA_START        = "2010-01-01"  # warmup start for accurate rolling high

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


# -- Strategy 1: TusharStrategy v1 (fixed position sizing) --------------------

def compute_signal_v1(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """QQQ 15%-below-252d-high rule."""
    df = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100

    regime_list, days_list, action_list = [], [], []
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
        days_list.append(days_below)
        action_list.append(act)
        prev_in = in_tqqq

    df["regime"]     = regime_list
    df["days_below"] = days_list
    df["action"]     = action_list
    return df




def _price_on(df: pd.DataFrame, dt) -> float | None:
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest(sig_df: pd.DataFrame, price_df, capital: float) -> list[dict]:
    """Backtest with position sizing.

    Single-asset mode (price_df is a DataFrame): v1-v5 behavior, unchanged.
    Multi-asset mode (price_df is a dict[str, DataFrame], e.g. {"TQQQ": ..., "SQQQ": ...}):
        sig_df must include an "asset" column. On asset switch the current position is
        liquidated and the new asset is bought. v6 also applies an 8% trailing stop on
        the BEAR_HEDGE portfolio: if drawdown from BEAR_HEDGE peak exceeds the stop,
        the position is forced to CASH until regime leaves BEAR_HEDGE.
    """
    multi_asset = isinstance(price_df, dict)

    shares        = 0
    cash          = capital
    daily         = []
    current_asset = None       # multi-asset only
    bear_peak     = 0.0        # multi-asset only
    stop_active   = False      # multi-asset only

    for dt, row in sig_df.iterrows():
        if multi_asset:
            target_asset = row.get("asset", "CASH")
            regime       = row.get("regime", "")
            pos_size     = row.get("position_size", 0.0)

            # Mark-to-market of current position
            if current_asset and current_asset != "CASH":
                p_cur = _price_on(price_df[current_asset], dt)
                if p_cur is None:
                    continue
                port_value = shares * p_cur + cash
            else:
                p_cur = None
                port_value = cash

            # --- Trailing stop on BEAR_HEDGE ---
            if regime == "BEAR_HEDGE":
                if not stop_active:
                    bear_peak = max(bear_peak, port_value) if bear_peak > 0 else port_value
                    if port_value < bear_peak * (1 - BEAR_TRAILING_STOP):
                        stop_active  = True
                        target_asset = "CASH"
                        pos_size     = 0.0
                else:
                    # remain in CASH until regime leaves BEAR_HEDGE
                    target_asset = "CASH"
                    pos_size     = 0.0
            else:
                stop_active = False
                bear_peak   = 0.0

            # --- Asset switch: liquidate first ---
            if current_asset and current_asset != "CASH" and target_asset != current_asset:
                cash  += shares * p_cur
                shares = 0
                port_value = cash

            # --- Buy target asset to reach pos_size ---
            if target_asset == "CASH" or pos_size <= 0:
                shares        = 0
                current_asset = "CASH"
                price_for_log = p_cur if p_cur is not None else 0.0
            else:
                p_new = _price_on(price_df[target_asset], dt)
                if p_new is None:
                    continue
                target_dollars = pos_size * port_value
                target_shares  = math.floor(target_dollars / p_new) if p_new > 0 else 0
                delta_shares   = target_shares - shares
                if delta_shares > 0:
                    cost = delta_shares * p_new
                    if cost <= cash:
                        cash  -= cost
                        shares = target_shares
                elif delta_shares < 0:
                    shares  = target_shares
                    cash   += abs(delta_shares) * p_new
                current_asset = target_asset
                price_for_log = p_new

            port = round(shares * price_for_log + cash, 2)
            daily.append({
                "date":        dt,
                "portfolio":   port,
                "regime":      regime,
                "action":      row.get("action", "HOLD"),
                "position":    pos_size,
                "pcthi":       float(row.get("pcthi", 0.0)),
                "shares":      shares,
                "asset":       current_asset,
            })
            continue

        # --- Single-asset path (v1-v5, unchanged) ---
        p = _price_on(price_df, dt)
        if p is None:
            continue

        pos_size = row.get("position_size", 1.0 if row["regime"] == "BUY_TQQQ" else 0.0)
        port_value = shares * p + cash
        target_dollars = pos_size * port_value
        target_shares = math.floor(target_dollars / p) if p > 0 else 0
        delta_shares = target_shares - shares
        if delta_shares > 0:
            cost = delta_shares * p
            if cost <= cash:
                cash -= cost
                shares = target_shares
        elif delta_shares < 0:
            shares = target_shares
            cash += abs(delta_shares) * p

        port = round(shares * p + cash, 2)
        daily.append({
            "date":        dt,
            "portfolio":   port,
            "regime":      row["regime"],
            "action":      row["action"],
            "position":    pos_size,
            "pcthi":       float(row.get("pcthi", 0.0)),
            "shares":      shares,
        })
    return daily


def run_buyhold(price_df: pd.DataFrame, capital: float) -> list[dict]:
    shares = 0
    cash   = capital
    daily  = []
    for i, (dt, row) in enumerate(price_df.iterrows()):
        p = float(row["close"])
        if i == 0:
            shares = math.floor(cash / p) if p > 0 else 0
            cash  -= shares * p
        daily.append({"date": dt, "portfolio": round(shares * p + cash, 2),
                      "regime": "BUY_TQQQ", "action": "HOLD",
                      "pcthi": 0.0, "exposure": 50.0, "position_mult": 1.0})
    return daily


def optimize_v1(qqq_df: pd.DataFrame, tqqq_df: pd.DataFrame, capital: float) -> list[tuple]:
    """Grid search over HIGH_PERIOD, SIGNAL_THRESHOLD, REENTRY_DAYS for v1."""
    from itertools import product

    high_periods      = [63, 126, 189, 252]
    thresholds        = [8.0, 10.0, 12.0, 15.0, 18.0]
    reentry_days_list = [1, 2, 3, 5]

    results = []
    common = qqq_df.index.intersection(tqqq_df.index)
    tqqq_al = tqqq_df.loc[common]
    qqq_al = qqq_df.loc[common]

    print(f"  Running grid search over {len(high_periods)} × {len(thresholds)} × {len(reentry_days_list)} = {len(high_periods) * len(thresholds) * len(reentry_days_list)} combinations...\n")

    combo_count = 0
    for hp, thresh, rdays in product(high_periods, thresholds, reentry_days_list):
        combo_count += 1
        if combo_count % 20 == 0:
            print(f"  Processed {combo_count} combinations...")

        # Inline v1 signal with custom params
        df = qqq_al.copy()
        df["high_hp"] = df["close"].rolling(hp, min_periods=1).max()
        df["pcthi"]   = (df["high_hp"] - df["close"]) / df["high_hp"] * 100

        position_list = []
        days_below = 0
        position = 1.0

        for pcthi in df["pcthi"]:
            if pcthi >= thresh:
                days_below = 0
                position = 0.0
            else:
                days_below += 1
                if days_below >= rdays:
                    position = 1.0
            position_list.append(position)

        df["position_size"] = position_list
        df["regime"] = ["BUY_TQQQ" if p > 0 else "CASH" for p in position_list]
        df["action"] = "HOLD"

        daily = run_backtest(df, tqqq_al, capital)

        # Calculate CAGR and max drawdown
        portfolios = [d["portfolio"] for d in daily]
        final = portfolios[-1]
        n_yr = len(daily) / 252
        cagr = ((final / capital) ** (1 / n_yr) - 1) * 100 if n_yr > 0 and final > 0 else -100

        # Max drawdown
        peak = capital
        max_dd = 0.0
        for p in portfolios:
            if p > peak:
                peak = p
            dd = (peak - p) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Results: (cagr, -max_dd for sorting, hp, thresh, rdays, final, max_dd)
        results.append((cagr, -max_dd, hp, thresh, rdays, final, max_dd))

    # Sort by CAGR (descending), then by max_dd (ascending)
    results.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return results


def print_optimize_results(results: list[tuple], top_n: int = 20) -> None:
    """Print top N optimization results ranked by CAGR."""
    W = 95
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  v1 Parameter Optimization — Top {top_n} by CAGR")
    print(f"{SEP}\n")
    print(f"  {'Rank':<5} {'HIGH_PERIOD':>12} {'THRESH%':>10} {'REENTRY':>8} {'CAGR':>10} {'MaxDD':>10} {'Final $':>15}")
    print(DIV)

    for i, (cagr, _, hp, thresh, rdays, final, max_dd) in enumerate(results[:top_n], 1):
        print(f"  {i:<5} {hp:>12} {thresh:>9.1f}% {rdays:>8} {cagr:>9.1f}% {-max_dd:>9.1f}% ${final:>14,.0f}")

    print(f"\n{SEP}")
    print(f"  Current v1 defaults: HIGH_PERIOD=189, THRESHOLD=15.0%, REENTRY_DAYS=3")
    print(f"  To apply best combo, update the constants at the top of the file.\n")


def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i - 1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(x):
    return f"{x:+.1f}%" if x is not None else "—"


def _diff(a, b, width):
    if a is None or b is None:
        return "—"
    return f"{a - b:+.1f}%".rjust(width)


def print_backtest(daily_v1: list[dict], daily_tbh: list[dict], years: list[int],
                   capital: float) -> None:
    """Backtest results: v1 vs TQQQ B&H."""
    r_v1  = _monthly_rets(daily_v1)
    r_tbh = _monthly_rets(daily_tbh)

    W   = 65
    SEP = "=" * W
    DIV = "-" * W

    print(f"\n{SEP}")
    print(f"  TusharStrategy v1 Backtest  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")

    yr_totals = []
    cum_v1 = cum_tbh = capital

    for year in years:
        ytbh0 = cum_tbh
        yv10  = cum_v1

        print(f"  -- {year} " + "-" * (W - 10))
        print(f"  {'Month':<7} {'TQQQ B&H':>10} {'v1':>10}")
        print(DIV)

        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym)
            v1  = r_v1.get(ym)

            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100

            print(f"  {MONTHS[m]:<7} {_fmt(tbh):>10} {_fmt(v1):>10}")

        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        yr_totals.append((year, fy_tbh, fy_v1))
        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10}")

    if len(yr_totals) > 1:
        print(f"\n{SEP}")
        n_yr = (date.today().year - min(y for y, _, _ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0

        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)

        print(f"  {'Total %':<7} {_fmt(ov_tbh):>10} {_fmt(ov_v1):>10}")
        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10}")
        print(f"\n  Final values:  TQQQ B&H ${cum_tbh:,.0f}  |  v1 ${cum_v1:,.0f}")
        print(SEP)
    print()


def print_v8_comparison(daily_v1, daily_v8, daily_tbh, years, capital):
    r_v1  = _monthly_rets(daily_v1)
    r_v8  = _monthly_rets(daily_v8)
    r_tbh = _monthly_rets(daily_tbh)
    W = 75; SEP = "=" * W; DIV = "-" * W
    print(f"\n{SEP}")
    print(f"  v8 MA-Blend vs v1 vs TQQQ B&H  |  Capital: ${capital:,.0f}")
    print(f"{SEP}\n")
    cum_v1 = cum_v8 = cum_tbh = capital
    yr_totals = []
    for year in years:
        yv10 = cum_v1; yv80 = cum_v8; ytbh0 = cum_tbh
        print(f"  -- {year} " + "-" * (W - 10))
        print(f"  {'Month':<7} {'TQQQ B&H':>10} {'v1':>10} {'v8':>10}")
        print(DIV)
        for m in range(1, 13):
            ym = (year, m)
            tbh = r_tbh.get(ym); v1 = r_v1.get(ym); v8 = r_v8.get(ym)
            if tbh: cum_tbh *= 1 + tbh / 100
            if v1:  cum_v1  *= 1 + v1  / 100
            if v8:  cum_v8  *= 1 + v8  / 100
            print(f"  {MONTHS[m]:<7} {_fmt(tbh):>10} {_fmt(v1):>10} {_fmt(v8):>10}")
        fy_tbh = round((cum_tbh / ytbh0 - 1) * 100, 1)
        fy_v1  = round((cum_v1  / yv10  - 1) * 100, 1)
        fy_v8  = round((cum_v8  / yv80  - 1) * 100, 1)
        yr_totals.append((year, fy_tbh, fy_v1, fy_v8))
        print(DIV)
        print(f"  {'FY '+str(year):<7} {_fmt(fy_tbh):>10} {_fmt(fy_v1):>10} {_fmt(fy_v8):>10}")
    if len(yr_totals) > 1:
        n_yr = (date.today().year - min(y for y, *_ in yr_totals)) + \
               (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr = lambda x: round(((x / capital) ** (1 / n_yr) - 1) * 100, 1) if n_yr > 0 and x > 0 else 0.0
        ov_tbh = round((cum_tbh / capital - 1) * 100, 1)
        ov_v1  = round((cum_v1  / capital - 1) * 100, 1)
        ov_v8  = round((cum_v8  / capital - 1) * 100, 1)
        print(f"\n{SEP}")
        print(f"  {'Total %':<7} {_fmt(ov_tbh):>10} {_fmt(ov_v1):>10} {_fmt(ov_v8):>10}")
        print(f"  {'CAGR':<7} {_fmt(cagr(cum_tbh)):>10} {_fmt(cagr(cum_v1)):>10} {_fmt(cagr(cum_v8)):>10}")
        print(f"\n  Final: TQQQ B&H ${cum_tbh:,.0f} | v1 ${cum_v1:,.0f} | v8 ${cum_v8:,.0f}")
        print(SEP)
    print()


def print_daily_signal(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame) -> None:
    row       = sig_df.iloc[-1]
    today     = sig_df.index[-1].date()
    qqq_close = float(row["close"])
    high252   = float(row["high252"])
    pcthi     = float(row["pcthi"])
    regime    = row["regime"]
    action    = row["action"]

    W   = 60
    SEP = "=" * W
    print(f"\n{SEP}")
    print(f"  v1 Signal: {today}")
    print(f"{SEP}")
    print(f"  QQQ Close:     ${qqq_close:>8.2f}")
    print(f"  189d High:     ${high252:>8.2f}")
    print(f"  % Below High:  {pcthi:>8.1f}%")
    print(f"  Regime:        {regime}")
    print(f"  Action:        {action}")
    print(SEP)


# -- Strategy 8: MA-Blend (incremental TQQQ sizing) ----------------------------

def compute_signal_v8_ma_blend(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """v8: QQQ MA crossovers → incremental TQQQ sizing. 0–100%, no SQQQ."""
    df = qqq_df.copy()
    df["ma20"]  = df["close"].rolling(20,  min_periods=1).mean()
    df["ma50"]  = df["close"].rolling(50,  min_periods=1).mean()
    df["ma200"] = df["close"].rolling(200, min_periods=1).mean()

    pos = 1.0
    pos_list, action_list = [], []
    prev_close = None
    prev_pos   = 0.0

    for _, row in df.iterrows():
        close = float(row["close"])
        ma20  = float(row["ma20"])
        ma50  = float(row["ma50"])
        ma200 = float(row["ma200"])

        if prev_close is not None:
            if prev_close < ma200 and close >= ma200:
                pos = 1.0
            elif prev_close >= ma200 and close < ma200:
                pos = 0.0
            else:
                delta = 0.0
                if   prev_close >= ma50 and close < ma50:
                    delta -= 0.5
                elif prev_close < ma50  and close >= ma50:
                    delta += 0.5
                if   prev_close >= ma20 and close < ma20:
                    delta -= 0.25
                elif prev_close < ma20  and close >= ma20:
                    delta += 0.25
                pos = max(0.0, min(1.0, pos + delta))

        act = ("BUY" if pos > prev_pos else "SELL" if pos < prev_pos else "HOLD")
        pos_list.append(round(pos, 4))
        action_list.append(act)
        prev_close = close
        prev_pos   = pos

    df["position_size"] = pos_list
    df["regime"]  = ["BUY_TQQQ" if p > 0 else "CASH" for p in pos_list]
    df["action"]  = action_list
    return df


# -- Main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capital",       type=float, default=DEFAULT_CAPITAL,
                    help="Portfolio capital (default: 100000)")
    ap.add_argument("--backtest",      action="store_true",
                    help="Run backtest (default: today's signal)")
    ap.add_argument("--all",           action="store_true",
                    help="Backtest all years")
    ap.add_argument("--year",          type=int,
                    help="Backtest specific year")
    ap.add_argument("--sqqq-hedge",    action="store_true",
                    help="Use v1+SQQQ Hedge strategy - long SQQQ in downtrends (requires --backtest)")
    ap.add_argument("--v8",             action="store_true",
                    help="v8: QQQ MA crossover blend — incremental TQQQ sizing (0–100%%)")
    args = ap.parse_args()

    print("\nLoading QQQ and TQQQ data...")
    qqq_df  = _load(QQQ_TICKER,  DATA_START)
    tqqq_df = _load(TQQQ_TICKER, DATA_START)

    print("Computing signals...")
    sig_v1 = compute_signal_v1(qqq_df)

    if args.backtest:
        # Align to common dates
        common  = sig_v1.index.intersection(tqqq_df.index)
        sig_v1  = sig_v1.loc[common]
        tqqq_al = tqqq_df.loc[common]

        if args.v8:
            sig_v8    = compute_signal_v8_ma_blend(qqq_df.loc[common])
            daily_v1  = run_backtest(sig_v1, tqqq_al, args.capital)
            daily_v8  = run_backtest(sig_v8, tqqq_al, args.capital)
            daily_tbh = run_buyhold(tqqq_al, args.capital)
            start_year = int(DATA_START[:4])
            years = (sorted(set(d["date"].year for d in daily_v1 if d["date"].year >= start_year))
                     if args.all else [args.year] if args.year else [date.today().year])
            print("Running v8 MA-Blend backtest...")
            print_v8_comparison(daily_v1, daily_v8, daily_tbh, years, args.capital)
        elif args.sqqq_hedge:
            sqqq_df = _load(SQQQ_TICKER, DATA_START)
            sqqq_al = sqqq_df.loc[common]
            sig_sqqq_hedge = compute_signal_v1_sqqq_hedge(qqq_df.loc[common])
            print("Running v1+SQQQ Hedge backtest...")
            price_df_multi = {"TQQQ": tqqq_al, "SQQQ": sqqq_al}
            daily_v1       = run_backtest(sig_v1, tqqq_al, args.capital)
            daily_sqqq_hedge = run_backtest(sig_sqqq_hedge, price_df_multi, args.capital)
            daily_tbh      = run_buyhold(tqqq_al, args.capital)

            start_year = int(DATA_START[:4])
            if args.all:
                years = sorted(set(d["date"].year for d in daily_v1 if d["date"].year >= start_year))
            elif args.year:
                years = [args.year]
            else:
                years = [date.today().year]

            print_backtest_sqqq_hedge(daily_v1, daily_sqqq_hedge, daily_tbh, years, args.capital)
        else:
            print("Running v1 backtest...")
            daily_v1  = run_backtest(sig_v1, tqqq_al, args.capital)
            daily_tbh = run_buyhold(tqqq_al, args.capital)

            start_year = int(DATA_START[:4])
            if args.all:
                years = sorted(set(d["date"].year for d in daily_v1 if d["date"].year >= start_year))
            elif args.year:
                years = [args.year]
            else:
                years = [date.today().year]

            print_backtest(daily_v1, daily_tbh, years, args.capital)
    else:
        print_daily_signal(sig_v1, tqqq_df)


if __name__ == "__main__":
    main()
