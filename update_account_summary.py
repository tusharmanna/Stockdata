"""Update accounts_summary.md with current signals and buy/sell actions.

Usage:
    python update_account_summary.py

Prompts for:
    - Current account balances (Roth IRA, HSA, BrokerageLink)
    - Current holdings (shares of QLD/TQQQ if you already own any)

Outputs:
    - Updated docs/accounts_summary.md with today's actions
"""

import subprocess
import os
import sys
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np


def get_signals():
    """Run signal tools and capture their output."""
    print("\n📊 Running today's signals...\n")

    # Run TQQQ signal
    result_tqqq = subprocess.run(
        ["python", "tushar_v2_signal.py"],
        capture_output=True,
        text=True,
    )
    output_tqqq = result_tqqq.stdout + result_tqqq.stderr

    # Run QLD signal
    result_qld = subprocess.run(
        ["python", "tushar_v2_qld_signal.py"],
        capture_output=True,
        text=True,
    )
    output_qld = result_qld.stdout + result_qld.stderr

    return output_tqqq, output_qld


def get_prices():
    """Fetch current QLD and TQQQ prices."""
    print("💹 Fetching current prices...\n")
    qld = yf.Ticker("QLD").history(period="1d")
    tqqq = yf.Ticker("TQQQ").history(period="1d")
    qld_price = float(qld["Close"].values[0])
    tqqq_price = float(tqqq["Close"].values[0])
    return qld_price, tqqq_price


def get_account_inputs():
    """Get current account balances and holdings from user."""
    print("\n💰 Enter current account information:\n")

    # Get balances
    roth_balance = float(input("Roth IRA balance ($): "))
    hsa_balance = float(input("HSA balance ($): "))
    brokerage_balance = float(input("BrokerageLink balance ($): "))

    # Get current holdings
    print("\nCurrent holdings (leave blank if 0):")
    roth_qld = float(input("Roth IRA: shares of QLD (default 0): ") or 0)
    hsa_qld = float(input("HSA: shares of QLD (default 0): ") or 0)
    brokerage_tqqq = float(input("BrokerageLink: shares of TQQQ (default 0): ") or 0)

    return {
        "roth_balance": roth_balance,
        "hsa_balance": hsa_balance,
        "brokerage_balance": brokerage_balance,
        "roth_qld_shares": roth_qld,
        "hsa_qld_shares": hsa_qld,
        "brokerage_tqqq_shares": brokerage_tqqq,
    }


def parse_signals(output_tqqq, output_qld):
    """Extract signal details from tool outputs."""
    signals = {}

    # Parse TQQQ signal
    for line in output_tqqq.split("\n"):
        if "Target:" in line and "TQQQ" in line:
            signals["tqqq_target"] = line.split("Target: ")[1].split("Action")[0].strip()
        if "Action:" in line and "TQQQ" not in line:
            signals["tqqq_action"] = line.split("Action: ")[1].strip()

    # Parse QLD signal
    for line in output_qld.split("\n"):
        if "Target:" in line and "QLD" in line:
            signals["qld_target"] = line.split("Target: ")[1].split("Action")[0].strip()
        if "Action:" in line and "QLD" not in line:
            signals["qld_action"] = line.split("Action: ")[1].strip()

    return signals


def calculate_targets(accounts, qld_price, tqqq_price):
    """Calculate target shares and buy/sell actions."""
    results = {}

    # ROTH IRA - 78% QLD
    roth_target_cash = accounts["roth_balance"] * 0.78
    roth_target_shares = int(roth_target_cash / qld_price)
    roth_current_value = accounts["roth_qld_shares"] * qld_price
    roth_cash = accounts["roth_balance"] - roth_current_value
    roth_action_shares = roth_target_shares - accounts["roth_qld_shares"]

    results["roth"] = {
        "target_shares": roth_target_shares,
        "target_value": roth_target_shares * qld_price,
        "target_cash": accounts["roth_balance"] - (roth_target_shares * qld_price),
        "current_shares": accounts["roth_qld_shares"],
        "current_value": roth_current_value,
        "current_cash": roth_cash,
        "action_shares": roth_action_shares,
        "action": "BUY" if roth_action_shares > 0 else "SELL" if roth_action_shares < 0 else "HOLD",
    }

    # HSA - 78% QLD
    hsa_target_cash = accounts["hsa_balance"] * 0.78
    hsa_target_shares = int(hsa_target_cash / qld_price)
    hsa_current_value = accounts["hsa_qld_shares"] * qld_price
    hsa_cash = accounts["hsa_balance"] - hsa_current_value
    hsa_action_shares = hsa_target_shares - accounts["hsa_qld_shares"]

    results["hsa"] = {
        "target_shares": hsa_target_shares,
        "target_value": hsa_target_shares * qld_price,
        "target_cash": accounts["hsa_balance"] - (hsa_target_shares * qld_price),
        "current_shares": accounts["hsa_qld_shares"],
        "current_value": hsa_current_value,
        "current_cash": hsa_cash,
        "action_shares": hsa_action_shares,
        "action": "BUY" if hsa_action_shares > 0 else "SELL" if hsa_action_shares < 0 else "HOLD",
    }

    # BrokerageLink - 53% TQQQ
    brokerage_target_cash = accounts["brokerage_balance"] * 0.53
    brokerage_target_shares = int(brokerage_target_cash / tqqq_price)
    brokerage_current_value = accounts["brokerage_tqqq_shares"] * tqqq_price
    brokerage_cash = accounts["brokerage_balance"] - brokerage_current_value
    brokerage_action_shares = brokerage_target_shares - accounts["brokerage_tqqq_shares"]

    results["brokerage"] = {
        "target_shares": brokerage_target_shares,
        "target_value": brokerage_target_shares * tqqq_price,
        "target_cash": accounts["brokerage_balance"] - (brokerage_target_shares * tqqq_price),
        "current_shares": accounts["brokerage_tqqq_shares"],
        "current_value": brokerage_current_value,
        "current_cash": brokerage_cash,
        "action_shares": brokerage_action_shares,
        "action": "BUY" if brokerage_action_shares > 0 else "SELL" if brokerage_action_shares < 0 else "HOLD",
    }

    return results


def update_markdown(accounts, targets, qld_price, tqqq_price, signals):
    """Update accounts_summary.md with current positions and actions."""

    md_path = "docs/accounts_summary.md"

    # Read existing markdown to preserve header
    with open(md_path, "r") as f:
        content = f.read()

    # Extract everything up to "## Current Positions" or insert before next section
    header_end = content.find("## Current Positions")
    if header_end == -1:
        header_end = content.find("## Daily Signal Running")

    header = content[:header_end].rstrip() + "\n\n"

    # Build current positions section
    current_section = f"""## Current Positions & Actions (Updated {datetime.now().strftime('%Y-%m-%d %H:%M')})

**Prices:**
- QLD: ${qld_price:.2f}
- TQQQ: ${tqqq_price:.2f}

### ROTH IRA

| Item | Current | Target | Action |
|------|---------|--------|--------|
| QLD Shares | {targets['roth']['current_shares']:.0f} | {targets['roth']['target_shares']:.0f} | **{targets['roth']['action']} {abs(targets['roth']['action_shares']):.0f}** |
| QLD Value | ${targets['roth']['current_value']:,.0f} | ${targets['roth']['target_value']:,.0f} | — |
| Cash | ${targets['roth']['current_cash']:,.0f} | ${targets['roth']['target_cash']:,.0f} | — |
| Balance | ${accounts['roth_balance']:,.2f} | ${accounts['roth_balance']:,.2f} | — |

### HEALTH SAVINGS ACCOUNT (HSA)

| Item | Current | Target | Action |
|------|---------|--------|--------|
| QLD Shares | {targets['hsa']['current_shares']:.0f} | {targets['hsa']['target_shares']:.0f} | **{targets['hsa']['action']} {abs(targets['hsa']['action_shares']):.0f}** |
| QLD Value | ${targets['hsa']['current_value']:,.0f} | ${targets['hsa']['target_value']:,.0f} | — |
| Cash | ${targets['hsa']['current_cash']:,.0f} | ${targets['hsa']['target_cash']:,.0f} | — |
| Balance | ${accounts['hsa_balance']:,.2f} | ${accounts['hsa_balance']:,.2f} | — |

### BrokerageLink (Self-Directed)

| Item | Current | Target | Action |
|------|---------|--------|--------|
| TQQQ Shares | {targets['brokerage']['current_shares']:.0f} | {targets['brokerage']['target_shares']:.0f} | **{targets['brokerage']['action']} {abs(targets['brokerage']['action_shares']):.0f}** |
| TQQQ Value | ${targets['brokerage']['current_value']:,.0f} | ${targets['brokerage']['target_value']:,.0f} | — |
| Cash | ${targets['brokerage']['current_cash']:,.0f} | ${targets['brokerage']['target_cash']:,.0f} | — |
| Balance | ${accounts['brokerage_balance']:,.2f} | ${accounts['brokerage_balance']:,.2f} | — |

"""

    # Append rest of document
    rest = content[header_end:]

    # Write updated file
    with open(md_path, "w") as f:
        f.write(header + current_section + rest)

    print(f"\n✅ Updated {md_path}")


def main():
    # Get signals
    output_tqqq, output_qld = get_signals()
    signals = parse_signals(output_tqqq, output_qld)

    # Get prices
    qld_price, tqqq_price = get_prices()

    # Get account info from user
    accounts = get_account_inputs()

    # Calculate targets and actions
    targets = calculate_targets(accounts, qld_price, tqqq_price)

    # Update markdown
    update_markdown(accounts, targets, qld_price, tqqq_price, signals)

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY OF ACTIONS")
    print("="*70)
    print(f"\nRoth IRA:      {targets['roth']['action']} {abs(targets['roth']['action_shares']):.0f} QLD shares")
    print(f"HSA:           {targets['hsa']['action']} {abs(targets['hsa']['action_shares']):.0f} QLD shares")
    print(f"BrokerageLink: {targets['brokerage']['action']} {abs(targets['brokerage']['action_shares']):.0f} TQQQ shares")
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
