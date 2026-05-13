"""
Threshold sweep: test every 0.5% from 10% to 15% — find the optimum.
Shows CAGR, worst year, and year-by-year win matrix.
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


print("Loading data...")
qqq_raw = load("QQQ")
tqqq    = build_synthetic_tqqq(load("QQQ"), load("TQQQ"))

sig = qqq_raw.copy()
sig["h252"]  = sig["close"].rolling(HIGH_PERIOD, min_periods=1).max()
sig["pcthi"] = (sig["h252"] - sig["close"]) / sig["h252"] * 100


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


# ── Sweep thresholds ───────────────────────────────────────────────────────────
print("Running threshold sweep (10.0% to 15.0% in 0.5% steps)...")
thresholds = [round(x * 0.5, 1) for x in range(20, 31)]  # 10.0 to 15.0

results = []
all_annual = {}

for thr in thresholds:
    daily  = run_tushar(thr)
    ann    = annual_rets(daily)
    all_annual[thr] = ann

    years  = [yr for yr in ann if yr >= SHOW_FROM]
    vals   = [ann[yr] for yr in years]

    cum    = DEFAULT_CAPITAL
    for yr in years:
        cum *= 1 + ann[yr] / 100

    today = date.today()
    yrs   = (today.year - SHOW_FROM) + (today.month - 1) / 12 + (today.day - 1) / 365
    cagr  = round((cum / DEFAULT_CAPITAL) ** (1 / yrs) - 1, 4) * 100

    worst     = min(vals)
    worst_yr  = years[vals.index(worst)]
    n_bad     = sum(1 for v in vals if v < -20)
    n_loss    = sum(1 for v in vals if v < 0)
    final_m   = cum / 1_000_000

    results.append({
        "thr":      thr,
        "cagr":     round(cagr, 1),
        "final_m":  round(final_m, 2),
        "worst":    worst,
        "worst_yr": worst_yr,
        "n_bad":    n_bad,
        "n_loss":   n_loss,
    })

# ── Summary table ──────────────────────────────────────────────────────────────
W = 90; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  THRESHOLD SWEEP SUMMARY  (pctHigh252 threshold, 3-day re-entry, 2006-present)")
print(DIV)
print(f"  {'Thresh':>7}  {'CAGR':>7}  {'Final$M':>8}  {'Worst Yr':>9}  {'Worst%':>8}  {'Yrs<-20%':>9}  {'Yrs Loss':>9}")
print(DIV)

best_cagr = max(r["cagr"] for r in results)
for r in results:
    flag = " <-- BEST CAGR" if r["cagr"] == best_cagr else ""
    print(f"  {r['thr']:>6}%  {r['cagr']:>6}%  "
          f"  ${r['final_m']:>6.2f}M  "
          f"  {r['worst_yr']:>5}     "
          f"  {r['worst']:>6}%  "
          f"  {r['n_bad']:>5}      "
          f"  {r['n_loss']:>5}{flag}")
print(SEP)

# ── Year-by-year matrix ────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANNUAL RETURNS BY THRESHOLD  (2006-present)")
years_to_show = [yr for yr in sorted(all_annual[15.0]) if yr >= SHOW_FROM]
hdr = f"  {'Year':<6}" + "".join(f"{t:>7}%" for t in thresholds)
print(hdr)
print(DIV)

for yr in years_to_show:
    row = f"  {yr:<6}"
    vals_row = [all_annual[t].get(yr, 0.0) for t in thresholds]
    best_val = max(vals_row)
    for t, v in zip(thresholds, vals_row):
        s = f"{v:+.1f}%"
        marker = "*" if v == best_val else " "
        row += f"{marker}{s:>6} "
    print(row)

print(DIV)

# CAGR row
cagr_row = f"  {'CAGR':<6}"
cagr_vals = [r["cagr"] for r in results]
best_cagr_v = max(cagr_vals)
for t, v in zip(thresholds, cagr_vals):
    s = f"{v:+.1f}%"
    marker = "*" if v == best_cagr_v else " "
    cagr_row += f"{marker}{s:>6} "
print(cagr_row)

# Worst row
worst_row = f"  {'Worst':<6}"
worst_vals = [r["worst"] for r in results]
best_worst = max(worst_vals)
for t, v in zip(thresholds, worst_vals):
    s = f"{v:+.1f}%"
    marker = "*" if v == best_worst else " "
    worst_row += f"{marker}{s:>6} "
print(worst_row)

print(SEP)

# ── Recommendation ─────────────────────────────────────────────────────────────
print()
best_cagr_r  = max(results, key=lambda r: r["cagr"])
best_combo_r = max(results, key=lambda r: r["cagr"] + r["worst"] * 0.5)
print(f"  Best CAGR alone    : {best_cagr_r['thr']}%  ->  CAGR {best_cagr_r['cagr']}%  |  Worst year {best_cagr_r['worst']}% ({best_cagr_r['worst_yr']})")
print(f"  Best CAGR + Safety : {best_combo_r['thr']}%  ->  CAGR {best_combo_r['cagr']}%  |  Worst year {best_combo_r['worst']}% ({best_combo_r['worst_yr']})")
print(SEP)
