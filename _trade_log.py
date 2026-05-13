import math, sys
sys.path.insert(0, "E:\\work\\Stockdata")
from tushar_strategy import _load, compute_signal, ACCOUNTS, TQQQ_ALLOCATION

CAPITAL   = sum(a["balance"] for a in ACCOUNTS)
START     = "2021-01-01"

print("Loading data...")
qqq  = _load("QQQ",  "2015-01-01")   # need 2015 warmup for 252d high
tqqq = _load("TQQQ", "2015-01-01")

sig = compute_signal(qqq)

# ── Extract trades since START ─────────────────────────────────────────────────
trades = []
open_trade = None

for dt, row in sig.iterrows():
    if dt.date().isoformat() < START:
        continue

    act      = row["action"]
    pcthi    = float(row["pcthi"])
    qqq_px   = float(row["close"])

    # Get TQQQ price
    if dt in tqqq.index:
        tqqq_px = float(tqqq.loc[dt, "close"])
    else:
        avail = tqqq.index[tqqq.index <= dt]
        tqqq_px = float(tqqq.loc[avail[-1], "close"]) if not avail.empty else None

    if act == "BUY":
        open_trade = {
            "buy_date":   dt,
            "buy_qqq":    qqq_px,
            "buy_tqqq":   tqqq_px,
            "buy_pcthi":  pcthi,
        }
    elif act == "SELL" and open_trade:
        dur = (dt - open_trade["buy_date"]).days
        tqqq_ret = (tqqq_px - open_trade["buy_tqqq"]) / open_trade["buy_tqqq"] * 100
        qqq_ret  = (qqq_px  - open_trade["buy_qqq"])  / open_trade["buy_qqq"]  * 100
        trades.append({**open_trade,
            "sell_date":  dt,
            "sell_qqq":   qqq_px,
            "sell_tqqq":  tqqq_px,
            "sell_pcthi": pcthi,
            "dur_days":   dur,
            "tqqq_ret":   round(tqqq_ret, 1),
            "qqq_ret":    round(qqq_ret, 1),
        })
        open_trade = None

# ── Check for currently open trade ────────────────────────────────────────────
last_row = sig.iloc[-1]
last_dt  = sig.index[-1]
if last_row["action"] != "SELL" and last_row["regime"] == "BUY_TQQQ" and open_trade:
    import yfinance as yf
    live_tqqq = float(yf.Ticker("TQQQ").fast_info.last_price)
    live_qqq  = float(yf.Ticker("QQQ").fast_info.last_price)
    dur = (last_dt - open_trade["buy_date"]).days
    tqqq_ret = (live_tqqq - open_trade["buy_tqqq"]) / open_trade["buy_tqqq"] * 100
    qqq_ret  = (live_qqq  - open_trade["buy_qqq"])  / open_trade["buy_qqq"]  * 100
    trades.append({**open_trade,
        "sell_date":  None,
        "sell_qqq":   live_qqq,
        "sell_tqqq":  live_tqqq,
        "sell_pcthi": None,
        "dur_days":   dur,
        "tqqq_ret":   round(tqqq_ret, 1),
        "qqq_ret":    round(qqq_ret, 1),
    })

# ── Print trade log ────────────────────────────────────────────────────────────
W = 110; SEP = "=" * W; DIV = "-" * W

print(); print(SEP)
print("  TUSHAR STRATEGY — Trade Log  (BUY / SELL since 2021)")
print(f"  Strategy: pctHigh252 >= 15% -> CASH | 3-day re-entry")
print(f"  TQQQ Allocation: {int(TQQQ_ALLOCATION*100)}% of each account | Total capital: ${CAPITAL:,.0f}")
print(SEP)
print(f"  {'#':<3} {'BUY Date':<12} {'TQQQ Buy':>9} {'QQQ Buy':>8}  {'SELL Date':<12} {'TQQQ Sell':>10} {'QQQ Sell':>9}  {'Days':>5}  {'TQQQ Ret':>9}  {'QQQ Ret':>8}  Status")
print(DIV)

cum_tqqq = 1.0    # compound multiplier for TQQQ allocation portion
n = 0
wins = losses = 0

for t in trades:
    n += 1
    b_dt  = t["buy_date"].strftime("%Y-%m-%d")
    b_tq  = f"${t['buy_tqqq']:.2f}"
    b_qq  = f"${t['buy_qqq']:.2f}"

    is_open = t["sell_date"] is None
    if is_open:
        s_dt  = "OPEN"
        s_tq  = f"${t['sell_tqqq']:.2f}*"
        s_qq  = f"${t['sell_qqq']:.2f}*"
        status = "OPEN (live)"
    else:
        s_dt  = t["sell_date"].strftime("%Y-%m-%d")
        s_tq  = f"${t['sell_tqqq']:.2f}"
        s_qq  = f"${t['sell_qqq']:.2f}"
        status = "WIN" if t["tqqq_ret"] >= 0 else "LOSS"
        if t["tqqq_ret"] >= 0: wins += 1
        else: losses += 1

    ret_s = f"{t['tqqq_ret']:+.1f}%"
    qq_s  = f"{t['qqq_ret']:+.1f}%"
    cum_tqqq *= (1 + t["tqqq_ret"] / 100)

    print(f"  {n:<3} {b_dt:<12} {b_tq:>9} {b_qq:>8}  {s_dt:<12} {s_tq:>10} {s_qq:>9}  {t['dur_days']:>5}d  {ret_s:>9}  {qq_s:>8}  {status}")

print(DIV)

# ── Summary ────────────────────────────────────────────────────────────────────
completed = [t for t in trades if t["sell_date"] is not None]
if completed:
    avg_win  = sum(t["tqqq_ret"] for t in completed if t["tqqq_ret"] >= 0) / max(wins, 1)
    avg_loss = sum(t["tqqq_ret"] for t in completed if t["tqqq_ret"] <  0) / max(losses, 1)
    avg_dur  = sum(t["dur_days"] for t in completed) / len(completed)

    tqqq_alloc = CAPITAL * TQQQ_ALLOCATION
    gain_alloc = tqqq_alloc * (cum_tqqq - 1)

    print(f"  Completed trades : {len(completed)}  ({wins} wins, {losses} losses)")
    print(f"  Avg win          : {avg_win:+.1f}%    Avg loss: {avg_loss:+.1f}%")
    print(f"  Avg hold duration: {avg_dur:.0f} days")
    print(f"  TQQQ compound ret: {(cum_tqqq-1)*100:+.1f}%  (on the TQQQ {int(TQQQ_ALLOCATION*100)}% allocation)")
    print(f"  Dollar gain/loss : ${gain_alloc:+,.0f}  (on ${tqqq_alloc:,.0f} deployed)")
print(SEP)

# ── Cash periods ───────────────────────────────────────────────────────────────
print()
print(SEP)
print("  TUSHAR STRATEGY — Cash Periods  (when in CASH since 2021)")
print(DIV)
print(f"  {'#':<3} {'SELL (exit)':<12}  {'Re-entry (BUY)':<15}  {'Duration':>9}  {'QQQ during cash':>15}  What happened")
print(DIV)

cash_trades = []
for i, t in enumerate(trades):
    if t["sell_date"] is None:
        continue
    # Cash period: from this SELL to next BUY
    next_t = trades[i+1] if i+1 < len(trades) else None
    if next_t:
        cash_dur = (next_t["buy_date"] - t["sell_date"]).days
        qqq_cash = (next_t["buy_qqq"] - t["sell_qqq"]) / t["sell_qqq"] * 100
        cash_trades.append((t["sell_date"], next_t["buy_date"], cash_dur, qqq_cash, t["sell_qqq"], next_t["buy_qqq"]))

for i, (sd, bd, dur, qr, qp_s, qp_e) in enumerate(cash_trades):
    sd_s = sd.strftime("%Y-%m-%d")
    bd_s = bd.strftime("%Y-%m-%d")
    qr_s = f"{qr:+.1f}%"
    note = "QQQ fell further" if qr < -2 else ("QQQ recovered" if qr > 2 else "QQQ flat")
    print(f"  {i+1:<3} {sd_s:<12}   {bd_s:<15}  {dur:>6}d     {qr_s:>8} ({note})")

print(SEP)
