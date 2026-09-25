"""Research suite for v2 improvement ideas.

This does not alter production signals.  Option protection is a transparent
model (monthly 7.5%-12.5% QQQ put spread, 1.0% annual premium); it is not a
historical option-chain reconstruction.  The diversification sleeve uses ETF
proxies for equity-index, Treasury, gold, commodity and dollar futures.
"""
import numpy as np
import pandas as pd
import yfinance as yf
from tusharStrategyDev import _load, compute_signal_v1, QQQ_TICKER, TQQQ_TICKER

TD, TARGET, CAP, WIN = 252, .45, 1.0, 20
SLIP, EXPENSE = .0005, .0095
IS_END = pd.Timestamp('2018-12-31')

def load_close(ticker):
    return _load(ticker)['close']

def vol_target(regime, ret, downside=False):
    if downside:
        # Downside semideviation: RMS of negative returns, annualized.
        x = ret.clip(upper=0.0)
        rv = np.sqrt((x * x).rolling(WIN).mean()) * np.sqrt(TD)
    else:
        rv = ret.rolling(WIN).std() * np.sqrt(TD)
    return (regime * (TARGET / rv.bfill()).clip(0, CAP)).clip(0, CAP)

def simulate(target, asset_ret, dates, premium=0.0):
    e = target.shift(1).fillna(0.0)
    years = (dates - dates.iloc[0]).dt.days.to_numpy() / 365.25
    cash = np.where(years > 12, .05, .015)
    turnover = e.diff().abs().fillna(e.abs())
    r = e * asset_ret + (1-e) * cash / TD - e * EXPENSE / TD - turnover * SLIP
    if premium:
        r = r - premium / TD
    return r

def metrics(r):
    eq=(1+r).cumprod(); n=len(r)/TD
    return (eq.iloc[-1]**(1/n)-1, r.mean()/r.std()*np.sqrt(TD), (eq/eq.cummax()-1).min(), eq.iloc[-1]*100000)

def print_table(title, rows, masks):
    print('\n'+title); print('='*90)
    print(f"{'Strategy':<31}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>10}{'Final $':>15}")
    for name,r in rows:
        vals=[]
        for mask in masks:
            c,s,d,f=metrics(r[mask]); vals.append((c,s,d,f))
        c,s,d,f=vals[-1]
        print(f"{name:<31}{c:>8.1%}{s:>9.2f}{d:>9.1%}{f:>15,.0f}")

def trend_sleeve(proxy_returns):
    parts=[]
    for name,r in proxy_returns.items():
        ma=r.add(1).cumprod().rolling(100).mean()
        price=r.add(1).cumprod()
        direction=np.where(price>=ma,1.0,-1.0)
        rv=r.rolling(60).std()*np.sqrt(TD)
        pos=pd.Series(direction,index=r.index)*(0.10/rv.bfill()).clip(0,1)
        parts.append(pos.shift(1).fillna(0)*r)
    return pd.concat(parts,axis=1).mean(axis=1)

def modeled_put_spread(qqq_ret, premium=.01):
    # Monthly hedge: buy 7.5% put, sell 12.5% put; payoff only at month-end.
    q=(1+qqq_ret).groupby(qqq_ret.index.to_period('M')).cumprod()-1
    payoff=((-.075-q).clip(lower=0) - (-.125-q).clip(lower=0)).clip(0,.05)
    end=qqq_ret.index.to_series().groupby(qqq_ret.index.to_period('M')).transform('max')==qqq_ret.index
    return payoff.where(end,0.0), premium

def main():
    qqq,tqqq=_load(QQQ_TICKER),_load(TQQQ_TICKER)
    proxies={t:load_close(t).pct_change() for t in ['IEF','GLD','DBC','UUP']}
    idx=qqq.index.intersection(tqqq.index)
    for x in proxies.values(): idx=idx.intersection(x.index)
    qqq,tqqq=qqq.loc[idx],tqqq.loc[idx]
    proxies={k:v.loc[idx].fillna(0) for k,v in proxies.items()}
    dates=pd.Series(idx,index=idx); qr=qqq.close.pct_change().fillna(0); tr=tqqq.close.pct_change().fillna(0)
    regime=(compute_signal_v1(qqq).regime=='BUY_TQQQ').astype(float)
    base=vol_target(regime,tr); down=vol_target(regime,tr,True)
    ma100=qqq.close.rolling(100).mean().bfill(); fast=(base*np.where(qqq.close>=ma100,1,.75)).clip(0,1)
    rbase=simulate(base,tr,dates); rdown=simulate(down,tr,dates); rfast=simulate(fast,tr,dates)
    sleeve=trend_sleeve(proxies)
    rdiv=.85*rbase+.15*sleeve
    payoff,prem=modeled_put_spread(qr)
    rput=rbase+payoff-prem/TD
    rows=[('v2 baseline',rbase),('downside-vol targeting',rdown),('100d trend confirmation',rfast),('15% diversified trend sleeve',rdiv),('modeled QQQ put spread',rput)]
    masks=[idx<=IS_END,idx>IS_END]
    print(f'Range: {idx[0].date()} to {idx[-1].date()} | v2 costs: {SLIP*10000:.0f}bp turnover + {EXPENSE:.2%} annual TQQQ drag')
    print_table('FULL PERIOD',rows,[pd.Series(True,index=idx)])
    print_table('OUT-OF-SAMPLE 2019+',rows,masks)
    print('\nNOTE: put-spread result is modeled, not historical option-chain data; proxy sleeve is not actual futures execution.')

if __name__=='__main__': main()
