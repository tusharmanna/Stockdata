"""
MA200Strategy vs TusharStrategy vs QQQ — backtest since 2017

MA200Strategy:
  - BUY  TQQQ when QQQ daily close crosses ABOVE 200-day MA
  - SELL TQQQ when QQQ daily close crosses BELOW 200-day MA
  - No confirmation filter (immediate on crossover)
"""
import math
from collections import defaultdict
from datetime import date

from tushar_strategy import _load, compute_signal

CAPITAL = 100_000.0
MONTHS  = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data...")
qqq  = _load("QQQ",  "2015-01-01")
tqqq = _load("TQQQ", "2015-01-01")

# ── Signals ────────────────────────────────────────────────────────────────────
qqq["ma200"]    = qqq["close"].rolling(200, min_periods=1).mean()
qqq["above200"] = qqq["close"] > qqq["ma200"]

sig = compute_signal(qqq)   # TusharStrategy signal


# ── Simulation ─────────────────────────────────────────────────────────────────
def price_on(df, dt):
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_strategy(signal_series, tqqq_df, capital=CAPITAL):
    cash, shares, prev_in = capital, 0, False
    daily, trades = [], []
    buy_price = buy_date = None

    for dt, in_tqqq in signal_series.items():
        tp = price_on(tqqq_df, dt)
        if tp is None:
            continue

        if in_tqqq and not prev_in:
            shares    = math.floor(cash / tp)
            cash     -= shares * tp
            buy_price, buy_date = tp, dt
            trades.append({"type": "BUY", "date": dt, "price": tp, "shares": shares})

        elif not in_tqqq and prev_in:
            proceeds = shares * tp
            pnl      = proceeds - shares * buy_price
            pnl_pct  = (tp - buy_price) / buy_price * 100
            cash    += proceeds
            trades.append({"type": "SELL", "date": dt, "price": tp, "shares": shares,
                           "pnl": round(pnl, 0), "pnl_pct": round(pnl_pct, 1),
                           "cum": round(cash, 0)})
            shares = 0

        prev_in = in_tqqq
        daily.append({"date": dt, "port": round(shares * tp + cash, 2)})

    if shares > 0:
        last_tp = float(tqqq_df.iloc[-1]["close"])
        port    = shares * last_tp + cash
        pnl     = shares * last_tp - shares * buy_price
        trades.append({"type": "OPEN", "date": tqqq_df.index[-1], "price": last_tp,
                       "shares": shares, "pnl": round(pnl, 0),
                       "pnl_pct": round((last_tp - buy_price) / buy_price * 100, 1),
                       "cum": round(port, 0)})
    return daily, trades


tushar_signal = (sig["regime"] == "BUY_TQQQ")
ma200_signal  = qqq["above200"]

tushar_daily, tushar_trades = run_strategy(tushar_signal, tqqq)
ma200_daily,  ma200_trades  = run_strategy(ma200_signal,  tqqq)


# ── Monthly return helpers ─────────────────────────────────────────────────────
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


def qqq_monthly(df):
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


def fmt(v, w=8):
    if v is None:
        return "  N/A  ".rjust(w)
    return f"{'+'if v >= 0 else ''}{v:.1f}%".rjust(w)


tr = monthly_rets(tushar_daily)
mr = monthly_rets(ma200_daily)
qr = qqq_monthly(qqq)

# ── Monthly comparison table ───────────────────────────────────────────────────
W = 80; SEP = "=" * W; DIV = "-" * W

print()
print(SEP)
print("  COMPARISON: TusharStrategy vs MA200Strategy vs QQQ  (2017-present)")
print("  Tushar : QQQ >15% below 252d-high => CASH (3-day re-entry)")
print("  MA200  : QQQ close < 200-day MA   => CASH (immediate)")
print(SEP)

cum       = {"q": CAPITAL, "t": CAPITAL, "m": CAPITAL}
yr_totals = []
all_years = sorted(set(ym[0] for ym in tr if ym[0] >= 2017))

for year in all_years:
    months = sorted(ym for ym in tr if ym[0] == year)
    if not months:
        continue
    yr_s = dict(cum)
    print(f"\n  -- {year} {'-'*66}")
    print(f"  {'Month':<6} {'QQQ':>8} {'Tushar':>10} {'MA200':>10}  Regime-T  Regime-M")
    print(DIV)

    for ym in months:
        m  = ym[1]
        q  = qr.get(ym)
        t  = tr.get(ym)
        mv = mr.get(ym)
        if q:  cum["q"] *= 1 + q  / 100
        if t:  cum["t"] *= 1 + t  / 100
        if mv: cum["m"] *= 1 + mv / 100

        # Tushar regime label
        ph_vals = [float(sig.loc[d, "pcthi"])
                   for d in sig.index if d.year == year and d.month == m]
        avg_ph = sum(ph_vals) / len(ph_vals) if ph_vals else 0
        rt = "CASH" if avg_ph >= 15.0 else "TQQQ"

        # MA200 regime label
        ma_vals = [bool(qqq.loc[d, "above200"])
                   for d in qqq.index if d.year == year and d.month == m]
        rm = "TQQQ" if (sum(ma_vals) / len(ma_vals) >= 0.5) else "CASH"

        print(f"  {MONTHS[m]:<6} {fmt(q):>8} {fmt(t):>10} {fmt(mv):>10}  {rt:<9} {rm}")

    fy_q = round((cum["q"] / yr_s["q"] - 1) * 100, 1)
    fy_t = round((cum["t"] / yr_s["t"] - 1) * 100, 1)
    fy_m = round((cum["m"] / yr_s["m"] - 1) * 100, 1)
    yr_totals.append((year, fy_q, fy_t, fy_m))
    print(DIV)
    print(f"  {'FY '+str(year):<6} {fmt(fy_q):>8} {fmt(fy_t):>10} {fmt(fy_m):>10}")

# ── Annual summary ─────────────────────────────────────────────────────────────
print()
print(SEP)
print("  ANNUAL SUMMARY")
print(DIV)
print(f"  {'Year':<6} {'QQQ':>8} {'Tushar':>10} {'MA200':>10}")
print(DIV)
for y, q, t, m in yr_totals:
    print(f"  {str(y):<6} {fmt(q):>8} {fmt(t):>10} {fmt(m):>10}")
print(DIV)
ov_q = round((cum["q"] / CAPITAL - 1) * 100, 1)
ov_t = round((cum["t"] / CAPITAL - 1) * 100, 1)
ov_m = round((cum["m"] / CAPITAL - 1) * 100, 1)
today = date.today()
yrs   = (today.year - 2017) + (today.month - 1) / 12 + (today.day - 1) / 365
cq    = round(((cum["q"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
ct    = round(((cum["t"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
cm    = round(((cum["m"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
print(f"  {'Total%':<6} {fmt(ov_q):>8} {fmt(ov_t):>10} {fmt(ov_m):>10}")
print(f"  {'CAGR':<6} {fmt(cq):>8} {fmt(ct):>10} {fmt(cm):>10}")
print(SEP)

# ── Trade log MA200 ────────────────────────────────────────────────────────────
print()
print(SEP)
print("  MA200 STRATEGY — Trade Log (2017-present)")
print(SEP)
print(f"  {'#':<3} {'Type':<6} {'Date':<13} {'TQQQ Px':>9} {'Shares':>8} {'P&L $':>12} {'P&L%':>8} {'Portfolio':>12}")
print(DIV)
n = 0
for t in ma200_trades:
    if t["date"].year < 2017:
        continue
    n += 1
    dt_s = t["date"].strftime("%Y-%m-%d")
    pr   = f"${t['price']:.2f}"
    sh   = f"{t['shares']:,}"
    if t["type"] == "BUY":
        print(f"  {n:<3} {'BUY':<6} {dt_s:<13} {pr:>9} {sh:>8} {'':>12} {'':>8} {'':>12}")
    else:
        label = t["type"]
        pnl_s = f"{'+'if t['pnl']>=0 else ''}${t['pnl']:,.0f}"
        pct_s = f"{'+'if t['pnl_pct']>=0 else ''}{t['pnl_pct']:.1f}%"
        port_s = f"${t['cum']:,.0f}"
        print(f"  {n:<3} {label:<6} {dt_s:<13} {pr:>9} {sh:>8} {pnl_s:>12} {pct_s:>8} {port_s:>12}")
print(SEP)
buys  = sum(1 for t in ma200_trades if t["type"] == "BUY"  and t["date"].year >= 2017)
sells = sum(1 for t in ma200_trades if t["type"] == "SELL" and t["date"].year >= 2017)
print(f"  {buys} buys, {sells} completed sells   OPEN* = position held today")
print(SEP)
