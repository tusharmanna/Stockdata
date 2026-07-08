"""Run both v2 signals daily and update accounts_summary.md with results.

Usage:
    python run_daily_signals.py

This script:
1. Runs tushar_v2_signal.py (TQQQ signal)
2. Runs tushar_v2_qld_signal.py (QLD signal)
3. Runs tushar_v2_qqq_signal.py (QQQ comparison)
4. Emails results to EMAIL_ADDRESS via Gmail SMTP
5. Texts a short summary via AT&T email-to-SMS gateway
"""

import json
import os
import re
import smtplib
import ssl
import subprocess
import traceback
import webbrowser
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import yfinance as yf

from sync_account_data import sync_account_data


# ── Signal runners ─────────────────────────────────────────────────────────────

def run_signal(script_name):
    result = subprocess.run(
        ["python3", script_name],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


# ── Data helpers ───────────────────────────────────────────────────────────────

def extract_signal_data(output_tqqq, output_qld):
    """Read signal data from CSVs (authoritative); fall back to output parsing for high189."""
    signals = {}

    try:
        df  = pd.read_csv("signals/tushar_v2_history.csv", dtype={"date": str})
        row = df.sort_values("date").iloc[-1]
        signals["qqq_close"]     = float(row["qqq_close"])
        signals["pcthi"]         = float(row["pcthi"])
        signals["regime"]        = str(row["regime"])
        signals["tqqq_vol"]      = int(round(float(row["tqqq_vol"]) * 100))
        signals["tqqq_exposure"] = float(row["exposure"])
    except Exception as e:
        print(f"Warning: could not read TQQQ history CSV: {e}")

    try:
        df  = pd.read_csv("signals/tushar_v2_qld_history.csv", dtype={"date": str})
        row = df.sort_values("date").iloc[-1]
        signals["qld_vol"]      = int(round(float(row["qld_vol"]) * 100))
        signals["qld_exposure"] = int(row["pct_in_qld"])
    except Exception as e:
        print(f"Warning: could not read QLD history CSV: {e}")

    for line in output_tqqq.split("\n"):
        if "189d High:" in line:
            m = re.search(r"\$(\d+\.\d+)", line)
            if m:
                signals["high189"] = float(m.group(1))
                break

    return signals


def get_last_7_days_exposure():
    exposures = {"tqqq": [], "qld": [], "qqq": []}

    csv_map = {
        "tqqq": ("signals/tushar_v2_history.csv",     "exposure",   lambda r: f"{r['exposure']*100:.0f}%"),
        "qld":  ("signals/tushar_v2_qld_history.csv", "pct_in_qld", lambda r: f"{r['pct_in_qld']:.0f}%"),
        "qqq":  ("signals/tushar_v2_qqq_history.csv", "exposure",   lambda r: f"{r['exposure']*100:.0f}%"),
    }
    for key, (path, col, fmt) in csv_map.items():
        try:
            df = pd.read_csv(path)
            if col in df.columns and "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                for _, row in df.sort_values("date").tail(7).iterrows():
                    exposures[key].append((row["date"].strftime("%Y-%m-%d"), fmt(row)))
        except Exception:
            pass

    return exposures


def display_7day_exposure(exposures):
    print("\nLAST 7 DAYS EXPOSURE %:")
    print("-" * 70)
    print(f"{'Date':<12} {'TQQQ v2':<15} {'QLD v2':<15} {'QQQ v2':<15}")
    print("-" * 70)
    max_rows = max(len(v) for v in exposures.values())
    for i in range(max_rows):
        t = exposures["tqqq"][i] if i < len(exposures["tqqq"]) else ("", "-")
        q = exposures["qld"][i]  if i < len(exposures["qld"])  else ("", "-")
        u = exposures["qqq"][i]  if i < len(exposures["qqq"])  else ("", "-")
        date_str = t[0] or q[0] or u[0]
        print(f"{date_str:<12} {t[1]:<15} {q[1]:<15} {u[1]:<15}")
    print("-" * 70)


def write_sms_summary(signals):
    """Write a short SMS-ready summary (<160 chars) to signals/sms_summary.txt."""
    today  = datetime.now().strftime("%m/%d")
    regime = signals.get("regime", "?")
    pcthi  = signals.get("pcthi", 0)
    t_expo = signals.get("tqqq_exposure", "?")
    t_vol  = signals.get("tqqq_vol", "?")
    q_expo = signals.get("qld_exposure", "?")
    text   = f"{today} {regime} {pcthi:.1f}%|TQQQ:{t_expo}x({t_vol}%vol)|QLD:{q_expo}%"
    os.makedirs("signals", exist_ok=True)
    with open("signals/sms_summary.txt", "w") as f:
        f.write(text[:160])
    print(f"[notify] SMS summary: {text[:160]}")


def write_exposure_history_js(exposures):
    history = {}
    for strat in ("tqqq", "qld", "qqq"):
        for date, pct in exposures.get(strat, []):
            history.setdefault(date, {})[strat] = pct
    rows     = [{"date": d, **history[d]} for d in sorted(history.keys())]
    out_path = os.path.join("signals", "exposure_history.js")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("window.EXPOSURE_HISTORY = " + json.dumps(rows) + ";")
    print(f"[DONE] Wrote exposure history: {out_path}")


def update_document(signals):
    doc_path = "docs/accounts_summary.md"
    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_section = (
        f"## TODAY'S SIGNALS ({datetime.now().strftime('%Y-%m-%d')})\n\n"
        f"**Regime Gate:** {signals.get('regime','?')} - "
        f"{signals.get('pcthi', 0):.1f}% below 189d high (threshold: 15%)\n\n"
        f"**v2 Strategies:**\n"
        f"- TQQQ v2 (1.5x cap): Hold {signals.get('tqqq_exposure','?')}x | Vol: {signals.get('tqqq_vol','?')}%\n"
        f"- QLD v2 (1.0x cap): {signals.get('qld_exposure','?')}% | Vol: {signals.get('qld_vol','?')}%\n\n"
        f"**Market Data:**\n"
        f"- QQQ Close: ${signals.get('qqq_close', 0):.2f}\n"
        f"- 189d High: ${signals.get('high189', 0):.2f}"
    )
    content = re.sub(r"## TODAY'S SIGNALS.*?(?=---)", new_section + "\n\n",
                     content, flags=re.DOTALL)
    content = re.sub(r"\*\*Last Updated:\*\*.*",
                     f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                     content)
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[DONE] Updated {doc_path}")


def open_dashboard():
    path = os.path.abspath("portfolio_dashboard.html")
    if os.path.exists(path):
        webbrowser.open("file://" + path)
        print(f"[DONE] Dashboard opened: {path}")
    else:
        print(f"[WARNING] Dashboard not found: {path}")


# ── Notifications ──────────────────────────────────────────────────────────────

def _smtp_send(to_addr, subject, body, attachments=None):
    """Send plain-text email via Gmail SMTP. Returns True on success.

    attachments: optional list of (filename, content_str) tuples.
    """
    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        print("[notify] EMAIL_ADDRESS or EMAIL_PASSWORD not set — skipping.")
        return False
    try:
        msg            = MIMEMultipart()
        msg["From"]    = email_addr
        msg["To"]      = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        for filename, content in attachments or []:
            part = MIMEApplication(content.encode("utf-8"), _subtype="html")
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(email_addr, email_pass)
            server.sendmail(email_addr, to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"[notify] SMTP error: {e}")
        return False


def _self_contained_dashboard():
    """Dashboard HTML with local signals/*.js inlined so it renders standalone.

    Returns the HTML string, or None if the dashboard file is missing."""
    path = "portfolio_dashboard.html"
    if not os.path.exists(path):
        print(f"[notify] {path} not found — sending email without dashboard.")
        return None
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    def inline(m):
        src = m.group(1)
        try:
            with open(src, "r", encoding="utf-8") as jf:
                return "<script>\n" + jf.read() + "\n</script>"
        except OSError as e:
            print(f"[notify] Could not inline {src}: {e}")
            return m.group(0)

    return re.sub(r'<script src="(signals/[^"]+)"[^>]*></script>', inline, html)


def _ntfy_send(topic, title, message):
    """Push notification via ntfy.sh. Returns True on success.

    Replaces the AT&T email-to-SMS gateway, which AT&T shut down 2025-06-17."""
    try:
        import requests
        r = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Tags": "chart_with_upwards_trend"},
            timeout=15,
        )
        if not r.ok:
            print(f"[notify] ntfy error: HTTP {r.status_code} {r.text[:200]}")
        return r.ok
    except Exception as e:
        print(f"[notify] ntfy error: {e}")
        return False


def _build_email_body(signals, exposures):
    today  = datetime.now().strftime("%Y-%m-%d")
    regime = signals.get("regime", "?")
    pcthi  = signals.get("pcthi", 0)
    qqq_cl = signals.get("qqq_close", 0)
    hi189  = signals.get("high189", 0)
    t_vol  = signals.get("tqqq_vol", "?")
    t_expo = signals.get("tqqq_exposure", "?")
    q_vol  = signals.get("qld_vol", "?")
    q_expo = signals.get("qld_exposure", "?")

    lines = [
        f"=== TUSHAR V2 DAILY SIGNALS -- {today} ===",
        "",
        f"REGIME : {regime}",
        f"QQQ    : ${qqq_cl:.2f}  |  189d High: ${hi189:.2f}  |  {pcthi:.1f}% below high  |  Gate at 15%",
        "",
        "TQQQ v2  (taxable / margin account)",
        f"  Target Exposure  : {t_expo}x TQQQ   (cap 1.5x)",
        f"  20d Vol          : {t_vol}%",
        "",
        "QLD v2  (Roth / HSA / 401k -- no margin)",
        f"  Target Allocation: {q_expo}% of account   (cap 100%)",
        f"  20d Vol          : {q_vol}%",
        "",
        "LAST 7 DAYS EXPOSURE:",
        f"{'Date':<12} {'TQQQ v2':>9} {'QLD v2':>9} {'QQQ v2':>9}",
        "-" * 44,
    ]

    all_dates = sorted({d for strat in exposures.values() for d, _ in strat})
    t_map = dict(exposures.get("tqqq", []))
    q_map = dict(exposures.get("qld",  []))
    u_map = dict(exposures.get("qqq",  []))
    for d in all_dates:
        lines.append(
            f"{d:<12} {t_map.get(d,'-'):>9} {q_map.get(d,'-'):>9} {u_map.get(d,'-'):>9}"
        )

    lines += ["", "---", "Automated signal | Tushar v2 strategy"]
    return "\n".join(lines)


def send_notifications(signals, exposures):
    """Email full report + SMS summary. Failures never crash the script."""
    email_addr = os.environ.get("EMAIL_ADDRESS", "")

    today      = datetime.now().strftime("%Y-%m-%d")
    regime     = signals.get("regime", "?")
    t_expo     = signals.get("tqqq_exposure", "?")
    q_expo     = signals.get("qld_exposure", "?")
    pcthi      = signals.get("pcthi", 0)
    t_vol      = signals.get("tqqq_vol", "?")

    # Email
    try:
        subject = f"Daily Signal - {today} | {regime} | TQQQ: {t_expo}x | QLD: {q_expo}%"
        body    = _build_email_body(signals, exposures)
        attachments = []
        dashboard   = _self_contained_dashboard()
        if dashboard:
            attachments.append(("portfolio_dashboard.html", dashboard))
        ok = _smtp_send(email_addr, subject, body, attachments)
        if ok:
            print(f"[notify] Email sent to {email_addr}")
    except Exception as e:
        print(f"[notify] Email error: {e}")

    # Phone push via ntfy.sh (AT&T killed the txt.att.net email-to-SMS gateway)
    try:
        ntfy_topic = os.environ.get("NTFY_TOPIC", "")
        if ntfy_topic:
            push_title = f"{regime} | TQQQ {t_expo}x | QLD {q_expo}%"
            push_body  = f"{today} {regime} {pcthi:.1f}% below 189d high | TQQQ: {t_expo}x ({t_vol}% vol) | QLD: {q_expo}%"
            if _ntfy_send(ntfy_topic, push_title, push_body):
                print("[notify] Push sent via ntfy.sh")
        else:
            print("[notify] NTFY_TOPIC not set — skipping phone push.")
    except Exception as e:
        print(f"[notify] Push error: {e}")


def send_failure_email(error_msg):
    """Send failure alert. Safe to call from an except block."""
    try:
        email_addr = os.environ.get("EMAIL_ADDRESS", "")
        today      = datetime.now().strftime("%Y-%m-%d")
        subject    = f"Daily Signal FAILED - {today}"
        body       = f"The daily signal script failed on {today}.\n\nError:\n{error_msg}"
        ok         = _smtp_send(email_addr, subject, body)
        if ok:
            print(f"[notify] Failure email sent to {email_addr}")
    except Exception as e:
        print(f"[notify] Could not send failure email: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    try:
        print("Running daily signals...\n")
        print("=" * 70)

        print("1. Running TQQQ Signal (tushar_v2_signal.py)...\n")
        output_tqqq = run_signal("tushar_v2_signal.py")
        print(output_tqqq)

        print("\n" + "=" * 70)

        print("2. Running QLD Signal (tushar_v2_qld_signal.py)...\n")
        output_qld = run_signal("tushar_v2_qld_signal.py")
        print(output_qld)

        print("\n" + "=" * 70)

        print("3. Running QQQ v2 Signal (tushar_v2_qqq_signal.py)...\n")
        output_qqq = run_signal("tushar_v2_qqq_signal.py")
        print(output_qqq)

        print("\n" + "=" * 70)

        signals = extract_signal_data(output_tqqq, output_qld)
        signals["qqq_close_ref"] = signals.get("qqq_close")
        signals["qqq_vol_ref"]   = None

        for line in output_qqq.split("\n"):
            if "QQQ 20d Vol:" in line:
                m = re.search(r"(\d+)%", line)
                if m:
                    signals["qqq_vol_v2"] = int(m.group(1))
            if "Target:" in line and "QQQ" in line:
                m = re.search(r"Hold ([\d.]+)x QQQ", line)
                if m:
                    signals["qqq_exposure_v2"] = float(m.group(1))

        def _fmt(v, spec):
            try:
                return format(v, spec)
            except (TypeError, ValueError):
                return "?"

        print("\n" + "=" * 70)
        print("[DONE] Daily signals complete!")
        print(f"\nToday's Signals ({datetime.now().strftime('%Y-%m-%d')}):")
        print(f"  Regime Gate: {signals.get('regime','?')} ({_fmt(signals.get('pcthi'),'.1f')}% below 189d high)")
        print(f"  QQQ v2 : {signals.get('qqq_exposure_v2','?')}x | Vol: {_fmt(signals.get('qqq_vol_v2'),'.0f')}%")
        print(f"  TQQQ v2: {signals.get('tqqq_exposure','?')}x (cap 1.5x, with margin)")
        print(f"  QLD v2 : {signals.get('qld_exposure','?')}% (cap 100%, no margin)")
        print("=" * 70)

        exposures = get_last_7_days_exposure()
        display_7day_exposure(exposures)

        try:
            write_exposure_history_js(exposures)
        except Exception as e:
            print(f"[WARNING] Could not write exposure JS: {e}")

        try:
            write_sms_summary(signals)
        except Exception as e:
            print(f"[WARNING] Could not write SMS summary: {e}")

        try:
            update_document(signals)
        except Exception as e:
            print(f"[WARNING] Could not update accounts_summary.md: {e}")

        try:
            sync_account_data()
        except Exception as e:
            print(f"[WARNING] Could not sync account data: {e}")

        try:
            open_dashboard()
        except Exception as e:
            print(f"[WARNING] Could not open dashboard: {e}")

        send_notifications(signals, exposures)

    except Exception:
        err = traceback.format_exc()
        print(f"\n[ERROR] Script failed:\n{err}")
        send_failure_email(err)
        raise


if __name__ == "__main__":
    main()
