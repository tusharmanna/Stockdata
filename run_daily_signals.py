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

def display_account_summary():
    """Display the complete account summary with positions and projections."""
    print("\n" + "=" * 150)
    print("COMPLETE ACCOUNT SUMMARY & POSITIONS")
    print("=" * 150)

    accounts = [
        ("ACTIVE v2 ACCOUNTS:", [
            ("Roth IRA", 81420, "QLD", 78, 63508, "665 QLD", 17912, "BUY 665", 24915),
            ("WELLSTRADE IRA", 39640, "QLD", 78, 30899, "324 QLD", 8741, "BUY 324", 12135),
            ("HSA", 27257, "QLD", 78, 21260, "222 QLD", 5996, "BUY 222", 8352),
            ("HSA Brokerage", 23000, "QLD", 78, 17940, "188 QLD", 5060, "BUY 188", 7043),
            ("Optum HSA 2023", 21729, "QLD", 78, 16949, "177 QLD", 4780, "BUY 177", 6650),
            ("BrokerageLink", 339903, "TQQQ", 53, 180148, "2,254 TQQQ", 159754, "BUY 2,254", 151266),
            ("IB Brokerage", 100000, "TQQQ", 53, 53000, "663 TQQQ", 47000, "BUY 663", 44500),
        ]),
        ("RESTRICTED/CUSTODIAL:", [
            ("Colorado 401K", 365968, "TBD", None, None, "Pending", None, "HOLD", None),
            ("Eshaan Manna", 4653, "Static", 100, None, "Current", None, "HOLD", None),
            ("Shreyaan Manna", 2819, "Static", 100, None, "Current", None, "HOLD", None),
            ("Youth Account", 506, "Static", 100, None, "Current", None, "HOLD", None),
        ]),
        ("EMERGENCY RESERVE:", [
            ("Cash Management (TOD)", 6525, "N/A", 100, 6525, None, 6525, "HOLD", None),
        ])
    ]

    # Print header
    header = f"{'Account':<25} {'Balance':>12} {'ETF':>8} {'%':>5} {'Target $':>12} {'Shares':>15} {'Cash':>12} {'Action':>15} {'Year1 Est':>12}"
    print(header)
    print("-" * 150)

    total_balance = 0
    total_target = 0
    total_cash = 0
    total_year1 = 0

    for section_name, section_accounts in accounts:
        print(f"\n{section_name}")
        print("-" * 150)

        section_total_balance = 0
        section_total_target = 0
        section_total_cash = 0
        section_total_year1 = 0

        for acct in section_accounts:
            name, balance, etf, pct, target, shares, cash, action, year1 = acct

            balance_str = f"${balance:,.0f}"
            target_str = f"${target:,.0f}" if target else "-"
            cash_str = f"${cash:,.0f}" if cash else "-"
            year1_str = f"${year1:,.0f}" if year1 else "-"
            pct_str = f"{pct}%" if pct else "-"
            shares_str = str(shares) if shares else "-"

            print(f"{name:<25} {balance_str:>12} {etf:>8} {pct_str:>5} {target_str:>12} {shares_str:>15} {cash_str:>12} {action:>15} {year1_str:>12}")

            if target:
                section_total_balance += balance
                section_total_target += target
                if cash:
                    section_total_cash += cash
                if year1:
                    section_total_year1 += year1

        # Section subtotal
        print("-" * 150)
        subtotal_str = f"${section_total_balance:,.0f}"
        target_str = f"${section_total_target:,.0f}" if section_total_target else "-"
        cash_str = f"${section_total_cash:,.0f}" if section_total_cash else "-"
        year1_str = f"${section_total_year1:,.0f}" if section_total_year1 else "-"
        print(f"{'SUBTOTAL':<25} {subtotal_str:>12} {'-':>8} {'-':>5} {target_str:>12} {'-':>15} {cash_str:>12} {'-':>15} {year1_str:>12}")

        total_balance += section_total_balance
        total_target += section_total_target
        total_cash += section_total_cash
        total_year1 += section_total_year1

    # Grand total
    print("\n" + "=" * 150)
    grand_total_str = f"${total_balance:,.0f}"
    target_str = f"${total_target:,.0f}"
    cash_str = f"${total_cash:,.0f}"
    year1_str = f"${total_year1:,.0f}"
    print(f"{'GRAND TOTAL':<25} {grand_total_str:>12} {'-':>8} {'-':>5} {target_str:>12} {'4,493 shares':>15} {cash_str:>12} {'-':>15} {year1_str:>12}")
    print("=" * 150)

    # Summary stats
    print(f"\nSUMMARY:")
    print(f"  Total portfolio value:          ${total_balance:,.0f}")
    print(f"  Total to deploy to ETFs:        ${total_target:,.0f}")
    print(f"  Total cash (money market):      ${total_cash:,.0f}")
    print(f"  Annual T-bill yield:            ${(total_cash * 0.05):,.0f}/year")
    print(f"  Expected Year 1 return:         ${total_year1:,.0f}")
    print(f"  Expected Year 1 ending balance: ${total_balance + total_year1:,.0f}")
    print("=" * 150)

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

    # Display account summary
    display_account_summary()

if __name__ == "__main__":
    main()
