"""
20-year backtest: TusharStrategy vs QQQ (2006-2026)

TQQQ IPO was Feb 9, 2010. Pre-2010 TQQQ is synthesized by rolling back
from the IPO price using 3x QQQ daily returns each day.
"""
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

START            = "2004-01-01"   # need 252-day warmup before 2006
SHOW_FROM        = 2006
SIGNAL_THRESHOLD = 15.0
REENTRY_DAYS     = 3
HIGH_PERIOD      = 252
DEFAULT_CAPITAL  = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

TARGET = {
    2023: {1:12.8, 2:-5.1,  3:7.3,   4:-0.9, 5:23.8, 6:12.1, 7:10.1, 8:-1.8, 9:-6.1, 10:-2.9, 11:9.7,  12:3.6},
    2024: {1:7.3,  2:4.5,   3:-0.6,  4:-8.6, 5:19.2, 6:1.7,  7:-3.3, 8:1.0,  9:-4.0, 10:-0.7, 11:-9.1, 12:5.2},
    2025: {1:2.8,  2:-3.5,  3:-21.2, 4:2.6,  5:17.7, 6:21.2, 7:5.4,  8:4.0,  9:11.5, 10:-0.7, 11:1.4,  12:-1.8},
    2026: {1:-4.9, 2:-4.9,  3:-1.6,  4:23.8},
}


def load(ticker):
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    df  = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index).tz_localize(None)
    return df


def build_synthetic_tqqq(qqq_df, tqqq_df):
    """
    Extend TQQQ backwards before its Feb 2010 IPO.
    Works backwards from the IPO price using: tqqq[d-1] = tqqq[d] / (1 + 3 * qqq_ret[d])
    """
    tqqq_start   = tqqq_df.index[0]
    anchor_price = float(tqqq_df.iloc[0]["close"])

    # QQQ closes up to and including TQQQ IPO date
    pre_qqq = qqq_df.loc[:tqqq_start, "close"]
    qqq_ret = pre_qqq.pct_change().fillna(0.0)
    dates   = pre_qqq.index.tolist()   # ascending; last element == tqqq_start

    prices = {tqqq_start: anchor_price}
    for i in range(len(dates) - 2, -1, -1):
        curr = dates[i]
        nxt  = dates[i + 1]
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


# ── Download ───────────────────────────────────────────────────────────────────
print("Downloading QQQ and TQQQ (2004-present)...")
qqq_raw  = load("QQQ")
tqqq_raw = load("TQQQ")

tqqq_ipo = tqqq_raw.index[0].date()
print(f"  QQQ : {qqq_raw.index[0].date()} to {qqq_raw.index[-1].date()}  ({len(qqq_raw)} days)")
print(f"  TQQQ: {tqqq_ipo} to {tqqq_raw.index[-1].date()}  ({len(tqqq_raw)} days, actual)")
print(f"  Synthesizing TQQQ pre-{tqqq_ipo} from 3x QQQ daily returns...")

tqqq = build_synthetic_tqqq(qqq_raw, tqqq_raw)
print(f"  TQQQ: {tqqq.index[0].date()} to {tqqq.index[-1].date()}  ({len(tqqq)} days, combined)")

# ── Signal ─────────────────────────────────────────────────────────────────────
sig          = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100

# ── TusharStrategy simulation ──────────────────────────────────────────────────
m_sh = 0; m_cash = DEFAULT_CAPITAL; m_days = 0; m_in = True; m_prev = False
m_daily = []
for dt, row in sig.iterrows():
    tp = price_on(tqqq, dt)
    if tp is None:
        continue
    ph = float(row["pcthi"])
    if ph >= SIGNAL_THRESHOLD:
        m_days = 0; m_in = False
    else:
        m_days += 1
        if m_days >= REENTRY_DAYS:
            m_in = True
    if m_in and not m_prev:
        ns = math.floor(m_cash / tp) if tp > 0 else 0
        m_cash -= ns * tp; m_sh = ns
    elif not m_in and m_prev:
        m_cash += m_sh * tp; m_sh = 0
    m_prev = m_in
    m_daily.append({"date": dt, "port": round(m_sh * tp + m_cash, 2)})


# ── Monthly return helpers ─────────────────────────────────────────────────────
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


qr = qqq_monthly_rets(qqq_raw)
mr = monthly_rets(m_daily)

ph_by_month = defaultdict(list)
for dt, row in sig.iterrows():
    ph_by_month[(dt.year, dt.month)].append(float(row["pcthi"]))


def fmt(v, w=8):
    if v is None:
        return "  N/A  ".rjust(w)
    s = "+" if v >= 0 else ""
    return f"{s}{v:.1f}%".rjust(w)


# ── Print ──────────────────────────────────────────────────────────────────────
W   = 84
SEP = "=" * W
DIV = "-" * W

print()
print(SEP)
print(f"  20-YEAR BACKTEST  2006-2026  |  Capital: ${DEFAULT_CAPITAL:,.0f}")
print(f"  Signal : QQQ >= 15% below 252d-high => CASH  |  < 15% => hold TQQQ")
print(f"  Pre-{tqqq_ipo}: TQQQ simulated as 3x QQQ daily returns")
print(SEP)
print(f"  {'Month':<8}  {'QQQ B&H':>9}  {'TusharStrategy':>16}  {'C2 Target':>10}  Regime")
print(DIV)

cum = {"qqq": DEFAULT_CAPITAL, "mod": DEFAULT_CAPITAL, "c2": DEFAULT_CAPITAL}
c2_started = False
yr_totals  = []
all_years  = sorted(set(ym[0] for ym in qr if ym[0] >= SHOW_FROM))

for year in all_years:
    months_in_yr = sorted(ym for ym in qr if ym[0] == year)
    if not months_in_yr:
        continue

    yr_start = dict(cum)
    print(f"\n  -- {year} {'-'*70}")

    for ym in months_in_yr:
        m  = ym[1]
        q  = qr.get(ym)
        md = mr.get(ym)
        c2 = TARGET.get(year, {}).get(m)

        phs    = ph_by_month.get(ym, [0])
        avg_ph = round(sum(phs) / len(phs), 1)
        regime = "CASH" if avg_ph >= SIGNAL_THRESHOLD else "TQQQ"

        if q:  cum["qqq"] *= 1 + q  / 100
        if md: cum["mod"] *= 1 + md / 100
        if c2 is not None:
            if not c2_started:
                c2_started     = True
                cum["c2"]      = DEFAULT_CAPITAL
                yr_start["c2"] = DEFAULT_CAPITAL
            cum["c2"] *= 1 + c2 / 100

        c2_f = fmt(c2) if c2 is not None else "    N/A "
        print(f"  {MONTHS[m]:<8}  {fmt(q):>9}  {fmt(md):>16}  {c2_f:>10}  {regime} ({avg_ph:.1f}%)")

    fy_q  = round((cum["qqq"] / yr_start["qqq"] - 1) * 100, 1)
    fy_m  = round((cum["mod"] / yr_start["mod"] - 1) * 100, 1)
    fy_c2 = (round((cum["c2"] / yr_start["c2"] - 1) * 100, 1)
              if c2_started and yr_start.get("c2", 0) > 0 else None)
    yr_totals.append((year, fy_q, fy_m, fy_c2))

    c2_fy = fmt(fy_c2) if fy_c2 is not None else "    N/A "
    print(DIV)
    print(f"  {'FY '+str(year):<8}  {fmt(fy_q):>9}  {fmt(fy_m):>16}  {c2_fy:>10}")

# ── Annual summary ─────────────────────────────────────────────────────────────
print()
print(SEP)
print(f"  ANNUAL SUMMARY  (Jan 2006 -> present)")
print(DIV)
print(f"  {'Year':<8}  {'QQQ B&H':>9}  {'TusharStrategy':>16}  {'C2 Target':>10}")
print(DIV)
for y, q, m, c2 in yr_totals:
    c2f = fmt(c2) if c2 is not None else "    N/A "
    print(f"  {str(y):<8}  {fmt(q):>9}  {fmt(m):>16}  {c2f:>10}")

print(DIV)
ov_q  = round((cum["qqq"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_m  = round((cum["mod"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_c2 = round((cum["c2"] / DEFAULT_CAPITAL - 1) * 100, 1) if c2_started else None

# CAGR from Jan 2006 to today
today        = date.today()
years_elapsed = (today.year - 2006) + (today.month - 1) / 12 + (today.day - 1) / 365
cagr_qqq = round(((cum["qqq"] / DEFAULT_CAPITAL) ** (1 / years_elapsed) - 1) * 100, 1)
cagr_mod = round(((cum["mod"] / DEFAULT_CAPITAL) ** (1 / years_elapsed) - 1) * 100, 1)

c2_note = f"  ${cum['c2']:>8,.0f}" if c2_started else "        N/A"
print(f"  {'Final $':<8}  ${cum['qqq']:>8,.0f}  ${cum['mod']:>14,.0f} {c2_note}")
print(f"  {'Total %':<8}  {fmt(ov_q):>9}  {fmt(ov_m):>16}  {fmt(ov_c2):>10}")
print(f"  {'CAGR':<8}  {fmt(cagr_qqq):>9}  {fmt(cagr_mod):>16}  {'(annualized)':>10}")
print(DIV)
print(f"  C2 starts Jan 2023 (first available data).  Pre-{tqqq_ipo} TQQQ is simulated.")
print(SEP)
