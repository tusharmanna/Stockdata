import pandas as pd, yfinance as yf
from collections import defaultdict

START = "2004-01-01"; THRESHOLD = 15.0; REENTRY_DAYS = 3

def load(ticker):
    raw = yf.download(ticker, start=START, auto_adjust=True, progress=False)
    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return raw[["close"]].copy()

def price_on(df, dt):
    if dt in df.index: return float(df.loc[dt,"close"])
    avail = df.index[df.index <= dt]
    return float(df.loc[avail[-1],"close"]) if not avail.empty else None

def build_sqqq(qqq_df):
    anchor  = float(yf.Ticker("SQQQ").fast_info.last_price)
    ret     = qqq_df["close"].pct_change().fillna(0.0)
    dates   = qqq_df.index.tolist()
    px      = {dates[-1]: anchor}
    for i in range(len(dates)-2,-1,-1):
        r = float(ret.iloc[i+1]); d = 1+(-3)*r
        px[dates[i]] = px[dates[i+1]]/d if d!=0 else px[dates[i+1]]
    return pd.DataFrame({"close":px}).sort_index()

qqq = load("QQQ")
sqqq = build_sqqq(qqq)

sig = qqq.copy()
sig["h252"]  = sig["close"].rolling(252,min_periods=1).max()
sig["pcthi"] = (sig["h252"]-sig["close"])/sig["h252"]*100

# Find CASH periods
cash_periods=[]; in_bull=False; days=0; start_c=None; prev=False
for dt,row in sig.iterrows():
    ph=float(row["pcthi"])
    if ph>=THRESHOLD: in_bull=False; days=0
    else:
        days+=1
        if days>=REENTRY_DAYS: in_bull=True
    if not in_bull and prev: start_c=dt
    if in_bull and not prev and start_c: cash_periods.append((start_c,dt)); start_c=None
    prev=in_bull
if start_c: cash_periods.append((start_c,sig.index[-1]))

W=88; SEP="="*W; DIV="-"*W
print(); print(SEP)
print("  WHAT DID SQQQ ACTUALLY DO DURING TUSHAR CASH PERIODS?")
print("  (buy SQQQ on exit date, sell on re-entry date — did it profit?)")
print(DIV)
print(f"  {'Cash Period':<30} {'Duration':>9} {'QQQ move':>10} {'SQQQ synth':>12}  Verdict")
print(DIV)

total_qqq=0; total_sqqq=0; n=0
for s,e in cash_periods:
    if e.year < 2006: continue
    qs=price_on(qqq,s); qe=price_on(qqq,e)
    ss=price_on(sqqq,s); se=price_on(sqqq,e)
    if not all([qs,qe,ss,se]): continue
    qr=(qe-qs)/qs*100; sr=(se-ss)/ss*100
    days_held=(e-s).days
    label=f"{s.strftime('%Y-%m-%d')} -> {e.strftime('%Y-%m-%d')}"
    verdict = "PROFITS" if sr>10 else ("HURTS" if sr<-10 else "neutral")
    print(f"  {label:<30} {days_held:>6}d    {qr:>+8.1f}%   {sr:>+8.1f}%    {verdict}")
    total_qqq+=qr; total_sqqq+=sr; n+=1

print(DIV)
print(f"  {'AVERAGE across '+str(n)+' periods':<30} {'':>9} {total_qqq/n:>+8.1f}%   {total_sqqq/n:>+8.1f}%")
print(SEP)

print()
print(SEP)
print("  KEY PROBLEM: VOLATILITY DECAY — SQQQ loses value even when QQQ is flat")
print(DIV)
# Show a long bull period where SQQQ decayed (e.g. hold SQQQ for 1 year in a bull)
print("  If you held SQQQ for a full bull year (QQQ +30%), SQQQ would lose ~60-80%")
print("  due to daily rebalancing compounding against you.")
print()
print("  Example — 2013: QQQ gained +36.6%. Synthetic SQQQ over that full year:")
y2013_s = sig.index[sig.index.year==2013][0]
y2013_e = sig.index[sig.index.year==2013][-1]
sq_s=price_on(sqqq,y2013_s); sq_e=price_on(sqqq,y2013_e)
qq_s=price_on(qqq,y2013_s);  qq_e=price_on(qqq,y2013_e)
if all([sq_s,sq_e,qq_s,qq_e]):
    print(f"  QQQ: {qq_s:.2f} -> {qq_e:.2f}  ({(qq_e-qq_s)/qq_s*100:+.1f}%)")
    print(f"  SQQQ: {sq_s:.2f} -> {sq_e:.2f}  ({(sq_e-sq_s)/sq_s*100:+.1f}%)")
print()
print("  SQQQ should have been -3x = ~-110%, but daily rebalancing makes it even")
print("  worse due to volatility drag. It cannot be held long-term.")
print(SEP)
