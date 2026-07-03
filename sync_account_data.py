#!/usr/bin/env python3
"""
Sync account_transactions.json to signals/account_data.js
Run this after modifying account_transactions.json to update the dashboard
"""

import json
from pathlib import Path

def sync_account_data():
    """Generate account_data.js from account_transactions.json"""

    # Read the account data
    accounts_file = Path(__file__).parent / 'account_transactions.json'
    data = json.loads(accounts_file.read_text())

    # Create JavaScript file with embedded data
    js_content = f"""// Auto-generated account data
// Source: account_transactions.json
// Last updated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
window.ACCOUNT_DATA = {json.dumps(data, indent=2)};
"""

    # Write to signals directory
    signals_dir = Path(__file__).parent / 'signals'
    signals_dir.mkdir(exist_ok=True)
    account_data_file = signals_dir / 'account_data.js'
    account_data_file.write_text(js_content)

    print(f"✓ Synced account_transactions.json → signals/account_data.js")
    return True

if __name__ == '__main__':
    sync_account_data()
