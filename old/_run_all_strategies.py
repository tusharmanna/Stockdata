"""
All-strategies drawdown comparison -- TusharStrategy variants (2006-present)

Strategies
----------
Tushar   : Binary 100%/0% TQQQ on 252d pctHigh < 15%, 3-day re-entry filter
Tiered   : Same 252d gate + daily scaled alloc (100%->0% as pctHigh 7%->15%)
DualWin  : Exit on 252d pctHigh >= 15% (immediate); re-enter on 126d < 15% x3 days
VIX      : Same as Tushar + hard exit if VIX >= 28; both conditions must clear for re-entry
Combined : VIX exit gate + tiered allocation
"""
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

START             = "2004-01-01"
SHOW_FROM         = 2006
SIGNAL_THRESHOLD  = 15.0
REENTRY_DAYS      = 3
HIGH_PERIOD_LONG  = 252
HIGH_PERIOD_SHORT = 126
SCALE_LOW         = 7.0
VIX_THRESHOLD     = 28.0
DEFAULT_CAPITAL   = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def load(ticker):
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    df  = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index).tz_localize(None)
    return df


def build_synthetic_tqqq(qqq_df, tqqq_df):
    tqqq_start   = tqqq_df.index[0]
    anchor_price = float(tqqq_df.iloc[0]["close"])
    pre_qqq = qqq_df.loc[:tqqq_start, "close"]
    qqq_ret = pre_qqq.pct_change().fillna(0.0)
    dates   = pre_qqq.index.tolist()
    prices  = {tqqq_start: anchor_price}
    for i in range(len(dates) - 2, -1, -1):
        curr = dates[i]; nxt = dates[i + 1]
        r    = float(qqq_ret.get(nxt, 0.0))
        d    = 1 + 3 * r
        prices[curr] = prices[nxt] / d if d != 0 else prices[nxt]
    synth = {d: p for d, p in prices.items() if d < tqqq_start}
    sdf   = pd.DataFrame({"close": synth}).sort_index()
    for col in ("open", "high", "low"):
        sdf[col] = sdf["close"]
    sdf["volume"] = 0
    combined = pd.concat([sdf, tqqq_df]).sort_index()
    return combined[~combined.index.duplicated(keep="last")]


def price_on(df, d):
    if d in df.index:
        return float(df.loc[d, "close"])
    avail = df.index[df.index <= d]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def vix_on(vix_df, d):
    if d in vix_df.index:
        return float(vix_df.loc[d, "close"])
    avail = vix_df.index[vix_df.index <= d]
    return float(vix_df.loc[avail[-1], "close"]) if not avail.empty else 20.0


def build_sig(df, window):
    s = df[["close"]].copy()
    s["high_n"] = s["close"].rolling(window, min_periods=1).max()
    s["pcthi"]  = (s["high_n"] - s["close"]) / s["high_n"] * 100
    return s


# -- Download ------------------------------------------------------------------
print("Downloading QQQ, TQQQ, VIX (2004-present)...")
qqq_raw  = load("QQQ")
tqqq_raw = load("TQQQ")
vix_raw  = load("^VIX")

tqqq_ipo = tqqq_raw.index[0].date()
print(f"  QQQ : {qqq_raw.index[0].date()} to {qqq_raw.index[-1].date()}  ({len(qqq_raw)} days)")
print(f"  TQQQ: {tqqq_ipo} to {tqqq_raw.index[-1].date()}  ({len(tqqq_raw)} days)")
print(f"  VIX : {vix_raw.index[0].date()} to {vix_raw.index[-1].date()}  ({len(vix_raw)} days)")
print(f"  Synthesizing pre-{tqqq_ipo} TQQQ from 3x QQQ daily returns...")

tqqq = build_synthetic_tqqq(qqq_raw, tqqq_raw)
print(f"  TQQQ combined: {tqqq.index[0].date()} to {tqqq.index[-1].date()}  ({len(tqqq)} days)")

sig252 = build_sig(qqq_raw, HIGH_PERIOD_LONG)
sig126 = build_sig(qqq_raw, HIGH_PERIOD_SHORT)


# -- Simulations ---------------------------------------------------------------
def run_tushar(capital=DEFAULT_CAPITAL):
    """Binary 100%/0%, identical to _run_20yr.py."""
    cash, sh, days, in_t, prev = capital, 0, 0, True, False
    daily = []
    for dt, row in sig252.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        ph = float(row["pcthi"])
        if ph >= SIGNAL_THRESHOLD:
            days = 0; in_t = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_t = True
        if in_t and not prev:
            ns = math.floor(cash / tp); cash -= ns * tp; sh = ns
        elif not in_t and prev:
            cash += sh * tp; sh = 0
        prev = in_t
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


def run_tiered(capital=DEFAULT_CAPITAL):
    """
    Same 252d exit gate as Tushar, but allocation scales daily:
      pctHigh 0-7%   -> 100% TQQQ
      pctHigh 7-15%  -> (15-pcthi)/8  linear ramp down
      pctHigh >= 15% -> 0%
    """
    cash, sh, days, in_t = capital, 0, 0, True
    daily = []
    for dt, row in sig252.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        ph = float(row["pcthi"])
        if ph >= SIGNAL_THRESHOLD:
            days = 0; in_t = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_t = True
        alloc  = max(0.0, min(1.0, (SIGNAL_THRESHOLD - ph) / (SIGNAL_THRESHOLD - SCALE_LOW))) if in_t else 0.0
        port   = sh * tp + cash
        new_sh = math.floor(port * alloc / tp) if tp > 0 else 0
        cash  += (sh - new_sh) * tp
        sh     = new_sh
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


def run_dual(capital=DEFAULT_CAPITAL):
    """
    Exit : 252d pctHigh >= 15% (immediate)
    Enter: 126d pctHigh < 15% for 3 consecutive days
    """
    cash, sh, days126, in_t, prev = capital, 0, 0, True, False
    daily = []
    for dt in sig252.index:
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        ph252 = float(sig252.loc[dt, "pcthi"])
        ph126 = float(sig126.loc[dt, "pcthi"])
        if ph252 >= SIGNAL_THRESHOLD:
            days126 = 0; in_t = False
        else:
            if ph126 < SIGNAL_THRESHOLD:
                days126 += 1
            else:
                days126 = 0
            if days126 >= REENTRY_DAYS:
                in_t = True
        if in_t and not prev:
            ns = math.floor(cash / tp); cash -= ns * tp; sh = ns
        elif not in_t and prev:
            cash += sh * tp; sh = 0
        prev = in_t
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


def run_vix(capital=DEFAULT_CAPITAL):
    """
    Exit : 252d pctHigh >= 15%  OR  VIX >= 28
    Enter: BOTH pctHigh < 15% AND VIX < 28 for 3 consecutive days
    """
    cash, sh, days, in_t, prev = capital, 0, 0, True, False
    daily = []
    for dt, row in sig252.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        ph = float(row["pcthi"])
        v  = vix_on(vix_raw, dt)
        if ph >= SIGNAL_THRESHOLD or v >= VIX_THRESHOLD:
            days = 0; in_t = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_t = True
        if in_t and not prev:
            ns = math.floor(cash / tp); cash -= ns * tp; sh = ns
        elif not in_t and prev:
            cash += sh * tp; sh = 0
        prev = in_t
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


def run_combined(capital=DEFAULT_CAPITAL):
    """VIX exit gate + tiered daily allocation."""
    cash, sh, days, in_t = capital, 0, 0, True
    daily = []
    for dt, row in sig252.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        ph = float(row["pcthi"])
        v  = vix_on(vix_raw, dt)
        if ph >= SIGNAL_THRESHOLD or v >= VIX_THRESHOLD:
            days = 0; in_t = False
        else:
            days += 1
            if days >= REENTRY_DAYS:
                in_t = True
        alloc  = max(0.0, min(1.0, (SIGNAL_THRESHOLD - ph) / (SIGNAL_THRESHOLD - SCALE_LOW))) if in_t else 0.0
        port   = sh * tp + cash
        new_sh = math.floor(port * alloc / tp) if tp > 0 else 0
        cash  += (sh - new_sh) * tp
        sh     = new_sh
        daily.append({"date": dt, "port": round(sh * tp + cash, 2)})
    return daily


# -- Run -----------------------------------------------------------------------
print("Running simulations...")
tushar_d   = run_tushar()
tiered_d   = run_tiered()
dual_d     = run_dual()
vix_d      = run_vix()
combined_d = run_combined()
print("Done.")


# -- Monthly return helpers ----------------------------------------------------
def monthly_rets(daily):
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["port"])
    sm = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def qqq_monthly_rets(df):
    bm = defaultdict(list)
    for d, row in df.iterrows():
        bm[(d.year, d.month)].append(float(row["close"]))
    sm = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def fmt(v, w=8):
    if v is None:
        return "  N/A  ".rjust(w)
    return f"{'+'if v >= 0 else ''}{v:.1f}%".rjust(w)


qr  = qqq_monthly_rets(qqq_raw)
tr  = monthly_rets(tushar_d)
tir = monthly_rets(tiered_d)
dr  = monthly_rets(dual_d)
vr  = monthly_rets(vix_d)
cr  = monthly_rets(combined_d)

ph252_by_month = defaultdict(list)
vix_by_month   = defaultdict(list)
for dt, row in sig252.iterrows():
    ph252_by_month[(dt.year, dt.month)].append(float(row["pcthi"]))
for dt, row in vix_raw.iterrows():
    vix_by_month[(dt.year, dt.month)].append(float(row["close"]))


# -- Print monthly detail ------------------------------------------------------
W   = 104
SEP = "=" * W
DIV = "-" * W

print()
print(SEP)
print("  ALL-STRATEGIES DRAWDOWN COMPARISON  (2006-present)  |  Capital: $100,000")
print("  Tushar  : 252d pctHigh < 15% x3days => 100% TQQQ  |  >= 15% => CASH")
print("  Tiered  : Same exit gate + daily scaled alloc (100%->0% as pctHigh 7%->15%)")
print("  DualWin : Exit on 252d pctHigh >= 15%  |  Re-enter on 126d pctHigh < 15% x3days")
print("  VIX     : Tushar + hard exit if VIX >= 28  |  Dual gate (pctHigh + VIX) for re-entry")
print("  Combined: VIX exit gate + tiered allocation (best of both)")
print(SEP)

cum = {k: DEFAULT_CAPITAL for k in ("q","t","ti","d","v","c")}
yr_totals = []
all_years = sorted(set(ym[0] for ym in tr if ym[0] >= SHOW_FROM))

for year in all_years:
    months = sorted(ym for ym in tr if ym[0] == year)
    if not months:
        continue
    yr_s = dict(cum)
    print(f"\n  -- {year} {'-'*90}")
    print(f"  {'Mo':<4} {'QQQ':>8} {'Tushar':>9} {'Tiered':>9} {'DualWin':>9} {'VIX':>9} {'Combined':>10}  Regime(pctHi) VIX")
    print(DIV)

    for ym in months:
        m  = ym[1]
        q  = qr.get(ym);  t  = tr.get(ym);  ti = tir.get(ym)
        d  = dr.get(ym);  v  = vr.get(ym);  c  = cr.get(ym)
        if q:  cum["q"]  *= 1 + q  / 100
        if t:  cum["t"]  *= 1 + t  / 100
        if ti: cum["ti"] *= 1 + ti / 100
        if d:  cum["d"]  *= 1 + d  / 100
        if v:  cum["v"]  *= 1 + v  / 100
        if c:  cum["c"]  *= 1 + c  / 100

        phs     = ph252_by_month.get(ym, [0])
        avg_ph  = sum(phs) / len(phs)
        vixa    = vix_by_month.get(ym, [20])
        avg_vix = sum(vixa) / len(vixa)
        regime  = "CASH" if avg_ph >= SIGNAL_THRESHOLD else "TQQQ"
        rstr    = f"{regime}({avg_ph:.0f}%) VIX:{avg_vix:.0f}"

        print(f"  {MONTHS[m]:<4} {fmt(q):>8} {fmt(t):>9} {fmt(ti):>9} {fmt(d):>9} {fmt(v):>9} {fmt(c):>10}  {rstr}")

    fy_q  = round((cum["q"]  / yr_s["q"]  - 1) * 100, 1)
    fy_t  = round((cum["t"]  / yr_s["t"]  - 1) * 100, 1)
    fy_ti = round((cum["ti"] / yr_s["ti"] - 1) * 100, 1)
    fy_d  = round((cum["d"]  / yr_s["d"]  - 1) * 100, 1)
    fy_v  = round((cum["v"]  / yr_s["v"]  - 1) * 100, 1)
    fy_c  = round((cum["c"]  / yr_s["c"]  - 1) * 100, 1)
    yr_totals.append((year, fy_q, fy_t, fy_ti, fy_d, fy_v, fy_c))
    print(DIV)
    print(f"  {'FY '+str(year):<4} {fmt(fy_q):>8} {fmt(fy_t):>9} {fmt(fy_ti):>9} {fmt(fy_d):>9} {fmt(fy_v):>9} {fmt(fy_c):>10}")


# -- Annual summary ------------------------------------------------------------
print()
print(SEP)
print("  ANNUAL SUMMARY  (Jan 2006 -> present)")
print(DIV)
print(f"  {'Year':<6} {'QQQ':>8} {'Tushar':>9} {'Tiered':>9} {'DualWin':>9} {'VIX':>9} {'Combined':>10}")
print(DIV)
for y, q, t, ti, d, v, c in yr_totals:
    note = "  << bear year" if y in (2011, 2018, 2022) and t < -5 else ""
    print(f"  {str(y):<6} {fmt(q):>8} {fmt(t):>9} {fmt(ti):>9} {fmt(d):>9} {fmt(v):>9} {fmt(c):>10}{note}")

print(DIV)
ov_q  = round((cum["q"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_t  = round((cum["t"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_ti = round((cum["ti"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_d  = round((cum["d"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_v  = round((cum["v"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_c  = round((cum["c"]  / DEFAULT_CAPITAL - 1) * 100, 1)

today = date.today()
yrs   = (today.year - 2006) + (today.month - 1) / 12 + (today.day - 1) / 365
cq    = round(((cum["q"]  / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
ct    = round(((cum["t"]  / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
cti   = round(((cum["ti"] / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
cd    = round(((cum["d"]  / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
cv    = round(((cum["v"]  / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
cc    = round(((cum["c"]  / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)

print(f"  {'Total%':<6} {fmt(ov_q):>8} {fmt(ov_t):>9} {fmt(ov_ti):>9} {fmt(ov_d):>9} {fmt(ov_v):>9} {fmt(ov_c):>10}")
print(f"  {'CAGR':<6} {fmt(cq):>8} {fmt(ct):>9} {fmt(cti):>9} {fmt(cd):>9} {fmt(cv):>9} {fmt(cc):>10}")

def fmtd(v):
    return f"${v:>9,.0f}"

print(f"  {'Final$':<6} {fmtd(cum['q'])} {fmtd(cum['t'])} {fmtd(cum['ti'])} {fmtd(cum['d'])} {fmtd(cum['v'])} {fmtd(cum['c'])}")
print(DIV)
print(f"  Pre-{tqqq_ipo}: TQQQ synthesized from 3x QQQ daily returns (backward roll from IPO price).")
print(f"  VIX threshold: {VIX_THRESHOLD:.0f}  |  Tiered scale band: {SCALE_LOW:.0f}%-{SIGNAL_THRESHOLD:.0f}% pctHigh")
print(SEP)
