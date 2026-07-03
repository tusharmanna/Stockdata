# Portfolio Status & Exposure Analysis

**Last Updated:** 07/02/2026
**Current TQQQ Price:** $81.00
**Target Exposure:** 45%

---

## Current Portfolio Summary

| Account | ETF | Balance | Current Shares | Current Exposure | Target Shares | Action |
|---------|-----|---------|-----------------|-----------------|----------------|--------|
| BrokerageLink | TQQQ | $339,903 | 170 | 4.1% | 1,888 | **BUY 1,718** |
| Roth IRA | TQQQ | $81,420 | 18 | 1.8% | 452 | **BUY 434** |
| HSA | TQQQ | $27,257 | 11 | 3.3% | 151 | **BUY 140** |
| Cash Management (TOD) | TQQQ | $6,525 | 17 | 21.1% | 36 | **BUY 19** |
| **TOTAL (Trading)** | | **$455,105** | **216** | **3.2%** | **2,527** | **BUY 2,311** |

---

## Detailed Account Analysis

### BrokerageLink (TQQQ)
**Account Balance:** $339,903
**Current Holdings:** 170 shares × $81 = $13,770 (4.1% exposure)

**Transaction History:**
- 2024-01-15: BUY 100 @ $75.50
- 2024-02-10: SELL 15 @ $78.00
- 2024-06-24: BUY 100 @ $72.92
- 2024-06-30: SELL 15 @ $81.00

**To reach 45% exposure:**
- Target Holdings Value: $339,903 × 0.45 = $152,956
- Target Shares: floor($152,956 / $81) = 1,888 shares
- **Action: BUY 1,718 shares**
- Cost: 1,718 × $81 = $139,158
- Cash Released: $139,158

---

### Roth IRA (TQQQ)
**Account Balance:** $81,420
**Current Holdings:** 18 shares × $81 = $1,458 (1.8% exposure)

**Transaction History:**
- 2024-06-24: BUY 20 @ $72.95
- 2024-06-30: SELL 2 @ $81.00

**To reach 45% exposure:**
- Target Shares: floor($81,420 × 0.45 / $81) = 452 shares
- **Action: BUY 434 shares**
- Cost: 434 × $81 = $35,154

---

### HSA
**Account Balance:** $27,257
**Current Holdings:** 11 shares × $81 = $891 (3.3% exposure)

**Transaction History:**
- 2024-06-24: BUY 14 @ $72.81
- 2024-06-30: SELL 3 @ $81.00

**To reach 45% exposure:**
- Target Shares: floor($27,257 × 0.45 / $81) = 151 shares
- **Action: BUY 140 shares**
- Cost: 140 × $81 = $11,340

---

### Cash Management (TOD)
**Account Balance:** $6,525
**Current Holdings:** 17 shares × $81 = $1,377 (21.1% exposure)

**Transaction History:**
- 2024-06-24: BUY 19 @ $72.73
- 2024-06-30: SELL 2 @ $81.00

**To reach 45% exposure:**
- Target Shares: floor($6,525 × 0.45 / $81) = 36 shares
- **Action: BUY 19 shares**
- Cost: 19 × $81 = $1,539

---

## Generic Exposure Formula

For **any account**, the calculation is:

```
Current Exposure % = (Current Shares × Current Price) / Account Balance × 100

Target Shares = floor(Account Balance × Target% / 100) / Current Price)

Action = Target Shares - Current Shares
```

**Example:** BrokerageLink at 45%
```
Current: (170 × $81) / $339,903 × 100 = 4.1%
Target:  floor($339,903 × 0.45 / $81) = floor(1,888.1) = 1,888 shares
Action:  1,888 - 170 = BUY 1,718 shares
```

---

## How to Update This System

### Adding a Transaction
```bash
python3 manage_transactions.py add brokeragelink BUY 1718 81.00 "Rebalance to 45%"
```

### Updating Account Balance
```bash
python3 manage_transactions.py update brokeragelink 339903
```

### Updating Current Price
```bash
python3 manage_transactions.py price brokeragelink 81.00
```

### Viewing Account History
```bash
python3 manage_transactions.py history brokeragelink
```

### Listing All Accounts
```bash
python3 manage_transactions.py list
```

---

## Key Insights

1. **Current Portfolio:** Significantly underexposed at 3.2% (target 45%)
2. **All accounts need BUY orders** to reach 45% target
3. **Total capital needed:** ~$186,191 across all trading accounts
4. **System works for any balance:** Each account calculates independently based on its balance and current holdings

---

## Dashboard Usage

Open `portfolio_dashboard.html` in your browser to:
- View all accounts in a table
- See current vs target exposure
- Adjust target exposure percentage dynamically
- View recent trading history
