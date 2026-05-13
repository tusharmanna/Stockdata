"""
TusharStrategy on NDX signal vs QQQ signal — year-by-year returns
Uses NDX 252-day rolling high to generate BUY/CASH signal.
Instrument remains TQQQ (3x NDX/QQQ).
"""
import math, sqlite3
from collections import defaultdict
from datetime import date
import pandas as pd
import yfinance as yf

START         = "2004-01-01"
SHOW_FROM     = 2006
THRESHOLD     = 15.0
REENTRY_DAYS  = 3
HIGH_PERIOD   = 252
CAPITAL       = 100_000.0
MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


# ── Load NDX from local DB ─────────────────────────────────────────────────────
def load_ndx_from_db():
    conn = sqlite3.connect("stockdata.db")
    df   = pd.read_sql(
        "SELECT date, open, high, low, close, volume FROM prices WHERE ticker='NDX' ORDER BY date",
        conn, parse_dates=["date"], index_col="date"
    )
    conn.close()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


# ── Load QQQ / TQQQ from yfinance ─────────────────────────────────────────────
def load_yf(ticker):
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


def build_sig(df):
    s = df[["close"]].copy()
    s["h252"]  = s["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    s["pcthi"] = (s["h252"] - s["close"]) / s["h252"] * 100
    return s


print("Loading data...")
ndx_raw = load_ndx_from_db()
qqq_raw = load_yf("QQQ")
tqqq    = build_synthetic_tqqq(load_yf("QQQ"), load_yf("TQQQ"))

# Align NDX to QQQ trading dates
sig_ndx = build_sig(ndx_raw)
sig_qqq = build_sig(qqq_raw)


# ── Generic Tushar simulator ───────────────────────────────────────────────────
def run_tushar(sig, capital=CAPITAL):
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
        daily.append({"date": dt, "port": round(sh * tp + cash, 2),
                      "in_bull": in_bull, "pcthi": ph})
    return daily


# ── Annual returns + helpers ───────────────────────────────────────────────────
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


def index_annual(df):
    bm = defaultdict(list)
    for dt, row in df.iterrows():
        bm[dt.year].append(float(row["close"]))
    sy = sorted(bm); res = {}
    for i, yr in enumerate(sy):
        e = bm[yr][-1]
        s = bm[sy[i-1]][-1] if i > 0 else bm[yr][0]
        res[yr] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def fmt(v, w=9):
    if v is None: return "  N/A  ".rjust(w)
    return f"{'+'if v>=0 else ''}{v:.1f}%".rjust(w)


print("Running simulations...")
ndx_daily = run_tushar(sig_ndx)
qqq_daily = run_tushar(sig_qqq)

ann_ndx  = annual_rets(ndx_daily)
ann_qqq  = annual_rets(qqq_daily)
ann_ndxi = index_annual(ndx_raw)   # raw NDX index %
ann_qqqi = index_annual(qqq_raw)   # raw QQQ %

# ── Print year-by-year table ───────────────────────────────────────────────────
W = 90; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  TusharStrategy on NDX signal vs QQQ signal  —  Year-by-Year Returns")
print("  Same rules: pctHigh252 >= 15% -> CASH | 3-day re-entry | Instrument: TQQQ")
print(SEP)
print(f"  {'Year':<6} {'NDX Index':>10} {'QQQ ETF':>10} {'T(NDX sig)':>12} {'T(QQQ sig)':>12}  {'Diff':>7}  Signal match?")
print(DIV)

all_years = sorted(set(list(ann_ndx.keys()) + list(ann_qqq.keys())))
all_years = [yr for yr in all_years if yr >= SHOW_FROM]

cum = {"ndx": CAPITAL, "qqq": CAPITAL, "tndx": CAPITAL, "tqqq": CAPITAL}
yr_totals = []

for yr in all_years:
    ni  = ann_ndxi.get(yr)
    qi  = ann_qqqi.get(yr)
    tnd = ann_ndx.get(yr)
    tqq = ann_qqq.get(yr)
    if ni:  cum["ndx"]  *= 1 + ni  / 100
    if qi:  cum["qqq"]  *= 1 + qi  / 100
    if tnd: cum["tndx"] *= 1 + tnd / 100
    if tqq: cum["tqqq"] *= 1 + tqq / 100

    diff = round(tnd - tqq, 1) if (tnd is not None and tqq is not None) else None
    diff_s = f"{diff:+.1f}%" if diff is not None else "  N/A"

    # Check if signals agreed (same regime each month)
    ndx_sig_yr = [d for d in ndx_daily if d["date"].year == yr]
    qqq_sig_yr = [d for d in qqq_daily if d["date"].year == yr]
    ndx_dates  = {d["date"]: d["in_bull"] for d in ndx_sig_yr}
    qqq_dates  = {d["date"]: d["in_bull"] for d in qqq_sig_yr}
    common     = set(ndx_dates) & set(qqq_dates)
    if common:
        agree = sum(1 for d in common if ndx_dates[d] == qqq_dates[d])
        pct   = agree / len(common) * 100
        match = f"{pct:.0f}% agree"
    else:
        match = "N/A"

    winner = ""
    if tnd is not None and tqq is not None:
        winner = " NDX>" if tnd > tqq else (" QQQ>" if tqq > tnd else "")

    print(f"  {yr:<6} {fmt(ni):>10} {fmt(qi):>10} {fmt(tnd):>12} {fmt(tqq):>12}  {diff_s:>7}  {match}{winner}")
    yr_totals.append((yr, ni, qi, tnd, tqq))

# ── Summary ────────────────────────────────────────────────────────────────────
print(DIV)
today = date.today()
yrs   = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365

def cagr(final): return round(((final / CAPITAL) ** (1 / yrs) - 1) * 100, 1)

print()
print(SEP)
print("  SUMMARY")
print(DIV)
print(f"  {'':20} {'NDX Index':>10} {'QQQ ETF':>10} {'T(NDX sig)':>12} {'T(QQQ sig)':>12}")
print(DIV)
ov_ni  = round((cum["ndx"]  / CAPITAL - 1) * 100, 1)
ov_qi  = round((cum["qqq"]  / CAPITAL - 1) * 100, 1)
ov_tnd = round((cum["tndx"] / CAPITAL - 1) * 100, 1)
ov_tqq = round((cum["tqqq"] / CAPITAL - 1) * 100, 1)
print(f"  {'Total Return':<20} {fmt(ov_ni):>10} {fmt(ov_qi):>10} {fmt(ov_tnd):>12} {fmt(ov_tqq):>12}")
print(f"  {'CAGR':<20} {fmt(cagr(cum['ndx'])):>10} {fmt(cagr(cum['qqq'])):>10} {fmt(cagr(cum['tndx'])):>12} {fmt(cagr(cum['tqqq'])):>12}")
print(f"  {'Final $ (from $100K)':<20} {'${:,.0f}'.format(cum['ndx']):>10} {'${:,.0f}'.format(cum['qqq']):>10} {'${:,.0f}'.format(cum['tndx']):>12} {'${:,.0f}'.format(cum['tqqq']):>12}")
print(DIV)

# Wins each
ndx_wins = sum(1 for _, ni, qi, tnd, tqq in yr_totals
               if tnd is not None and tqq is not None and tnd > tqq)
qqq_wins = sum(1 for _, ni, qi, tnd, tqq in yr_totals
               if tnd is not None and tqq is not None and tqq > tnd)
ties     = sum(1 for _, ni, qi, tnd, tqq in yr_totals
               if tnd is not None and tqq is not None and tnd == tqq)
print(f"  NDX signal wins: {ndx_wins} years | QQQ signal wins: {qqq_wins} years | Ties: {ties} years")
print(SEP)
