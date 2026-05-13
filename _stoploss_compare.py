"""
Stop-loss rules applied on top of TusharStrategy — backtest 2006-present

Three stop-loss variants tested at multiple levels:

SL1 — Portfolio High-Water Mark (HWM) Stop
   Track the portfolio peak since inception.
   If portfolio falls X% below its all-time high -> sell -> CASH
   Re-entry: normal Tushar signal (pctHigh < 15% for 3 days)
   Protects realised gains. Fires in any extended drawdown.

SL2 — TQQQ Trailing Stop from Entry Peak
   On each new BUY, start tracking the highest TQQQ close seen since entry.
   If TQQQ closes X% below that rolling peak -> stop out -> CASH
   Re-entry: normal Tushar signal
   Classic trailing stop — lets winners run but cuts losers.

SL3 — Monthly Circuit Breaker
   At the end of each calendar month, if the strategy return for that
   month is worse than -X% -> sell -> CASH for the rest of that month
   Re-entry: Tushar signal fires (3 days below 15%) in any subsequent month
   Simple rule: one bad month triggers a pause.
"""
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

START           = "2004-01-01"
SHOW_FROM       = 2006
REENTRY_DAYS    = 3
HIGH_PERIOD     = 252
THRESHOLD       = 15.0
DEFAULT_CAPITAL = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def load(ticker):
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
    raw.index   = pd.to_datetime(raw.index).tz_localize(None)
    return raw[["open","high","low","close","volume"]].copy()


def build_synthetic_tqqq(qqq_df, tqqq_df):
    ipo     = tqqq_df.index[0]
    qqq_ret = qqq_df["close"].pct_change().fillna(0.0)
    dates   = qqq_df.index.tolist()
    anchor  = float(tqqq_df.iloc[0]["close"])
    px      = {ipo: anchor}
    for i in range(dates.index(ipo) - 1, -1, -1):
        r = float(qqq_ret.iloc[i + 1])
        d = 1 + 3 * r
        px[dates[i]] = px[dates[i + 1]] / d if d != 0 else px[dates[i + 1]]
    synth = pd.DataFrame({"close": px}).sort_index()
    return pd.concat([synth[synth.index < ipo], tqqq_df[["close"]]]).drop_duplicates().sort_index()


def price_on(df, dt):
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


print("Loading data...")
qqq_raw = load("QQQ")
tqqq    = build_synthetic_tqqq(load("QQQ"), load("TQQQ"))

sig = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100


# ── Baseline TusharStrategy ────────────────────────────────────────────────────
def run_tushar(capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph = float(row["pcthi"])
        if ph >= THRESHOLD:
            in_bull = False; days = 0
        else:
            days += 1
            if days >= REENTRY_DAYS: in_bull = True
        if in_bull and not prev:
            sh = math.floor(cash / tp) if tp > 0 else 0; cash -= sh * tp
        elif not in_bull and prev:
            cash += sh * tp; sh = 0
        prev = in_bull
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# ── SL1: Portfolio HWM Stop ────────────────────────────────────────────────────
def run_hwm_stop(stop_pct, capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    hwm        = capital          # all-time portfolio high
    sl_active  = False            # True when stop has fired; waiting for Tushar re-entry
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph   = float(row["pcthi"])
        port = sh * tp + cash

        # Update HWM
        if port > hwm: hwm = port

        # Tushar regime gate
        if ph >= THRESHOLD:
            in_bull = False; days = 0; sl_active = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_bull = True; sl_active = False   # Tushar re-entry clears the stop

        # HWM stop check (only when in TQQQ)
        if sh > 0 and port < hwm * (1 - stop_pct / 100):
            # Stop fired — sell everything
            cash += sh * tp; sh = 0
            in_bull   = False; sl_active = True; days = 0

        # Execute position changes based on in_bull (ignore if sl_active waiting)
        if in_bull and not prev and not sl_active:
            sh = math.floor(cash / tp) if tp > 0 else 0; cash -= sh * tp
        elif not in_bull and prev:
            cash += sh * tp; sh = 0
        prev = in_bull
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# ── SL2: TQQQ Trailing Stop from Entry Peak ────────────────────────────────────
def run_trail_stop(stop_pct, capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    peak_since_entry = None      # highest TQQQ close since last BUY
    sl_active        = False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph = float(row["pcthi"])

        # Tushar regime gate
        if ph >= THRESHOLD:
            in_bull = False; days = 0; sl_active = False; peak_since_entry = None
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_bull = True; sl_active = False

        # Track TQQQ peak while in position
        if sh > 0:
            if peak_since_entry is None or tp > peak_since_entry:
                peak_since_entry = tp
            # Trailing stop check
            if tp < peak_since_entry * (1 - stop_pct / 100):
                cash += sh * tp; sh = 0
                in_bull = False; sl_active = True; days = 0; peak_since_entry = None

        # Execute buy/sell
        if in_bull and not prev and not sl_active:
            sh = math.floor(cash / tp) if tp > 0 else 0
            cash -= sh * tp
            peak_since_entry = tp
        elif not in_bull and prev:
            cash += sh * tp; sh = 0; peak_since_entry = None
        prev = in_bull
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# ── SL3: Monthly Circuit Breaker ───────────────────────────────────────────────
def run_monthly_breaker(stop_pct, capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    sl_active         = False
    month_start_port  = capital
    cur_month         = None
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph   = float(row["pcthi"])
        port = sh * tp + cash
        ym   = (dt.year, dt.month)

        # New month: reset month tracking, clear stop
        if ym != cur_month:
            cur_month        = ym
            month_start_port = port
            sl_active        = False

        # Tushar regime gate
        if ph >= THRESHOLD:
            in_bull = False; days = 0; sl_active = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_bull = True

        # Monthly circuit breaker (only while in TQQQ)
        if sh > 0 and month_start_port > 0:
            month_ret = (port - month_start_port) / month_start_port * 100
            if month_ret <= -stop_pct:
                cash += sh * tp; sh = 0
                in_bull = False; sl_active = True; days = 0

        # Execute buy/sell (sl_active blocks re-entry within same month)
        if in_bull and not prev and not sl_active:
            sh = math.floor(cash / tp) if tp > 0 else 0; cash -= sh * tp
        elif not in_bull and prev:
            cash += sh * tp; sh = 0
        prev = in_bull
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# ── Annual returns helper ──────────────────────────────────────────────────────
def annual_rets(daily):
    bm = defaultdict(list)
    for d in daily:
        bm[d["date"].year].append(d["port"])
    sy = sorted(bm); res = {}
    for i, yr in enumerate(sy):
        e = bm[yr][-1]
        s = bm[sy[i-1]][-1] if i > 0 else bm[yr][0]
        res[yr] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def summarise(daily, label):
    ann   = annual_rets(daily)
    years = [yr for yr in ann if yr >= SHOW_FROM]
    vals  = [ann[yr] for yr in years]
    cum   = DEFAULT_CAPITAL
    for v in vals: cum *= 1 + v / 100
    today = date.today()
    yrs   = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365
    cagr  = round(((cum / DEFAULT_CAPITAL) ** (1 / yrs) - 1) * 100, 1)
    worst = min(vals); worst_yr = years[vals.index(worst)]
    n_bad = sum(1 for v in vals if v < -20)
    return {"label": label, "ann": ann, "cagr": cagr, "final": cum,
            "worst": worst, "worst_yr": worst_yr, "n_bad": n_bad}


# ── Run all variants ───────────────────────────────────────────────────────────
print("Running simulations...")
variants = []
variants.append(summarise(run_tushar(),          "Tushar (no stop)"))
for pct in (15, 20, 25, 30):
    variants.append(summarise(run_hwm_stop(pct),    f"HWM-Stop  {pct}%"))
for pct in (15, 20, 25, 30):
    variants.append(summarise(run_trail_stop(pct),  f"Trail-Stop {pct}%"))
for pct in (10, 15, 20, 25):
    variants.append(summarise(run_monthly_breaker(pct), f"Monthly-CB {pct}%"))


# ── Summary table ──────────────────────────────────────────────────────────────
W = 88; SEP = "=" * W; DIV = "-" * W
print(); print(SEP)
print("  STOP-LOSS COMPARISON vs TusharStrategy  (2006-present, $100K start)")
print("  HWM-Stop  : sell when portfolio drops X% below all-time high")
print("  Trail-Stop: sell when TQQQ drops X% below peak since entry")
print("  Monthly-CB: sell if strategy loses X% within the calendar month")
print(DIV)
print(f"  {'Strategy':<22} {'CAGR':>7} {'Final$M':>8} {'Worst':>8} {'WrstYr':>7} {'Yrs<-20%':>9}")
print(DIV)
best_cagr  = max(v["cagr"]  for v in variants)
best_worst = max(v["worst"] for v in variants)
for v in variants:
    c_flag = " *" if v["cagr"]  == best_cagr  else "  "
    w_flag = "*"  if v["worst"] == best_worst  else " "
    print(f"  {v['label']:<22} {v['cagr']:>6}%{c_flag}"
          f"  ${v['final']/1e6:>5.2f}M  {w_flag}{v['worst']:>6}%"
          f"  {v['worst_yr']:>6}   {v['n_bad']:>5}")
print(DIV)
print("  * = best in column")
print(SEP)


# ── Year-by-year detail for best stop-loss per type vs Tushar ─────────────────
# Pick the best (highest CAGR) from each stop type
hwm_best   = max((v for v in variants if "HWM"     in v["label"]), key=lambda v: v["cagr"])
trail_best = max((v for v in variants if "Trail"   in v["label"]), key=lambda v: v["cagr"])
month_best = max((v for v in variants if "Monthly" in v["label"]), key=lambda v: v["cagr"])
tushar     = variants[0]
show       = [tushar, hwm_best, trail_best, month_best]

years_show = [yr for yr in sorted(tushar["ann"]) if yr >= SHOW_FROM]

print()
print(SEP)
print("  YEAR-BY-YEAR: Tushar vs Best of Each Stop-Loss Type")
print(DIV)
labels = [v["label"] for v in show]
print(f"  {'Year':<6}" + "".join(f"{lb:>16}" for lb in labels))
print(DIV)
for yr in years_show:
    row = f"  {yr:<6}"
    vals_yr = [v["ann"].get(yr, 0.0) for v in show]
    best_v  = max(vals_yr)
    for val in vals_yr:
        s = f"{'+'if val>=0 else ''}{val:.1f}%"
        marker = "*" if val == best_v else " "
        row += f"{marker}{s:>14} "
    print(row)
print(DIV)
cagr_row = f"  {'CAGR':<6}"
cagr_vals = [v["cagr"] for v in show]
best_c    = max(cagr_vals)
for cv in cagr_vals:
    s = f"{'+'if cv>=0 else ''}{cv:.1f}%"
    m = "*" if cv == best_c else " "
    cagr_row += f"{m}{s:>14} "
print(cagr_row)
worst_row = f"  {'Worst':<6}"
worst_vals = [v["worst"] for v in show]
best_w    = max(worst_vals)
for wv in worst_vals:
    s = f"{'+'if wv>=0 else ''}{wv:.1f}%"
    m = "*" if wv == best_w else " "
    worst_row += f"{m}{s:>14} "
print(worst_row)
print(SEP)
