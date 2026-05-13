"""
HedgedTushar Strategy vs TusharStrategy vs QQQ — backtest since 2017

HedgedTushar rules:
  BASE  : Same as TusharStrategy — QQQ pctHigh vs 252d rolling high
          pctHigh >= 15%  → full CASH  (3-day re-entry filter)
          pctHigh <  15%  → bull regime

  HEDGE : While in bull regime, watch QQQ vs its 50-day MA:
          QQQ above MA50  → 100% TQQQ
          QQQ below MA50  → 50% TQQQ  +  50% SQQQ (3x inverse)
          When QQQ crosses back above MA50 → close SQQQ, redeploy to TQQQ

  EXIT  : If bear regime triggers while hedged → sell both TQQQ and SQQQ → CASH
"""
import math
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

from tushar_strategy import _load, compute_signal

CAPITAL = 100_000.0
MONTHS  = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading QQQ and TQQQ data...")
qqq  = _load("QQQ",  "2015-01-01")
tqqq = _load("TQQQ", "2015-01-01")

# Synthesize SQQQ from -3x QQQ daily returns (avoids yfinance reverse-split
# auto_adjust issues that produce absurd historical prices for SQQQ)
print("Synthesizing SQQQ from -3x QQQ daily returns...")
_anchor = float(yf.Ticker("SQQQ").fast_info.last_price)
_ret    = qqq["close"].pct_change().fillna(0.0)
_dates  = qqq.index.tolist()
_px     = {_dates[-1]: _anchor}
for i in range(len(_dates) - 2, -1, -1):
    r           = float(_ret.iloc[i + 1])
    d           = 1 + (-3) * r
    _px[_dates[i]] = _px[_dates[i + 1]] / d if d != 0 else _px[_dates[i + 1]]
sqqq = pd.DataFrame({"close": _px}).sort_index()
print(f"  SQQQ anchor: ${_anchor:.2f}  |  synthetic 2015-01-02: ${_px[_dates[0]]:.2f}")

# ── Signals ────────────────────────────────────────────────────────────────────
qqq["ma50"]     = qqq["close"].rolling(50, min_periods=1).mean()
qqq["above50"]  = qqq["close"] > qqq["ma50"]
sig = compute_signal(qqq)   # adds regime, pcthi, action columns


# ── Price helpers ──────────────────────────────────────────────────────────────
def price_on(df, dt):
    if dt in df.index:
        return float(df.loc[dt, "close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


# ── TusharStrategy simulation ──────────────────────────────────────────────────
def run_tushar(capital=CAPITAL):
    cash, tqqq_sh, prev_in = capital, 0, False
    buy_price = buy_date = None
    daily, trades = [], []

    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        if tp is None:
            continue
        in_tqqq = (row["regime"] == "BUY_TQQQ")

        if in_tqqq and not prev_in:
            tqqq_sh   = math.floor(cash / tp)
            cash     -= tqqq_sh * tp
            buy_price, buy_date = tp, dt
            trades.append({"type": "BUY", "date": dt, "tqqq_px": tp, "tqqq_sh": tqqq_sh})
        elif not in_tqqq and prev_in:
            proceeds  = tqqq_sh * tp
            pnl       = proceeds - tqqq_sh * buy_price
            cash     += proceeds
            trades.append({"type": "SELL", "date": dt, "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                           "pnl": round(pnl, 0), "cum": round(cash, 0)})
            tqqq_sh = 0

        prev_in = in_tqqq
        daily.append({"date": dt, "port": round(tqqq_sh * tp + cash, 2)})

    return daily, trades


# ── HedgedTushar simulation ────────────────────────────────────────────────────
def run_hedged(capital=CAPITAL):
    cash     = capital
    tqqq_sh  = 0
    sqqq_sh  = 0
    prev_bull   = False   # was in bull regime last bar
    prev_hedged = False   # was hedge (SQQQ) active last bar
    daily, trades = [], []

    for dt, row in sig.iterrows():
        tp = price_on(tqqq, dt)
        sp = price_on(sqqq, dt)
        if tp is None or sp is None:
            continue

        bull    = (row["regime"] == "BUY_TQQQ")
        hedged  = bull and not bool(qqq.loc[dt, "above50"])
        port    = tqqq_sh * tp + sqqq_sh * sp + cash

        # ── Regime: CASH → BULL ───────────────────────────────────────────────
        if bull and not prev_bull:
            if hedged:
                # enter bull below MA50 → split 50/50 TQQQ + SQQQ
                half      = port / 2
                tqqq_sh   = math.floor(half / tp)
                sqqq_sh   = math.floor(half / sp)
                cash      = port - tqqq_sh * tp - sqqq_sh * sp
                trades.append({"type": "BUY 50/50", "date": dt,
                               "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                               "sqqq_px": sp, "sqqq_sh": sqqq_sh})
            else:
                # enter bull above MA50 → 100% TQQQ
                tqqq_sh   = math.floor(port / tp)
                cash      = port - tqqq_sh * tp
                trades.append({"type": "BUY 100%", "date": dt,
                               "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                               "sqqq_px": None, "sqqq_sh": 0})

        # ── Regime: BULL → CASH ───────────────────────────────────────────────
        elif not bull and prev_bull:
            cash    = tqqq_sh * tp + sqqq_sh * sp + cash
            trades.append({"type": "SELL ALL", "date": dt,
                           "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                           "sqqq_px": sp, "sqqq_sh": sqqq_sh,
                           "cum": round(cash, 0)})
            tqqq_sh = sqqq_sh = 0

        # ── Hedge ON: TQQQ 100% → TQQQ 50% + SQQQ 50% ───────────────────────
        elif bull and hedged and not prev_hedged:
            # sell half TQQQ, buy SQQQ
            sell_sh    = tqqq_sh // 2
            proceeds   = sell_sh * tp
            tqqq_sh   -= sell_sh
            new_sqqq   = math.floor(proceeds / sp)
            sqqq_sh    = new_sqqq
            cash      += proceeds - new_sqqq * sp
            trades.append({"type": "HEDGE ON", "date": dt,
                           "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                           "sqqq_px": sp, "sqqq_sh": sqqq_sh,
                           "note": "sold 50% TQQQ, bought SQQQ"})

        # ── Hedge OFF: TQQQ 50% + SQQQ 50% → TQQQ 100% ──────────────────────
        elif bull and not hedged and prev_hedged:
            # sell all SQQQ, buy more TQQQ
            sqqq_proc  = sqqq_sh * sp + cash
            sqqq_sh    = 0
            new_tqqq   = math.floor(sqqq_proc / tp)
            tqqq_sh   += new_tqqq
            cash       = sqqq_proc - new_tqqq * tp
            trades.append({"type": "HEDGE OFF", "date": dt,
                           "tqqq_px": tp, "tqqq_sh": tqqq_sh,
                           "sqqq_px": sp, "sqqq_sh": 0,
                           "note": "sold SQQQ, bought back TQQQ"})

        prev_bull   = bull
        prev_hedged = hedged
        daily.append({"date": dt, "port": round(tqqq_sh * tp + sqqq_sh * sp + cash, 2)})

    return daily, trades


# ── Run both ───────────────────────────────────────────────────────────────────
tushar_daily, tushar_trades = run_tushar()
hedged_daily, hedged_trades = run_hedged()


# ── Monthly returns ────────────────────────────────────────────────────────────
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


def qqq_monthly(df):
    bm = defaultdict(list)
    for d, row in df.iterrows():
        bm[(d.year, d.month)].append(float(row["close"]))
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


tr = monthly_rets(tushar_daily)
hr = monthly_rets(hedged_daily)
qr = qqq_monthly(qqq)

# ── Print monthly comparison ───────────────────────────────────────────────────
W = 85; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  HedgedTushar vs TusharStrategy vs QQQ  (2017-present)")
print("  Tushar  : pctHigh < 15% => 100% TQQQ  |  >= 15% => CASH")
print("  Hedged  : Same + if QQQ < MA50 => 50% TQQQ + 50% SQQQ")
print(SEP)

cum       = {"q": CAPITAL, "t": CAPITAL, "h": CAPITAL}
yr_totals = []
all_years = sorted(set(ym[0] for ym in tr if ym[0] >= 2017))

for year in all_years:
    months = sorted(ym for ym in tr if ym[0] == year)
    if not months:
        continue
    yr_s = dict(cum)
    print(f"\n  -- {year} {'-'*71}")
    print(f"  {'Month':<6} {'QQQ':>8} {'Tushar':>10} {'Hedged':>10}  Regime-T    Hedge")
    print(DIV)

    for ym in months:
        m  = ym[1]
        q  = qr.get(ym)
        t  = tr.get(ym)
        h  = hr.get(ym)
        if q:  cum["q"] *= 1 + q / 100
        if t:  cum["t"] *= 1 + t / 100
        if h:  cum["h"] *= 1 + h / 100

        # regime labels
        ph_vals  = [float(sig.loc[d, "pcthi"])
                    for d in sig.index if d.year == year and d.month == m]
        avg_ph   = sum(ph_vals) / len(ph_vals) if ph_vals else 0
        rt       = "CASH" if avg_ph >= 15.0 else "TQQQ"

        a50_vals = [bool(qqq.loc[d, "above50"])
                    for d in qqq.index if d.year == year and d.month == m]
        hedge_lbl = "50/50" if (rt == "TQQQ" and sum(a50_vals) / len(a50_vals) < 0.5) else ("OFF" if rt == "TQQQ" else "CASH")

        print(f"  {MONTHS[m]:<6} {fmt(q):>8} {fmt(t):>10} {fmt(h):>10}  {rt:<10}  {hedge_lbl}")

    fy_q = round((cum["q"] / yr_s["q"] - 1) * 100, 1)
    fy_t = round((cum["t"] / yr_s["t"] - 1) * 100, 1)
    fy_h = round((cum["h"] / yr_s["h"] - 1) * 100, 1)
    yr_totals.append((year, fy_q, fy_t, fy_h))
    print(DIV)
    print(f"  {'FY '+str(year):<6} {fmt(fy_q):>8} {fmt(fy_t):>10} {fmt(fy_h):>10}")

# ── Annual summary ─────────────────────────────────────────────────────────────
print(); print(SEP)
print("  ANNUAL SUMMARY")
print(DIV)
print(f"  {'Year':<6} {'QQQ':>8} {'Tushar':>10} {'Hedged':>10}")
print(DIV)
for y, q, t, h in yr_totals:
    winner = " <-- Hedged wins" if h > t else ""
    print(f"  {str(y):<6} {fmt(q):>8} {fmt(t):>10} {fmt(h):>10}{winner}")
print(DIV)
ov_q = round((cum["q"] / CAPITAL - 1) * 100, 1)
ov_t = round((cum["t"] / CAPITAL - 1) * 100, 1)
ov_h = round((cum["h"] / CAPITAL - 1) * 100, 1)
today = date.today()
yrs   = (today.year - 2017) + (today.month - 1) / 12 + (today.day - 1) / 365
cq    = round(((cum["q"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
ct    = round(((cum["t"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
ch    = round(((cum["h"] / CAPITAL) ** (1/yrs) - 1) * 100, 1)
print(f"  {'Total%':<6} {fmt(ov_q):>8} {fmt(ov_t):>10} {fmt(ov_h):>10}")
print(f"  {'CAGR':<6} {fmt(cq):>8} {fmt(ct):>10} {fmt(ch):>10}")
print(SEP)

# ── Hedged trade log ───────────────────────────────────────────────────────────
print()
print(SEP)
print("  HEDGED TUSHAR — Trade Log (2017-present)")
print(SEP)
print(f"  {'#':<3} {'Type':<10} {'Date':<13} {'TQQQ Px':>9} {'TQQQ Sh':>9} {'SQQQ Px':>9} {'SQQQ Sh':>9}  Note")
print(DIV)
n = 0
for t in hedged_trades:
    if t["date"].year < 2017:
        continue
    n += 1
    dt_s   = t["date"].strftime("%Y-%m-%d")
    tp_s   = f"${t['tqqq_px']:>7.2f}"
    tsh_s  = f"{t['tqqq_sh']:>8,}"
    sp_s   = f"${t['sqqq_px']:>7.2f}" if t.get("sqqq_px") else "    N/A"
    ssh_s  = f"{t['sqqq_sh']:>8,}"
    note   = t.get("note", "")
    cum_s  = f"  => ${t['cum']:,.0f}" if "cum" in t else ""
    print(f"  {n:<3} {t['type']:<10} {dt_s:<13} {tp_s:>9} {tsh_s:>9} {sp_s:>9} {ssh_s:>9}  {note}{cum_s}")
print(SEP)
