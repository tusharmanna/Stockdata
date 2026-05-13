import math, yfinance as yf, pandas as pd
from collections import defaultdict
from whitelight_strategy import DEFAULT_CAPITAL, HIGH_PERIOD, BULL_ETF, SIGNAL_TKR

START            = "2015-01-01"
SHOW_FROM        = 2016
SIGNAL_THRESHOLD = 15.0
REENTRY_DAYS     = 3
ADX_THRESHOLD    = 36.0
STAGE_BANDS      = [(15.0, 1.00), (25.0, 0.50), (float("inf"), 0.00)]

TARGET = {
    2023: {1:12.8, 2:-5.1,  3:7.3,   4:-0.9, 5:23.8, 6:12.1, 7:10.1, 8:-1.8, 9:-6.1, 10:-2.9, 11:9.7,  12:3.6},
    2024: {1:7.3,  2:4.5,   3:-0.6,  4:-8.6, 5:19.2, 6:1.7,  7:-3.3, 8:1.0,  9:-4.0, 10:-0.7, 11:-9.1, 12:5.2},
    2025: {1:2.8,  2:-3.5,  3:-21.2, 4:2.6,  5:17.7, 6:21.2, 7:5.4,  8:4.0,  9:11.5, 10:-0.7, 11:1.4,  12:-1.8},
    2026: {1:-4.9, 2:-4.9,  3:-1.6,  4:23.8},
}
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def load(ticker):
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    df  = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index).tz_localize(None)
    return df


def calc_adx(df, p=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr  = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    dp  = (h-h.shift()).clip(lower=0).where((h-h.shift()) > (l.shift()-l), 0.0)
    dm  = (l.shift()-l).clip(lower=0).where((l.shift()-l) > (h-h.shift()), 0.0)
    a   = 1/p
    atr = tr.ewm(alpha=a, adjust=False, min_periods=p).mean()
    dp2 = dp.ewm(alpha=a, adjust=False, min_periods=p).mean()
    dm2 = dm.ewm(alpha=a, adjust=False, min_periods=p).mean()
    pip = 100 * dp2 / atr.replace(0, float("nan"))
    pim = 100 * dm2 / atr.replace(0, float("nan"))
    dx  = 100 * (pip-pim).abs() / (pip+pim).replace(0, float("nan"))
    return dx.ewm(alpha=a, adjust=False, min_periods=p).mean()


def stage_factor(p):
    for mx, f in STAGE_BANDS:
        if p < mx:
            return f
    return 0.0


def price_on(df, d):
    if d in df.index:
        return float(df.loc[d, "close"])
    avail = df.index[df.index <= d]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


print("Downloading QQQ + TQQQ (2015-present)...")
qqq  = load(SIGNAL_TKR)
tqqq = load(BULL_ETF)

sig           = qqq.copy()
sig["h252"]   = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"]  = (sig["h252"] - sig["close"]) / sig["h252"] * 100
sig["adx14"]  = calc_adx(sig)

# ── TQQQ Strategy (daily ADX-scaled rebalancing) ──────────────────────────────
t_sh = 0; t_cash = DEFAULT_CAPITAL; t_days = 0; t_in = True
t_daily = []
for date, row in sig.iterrows():
    tp = price_on(tqqq, date)
    if tp is None:
        continue
    port = t_sh * tp + t_cash
    ph   = float(row["pcthi"])
    af   = min(1.0, float(row["adx14"]) / ADX_THRESHOLD)
    if ph >= SIGNAL_THRESHOLD:
        t_days = 0; t_in = False
    else:
        t_days += 1
        if t_days >= REENTRY_DAYS:
            t_in = True
    pct = stage_factor(ph) * af if t_in else 0.0
    ns  = math.floor(port * pct / tp) if pct > 0 else 0
    t_cash += (t_sh - ns) * tp
    t_sh    = ns
    t_daily.append({"date": date, "port": round(t_sh * tp + t_cash, 2)})

# ── TusharStrategy (buy-and-hold until signal changes) ───────────────────────
m_sh = 0; m_cash = DEFAULT_CAPITAL; m_days = 0; m_in = True; m_prev = False
m_daily = []
for date, row in sig.iterrows():
    tp = price_on(tqqq, date)
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
    m_daily.append({"date": date, "port": round(m_sh * tp + m_cash, 2)})


def monthly_rets(daily):
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["port"])
    sm  = sorted(bm)
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
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i-1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


qr = qqq_monthly_rets(qqq)
tr = monthly_rets(t_daily)
mr = monthly_rets(m_daily)

ph_by_month = defaultdict(list)
for date, row in sig.iterrows():
    ph_by_month[(date.year, date.month)].append(float(row["pcthi"]))


def fmt(v, w=8):
    if v is None:
        return "  N/A  ".rjust(w)
    s = "+" if v >= 0 else ""
    return f"{s}{v:.1f}%".rjust(w)


W   = 92
SEP = "=" * W
DIV = "-" * W

print()
print(SEP)
print(f"  10-YEAR BACKTEST  2016-2026  |  Capital: ${DEFAULT_CAPITAL:,.0f}")
print(f"  Signal: QQQ % below 252d-high < 15% => TQQQ  |  >= 15% => CASH")
print(SEP)
print(f"  {'Month':<8}  {'QQQ':>9}  {'TQQQ Strat':>11}  {'TusharStrategy':>10}  {'C2 Target':>10}  Regime")
print(f"  {'':8}  {'B&H':>9}  {'DailyRebal':>11}  {'TusharStrat':>10}  {'Actual':>10}")
print(DIV)

cum = {k: DEFAULT_CAPITAL for k in ("qqq","tqqq","mod","c2")}
c2_started = False
yr_totals  = []
all_years  = sorted(set(ym[0] for ym in qr if ym[0] >= SHOW_FROM))

for year in all_years:
    months_in_yr = sorted(ym for ym in qr if ym[0] == year)
    if not months_in_yr:
        continue

    yr_start = dict(cum)

    print(f"\n  -- {year} {'-'*78}")

    for ym in months_in_yr:
        m   = ym[1]
        q   = qr.get(ym)
        t   = tr.get(ym)
        md  = mr.get(ym)
        c2  = TARGET.get(year, {}).get(m)

        phs    = ph_by_month.get(ym, [0])
        avg_ph = round(sum(phs) / len(phs), 1)
        regime = "CASH" if avg_ph >= SIGNAL_THRESHOLD else "TQQQ"

        if q:  cum["qqq"]  *= 1 + q  / 100
        if t:  cum["tqqq"] *= 1 + t  / 100
        if md: cum["mod"]  *= 1 + md / 100
        if c2 is not None:
            if not c2_started:
                c2_started    = True
                cum["c2"]     = DEFAULT_CAPITAL
                yr_start["c2"] = DEFAULT_CAPITAL
            cum["c2"] *= 1 + c2 / 100

        c2_f = fmt(c2) if c2 is not None else "    N/A "
        print(f"  {MONTHS[m]:<8}  {fmt(q):>9}  {fmt(t):>11}  {fmt(md):>10}  {c2_f:>10}  {regime} ({avg_ph:.1f}%)")

    fy_q  = round((cum["qqq"]  / yr_start["qqq"]  - 1) * 100, 1)
    fy_t  = round((cum["tqqq"] / yr_start["tqqq"] - 1) * 100, 1)
    fy_m  = round((cum["mod"]  / yr_start["mod"]  - 1) * 100, 1)
    fy_c2 = round((cum["c2"]   / yr_start["c2"]   - 1) * 100, 1) if c2_started and yr_start.get("c2", 0) > 0 else None
    yr_totals.append((year, fy_q, fy_t, fy_m, fy_c2))

    c2_fy = fmt(fy_c2) if fy_c2 is not None else "    N/A "
    print(DIV)
    print(f"  {'FY '+str(year):<8}  {fmt(fy_q):>9}  {fmt(fy_t):>11}  {fmt(fy_m):>10}  {c2_fy:>10}")

# ── Annual summary + grand total ──────────────────────────────────────────────
print()
print(SEP)
print(f"  ANNUAL SUMMARY  (Jan 2016 -> present)")
print(DIV)
print(f"  {'Year':<8}  {'QQQ':>9}  {'TQQQ Strat':>11}  {'TusharStrategy':>10}  {'C2 Target':>10}")
print(DIV)
for y, q, t, m, c2 in yr_totals:
    c2f = fmt(c2) if c2 is not None else "    N/A "
    print(f"  {str(y):<8}  {fmt(q):>9}  {fmt(t):>11}  {fmt(m):>10}  {c2f:>10}")

print(DIV)
ov_q  = round((cum["qqq"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_t  = round((cum["tqqq"] / DEFAULT_CAPITAL - 1) * 100, 1)
ov_m  = round((cum["mod"]  / DEFAULT_CAPITAL - 1) * 100, 1)
ov_c2 = round((cum["c2"]   / DEFAULT_CAPITAL - 1) * 100, 1) if c2_started else None

print(f"  {'Final $':<8}  ${cum['qqq']:>8,.0f}  ${cum['tqqq']:>9,.0f}  ${cum['mod']:>8,.0f}  ${cum['c2']:>8,.0f}")
print(f"  {'Total %':<8}  {fmt(ov_q):>9}  {fmt(ov_t):>11}  {fmt(ov_m):>10}  {fmt(ov_c2):>10}")
print(f"  {'C2 note':<8}  C2 portfolio starts at $100k from Jan 2023 (first available data)")
print(SEP)
