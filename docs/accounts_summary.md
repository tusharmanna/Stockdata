# Account Summary & v2 Strategy Allocation

**Last Updated:** 2026-06-16  
**Snapshot Date:** 2026-06-16

---

## Account Overview

| Account | Balance | Strategy | Status |
|---------|---------|----------|--------|
| ROTH IRA | $81,420.01 | v2 QLD (78%) | Starting positions |
| Health Savings (HSA) | $27,256.63 | v2 QLD (78%) | Starting positions |
| BrokerageLink (Self-Directed) | $339,902.67 | v2 TQQQ (53%) | Starting positions |
| Colorado INTERMEDIATE 401K | $365,967.74 | TBD (restricted) | Pending fund options |
| Individual - TOD (Taxable) | $750.15 | Hold cash | Too small for trading |
| Other (various) | ~$7,031 | Hold cash | Minimal |
| **TOTAL** | **$822,328.20** | — | — |

---

## Starting Positions (Based on 2026-06-16 Prices)

### ROTH IRA ($81,420.01)

**Strategy:** v2 QLD (Volatility-targeted, no-margin for Roth compatibility)  
**Signal Today:** 78% in QLD | Action: SCALE DOWN

| Item | Value |
|------|-------|
| Target: QLD shares | 665 shares @ $95.46 = $63,480 |
| Target: Cash | $17,940 (22% in T-bills @ ~5%) |
| Current: QLD shares | 0 (starting) |
| Current: Cash | $81,420 |
| **Action** | **BUY 665 QLD shares** |

**Annual cash yield (on $17,940):** ~$897/year

---

### Health Savings Account ($27,256.63)

**Strategy:** v2 QLD (Volatility-targeted, no-margin)  
**Signal Today:** 78% in QLD | Action: SCALE DOWN

| Item | Value |
|------|-------|
| Target: QLD shares | 222 shares @ $95.46 = $21,192 |
| Target: Cash | $6,065 (22% in T-bills @ ~5%) |
| Current: QLD shares | 0 (starting) |
| Current: Cash | $27,257 |
| **Action** | **BUY 222 QLD shares** |

**Annual cash yield (on $6,065):** ~$303/year

---

### BrokerageLink Self-Directed ($339,902.67)

**Strategy:** v2 TQQQ (Volatility-targeted, 3× leverage with margin)  
**Signal Today:** Hold 0.53x TQQQ | Action: HOLD

| Item | Value |
|------|-------|
| Target: TQQQ shares | 2,254 shares @ $79.93 = $180,100 |
| Target: Cash | $159,803 (47% in T-bills @ ~5%) |
| Current: TQQQ shares | 0 (starting) |
| Current: Cash | $339,903 |
| **Action** | **BUY 2,254 TQQQ shares** |

**Annual cash yield (on $159,803):** ~$7,990/year

**Note:** v2 TQQQ strategy uses margin financing on the leveraged portion. Actual margin cost is ~5.5–6% post-2022 rates, applied to the borrowed portion (when exposure > 1.0).

---

### Colorado INTERMEDIATE 401K ($365,967.74)

**Status:** ⏸️ PENDING  
**Note:** Likely plan-restricted to indexed/managed funds. Check fund menu for Nasdaq-tilted options.

**Options if available:**
- If Nasdaq Index available → hold 100% (no vol-targeting, just growth)
- If QQQ/Nasdaq ETF available → follow v2 QLD signals (78% target)
- If restricted to mutual funds → discuss with plan admin

---

## Daily Signal Running

**Run both daily (e.g., at market close):**

```bash
python tushar_v2_signal.py        # TQQQ signal for BrokerageLink
python tushar_v2_qld_signal.py    # QLD signal for Roth/HSA
```

**Output:** Percentage targets (e.g., "78% QLD", "0.53x TQQQ")

**Manual conversion to shares:**
```
Shares to buy/sell = (Target % × Account Balance − Current Value) / Price
```

Or use a helper script (TBD).

---

## Expected Annual Returns & Volatility

Based on 2010–2026 backtest (defensive settings):

| Strategy | Account | CAGR | Sharpe | Max DD | Annual Yield (Cash) |
|----------|---------|------|--------|--------|-------------------|
| v2 QLD | Roth IRA | 30.6% | 0.99 | −39% | ~$897 |
| v2 QLD | HSA | 30.6% | 0.99 | −39% | ~$303 |
| v2 TQQQ | BrokerageLink | 44.5% | 1.03 | −46.5% | ~$7,990 |

**⚠️ Disclaimer:** Past backtest results (2010–2026, single path, in-sample). Real-world results depend on market conditions, taxes (BrokerageLink only), slippage, and ability to hold through drawdowns.

---

## Key Behaviors

- **Roth IRA & HSA:** Tax-free trading. Regime switches and vol-targeting incur no tax friction.
- **BrokerageLink:** Margin financing costs apply to leverage > 1.0. T-bill yield credited on idle cash (~5% currently).
- **Signal frequency:** Daily (run morning or after market close).
- **Rebalancing:** Automatic via signal; no minimum holding periods.
- **Drawdown risk:** v2 QLD max −39%, v2 TQQQ max −46.5%. Both are survivable if you don't panic-sell.

---

## Next Steps

1. ✅ Document accounts (this file)
2. ⏳ Set up trading at Fidelity/broker
3. ⏳ Buy starting positions (665 QLD + 222 QLD + 2,254 TQQQ)
4. ⏳ Park cash in 4-week T-bills (~$184k)
5. ⏳ Create signal-to-shares helper script
6. ⏳ Set up daily signal reminders (via task scheduler or manual)
7. ⏳ Monitor first 3 months for signal stability & rebalancing cadence
