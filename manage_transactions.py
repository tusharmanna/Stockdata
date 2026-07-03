#!/usr/bin/env python3
"""
Portfolio Transaction Manager

Usage:
  python manage_transactions.py list                          # List all accounts
  python manage_transactions.py history ACCOUNT_ID            # Show transaction history
  python manage_transactions.py add ACCOUNT_ID BUY|SELL SHARES PRICE [NOTE]
  python manage_transactions.py update ACCOUNT_ID BALANCE     # Update account balance
  python manage_transactions.py price ACCOUNT_ID NEW_PRICE    # Update current ETF price
"""

import json
import sys
from datetime import datetime
from pathlib import Path

ACCOUNTS_FILE = Path(__file__).parent / 'account_transactions.json'

def load_accounts():
    """Load account data from JSON file."""
    with open(ACCOUNTS_FILE, 'r') as f:
        return json.load(f)

def save_accounts(data):
    """Save account data to JSON file."""
    with open(ACCOUNTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def find_account(account_id, data):
    """Find account by ID."""
    for acc in data['accounts']:
        if acc['id'].lower() == account_id.lower():
            return acc
    return None

def list_accounts():
    """List all accounts with their current state."""
    data = load_accounts()
    print("\n" + "="*100)
    print(f"{'Account':<40} {'ETF':<8} {'Balance':>15} {'Shares':>8} {'Exposure':>12} {'Price':>8}")
    print("="*100)

    for acc in data['accounts']:
        shares = sum(t['shares'] if t['action'] == 'BUY' else -t['shares']
                    for t in acc['transactions'])
        exposure = (shares * acc['current_price'] / acc['current_balance'] * 100) if shares > 0 else 0
        print(f"{acc['name']:<40} {acc['etf']:<8} ${acc['current_balance']:>14,.0f} {shares:>8} {exposure:>11.1f}% ${acc['current_price']:>7.2f}")

    print("="*100 + "\n")

def show_history(account_id):
    """Show transaction history for an account."""
    data = load_accounts()
    acc = find_account(account_id, data)

    if not acc:
        print(f"Account '{account_id}' not found")
        return

    print(f"\nTransaction History: {acc['name']} ({acc['etf']})")
    print(f"Current Balance: ${acc['current_balance']:,.2f}")
    print(f"Current Price: ${acc['current_price']:.2f}\n")

    if not acc['transactions']:
        print("No transactions recorded.\n")
        return

    print(f"{'Date':<12} {'Action':<6} {'Shares':>8} {'Price':>8} {'Exposure':>12} {'Note':<30}")
    print("-"*80)

    running_shares = 0
    for tx in acc['transactions']:
        if tx['action'] == 'BUY':
            running_shares += tx['shares']
        else:
            running_shares -= tx['shares']
        exposure = (running_shares * acc['current_price'] / acc['current_balance'] * 100) if running_shares > 0 else 0
        note = tx.get('note', '')
        print(f"{tx['date']:<12} {tx['action']:<6} {tx['shares']:>8} ${tx['price']:>7.2f} {exposure:>11.1f}% {note:<30}")

    final_shares = running_shares
    final_exposure = (final_shares * acc['current_price'] / acc['current_balance'] * 100) if final_shares > 0 else 0
    print("-"*80)
    print(f"{'CURRENT':<12} {'':6} {final_shares:>8} {'':>8} {final_exposure:>11.1f}%")
    print()

def add_transaction(account_id, action, shares, price, note=''):
    """Add a transaction to an account."""
    data = load_accounts()
    acc = find_account(account_id, data)

    if not acc:
        print(f"Account '{account_id}' not found")
        return

    if action.upper() not in ['BUY', 'SELL']:
        print("Action must be BUY or SELL")
        return

    try:
        shares = int(shares)
        price = float(price)
    except ValueError:
        print("Shares must be an integer, price must be a number")
        return

    transaction = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'action': action.upper(),
        'shares': shares,
        'price': price,
        'exposure_at_trade': (sum(t['shares'] if t['action'] == 'BUY' else -t['shares']
                                 for t in acc['transactions']) * acc['current_price'] /
                             acc['current_balance'] * 100) if acc['transactions'] else 0,
        'note': note
    }

    acc['transactions'].append(transaction)
    save_accounts(data)

    print(f"\n✓ Added {action.upper()} of {shares} shares at ${price:.2f}")
    print(f"  Account: {acc['name']}")
    print(f"  Date: {transaction['date']}\n")

def update_balance(account_id, new_balance):
    """Update account balance."""
    data = load_accounts()
    acc = find_account(account_id, data)

    if not acc:
        print(f"Account '{account_id}' not found")
        return

    try:
        new_balance = float(new_balance)
    except ValueError:
        print("Balance must be a number")
        return

    old_balance = acc['current_balance']
    acc['current_balance'] = new_balance
    save_accounts(data)

    print(f"\n✓ Updated balance for {acc['name']}")
    print(f"  Old: ${old_balance:,.2f}")
    print(f"  New: ${new_balance:,.2f}\n")

def update_price(account_id, new_price):
    """Update ETF price."""
    data = load_accounts()
    acc = find_account(account_id, data)

    if not acc:
        print(f"Account '{account_id}' not found")
        return

    try:
        new_price = float(new_price)
    except ValueError:
        print("Price must be a number")
        return

    old_price = acc['current_price']
    acc['current_price'] = new_price
    save_accounts(data)

    print(f"\n✓ Updated price for {acc['name']} ({acc['etf']})")
    print(f"  Old: ${old_price:.2f}")
    print(f"  New: ${new_price:.2f}\n")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == 'list':
        list_accounts()
    elif command == 'history':
        if len(sys.argv) < 3:
            print("Usage: python manage_transactions.py history ACCOUNT_ID")
            return
        show_history(sys.argv[2])
    elif command == 'add':
        if len(sys.argv) < 5:
            print("Usage: python manage_transactions.py add ACCOUNT_ID BUY|SELL SHARES PRICE [NOTE]")
            return
        note = ' '.join(sys.argv[6:]) if len(sys.argv) > 6 else ''
        add_transaction(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], note)
    elif command == 'update':
        if len(sys.argv) < 4:
            print("Usage: python manage_transactions.py update ACCOUNT_ID BALANCE")
            return
        update_balance(sys.argv[2], sys.argv[3])
    elif command == 'price':
        if len(sys.argv) < 4:
            print("Usage: python manage_transactions.py price ACCOUNT_ID NEW_PRICE")
            return
        update_price(sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown command: {command}")
        print(__doc__)

if __name__ == '__main__':
    main()
