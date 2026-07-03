# Portfolio Dashboard Setup & Usage Guide

## ✅ System Overview

You now have a **generic, transaction-based portfolio tracking system** that works for any account with any balance. The system tracks:
- All ETF transactions (BUY/SELL with dates and prices)
- Current portfolio exposure
- Target exposure (configurable, default 45%)
- Automatic calculations for all accounts

---

## 📁 Files

| File | Purpose |
|------|---------|
| `account_transactions.json` | Master transaction database (edit with manage_transactions.py) |
| `manage_transactions.py` | CLI tool to add/view/update transactions |
| `sync_account_data.py` | Sync JSON to JavaScript (run after bulk changes) |
| `portfolio_dashboard.html` | Interactive web dashboard |
| `signals/account_data.js` | Auto-generated—don't edit directly |
| `PORTFOLIO_STATUS.md` | Portfolio analysis summary |

---

## 🚀 Quick Start

### Open the Dashboard
```bash
# Just open the HTML file in your browser
open portfolio_dashboard.html

# Or view it directly - no server needed!
# File → Open (Ctrl+O / Cmd+O) → select portfolio_dashboard.html
```

The dashboard shows:
- **All Accounts** table with current/target exposure
- **Current Exposure %** — calculated from your actual holdings
- **Target Exposure %** — what you want (adjustable via slider)
- **Action** — how many shares to BUY/SELL to reach target

### Add a Transaction
```bash
# Add a BUY transaction
python3 manage_transactions.py add brokeragelink BUY 1718 81.00 "Rebalance to 45%"

# Add a SELL transaction
python3 manage_transactions.py add brokeragelink SELL 100 82.00 "Trim position"

# Update account balance (if it changed)
python3 manage_transactions.py update brokeragelink 355000

# Update current ETF price (for exposure calculations)
python3 manage_transactions.py price brokeragelink 82.00
```

### View Transaction History
```bash
python3 manage_transactions.py history brokeragelink
```

Output shows:
- Date, Action, Shares, Price
- Running exposure % at each trade
- Current state at bottom

### List All Accounts
```bash
python3 manage_transactions.py list
```

---

## 📊 Dashboard Features

### Current State (Left Side)
- **Current Shares**: Sum of all BUY minus SELL transactions
- **Current Exposure %**: (Current Shares × Price) / Balance × 100
- **Current Cash**: Balance - (Current Shares × Price)

### Target State (Right Side)
- **Target Shares**: floor(Balance × Target% / Price)
- **Target Exposure %**: Your goal (set at top: default 45%)
- **Target Cash**: How much cash after reaching target

### Action Column
- **BUY X**: You need to buy this many shares
- **SELL X**: You need to sell this many shares
- **HOLD**: Already at target exposure

---

## 🔄 Workflow After Trading

### After you execute trades:

1. **Record the trade in the system:**
   ```bash
   python3 manage_transactions.py add brokeragelink BUY 1718 81.00 "Rebalance"
   ```

2. **Sync to dashboard:**
   ```bash
   python3 sync_account_data.py
   ```

3. **Refresh the dashboard** (Cmd+R / Ctrl+R in browser)
   - Portfolio updates automatically
   - New current state is calculated
   - New action recommendations appear

---

## 📋 The Generic Formula

**This works for ANY account regardless of balance:**

```
Current Exposure % = (Current Shares × Current Price) / Account Balance × 100

Target Shares = floor(Account Balance × Target% / 100 / Current Price)

Action = Target Shares - Current Shares
```

**Example: BrokerageLink**
```
Balance: $339,903
Current: 170 shares × $81 = $13,770 → 4.1% exposure
Target:  floor($339,903 × 0.45 / $81) = 1,888 shares
Action:  1,888 - 170 = BUY 1,718 shares
```

**Example: Roth IRA (different balance)**
```
Balance: $81,420
Current: 18 shares × $81 = $1,458 → 1.8% exposure
Target:  floor($81,420 × 0.45 / $81) = 452 shares
Action:  452 - 18 = BUY 434 shares
```

The system scales automatically based on each account's balance.

---

## 🛠️ Advanced Usage

### Bulk Import Transactions
1. Export trades from your broker as CSV
2. Parse and insert manually using `manage_transactions.py add`
3. Or edit `account_transactions.json` directly (JSON format)
4. Run `python3 sync_account_data.py` to update dashboard

### Add New Account
Edit `account_transactions.json`:
```json
{
  "id": "my_new_account",
  "name": "New Account Name",
  "etf": "TQQQ",
  "current_balance": 50000,
  "initial_balance": 50000,
  "current_price": 81.00,
  "transactions": []
}
```

Then run:
```bash
python3 sync_account_data.py
```

### Change Target Exposure
Open the dashboard and use the **"New % Exposure"** input at top to change the target for all accounts. It recalculates instantly.

---

## 🐛 Troubleshooting

**Dashboard shows "Error: Failed to fetch"**
- This happens when `signals/account_data.js` isn't found
- Solution: Run `python3 sync_account_data.py`

**Dashboard shows old data**
- After adding/updating transactions, you need to sync
- Run: `python3 sync_account_data.py`
- Then refresh browser: Cmd+R / Ctrl+R

**Account not showing in dashboard**
- Make sure account has at least one transaction
- Accounts with 0 shares don't appear in the combined table

**Wrong exposure calculation**
- Verify `current_price` is up-to-date: `python3 manage_transactions.py list`
- Update if needed: `python3 manage_transactions.py price ACCOUNT_ID NEW_PRICE`

---

## 📈 Portfolio Summary (Current)

**Total Trading Accounts:**
- Balance: $455,105
- Current Exposure: 3.2% (216 shares)
- Target Exposure: 45% (2,527 shares)
- **Action: BUY 2,311 shares** (~$186k at $81)

**Breakdown by Account:**

| Account | Current | Target | Action |
|---------|---------|--------|--------|
| BrokerageLink | 170 | 1,888 | BUY 1,718 |
| Roth IRA | 18 | 452 | BUY 434 |
| HSA | 11 | 151 | BUY 140 |
| Cash Management | 17 | 36 | BUY 19 |

---

## ✨ Key Benefits

✅ **Generic:** Works for any account, any ETF, any balance
✅ **Accurate:** Based on actual transaction history, not assumptions
✅ **Automatic:** Exposure % calculated from real holdings
✅ **Scalable:** Add new accounts anytime
✅ **Simple:** CLI tools + HTML dashboard
✅ **Offline:** Everything runs locally, no internet needed
✅ **Editable:** JSON format, human-readable and easy to backup

---

## 📞 Support

For issues or questions:
1. Check `PORTFOLIO_STATUS.md` for detailed analysis
2. Review transaction history: `python3 manage_transactions.py history ACCOUNT_ID`
3. List all accounts: `python3 manage_transactions.py list`
4. Verify prices are current: Update with `price` command if needed
