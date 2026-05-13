"""
SQQQ variants vs TusharStrategy vs QQQ — backtest 2006-present

Three SQQQ ideas:
  SQQQ-Bear  : When TusharStrategy -> CASH, deploy into SQQQ instead
               (profit from bear markets instead of sitting idle)
  SQQQ-Half  : When TusharStrategy -> CASH, deploy 50% into SQQQ (50% cash)
               (partial bear bet, less risk)
  SQQQ-Hedge : While in TQQQ bull regime, if QQQ < MA50 for 3 days ->
               50% TQQQ + 50% SQQQ (hedge within bull periods)
               (same as _hedged_tushar.py logic)

Key risk: SQQQ suffers severe volatility decay — holding for months destroys
value even if QQQ trends sideways. Also: strategy exits to cash AFTER QQQ has
already fallen 15%+ from its 252d high — much of the bear move may be done.
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


def build_synthetic_sqqq(qqq_df):
    anchor  = float(yf.Ticker("SQQQ").fast_info.last_price)
    qqq_ret = qqq_df["close"].pct_change().fillna(0.0)
    dates   = qqq_df.index.tolist()
    px      = {dates[-1]: anchor}
    for i in range(len(dates) - 2, -1, -1):
        r = float(qqq_ret.iloc[i + 1])
        d = 1 + (-3) * r
        px[dates[i]] = px[dates[i + 1]] / d if d != 0 else px[dates[i + 1]]
    return pd.DataFrame({"close": px}).sort_index()


def price_on(df, dt):
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


print("Loading data...")
qqq_raw = load("QQQ")
tqqq    = build_synthetic_tqqq(load("QQQ"), load("TQQQ"))
print("Building synthetic SQQQ...")
sqqq    = build_synthetic_sqqq(qqq_raw)

sig = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100
sig["ma50"]  = sig["close"].rolling(50, min_periods=1).mean()


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


# ── SQQQ-Bear: hold SQQQ during CASH periods ──────────────────────────────────
def run_sqqq_bear(sqqq_pct=1.0, capital=DEFAULT_CAPITAL):
    cash = capital
    tqqq_sh = sqqq_sh = 0
    days, in_bull, prev = 0, False, False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        sp = price_on(sqqq, dt)
        if tp is None or sp is None: continue
        ph = float(row["pcthi"])
        if ph >= THRESHOLD:
            in_bull = False; days = 0
        else:
            days += 1
            if days >= REENTRY_DAYS: in_bull = True

        port = tqqq_sh * tp + sqqq_sh * sp + cash

        if in_bull and not prev:
            # Exit SQQQ -> enter TQQQ
            cash     = sqqq_sh * sp + cash
            sqqq_sh  = 0
            tqqq_sh  = math.floor(cash / tp) if tp > 0 else 0
            cash    -= tqqq_sh * tp
        elif not in_bull and prev:
            # Exit TQQQ -> enter SQQQ (sqqq_pct fraction)
            cash    += tqqq_sh * tp
            tqqq_sh  = 0
            invest   = cash * sqqq_pct
            sqqq_sh  = math.floor(invest / sp) if sp > 0 else 0
            cash    -= sqqq_sh * sp

        prev = in_bull
        port = tqqq_sh * tp + sqqq_sh * sp + cash
        daily.append({"date": dt, "port": round(port, 2)})
    return daily


# ── SQQQ-Hedge: 50% TQQQ + 50% SQQQ when QQQ below MA50 in bull regime ───────
def run_sqqq_hedge(capital=DEFAULT_CAPITAL):
    cash = capital
    tqqq_sh = sqqq_sh = 0
    days, in_bull, prev_bull = 0, False, False
    prev_hedged = False
    ma50_days_below = 0
    ma50_days_above = 0
    hedged = False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        sp = price_on(sqqq, dt)
        if tp is None or sp is None: continue
        ph    = float(row["pcthi"])
        above = float(row["close"]) > float(row["ma50"])

        # Tushar regime gate
        if ph >= THRESHOLD:
            in_bull = False; days = 0
            ma50_days_below = ma50_days_above = 0; hedged = False
        else:
            days += 1
            if days >= REENTRY_DAYS: in_bull = True

        # MA50 3-day confirmation (only in bull)
        if in_bull:
            if above:
                ma50_days_below = 0
                ma50_days_above += 1
                if ma50_days_above >= 3: hedged = False
            else:
                ma50_days_above = 0
                ma50_days_below += 1
                if ma50_days_below >= 3: hedged = True

        port = tqqq_sh * tp + sqqq_sh * sp + cash

        if in_bull and not prev_bull:
            # Enter bull — buy TQQQ (or 50/50 if already below MA50)
            cash = port
            sqqq_sh = 0
            if hedged:
                tqqq_sh = math.floor(port * 0.5 / tp) if tp > 0 else 0
                sqqq_sh = math.floor((port - tqqq_sh * tp) * 1.0 / sp) if sp > 0 else 0
                cash    = port - tqqq_sh * tp - sqqq_sh * sp
            else:
                tqqq_sh = math.floor(port / tp) if tp > 0 else 0
                cash    = port - tqqq_sh * tp
        elif not in_bull and prev_bull:
            # Exit bull — sell all
            cash    = tqqq_sh * tp + sqqq_sh * sp + cash
            tqqq_sh = sqqq_sh = 0
        elif in_bull and hedged and not prev_hedged:
            # Hedge ON: sell half TQQQ, buy SQQQ
            sell_sh  = tqqq_sh // 2
            proceeds = sell_sh * tp
            tqqq_sh -= sell_sh
            new_sq   = math.floor(proceeds / sp) if sp > 0 else 0
            sqqq_sh  = new_sq
            cash    += proceeds - new_sq * sp
        elif in_bull and not hedged and prev_hedged:
            # Hedge OFF: sell SQQQ, buy TQQQ
            proceeds = sqqq_sh * sp + cash
            sqqq_sh  = 0
            new_tq   = math.floor(proceeds / tp) if tp > 0 else 0
            tqqq_sh += new_tq
            cash     = proceeds - new_tq * tp

        prev_bull   = in_bull
        prev_hedged = hedged
        port = tqqq_sh * tp + sqqq_sh * sp + cash
        daily.append({"date": dt, "port": round(port, 2)})
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


def qqq_annual(df):
    bm = defaultdict(list)
    for dt, row in df.iterrows():
        bm[dt.year].append(float(row["close"]))
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
    cagr  = round(((cum / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
    worst = min(vals); worst_yr = years[vals.index(worst)]
    n_bad = sum(1 for v in vals if v < -20)
    return {"label": label, "ann": ann, "cagr": cagr, "final": cum,
            "worst": worst, "worst_yr": worst_yr, "n_bad": n_bad}


# ── Run ────────────────────────────────────────────────────────────────────────
print("Running simulations...")
results = [
    summarise(run_tushar(),           "Tushar (CASH)"),
    summarise(run_sqqq_bear(1.0),     "SQQQ-Bear 100%"),
    summarise(run_sqqq_bear(0.5),     "SQQQ-Bear  50%"),
    summarise(run_sqqq_hedge(),       "SQQQ-Hedge MA50"),
]

qa = qqq_annual(qqq_raw)

# ── Summary table ──────────────────────────────────────────────────────────────
W = 86; SEP = "=" * W; DIV = "-" * W
print(); print(SEP)
print("  SQQQ VARIANTS vs TusharStrategy vs QQQ  (2006-present, $100K start)")
print("  SQQQ-Bear 100%: hold SQQQ 100% during CASH periods")
print("  SQQQ-Bear  50%: hold SQQQ 50% + CASH 50% during CASH periods")
print("  SQQQ-Hedge    : 50% TQQQ + 50% SQQQ when QQQ < MA50 for 3d in bull")
print(DIV)
print(f"  {'Strategy':<22} {'CAGR':>7} {'Final$':>10} {'Worst':>8} {'WrstYr':>7} {'Yrs<-20%':>9}")
print(DIV)
best_cagr  = max(v["cagr"]  for v in results)
best_worst = max(v["worst"] for v in results)
for v in results:
    cf = "*" if v["cagr"]  == best_cagr  else " "
    wf = "*" if v["worst"] == best_worst else " "
    print(f"  {v['label']:<22} {v['cagr']:>6}%{cf}"
          f"  ${v['final']/1e6:>6.2f}M  {wf}{v['worst']:>6}%"
          f"  {v['worst_yr']:>6}   {v['n_bad']:>5}")
print(DIV)
print("  * = best in column")
print(SEP)

# ── Year-by-year ───────────────────────────────────────────────────────────────
years_show = [yr for yr in sorted(results[0]["ann"]) if yr >= SHOW_FROM]
print()
print(SEP)
print("  YEAR-BY-YEAR ANNUAL RETURNS")
labels = ["QQQ"] + [v["label"] for v in results]
print(f"  {'Year':<6}" + "".join(f"{lb:>17}" for lb in labels))
print(DIV)
for yr in years_show:
    q_val = qa.get(yr, 0.0)
    row_vals = [v["ann"].get(yr, 0.0) for v in results]
    best_v   = max(row_vals)
    row = f"  {yr:<6}{q_val:>+7.1f}%         "
    for val in row_vals:
        m = "*" if val == best_v else " "
        row += f"{m}{val:>+7.1f}%         "
    print(row)
print(DIV)
cagr_vals = [v["cagr"] for v in results]
best_c    = max(cagr_vals)
crow = f"  {'CAGR':<6}{'QQQ':>+7.1f}%         ".replace("QQQ", f"{sum(qa[y] for y in years_show if y in qa)/len(years_show):.1f}")
crow = f"  {'CAGR':<13}"
for cv in cagr_vals:
    m = "*" if cv == best_c else " "
    crow += f"{m}{cv:>+7.1f}%         "
print(crow)
worst_vals = [v["worst"] for v in results]
best_w    = max(worst_vals)
wrow = f"  {'Worst':<13}"
for wv in worst_vals:
    m = "*" if wv == best_w else " "
    wrow += f"{m}{wv:>+7.1f}%         "
print(wrow)
print(SEP)

# ── Key insight: what did SQQQ do during Tushar CASH periods ──────────────────
print()
print(SEP)
print("  SQQQ RETURN DURING TUSHAR CASH PERIODS (did being short actually help?)")
print(DIV)
print(f"  {'Period':<25} {'QQQ move':>10} {'SQQQ synth':>12}  {'Result'}")
print(DIV)

# Identify cash periods from Tushar
cash_periods = []
in_c = False; start_c = None
days = 0; prev_bull = False
in_bull = False
for dt, row in sig.iterrows():
    ph = float(row["pcthi"])
    if ph >= THRESHOLD:
        in_bull = False; days = 0
    else:
        days += 1
        if days >= REENTRY_DAYS: in_bull = True
    if not in_bull and prev_bull:
        start_c = dt
    if in_bull and not prev_bull and start_c:
        cash_periods.append((start_c, dt))
        start_c = None
    prev_bull = in_bull
if start_c:
    cash_periods.append((start_c, sig.index[-1]))

for (s, e) in cash_periods:
    if e.year < SHOW_FROM: continue
    qqq_s = price_on(qqq_raw, s); qqq_e = price_on(qqq_raw, e)
    sq_s  = price_on(sqqq, s);   sq_e  = price_on(sqqq, e)
    if not all([qqq_s, qqq_e, sq_s, sq_e]): continue
    qqq_ret  = (qqq_e - qqq_s) / qqq_s * 100
    sqqq_ret = (sq_e  - sq_s)  / sq_s  * 100
    label    = f"{s.strftime('%Y-%m-%d')} -> {e.strftime('%Y-%m-%d')}"
    verdict  = "HELPS" if sqqq_ret > 5 else ("HURTS" if sqqq_ret < -5 else "neutral")
    print(f"  {label:<25} {qqq_ret:>+8.1f}%   {sqqq_ret:>+8.1f}%    {verdict}")
print(SEP)
