"""
MA-Scale Strategy vs TusharStrategy vs QQQ — backtest 2006-present

MA-Scale rules:
  REGIME : Same as TusharStrategy — pctHigh252 >= 15% -> CASH (3-day re-entry)
  SCALE  : While in bull regime, reduce TQQQ 25% for each MA breached (3-day confirm):
             0 MAs breached -> 100% TQQQ
             1 MA  breached ->  75%
             2 MAs breached ->  50%
             3 MAs breached ->  25%  (minimum; Tushar gate is only path to 0%)
  RECOVER: Each MA recrossed above for 3 consecutive days -> +25% back
  REBALANCE: Daily rebalance to target allocation
  BREACH TRACKING: Continuous — MA state is NOT reset when going to CASH
"""
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

START            = "2004-01-01"
SHOW_FROM        = 2006
SIGNAL_THRESHOLD = 15.0
REENTRY_DAYS     = 3
HIGH_PERIOD      = 252
DEFAULT_CAPITAL  = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


# ── Data helpers ───────────────────────────────────────────────────────────────
def load(ticker):
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
    raw.index   = pd.to_datetime(raw.index).tz_localize(None)
    return raw[["open","high","low","close","volume"]].copy()


def build_synthetic_tqqq(qqq_df, tqqq_df):
    ipo = tqqq_df.index[0]
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


# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data...")
qqq_raw = load("QQQ")
tqqq    = build_synthetic_tqqq(load("QQQ"), load("TQQQ"))

# ── Signals ────────────────────────────────────────────────────────────────────
sig = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100

qqq_raw["ma20"]  = qqq_raw["close"].rolling(20,  min_periods=1).mean()
qqq_raw["ma50"]  = qqq_raw["close"].rolling(50,  min_periods=1).mean()
qqq_raw["ma200"] = qqq_raw["close"].rolling(200, min_periods=1).mean()


# ── Simulation helpers ─────────────────────────────────────────────────────────
def monthly_rets(daily):
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["port"])
    sm = sorted(bm); res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def qqq_monthly_rets(df):
    bm = defaultdict(list)
    for dt, row in df.iterrows():
        bm[(dt.year, dt.month)].append(float(row["close"]))
    sm = sorted(bm); res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def fmt(v, w=9):
    if v is None:
        return "  N/A  ".rjust(w)
    return f"{'+'if v >= 0 else ''}{v:.1f}%".rjust(w)


# ── TusharStrategy (binary 100/0) ──────────────────────────────────────────────
def run_tushar(capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph = float(row["pcthi"])
        if ph >= SIGNAL_THRESHOLD:
            in_bull = False; days = 0
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_bull = True
        if in_bull and not prev:
            sh    = math.floor(cash / tp) if tp > 0 else 0
            cash -= sh * tp
        elif not in_bull and prev:
            cash += sh * tp; sh = 0
        prev = in_bull
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# ── MA-Scale Strategy ──────────────────────────────────────────────────────────
def run_ma_scale(capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull = 0, False
    breach_days   = {20: 0, 50: 0, 200: 0}
    recovery_days = {20: 0, 50: 0, 200: 0}
    confirmed     = {20: False, 50: False, 200: False}
    daily = []

    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph = float(row["pcthi"])

        # Tushar regime gate
        if ph >= SIGNAL_THRESHOLD:
            in_bull = False; days = 0
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_bull = True

        # MA breach tracking (continuous — not reset on cash)
        if dt in qqq_raw.index:
            close = float(qqq_raw.loc[dt, "close"])
            for ma in (20, 50, 200):
                ma_val = float(qqq_raw.loc[dt, f"ma{ma}"])
                above  = (close > ma_val)
                if above:
                    breach_days[ma] = 0
                    if confirmed[ma]:
                        recovery_days[ma] += 1
                        if recovery_days[ma] >= 3:
                            confirmed[ma] = False; recovery_days[ma] = 0
                else:
                    recovery_days[ma] = 0
                    breach_days[ma] += 1
                    if breach_days[ma] >= 3:
                        confirmed[ma] = True

        # Allocation
        if not in_bull:
            alloc = 0.0
        else:
            alloc = max(0.25, 1.0 - 0.25 * sum(confirmed.values()))

        # Daily rebalance
        port   = sh * tp + cash
        new_sh = math.floor(port * alloc / tp) if tp > 0 else 0
        cash  += (sh - new_sh) * tp
        sh     = new_sh
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})

    return daily


# ── Run simulations ────────────────────────────────────────────────────────────
print("Running simulations...")
tushar_daily = run_tushar()
mscale_daily = run_ma_scale()

tr = monthly_rets(tushar_daily)
mr = monthly_rets(mscale_daily)
qr = qqq_monthly_rets(qqq_raw)

# Pre-compute daily allocations for MA-Scale (to show avg per month)
alloc_by_month = defaultdict(list)
{
    "dummy": (
        lambda: [
            alloc_by_month[(d["date"].year, d["date"].month)].append(None)
            for d in mscale_daily
        ]
    )
}
# Recompute allocations to track monthly average
_cash2, _sh2 = DEFAULT_CAPITAL, 0
_days2, _in2 = 0, False
_breach2   = {20: 0, 50: 0, 200: 0}
_recovery2 = {20: 0, 50: 0, 200: 0}
_confirmed2 = {20: False, 50: False, 200: False}
for dt, row in sig.iterrows():
    tp = price_on(tqqq, dt)
    if tp is None: continue
    ph = float(row["pcthi"])
    if ph >= SIGNAL_THRESHOLD:
        _in2 = False; _days2 = 0
    else:
        _days2 += 1
        if _days2 >= REENTRY_DAYS: _in2 = True
    if dt in qqq_raw.index:
        cl = float(qqq_raw.loc[dt, "close"])
        for ma in (20, 50, 200):
            mv = float(qqq_raw.loc[dt, f"ma{ma}"])
            ab = (cl > mv)
            if ab:
                _breach2[ma] = 0
                if _confirmed2[ma]:
                    _recovery2[ma] += 1
                    if _recovery2[ma] >= 3:
                        _confirmed2[ma] = False; _recovery2[ma] = 0
            else:
                _recovery2[ma] = 0
                _breach2[ma] += 1
                if _breach2[ma] >= 3: _confirmed2[ma] = True
    alloc = 0.0 if not _in2 else max(0.25, 1.0 - 0.25 * sum(_confirmed2.values()))
    alloc_by_month[(dt.year, dt.month)].append(alloc)


# ── Print comparison ───────────────────────────────────────────────────────────
W = 90; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  MA-Scale vs TusharStrategy vs QQQ  (2006-present)")
print("  Tushar  : pctHigh252 < 15% for 3d -> 100% TQQQ  |  >= 15% -> CASH")
print("  MA-Scale: Same regime gate + reduce 25% per MA (20/50/200) breached 3d")
print("            Recover 25% per MA recrossed above for 3d | min 25% in bull")
print(SEP)

cum = {"q": DEFAULT_CAPITAL, "t": DEFAULT_CAPITAL, "m": DEFAULT_CAPITAL}
yr_totals = []
all_years = sorted(set(ym[0] for ym in tr if ym[0] >= SHOW_FROM))

for year in all_years:
    months = sorted(ym for ym in tr if ym[0] == year)
    if not months: continue
    yr_s = dict(cum)
    print(f"\n  -- {year} {'-'*75}")
    print(f"  {'Mo':<5} {'QQQ':>8} {'Tushar':>10} {'MA-Scale':>10}   Regime       Avg-Alloc")
    print(DIV)

    for ym in months:
        m  = ym[1]
        q  = qr.get(ym)
        t  = tr.get(ym)
        ms = mr.get(ym)
        if q:  cum["q"] *= 1 + q  / 100
        if t:  cum["t"] *= 1 + t  / 100
        if ms: cum["m"] *= 1 + ms / 100

        ph_vals = [float(sig.loc[d, "pcthi"])
                   for d in sig.index if d.year == year and d.month == m]
        avg_ph  = sum(ph_vals) / len(ph_vals) if ph_vals else 0.0
        regime  = "CASH" if avg_ph >= SIGNAL_THRESHOLD else f"TQQQ({avg_ph:.0f}%)"

        allocs  = alloc_by_month.get(ym, [])
        avg_al  = sum(allocs) / len(allocs) * 100 if allocs else 0.0
        al_str  = f"{avg_al:.0f}%" if avg_ph < SIGNAL_THRESHOLD else "---"

        print(f"  {MONTHS[m]:<5} {fmt(q):>8} {fmt(t):>10} {fmt(ms):>10}   {regime:<12} {al_str}")

    fy_q = round((cum["q"] / yr_s["q"] - 1) * 100, 1)
    fy_t = round((cum["t"] / yr_s["t"] - 1) * 100, 1)
    fy_m = round((cum["m"] / yr_s["m"] - 1) * 100, 1)
    yr_totals.append((year, fy_q, fy_t, fy_m))
    print(DIV)
    print(f"  {'FY '+str(year):<5} {fmt(fy_q):>8} {fmt(fy_t):>10} {fmt(fy_m):>10}")

# ── Annual summary ─────────────────────────────────────────────────────────────
print(); print(SEP)
print("  ANNUAL SUMMARY")
print(DIV)
print(f"  {'Year':<6} {'QQQ':>8} {'Tushar':>10} {'MA-Scale':>10}   Winner")
print(DIV)
for y, q, t, ms in yr_totals:
    win = " <- MA-Scale" if ms > t else (" <- Tushar" if t > ms else "")
    print(f"  {str(y):<6} {fmt(q):>8} {fmt(t):>10} {fmt(ms):>10}  {win}")
print(DIV)
ov_q = round((cum["q"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_t = round((cum["t"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_m = round((cum["m"] / DEFAULT_CAPITAL - 1) * 100, 1)
today = date.today()
yrs   = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365
cq    = round(((cum["q"] / DEFAULT_CAPITAL) ** (1 / yrs) - 1) * 100, 1)
ct    = round(((cum["t"] / DEFAULT_CAPITAL) ** (1 / yrs) - 1) * 100, 1)
cm    = round(((cum["m"] / DEFAULT_CAPITAL) ** (1 / yrs) - 1) * 100, 1)
fq    = round(cum["q"])
ft    = round(cum["t"])
fm    = round(cum["m"])
print(f"  {'Total%':<6} {fmt(ov_q):>8} {fmt(ov_t):>10} {fmt(ov_m):>10}")
print(f"  {'CAGR':<6} {fmt(cq):>8} {fmt(ct):>10} {fmt(cm):>10}")
print(f"  {'Final$':<6} {'${:,.0f}'.format(fq):>9} {'${:,.0f}'.format(ft):>11} {'${:,.0f}'.format(fm):>11}")
print(SEP)
