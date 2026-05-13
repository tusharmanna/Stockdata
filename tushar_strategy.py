"""
tushar_strategy.py  --  TusharStrategy Daily Signal & Backtest

STRATEGY LOGIC
--------------
  - Watch QQQ's distance from its rolling 252-day (1-year) high.
  - When QQQ is within 15% of that high  -> hold TQQQ  (bull regime)
  - When QQQ falls more than 15% below   -> go to CASH (bear regime)
  - Re-entry after a cash period requires 3 consecutive days back below the 15% line.
  - Position: 100% of portfolio into TQQQ on entry; hold fixed shares until exit.
  - No daily rebalancing -- let winners run.

DAILY USAGE
-----------
  python tushar_strategy.py                    # today's signal + action
  python tushar_strategy.py --capital 50000    # signal with custom capital
  python tushar_strategy.py --backtest         # backtest all years
  python tushar_strategy.py --backtest --year 2025
  python tushar_strategy.py --backtest --all   # all years side-by-side
"""

import argparse
import math
import os
import smtplib
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import pandas as pd
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────
QQQ_TICKER       = "QQQ"
TQQQ_TICKER      = "TQQQ"
DEFAULT_CAPITAL  = 100_000.0
HIGH_PERIOD      = 252          # trading days in rolling high window
SIGNAL_THRESHOLD = 15.0         # % below 252d-high triggers CASH regime
REENTRY_DAYS     = 3            # consecutive days below threshold to re-enter TQQQ
DATA_START       = "2015-01-01" # warmup start for accurate 252d-high

# ── Account balances (update whenever balances change) ────────────────────────
ACCOUNTS = [
    {"name": "Interactive Brokers", "acct": "7581",      "balance": 94_715},
    {"name": "Fidelity",            "acct": "4838",      "balance": 320_313},
    {"name": "Fidelity",            "acct": "2305",      "balance": 76_873},
    {"name": "Fidelity",            "acct": "4262",      "balance": 25_773},
    {"name": "Fidelity",            "acct": "8549",      "balance": 8_525},
    {"name": "Fidelity",            "acct": "2029",      "balance": 525},
    {"name": "Wells Fargo",         "acct": "1539",      "balance": 37_438},
    {"name": "Charles Schwab HSA",  "acct": "042",       "balance": 23_000},
    {"name": "Optum HSA",           "acct": "5340",      "balance": 21_000},
    {"name": "Fidelity 401(k)",     "acct": "Color",     "balance": 348_926},
    {"name": "my529 (Tushar)",      "acct": "7208",      "balance": 3_880},
    {"name": "my529 (Shreyaan)",    "acct": "7209",      "balance": 2_339},
]

# ── Notification config ───────────────────────────────────────────────────────
# Set these as environment variables or fill in directly.
# Gmail App Password: myaccount.google.com → Security → App Passwords
NOTIFY_TO_EMAIL  = "tusharmanna@gmail.com"
GMAIL_USER       = os.environ.get("GMAIL_USER",        "tusharmanna@gmail.com")
GMAIL_APP_PASS   = os.environ.get("GMAIL_APP_PASSWORD", "pdvr ighp owqe fgmy")   # <-- set this env var

# Push notification via ntfy.sh (free, no account needed)
# Install the ntfy app on your phone and subscribe to this topic
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "tusharstrategy")

# Fraction of each account balance to deploy into TQQQ (rest stays in index funds)
TQQQ_ALLOCATION = 0.50

TARGET = {
    2023: {1:12.8, 2:-5.1,  3:7.3,   4:-0.9, 5:23.8, 6:12.1, 7:10.1, 8:-1.8, 9:-6.1, 10:-2.9, 11:9.7,  12:3.6},
    2024: {1:7.3,  2:4.5,   3:-0.6,  4:-8.6, 5:19.2, 6:1.7,  7:-3.3, 8:1.0,  9:-4.0, 10:-0.7, 11:-9.1, 12:5.2},
    2025: {1:2.8,  2:-3.5,  3:-21.2, 4:2.6,  5:17.7, 6:21.2, 7:5.4,  8:4.0,  9:11.5, 10:-0.7, 11:1.4,  12:-1.8},
    2026: {1:-4.9, 2:-4.9,  3:-1.6,  4:23.8},
}

MONTHS = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


# ── Notifications ─────────────────────────────────────────────────────────────

def _smtp_send(to_addr: str, subject: str, body: str) -> bool:
    if not GMAIL_APP_PASS:
        print("  [notify] GMAIL_APP_PASSWORD not set — skipping notification.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"]    = GMAIL_USER
        msg["To"]      = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"  [notify] Failed to send to {to_addr}: {e}")
        return False


def _ntfy_send(topic: str, title: str, body: str) -> bool:
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=10,
        )
        return True
    except Exception as e:
        print(f"  [notify] ntfy failed: {e}")
        return False


def send_notifications(action: str, body: str) -> None:
    """Send email + push notification on BUY or SELL signals. Skips HOLD."""
    if action not in ("BUY", "SELL"):
        return

    subject = f"TusharStrategy {action} TQQQ -- {datetime.now().strftime('%b %d %Y')}"

    # Email — full output
    ok = _smtp_send(NOTIFY_TO_EMAIL, subject, body)
    if ok:
        print(f"  [notify] Email sent to {NOTIFY_TO_EMAIL}")

    # Push notification via ntfy.sh — action + per-account shares
    if NTFY_TOPIC:
        import re
        lines       = [l.strip() for l in body.splitlines() if l.strip()]
        action_line = next((l for l in lines if "ACTION" in l), "")
        pct_line    = next((l for l in lines if "Below High" in l), "")
        tqqq_line   = next((l for l in lines if "TQQQ Close" in l), "")

        # Build per-account table
        m = re.search(r"\$([\d.]+)", tqqq_line)
        if m and action == "BUY":
            tp = float(m.group(1))
            alloc_pct = int(TQQQ_ALLOCATION * 100)
            acct_rows = [
                f"  {a['name']} ({a['acct']}): {math.floor(a['balance'] * TQQQ_ALLOCATION / tp):,} sh  (${a['balance'] * TQQQ_ALLOCATION:,.0f} of ${a['balance']:,})"
                for a in ACCOUNTS
            ]
            acct_rows.insert(0, f"Deploying {alloc_pct}% of each account into TQQQ @ ${tp:.2f}")
        else:
            acct_rows = [
                f"  {a['name']} ({a['acct']}): SELL ALL TQQQ"
                for a in ACCOUNTS
            ]

        push_body = "\n".join([action_line, tqqq_line, pct_line, ""] + acct_rows)
        ok = _ntfy_send(NTFY_TOPIC, subject, push_body)
        if ok:
            print(f"  [notify] Push notification sent (ntfy topic: {NTFY_TOPIC})")


# ── Live market helpers ───────────────────────────────────────────────────────

def _now_et() -> datetime:
    utc = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        offset = -4 if 3 <= utc.month <= 11 else -5
        return utc.astimezone(timezone(timedelta(hours=offset)))


def _is_market_hours() -> bool:
    et = _now_et()
    if et.weekday() >= 5:
        return False
    open_t  = et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_t <= et <= close_t


def _get_live_price(ticker: str) -> float | None:
    try:
        fi = yf.Ticker(ticker).fast_info
        for attr in ("last_price", "regular_market_price"):
            p = getattr(fi, attr, None)
            if p is not None:
                return float(p)
    except Exception:
        pass
    return None


def _today_live_signal(sig_df: pd.DataFrame, live_qqq: float) -> dict:
    last       = sig_df.iloc[-1]
    high252    = max(float(last["high252"]), live_qqq)
    pcthi      = (high252 - live_qqq) / high252 * 100
    prev_db    = int(last["days_below"])
    prev_in    = (last["regime"] == "BUY_TQQQ")

    if pcthi >= SIGNAL_THRESHOLD:
        days_below = 0
        in_tqqq    = False
    else:
        days_below = prev_db + 1
        in_tqqq    = prev_in or (days_below >= REENTRY_DAYS)

    if in_tqqq and not prev_in:
        action = "BUY"
    elif not in_tqqq and prev_in:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "pcthi": round(pcthi, 2), "high252": high252,
        "regime": "BUY_TQQQ" if in_tqqq else "CASH",
        "days_below": days_below, "action": action,
    }


# ── Data loading ──────────────────────────────────────────────────────────────

def _load(ticker: str, start: str = DATA_START) -> pd.DataFrame:
    raw = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    df  = raw.copy()
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


# ── Signal computation ────────────────────────────────────────────────────────

def compute_signal(qqq_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add columns to QQQ df:
      high252  : rolling 252-day high of close
      pcthi    : % QQQ is below that high
      regime   : BUY_TQQQ or CASH
      days_below: consecutive days pcthi has been < SIGNAL_THRESHOLD
      action   : BUY / SELL / HOLD  (detected regime change)
    """
    df            = qqq_df.copy()
    df["high252"] = df["close"].rolling(HIGH_PERIOD, min_periods=1).max()
    df["pcthi"]   = (df["high252"] - df["close"]) / df["high252"] * 100

    regime_list     = []
    days_below_list = []
    action_list     = []

    days_below  = 0
    in_tqqq     = True   # start invested
    prev_in_tqqq = False # triggers initial buy on first bar

    for pcthi in df["pcthi"]:
        if pcthi >= SIGNAL_THRESHOLD:
            days_below  = 0
            in_tqqq     = False
        else:
            days_below += 1
            if days_below >= REENTRY_DAYS:
                in_tqqq = True

        if in_tqqq and not prev_in_tqqq:
            act = "BUY"
        elif not in_tqqq and prev_in_tqqq:
            act = "SELL"
        else:
            act = "HOLD"

        regime_list.append("BUY_TQQQ" if in_tqqq else "CASH")
        days_below_list.append(days_below)
        action_list.append(act)
        prev_in_tqqq = in_tqqq

    df["regime"]     = regime_list
    df["days_below"] = days_below_list
    df["action"]     = action_list
    return df


# ── Daily signal output ───────────────────────────────────────────────────────

def print_daily_signal(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame,
                       capital: float) -> None:
    import io, sys
    _real_stdout = sys.stdout
    _buf = io.StringIO()

    class _Tee:
        def write(self, x):
            _real_stdout.write(x)
            _buf.write(x)
        def flush(self):
            _real_stdout.flush()

    sys.stdout = _Tee()        # capture output while still printing to terminal

    today_row = sig_df.iloc[-1]
    today     = sig_df.index[-1].date()

    qqq_close  = float(today_row["close"])
    high252    = float(today_row["high252"])
    pcthi      = float(today_row["pcthi"])
    regime     = today_row["regime"]
    days_bel   = int(today_row["days_below"])
    action     = today_row["action"]

    tqqq_close = float(tqqq_df.iloc[-1]["close"]) if not tqqq_df.empty else None

    # Use live prices if market is currently open (running between 9:30 AM – 4:00 PM ET)
    live_mode  = False
    fetch_time = ""
    if _is_market_hours():
        live_qqq  = _get_live_price(QQQ_TICKER)
        live_tqqq = _get_live_price(TQQQ_TICKER)
        if live_qqq:
            sig        = _today_live_signal(sig_df, live_qqq)
            qqq_close  = live_qqq
            high252    = sig["high252"]
            pcthi      = sig["pcthi"]
            regime     = sig["regime"]
            days_bel   = sig["days_below"]
            action     = sig["action"]
            if live_tqqq:
                tqqq_close = live_tqqq
            live_mode  = True
            fetch_time = _now_et().strftime("%I:%M %p ET")
            today      = _now_et().date()

    W   = 65
    SEP = "=" * W
    DIV = "-" * W

    live_label = "  (LIVE)" if live_mode else ""
    print(f"\n{SEP}")
    print(f"  TUSHAR STRATEGY  --  Daily Signal{live_label}")
    date_str = today.strftime('%A, %B %d, %Y')
    print(f"  {date_str}" + (f"  [{fetch_time}]" if live_mode else ""))
    print(SEP)
    price_label = "QQQ Price:" if live_mode else "QQQ Close:"
    print(f"  {price_label:<18}${qqq_close:>8.2f}" + ("  (live)" if live_mode else ""))
    print(f"  252-Day High:     ${high252:>8.2f}")
    pct_bar = "#" * int(pcthi) + "-" * max(0, 15 - int(pcthi))
    flag    = "  << THRESHOLD CROSSED" if pcthi >= SIGNAL_THRESHOLD else ""
    print(f"  % Below High:      {pcthi:>5.1f}%   [{pct_bar}] (limit 15%){flag}")
    print()

    if regime == "BUY_TQQQ":
        print(f"  REGIME:  BUY TQQQ  (QQQ within {SIGNAL_THRESHOLD:.0f}% of 1-year high)")
        print(f"  Confirmation days below 15%: {days_bel} / {REENTRY_DAYS} needed")
    else:
        print(f"  REGIME:  CASH  (QQQ is {pcthi:.1f}% below 1-year high)")
        print(f"  Consecutive days above threshold: {-days_bel + 1 if days_bel == 0 else 'many'}")

    print()
    print(DIV)

    exec_when = ("NOW -- place a market order before 4:00 PM ET close."
                 if live_mode else "at market open tomorrow morning.")

    if action == "BUY":
        print(f"  ACTION:  *** BUY TQQQ ***  (regime just changed to BUY_TQQQ)")
        print()
        if tqqq_close:
            price_lbl = "TQQQ Price:" if live_mode else "TQQQ Close:"
            print(f"  {price_lbl}  ${tqqq_close:.2f}/share" + ("  (live)" if live_mode else ""))
            print()
            alloc_pct = int(TQQQ_ALLOCATION * 100)
            print(f"  ({alloc_pct}% of each balance deployed into TQQQ, {100-alloc_pct}% stays in index funds)")
            print()
            print(f"  {'Account':<22} {'Acct#':<8} {'Balance':>10}  {f'TQQQ({alloc_pct}%)':>10}  {'Shares':>7}  {'Cost':>10}  {'Leftover':>10}")
            print(f"  {'-'*88}")
            total_cost = 0
            for acct in ACCOUNTS:
                bal      = acct["balance"]
                tqqq_bal = bal * TQQQ_ALLOCATION
                sh       = math.floor(tqqq_bal / tqqq_close) if tqqq_close > 0 else 0
                cost     = sh * tqqq_close
                leftover = tqqq_bal - cost
                total_cost += cost
                print(f"  {acct['name']:<22} {acct['acct']:<8} ${bal:>9,}  ${tqqq_bal:>9,.0f}  {sh:>7,}  ${cost:>9,.0f}  ${leftover:>7,.2f}")
            print(f"  {'-'*88}")
            total_bal  = sum(a["balance"] for a in ACCOUNTS)
            total_tqqq = total_bal * TQQQ_ALLOCATION
            total_sh   = sum(math.floor(a["balance"] * TQQQ_ALLOCATION / tqqq_close) for a in ACCOUNTS)
            print(f"  {'TOTAL':<22} {'':<8} ${total_bal:>9,}  ${total_tqqq:>9,.0f}  {total_sh:>7,}  ${total_cost:>9,.0f}")
        print()
        print(f"  Execute {exec_when}")
    elif action == "SELL":
        print(f"  ACTION:  *** SELL ALL TQQQ ***  (regime changed to CASH)")
        print()
        if tqqq_close:
            print(f"  {'Account':<22} {'Acct#':<8}  {'Action'}")
            print(f"  {'-'*55}")
            for acct in ACCOUNTS:
                print(f"  {acct['name']:<22} {acct['acct']:<8}  Sell ALL TQQQ shares -> move to cash")
            print()
        print(f"  Sell your entire TQQQ position {exec_when}")
        print(f"  Move all proceeds to cash / money market.")
        print(f"  Wait for re-entry signal (3 consecutive days below 15%).")
    else:
        if regime == "BUY_TQQQ":
            print(f"  ACTION:  HOLD  --  Stay in TQQQ, no trade needed.")
        else:
            print(f"  ACTION:  HOLD CASH  --  Remain in cash, no trade needed.")
            remaining = REENTRY_DAYS - days_bel
            if remaining > 0:
                print(f"  Re-entry: need {remaining} more day(s) below 15% for confirmation.")

    print(DIV)

    if tqqq_close:
        price_lbl = "TQQQ Price:" if live_mode else "TQQQ Close:"
        print(f"  {price_lbl}  ${tqqq_close:.2f}" + ("  (live)" if live_mode else ""))

    # Recent history: 6 historical rows + live today row (or 7 historical rows)
    print(f"\n  Recent pctHi history (last 7 trading days):")
    print(f"  {'Date':<12} {'QQQ':>8} {'pctHi':>7} {'Regime':<12} {'Action'}")
    print(f"  {'-'*55}")
    tail_n = 6 if live_mode else 7
    for ts, row in sig_df.tail(tail_n).iterrows():
        marker = "" if live_mode else (" <-- TODAY" if ts == sig_df.index[-1] else "")
        print(f"  {str(ts.date()):<12} {float(row['close']):>7.2f} "
              f"{float(row['pcthi']):>6.1f}%  {row['regime']:<12} {row['action']}{marker}")
    if live_mode:
        print(f"  {str(today):<12} {qqq_close:>7.2f} "
              f"{pcthi:>6.1f}%  {regime:<12} {action}  <-- NOW ({fetch_time})")
    print(SEP)
    print()

    sys.stdout = sys.__stdout__    # restore normal stdout
    captured = _buf.getvalue()
    send_notifications(action, captured)


# ── Backtest (buy-and-hold on signal change) ──────────────────────────────────

def _price_on(df: pd.DataFrame, date) -> float | None:
    if date in df.index:
        return float(df.loc[date, "close"])
    avail = df.index[df.index <= date]
    return float(df.loc[avail[-1], "close"]) if not avail.empty else None


def run_backtest(sig_df: pd.DataFrame, tqqq_df: pd.DataFrame,
                 capital: float) -> list[dict]:
    tqqq_sh      = 0
    cash         = capital
    daily        = []
    prev_in_tqqq = False

    for date, row in sig_df.iterrows():
        tp = _price_on(tqqq_df, date)
        if tp is None:
            continue
        in_tqqq = (row["regime"] == "BUY_TQQQ")

        if in_tqqq and not prev_in_tqqq:
            ns      = math.floor(cash / tp) if tp > 0 else 0
            cash   -= ns * tp
            tqqq_sh = ns
        elif not in_tqqq and prev_in_tqqq:
            cash   += tqqq_sh * tp
            tqqq_sh = 0

        prev_in_tqqq = in_tqqq
        port = round(tqqq_sh * tp + cash, 2)
        daily.append({"date": date, "portfolio": port,
                      "regime": row["regime"], "action": row["action"],
                      "pcthi": float(row["pcthi"]), "close": float(row["close"])})
    return daily


def _monthly_rets(daily: list[dict]) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d in daily:
        bm[(d["date"].year, d["date"].month)].append(d["portfolio"])
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i - 1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _qqq_monthly_rets(qqq_df: pd.DataFrame) -> dict[tuple, float]:
    bm = defaultdict(list)
    for d, row in qqq_df.iterrows():
        bm[(d.year, d.month)].append(float(row["close"]))
    sm  = sorted(bm)
    res = {}
    for i, ym in enumerate(sm):
        e = bm[ym][-1]
        s = bm[sm[i - 1]][-1] if i > 0 else bm[ym][0]
        res[ym] = round((e - s) / s * 100, 1) if s else 0.0
    return res


def _fmt(v: float | None, w: int = 8) -> str:
    if v is None:
        return "  N/A  ".rjust(w)
    s = "+" if v >= 0 else ""
    return f"{s}{v:.1f}%".rjust(w)


def print_backtest(daily: list[dict], qqq_df: pd.DataFrame,
                   years: list[int], capital: float) -> None:
    ts_r  = _monthly_rets(daily)
    qqq_r = _qqq_monthly_rets(qqq_df)
    ph_by = defaultdict(list)
    for d in daily:
        ph_by[(d["date"].year, d["date"].month)].append(d["pcthi"])

    W   = 72
    SEP = "=" * W
    DIV = "-" * W

    # Running portfolios for grand total
    cum_q  = capital
    cum_ts = capital

    print(f"\n{SEP}")
    print(f"  TUSHAR STRATEGY -- Monthly Backtest  |  Capital: ${capital:,.0f}")
    print(f"  Signal: QQQ >15% below 252d-high => CASH | <15% => hold TQQQ")
    print(SEP)

    yr_totals = []
    all_years = sorted(set(ym[0] for ym in ts_r if ym[0] in years))

    for year in all_years:
        months_in_yr = sorted(ym for ym in ts_r if ym[0] == year)
        if not months_in_yr:
            continue

        yr_q_start  = cum_q
        yr_ts_start = cum_ts

        print(f"\n  -- {year} {'-'*60}")
        print(f"  {'Month':<8}  {'QQQ':>8}  {'TusharStrategy':>16}  {'C2 Target':>10}  Regime")
        print(DIV)

        for ym in months_in_yr:
            m   = ym[1]
            q   = qqq_r.get(ym)
            ts  = ts_r.get(ym)
            c2  = TARGET.get(year, {}).get(m)
            phs = ph_by.get(ym, [0])
            avg_ph = round(sum(phs) / len(phs), 1)
            regime = "CASH" if avg_ph >= SIGNAL_THRESHOLD else "TQQQ"

            if q:  cum_q  *= 1 + q  / 100
            if ts: cum_ts *= 1 + ts / 100

            c2_f = _fmt(c2) if c2 is not None else "    N/A "
            print(f"  {MONTHS[m]:<8}  {_fmt(q):>8}  {_fmt(ts):>16}  {c2_f:>10}  "
                  f"{regime} ({avg_ph:.1f}%)")

        fy_q  = round((cum_q  / yr_q_start  - 1) * 100, 1)
        fy_ts = round((cum_ts / yr_ts_start - 1) * 100, 1)
        fy_c2_prod = 1.0
        for r in TARGET.get(year, {}).values():
            fy_c2_prod *= 1 + r / 100
        fy_c2 = round((fy_c2_prod - 1) * 100, 1) if TARGET.get(year) else None
        yr_totals.append((year, fy_q, fy_ts, fy_c2))

        print(DIV)
        c2_fy = _fmt(fy_c2) if fy_c2 is not None else "    N/A "
        print(f"  {'FY '+str(year):<8}  {_fmt(fy_q):>8}  {_fmt(fy_ts):>16}  {c2_fy:>10}")

    # Summary
    if len(all_years) > 1:
        print(f"\n{SEP}")
        print(f"  ANNUAL SUMMARY")
        print(DIV)
        print(f"  {'Year':<8}  {'QQQ':>8}  {'TusharStrategy':>16}  {'C2 Target':>10}")
        print(DIV)
        for y, q, ts, c2 in yr_totals:
            c2f = _fmt(c2) if c2 is not None else "    N/A "
            print(f"  {str(y):<8}  {_fmt(q):>8}  {_fmt(ts):>16}  {c2f:>10}")
        print(DIV)
        ov_q  = round((cum_q  / capital - 1) * 100, 1)
        ov_ts = round((cum_ts / capital - 1) * 100, 1)
        n_years = len(all_years) + (all_years[-1] == date.today().year) * (date.today().month - 1) / 12
        years_elapsed = (date.today().year - all_years[0]) + (date.today().month - 1) / 12 + (date.today().day - 1) / 365
        cagr_q  = round(((cum_q  / capital) ** (1 / years_elapsed) - 1) * 100, 1)
        cagr_ts = round(((cum_ts / capital) ** (1 / years_elapsed) - 1) * 100, 1)
        print(f"  {'Total %':<8}  {_fmt(ov_q):>8}  {_fmt(ov_ts):>16}")
        print(f"  {'CAGR':<8}  {_fmt(cagr_q):>8}  {_fmt(cagr_ts):>16}")
        print(SEP)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="TusharStrategy: TQQQ/CASH rotation signal + backtest")
    ap.add_argument("--capital",  type=float, default=DEFAULT_CAPITAL,
                    help="Portfolio size for position sizing (default: 100000)")
    ap.add_argument("--backtest", action="store_true",
                    help="Run historical backtest instead of daily signal")
    ap.add_argument("--year",     type=int,   default=None,
                    help="Backtest a specific year (default: current year)")
    ap.add_argument("--all",      action="store_true",
                    help="Backtest all available years")
    args = ap.parse_args()

    print("\nLoading QQQ and TQQQ data...")
    qqq_df  = _load(QQQ_TICKER)
    tqqq_df = _load(TQQQ_TICKER)

    sig_df = compute_signal(qqq_df)

    if args.backtest or args.all:
        print("Running TusharStrategy backtest...")
        daily = run_backtest(sig_df, tqqq_df, args.capital)
        print()

        if args.all:
            years = sorted(set(d["date"].year for d in daily if d["date"].year >= 2016))
        elif args.year:
            years = [args.year]
        else:
            import datetime
            years = [datetime.date.today().year]

        print_backtest(daily, qqq_df, years, args.capital)
    else:
        print_daily_signal(sig_df, tqqq_df, args.capital)


if __name__ == "__main__":
    main()
