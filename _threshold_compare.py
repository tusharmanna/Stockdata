"""
Threshold comparison: TusharStrategy at 10% vs 15% vs QQQ (2006-present)

10% threshold: pctHigh252 >= 10% -> CASH (exits sooner, re-enters sooner)
15% threshold: pctHigh252 >= 15% -> CASH (standard TusharStrategy)
Both use 3-day re-entry confirmation.
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
DEFAULT_CAPITAL = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def load(ticker):
    print(f"  Loading {ticker}...")
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


# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data...")
qqq_raw = load("QQQ")
tqqq    = build_synthetic_tqqq(load("QQQ"), load("TQQQ"))

sig = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100


# ── Generic runner (threshold is a parameter) ──────────────────────────────────
def run_tushar(threshold, capital=DEFAULT_CAPITAL):
    cash, sh = capital, 0
    days, in_bull, prev = 0, False, False
    daily = []
    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None: continue
        ph = float(row["pcthi"])
        if ph >= threshold:
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


# ── Run all three ──────────────────────────────────────────────────────────────
print("Running simulations...")
d15 = run_tushar(15.0)
d10 = run_tushar(10.0)

r15 = monthly_rets(d15)
r10 = monthly_rets(d10)
qr  = qqq_monthly_rets(qqq_raw)

# ── Print comparison ───────────────────────────────────────────────────────────
W = 88; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  10% Threshold vs 15% Threshold (TusharStrategy) vs QQQ  (2006-present)")
print("  T15: pctHigh252 >= 15% -> CASH | 3-day re-entry below 15%")
print("  T10: pctHigh252 >= 10% -> CASH | 3-day re-entry below 10%")
print(SEP)

cum = {"q": DEFAULT_CAPITAL, "t15": DEFAULT_CAPITAL, "t10": DEFAULT_CAPITAL}
yr_totals = []
all_years = sorted(set(ym[0] for ym in r15 if ym[0] >= SHOW_FROM))

for year in all_years:
    months = sorted(ym for ym in r15 if ym[0] == year)
    if not months: continue
    yr_s = dict(cum)
    print(f"\n  -- {year} {'-'*72}")
    print(f"  {'Mo':<5} {'QQQ':>8} {'T15(15%)':>10} {'T10(10%)':>10}   Regime-15   Regime-10")
    print(DIV)

    for ym in months:
        m   = ym[1]
        q   = qr.get(ym)
        t15 = r15.get(ym)
        t10 = r10.get(ym)
        if q:   cum["q"]   *= 1 + q   / 100
        if t15: cum["t15"] *= 1 + t15 / 100
        if t10: cum["t10"] *= 1 + t10 / 100

        ph_vals = [float(sig.loc[d, "pcthi"])
                   for d in sig.index if d.year == year and d.month == m]
        avg_ph  = sum(ph_vals) / len(ph_vals) if ph_vals else 0.0
        r15_lbl = "CASH" if avg_ph >= 15.0 else f"TQQQ({avg_ph:.0f}%)"
        r10_lbl = "CASH" if avg_ph >= 10.0 else f"TQQQ({avg_ph:.0f}%)"

        print(f"  {MONTHS[m]:<5} {fmt(q):>8} {fmt(t15):>10} {fmt(t10):>10}   {r15_lbl:<11} {r10_lbl}")

    fy_q   = round((cum["q"]   / yr_s["q"]   - 1) * 100, 1)
    fy_t15 = round((cum["t15"] / yr_s["t15"] - 1) * 100, 1)
    fy_t10 = round((cum["t10"] / yr_s["t10"] - 1) * 100, 1)
    yr_totals.append((year, fy_q, fy_t15, fy_t10))
    print(DIV)
    win = "<- T10" if fy_t10 > fy_t15 else ("<- T15" if fy_t15 > fy_t10 else "TIE")
    print(f"  {'FY '+str(year):<5} {fmt(fy_q):>8} {fmt(fy_t15):>10} {fmt(fy_t10):>10}   {win}")

# ── Annual summary ─────────────────────────────────────────────────────────────
print(); print(SEP)
print("  ANNUAL SUMMARY")
print(DIV)
print(f"  {'Year':<6} {'QQQ':>8} {'T15(15%)':>10} {'T10(10%)':>10}   Winner")
print(DIV)
t10_wins = t15_wins = 0
for y, q, t15, t10 in yr_totals:
    if t10 > t15:
        win = "<- T10 wins"; t10_wins += 1
    elif t15 > t10:
        win = "<- T15 wins"; t15_wins += 1
    else:
        win = "TIE"
    print(f"  {str(y):<6} {fmt(q):>8} {fmt(t15):>10} {fmt(t10):>10}   {win}")
print(DIV)
ov_q   = round((cum["q"]   / DEFAULT_CAPITAL - 1) * 100, 1)
ov_t15 = round((cum["t15"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_t10 = round((cum["t10"] / DEFAULT_CAPITAL - 1) * 100, 1)
today  = date.today()
yrs    = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365
cq     = round(((cum["q"]   / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
ct15   = round(((cum["t15"] / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
ct10   = round(((cum["t10"] / DEFAULT_CAPITAL) ** (1/yrs) - 1) * 100, 1)
fq     = round(cum["q"])
ft15   = round(cum["t15"])
ft10   = round(cum["t10"])
print(f"  {'Total%':<6} {fmt(ov_q):>8} {fmt(ov_t15):>10} {fmt(ov_t10):>10}")
print(f"  {'CAGR':<6} {fmt(cq):>8} {fmt(ct15):>10} {fmt(ct10):>10}")
print(f"  {'Final$':<6} {'${:,.0f}'.format(fq):>9} {'${:,.0f}'.format(ft15):>11} {'${:,.0f}'.format(ft10):>11}")
print(DIV)
print(f"  T15 wins: {t15_wins} years   T10 wins: {t10_wins} years")
print(SEP)
