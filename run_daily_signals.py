"""Run both v2 signals daily and update accounts_summary.md with results.

Usage:
    python run_daily_signals.py

This script:
1. Runs tushar_v2_signal.py (TQQQ signal)
2. Runs tushar_v2_qld_signal.py (QLD signal)
3. Fetches QQQ reference data (price, volatility)
4. Updates docs/accounts_summary.md with today's signals
"""

import subprocess
import re
from datetime import datetime
import yfinance as yf
import numpy as np
import pandas as pd
import webbrowser
import os

def run_signal(script_name):
    """Run a signal script and capture output."""
    result = subprocess.run(
        ["python", script_name],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr

def get_qqq_data():
    """Fetch QQQ price and volatility reference data."""
    try:
        qqq_df = yf.download('QQQ', period='3mo', progress=False, auto_adjust=True)
        if isinstance(qqq_df.columns, pd.MultiIndex):
            qqq_df.columns = qqq_df.columns.get_level_values(0)

        close = qqq_df['Close']
        ret = close.pct_change()

        qqq_close = close.iloc[-1]
        qqq_vol = (ret.rolling(20).std() * np.sqrt(252)).iloc[-1] * 100

        return {
            'qqq_close': qqq_close,
            'qqq_vol': qqq_vol
        }
    except Exception as e:
        print(f"Warning: Could not fetch QQQ data: {e}")
        return {'qqq_close': None, 'qqq_vol': None}

def extract_signal_data(output_tqqq, output_qld):
    """Extract signal data from outputs."""
    signals = {}

    # Parse TQQQ signal
    for line in output_tqqq.split("\n"):
        if "QQQ Close:" in line:
            match = re.search(r"\$(\d+\.\d+)", line)
            if match:
                signals["qqq_close"] = float(match.group(1))
        if "189d High:" in line:
            match = re.search(r"\$(\d+\.\d+)", line)
            if match:
                signals["high189"] = float(match.group(1))
        if "% Below High:" in line:
            match = re.search(r"([\d.]+)%", line)
            if match:
                signals["pcthi"] = float(match.group(1))
        if "Regime:" in line:
            signals["regime"] = "BULL" if "BULL" in line else "CASH"
        if "TQQQ 20d Vol:" in line:
            match = re.search(r"(\d+)%", line)
            if match:
                signals["tqqq_vol"] = int(match.group(1))
        if "Target:" in line and "TQQQ" in line:
            match = re.search(r"Hold ([\d.]+)x TQQQ", line)
            if match:
                signals["tqqq_exposure"] = float(match.group(1))
        if "Action:" in line and "TQQQ" not in line:
            signals["action"] = line.split("Action: ")[1].strip()

    # Parse QLD signal
    for line in output_qld.split("\n"):
        if "QLD 20d Vol:" in line:
            match = re.search(r"(\d+)%", line)
            if match:
                signals["qld_vol"] = int(match.group(1))
        if "Target:" in line and "QLD" in line:
            match = re.search(r"(\d+)% of account in QLD", line)
            if match:
                signals["qld_exposure"] = int(match.group(1))

    return signals

def update_document(signals):
    """Update accounts_summary.md with today's signals."""
    doc_path = "docs/accounts_summary.md"

    with open(doc_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find and replace the signals section
    qqq_ref = ""
    if signals.get('qqq_close_ref') and signals.get('qqq_vol_ref'):
        qqq_ref = f"\n- QQQ B&H (Ref): ${signals.get('qqq_close_ref'):.2f} | 20d Vol: {signals.get('qqq_vol_ref'):.0f}% | Always 100% invested"

    new_signals_section = f"""## TODAY'S SIGNALS ({datetime.now().strftime('%Y-%m-%d')})

**Regime Gate:** {signals.get('regime', '?')} - {signals.get('pcthi', '?'):.1f}% below 189d high (threshold: 15%)

**v2 Strategies (Comparison):**
- **QQQ v2** (1.0x cap, no margin): Hold {signals.get('qqq_exposure_v2', '?')}x | Vol: {signals.get('qqq_vol_v2', '?')}%
- **TQQQ v2** (1.5x cap, with margin): Hold {signals.get('tqqq_exposure', '?')}x | Vol: {signals.get('tqqq_vol', '?')}%
- **QLD v2** (1.0x cap, no margin): {signals.get('qld_exposure', '?')}% | Vol: {signals.get('qld_vol', '?')}%

**Market Data:**
- QQQ Close: ${signals.get('qqq_close', '?'):.2f}
- 189d High: ${signals.get('high189', '?'):.2f}{qqq_ref}"""

    # Replace old signals section
    pattern = r"## TODAY'S SIGNALS.*?(?=---)"
    content = re.sub(pattern, new_signals_section + "\n\n", content, flags=re.DOTALL)

    # Update Last Updated timestamp
    content = re.sub(
        r"\*\*Last Updated:\*\*.*",
        f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        content
    )

    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n[DONE] Updated {doc_path}")

def get_last_7_days_exposure():
    """Get the last 7 days of exposure % for all strategies."""
    exposures = {'tqqq': [], 'qld': [], 'qqq': []}

    # Read TQQQ exposure history
    try:
        tqqq_df = pd.read_csv("signals/tushar_v2_history.csv")
        if 'exposure' in tqqq_df.columns and 'date' in tqqq_df.columns:
            tqqq_df['date'] = pd.to_datetime(tqqq_df['date'])
            tqqq_df = tqqq_df.sort_values('date')
            last_7 = tqqq_df.tail(7)
            for _, row in last_7.iterrows():
                exposures['tqqq'].append((row['date'].strftime('%Y-%m-%d'), f"{row['exposure']*100:.0f}%"))
    except Exception as e:
        pass

    # Read QLD exposure history
    try:
        qld_df = pd.read_csv("signals/tushar_v2_qld_history.csv")
        if 'pct_in_qld' in qld_df.columns and 'date' in qld_df.columns:
            qld_df['date'] = pd.to_datetime(qld_df['date'])
            qld_df = qld_df.sort_values('date')
            last_7 = qld_df.tail(7)
            for _, row in last_7.iterrows():
                exposures['qld'].append((row['date'].strftime('%Y-%m-%d'), f"{row['pct_in_qld']:.0f}%"))
    except Exception as e:
        pass

    # Read QQQ exposure history
    try:
        qqq_df = pd.read_csv("signals/tushar_v2_qqq_history.csv")
        if 'exposure' in qqq_df.columns and 'date' in qqq_df.columns:
            qqq_df['date'] = pd.to_datetime(qqq_df['date'])
            qqq_df = qqq_df.sort_values('date')
            last_7 = qqq_df.tail(7)
            for _, row in last_7.iterrows():
                exposures['qqq'].append((row['date'].strftime('%Y-%m-%d'), f"{row['exposure']*100:.0f}%"))
    except Exception as e:
        pass

    return exposures

def display_7day_exposure(exposures):
    """Display last 7 days of exposure % for all strategies."""
    print("\nLAST 7 DAYS EXPOSURE %:")
    print("-" * 70)

    # Find max length for alignment
    max_rows = max(len(exposures['tqqq']), len(exposures['qld']), len(exposures['qqq']))

    # Print header
    print(f"{'Date':<12} {'TQQQ v2':<15} {'QLD v2':<15} {'QQQ v2':<15}")
    print("-" * 70)

    # Print rows
    for i in range(max_rows):
        tqqq_str = f"{exposures['tqqq'][i][1]}" if i < len(exposures['tqqq']) else "-"
        qld_str = f"{exposures['qld'][i][1]}" if i < len(exposures['qld']) else "-"
        qqq_str = f"{exposures['qqq'][i][1]}" if i < len(exposures['qqq']) else "-"

        date_str = exposures['tqqq'][i][0] if i < len(exposures['tqqq']) else (exposures['qld'][i][0] if i < len(exposures['qld']) else (exposures['qqq'][i][0] if i < len(exposures['qqq']) else ""))

        print(f"{date_str:<12} {tqqq_str:<15} {qld_str:<15} {qqq_str:<15}")

    print("-" * 70)

def write_exposure_history_js(exposures):
    """Write the 7-day exposure history to a JS file the dashboard can load.

    Browsers block XHR/fetch to file:// for security, but <script src> works,
    so we emit signals/exposure_history.js setting window.EXPOSURE_HISTORY.
    """
    # Merge all three strategies into a date-keyed map
    history = {}
    for strat in ('tqqq', 'qld', 'qqq'):
        for date, pct in exposures.get(strat, []):
            history.setdefault(date, {})[strat] = pct

    rows = [{"date": d, **history[d]} for d in sorted(history.keys())]

    import json
    js = "window.EXPOSURE_HISTORY = " + json.dumps(rows) + ";"
    out_path = os.path.join("signals", "exposure_history.js")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"[DONE] Wrote exposure history: {out_path}")

def open_dashboard():
    """Open the portfolio dashboard in default browser."""
    dashboard_path = os.path.abspath("portfolio_dashboard.html")
    if os.path.exists(dashboard_path):
        webbrowser.open("file://" + dashboard_path)
        print(f"\n[DONE] Dashboard opened: {dashboard_path}")
    else:
        print(f"\n[WARNING] Dashboard not found: {dashboard_path}")

def main():
    print("Running daily signals...\n")
    print("=" * 70)

    # Run TQQQ signal
    print("1. Running TQQQ Signal (tushar_v2_signal.py)...\n")
    output_tqqq = run_signal("tushar_v2_signal.py")
    print(output_tqqq)

    print("\n" + "=" * 70)

    # Run QLD signal
    print("2. Running QLD Signal (tushar_v2_qld_signal.py)...\n")
    output_qld = run_signal("tushar_v2_qld_signal.py")
    print(output_qld)

    print("\n" + "=" * 70)

    # Run QQQ v2 signal (for comparison)
    print("3. Running QQQ v2 Signal (tushar_v2_qqq_signal.py - comparison only)...\n")
    output_qqq = run_signal("tushar_v2_qqq_signal.py")
    print(output_qqq)

    print("\n" + "=" * 70)

    # Extract signals
    signals = extract_signal_data(output_tqqq, output_qld)
    signals['qqq_close_ref'] = signals.get('qqq_close', None)
    signals['qqq_vol_ref'] = None  # Will extract from QQQ signal

    # Extract QQQ v2 signal
    for line in output_qqq.split("\n"):
        if "QQQ 20d Vol:" in line:
            match = re.search(r"(\d+)%", line)
            if match:
                signals['qqq_vol_v2'] = int(match.group(1))
        if "Target:" in line and "QQQ" in line:
            match = re.search(r"Hold ([\d.]+)x QQQ", line)
            if match:
                signals['qqq_exposure_v2'] = float(match.group(1))

    print("\n" + "=" * 70)
    print("[DONE] Daily signals complete!")
    print(f"\nToday's Signals ({datetime.now().strftime('%Y-%m-%d')}):")
    print(f"  Regime Gate: {signals.get('regime', '?')} ({signals.get('pcthi', '?'):.1f}% below 189d high, threshold 15%)")
    print(f"  QQQ v2:  {signals.get('qqq_exposure_v2', '?')}x (1.0x cap, no margin) | Vol: {signals.get('qqq_vol_v2', '?'):.0f}%")
    print(f"  TQQQ v2: {signals.get('tqqq_exposure', '?')}x (1.5x cap, with margin)")
    print(f"  QLD v2:  {signals.get('qld_exposure', '?')}% (1.0x cap, no margin)")
    print("=" * 70)

    # Show last 7 days exposure
    exposures = get_last_7_days_exposure()
    display_7day_exposure(exposures)

    # Write exposure history for the dashboard, then open it
    write_exposure_history_js(exposures)
    open_dashboard()

if __name__ == "__main__":
    main()
