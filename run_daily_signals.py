"""Run both v2 signals daily and update accounts_summary.md with results.

Usage:
    python run_daily_signals.py

This script:
1. Runs tushar_v2_signal.py (TQQQ signal)
2. Runs tushar_v2_qld_signal.py (QLD signal)
3. Updates docs/accounts_summary.md with today's signals
"""

import subprocess
import re
from datetime import datetime

def run_signal(script_name):
    """Run a signal script and capture output."""
    result = subprocess.run(
        ["python", script_name],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr

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
    new_signals_section = f"""## TODAY'S SIGNALS ({datetime.now().strftime('%Y-%m-%d')})

**TQQQ Signal:** Hold {signals.get('tqqq_exposure', '?')}x | Action: {signals.get('action', '?')}
**QLD Signal:** {signals.get('qld_exposure', '?')}% of account | Action: SCALE DOWN

**Market Data:**
- QQQ Close: ${signals.get('qqq_close', '?'):.2f}
- 189d High: ${signals.get('high189', '?'):.2f}
- % Below High: {signals.get('pcthi', '?'):.1f}% ({signals.get('regime', '?')} regime)
- TQQQ 20d Vol: {signals.get('tqqq_vol', '?')}% -> exposure {signals.get('tqqq_exposure', '?')}x
- QLD 20d Vol: {signals.get('qld_vol', '?')}% -> exposure {signals.get('qld_exposure', '?')}%"""

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

    # Extract and update document
    print("3. Updating accounts_summary.md...\n")
    signals = extract_signal_data(output_tqqq, output_qld)
    update_document(signals)

    print("\n" + "=" * 70)
    print("[DONE] Daily signals complete!")
    print(f"\nToday's Signals ({datetime.now().strftime('%Y-%m-%d')}):")
    print(f"  TQQQ: {signals.get('tqqq_exposure', '?')}x exposure")
    print(f"  QLD:  {signals.get('qld_exposure', '?')}% of account")
    print("=" * 70)

if __name__ == "__main__":
    main()
