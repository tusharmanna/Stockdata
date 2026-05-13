"""
TusharStrategy on NDX — full history 1985 to present
Signal : NDX 252-day rolling high pctHigh >= 15% -> CASH | 3-day re-entry
Instrument: TQQQ (real from Feb 2010; synthetic 3x NDX before that)
"""
import math, sqlite3
from collections import defaultdict
from datetime import date
import pandas as pd
import yfinance as yf

THRESHOLD    = 15.0
REENTRY_DAYS = 3
HIGH_PERIOD  = 252
CAPITAL      = 100_000.0
SHOW_FROM    = 1986   # first full year (NDX starts Oct 1985)


def load_ndx_from_db():
    conn = sqlite3.connect("stockdata.db")
    df   = pd.read_sql(
        "SELECT date, close FROM prices WHERE ticker='NDX' ORDER BY date",
        conn, parse_dates=["date"], index_col="date"
    )
    conn.close()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def load_yf(ticker, start="2004-01-01"):
    raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
    raw.index   = pd.to_datetime(raw.index).tz_localize(None)
    return raw[["close"]].copy()


def price_on(df, dt):
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def fmt(v, w=9):
    if v is None: return "  N/A  ".rjust(w)
    return f"{'+'if v>=0 else ''}{v:.1f}%".rjust(w)


print("Loading data...")
ndx_raw  = load_ndx_from_db()
tqqq_raw = load_yf("TQQQ", "2010-01-01")

# ── Build synthetic TQQQ back to 1985 using 3x NDX daily returns ──────────────
print("Building synthetic TQQQ from 3x NDX (back to 1985)...")
ipo     = tqqq_raw.index[0]          # 2010-02-11
anchor  = float(tqqq_raw.iloc[0]["close"])
ndx_ret = ndx_raw["close"].pct_change().fillna(0.0)
dates   = ndx_raw.index.tolist()

px = {ipo: anchor}
ipo_idx = dates.index(ipo) if ipo in dates else None
if ipo_idx is None:
    # find closest date
    ipo_idx = next(i for i, d in enumerate(dates) if d >= ipo)

for i in range(ipo_idx - 1, -1, -1):
    r = float(ndx_ret.iloc[i + 1])
    d = 1 + 3 * r
    px[dates[i]] = px[dates[i + 1]] / d if d != 0 else px[dates[i + 1]]

# Combine synthetic + real
synth_before = pd.DataFrame({"close": {k: v for k, v in px.items() if k < ipo}}).sort_index()
tqqq = pd.concat([synth_before, tqqq_raw]).sort_index()
print(f"  TQQQ range: {tqqq.index[0].date()} to {tqqq.index[-1].date()}")
print(f"  Synthetic anchor @ IPO: ${anchor:.2f} | Synthetic 1985-10-01: ${px[dates[0]]:.6f}")

# ── Build signal on NDX ────────────────────────────────────────────────────────
sig = ndx_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100

# ── Run TusharStrategy ─────────────────────────────────────────────────────────
print("Running simulation...")
cash, sh = CAPITAL, 0
days, in_bull, prev = 0, False, False
daily = []
trade_log = []
open_trade = None

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
        sh = math.floor(cash / tp) if tp > 0 else 0
        cash -= sh * tp
        open_trade = {"buy_date": dt, "buy_px": tp}
    elif not in_bull and prev:
        proceeds = sh * tp
        pnl_pct  = (tp - open_trade["buy_px"]) / open_trade["buy_px"] * 100 if open_trade else 0
        trade_log.append({**open_trade, "sell_date": dt, "sell_px": tp,
                          "pnl_pct": round(pnl_pct, 1),
                          "days": (dt - open_trade["buy_date"]).days})
        cash += proceeds; sh = 0; open_trade = None

    prev = in_bull
    daily.append({"date": dt, "port": round(sh * tp + cash, 2),
                  "in_bull": in_bull, "pcthi": ph})

# ── Annual returns ─────────────────────────────────────────────────────────────
def annual_rets(daily):
    bm = defaultdict(list)
    for d in daily: bm[d["date"].year].append(d["port"])
    sy = sorted(bm); res = {}
    for i, yr in enumerate(sy):
        e = bm[yr][-1]
        s = bm[sy[i-1]][-1] if i > 0 else bm[yr][0]
        res[yr] = round((e - s) / s * 100, 1) if s else 0.0
    return res

def ndx_annual():
    bm = defaultdict(list)
    for dt, row in ndx_raw.iterrows(): bm[dt.year].append(float(row["close"]))
    sy = sorted(bm); res = {}
    for i, yr in enumerate(sy):
        e = bm[yr][-1]
        s = bm[sy[i-1]][-1] if i > 0 else bm[yr][0]
        res[yr] = round((e - s) / s * 100, 1) if s else 0.0
    return res

ann     = annual_rets(daily)
ann_ndx = ndx_annual()

# ── Print ──────────────────────────────────────────────────────────────────────
W = 80; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  TusharStrategy on NDX  —  Annual Returns 1986-present")
print("  Signal : NDX pctHigh252 >= 15% -> CASH  |  3-day re-entry")
print("  Instrument: 3x leveraged TQQQ (synthetic pre-2010, real post-2010)")
print(SEP)
print(f"  {'Year':<6} {'NDX Index':>10} {'Strategy':>10}  {'Regime':>8}  {'vs NDX':>8}")
print(DIV)

all_years = sorted(yr for yr in ann if yr >= SHOW_FROM)
cum = {"ndx": CAPITAL, "strat": CAPITAL}
yr_totals = []

for yr in all_years:
    ni  = ann_ndx.get(yr)
    st  = ann.get(yr)
    if ni: cum["ndx"]   *= 1 + ni / 100
    if st: cum["strat"] *= 1 + st / 100

    # Regime label: was strategy mostly in TQQQ or CASH?
    yr_days   = [d for d in daily if d["date"].year == yr]
    bull_days  = sum(1 for d in yr_days if d["in_bull"])
    total_days = len(yr_days)
    bull_pct   = bull_days / total_days * 100 if total_days else 0
    regime     = f"TQQQ {bull_pct:.0f}%" if bull_pct > 0 else "CASH"

    vs = round(st - ni, 1) if (st is not None and ni is not None) else None
    vs_s = f"{vs:+.1f}%" if vs is not None else ""

    # Highlight big years
    flag = ""
    if st is not None and st <= -30: flag = " << BAD"
    elif st is not None and st >= 100: flag = " !! GREAT"

    print(f"  {yr:<6} {fmt(ni):>10} {fmt(st):>10}  {regime:>8}  {vs_s:>8}{flag}")
    yr_totals.append((yr, ni, st))

# ── Summary ────────────────────────────────────────────────────────────────────
print(DIV)
today = date.today()
yrs   = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365
cagr_ndx  = round(((cum["ndx"]   / CAPITAL) ** (1/yrs) - 1) * 100, 1)
cagr_strat= round(((cum["strat"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
total_ndx  = round((cum["ndx"]   / CAPITAL - 1) * 100, 1)
total_strat= round((cum["strat"] / CAPITAL - 1) * 100, 1)

print()
print(SEP)
print("  SUMMARY  (1986 – present)")
print(DIV)
print(f"  {'':25} {'NDX Index':>12} {'Strategy':>12}")
print(DIV)
print(f"  {'Total Return':<25} {fmt(total_ndx):>12} {fmt(total_strat):>12}")
print(f"  {'CAGR':<25} {fmt(cagr_ndx):>12} {fmt(cagr_strat):>12}")
print(f"  {'Final $ (from $100K)':<25} {'${:,.0f}'.format(cum['ndx']):>12} {'${:,.0f}'.format(cum['strat']):>12}")

wins  = sum(1 for _, ni, st in yr_totals if st is not None and ni is not None and st > ni)
loses = sum(1 for _, ni, st in yr_totals if st is not None and ni is not None and st < ni)
best_yr  = max(yr_totals, key=lambda x: x[2] if x[2] else -999)
worst_yr = min(yr_totals, key=lambda x: x[2] if x[2] else 999)
print(f"  {'Strategy beats NDX':<25} {wins:>12} years  (loses {loses} years)")
print(f"  {'Best year':<25} {best_yr[0]:>12}  ({fmt(best_yr[2]).strip()})")
print(f"  {'Worst year':<25} {worst_yr[0]:>12}  ({fmt(worst_yr[2]).strip()})")
print(DIV)

# Decade breakdown
print()
print(SEP)
print("  DECADE BREAKDOWN")
print(DIV)
print(f"  {'Decade':<12} {'NDX CAGR':>10} {'Strategy CAGR':>15}  {'NDX Total':>11} {'Strat Total':>12}")
print(DIV)
decades = [(1986,1989,"1980s"), (1990,1999,"1990s"), (2000,2009,"2000s"),
           (2010,2019,"2010s"), (2020,2026,"2020s")]
for (d_start, d_end, label) in decades:
    yrs_d = [(yr, ni, st) for yr, ni, st in yr_totals if d_start <= yr <= d_end]
    if not yrs_d: continue
    cn = cd = CAPITAL
    for _, ni, st in yrs_d:
        if ni: cn *= 1 + ni / 100
        if st: cd *= 1 + st / 100
    n_yrs = len(yrs_d)
    cagr_n = round((cn / CAPITAL) ** (1/n_yrs) - 1, 4) * 100
    cagr_d = round((cd / CAPITAL) ** (1/n_yrs) - 1, 4) * 100
    tot_n  = round((cn / CAPITAL - 1) * 100, 1)
    tot_d  = round((cd / CAPITAL - 1) * 100, 1)
    print(f"  {label:<12} {fmt(cagr_n):>10} {fmt(cagr_d):>15}  {fmt(tot_n):>11} {fmt(tot_d):>12}")
print(SEP)
