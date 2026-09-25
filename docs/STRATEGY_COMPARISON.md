# Strategy Comparison — Backtest Results & Logic (2010–2026)

All strategies discussed, on one common date range (**2010-02-11 → 2026-08-13**), $100,000 start.
Reproduce any time with `python all_strategies_backtest.py` (pulls QQQ/TQQQ/QLD live from yfinance).

> **How to read this — bases & caveats (important):**
> - **v1 / v2** trade the **real TQQQ ETF** (its fees and volatility decay are already in the price). Production v2 is capped at 1.0× account equity; "after-cost" credits T-bill yield on idle cash.
> - **Binary / Pyramid** use **3× daily-rebalanced QQQ** (idealized — *slightly optimistic* vs a real 3× ETF, no financing modeled). These match the committed pyramid/crossover scripts.
> - **QLD Overlay** trades the **real QLD ETF (2×)**, capped at 100% of cash (no margin), plus cash yield.
> - **QQQ Gated** trades **real QQQ (1×)** plus cash yield.
> - Because v1/v2 use a real ETF and Binary/Pyramid use idealized 3×, the two families aren't *perfectly* comparable — the idealized ones flatter by ~1–2%/yr.
> - **Everything is single-asset, single-path, in-sample.** Past results are not a forecast. Taxes and slippage are not modeled (though Roth/HSA/401k are tax-free, which helps the gated/overlay variants).

---

## The shared building block: the v1 regime gate

Several strategies reuse one idea — a **regime filter** that decides "risk-on" vs "risk-off":

> Track QQQ's distance below its **rolling 189-day high**.
> - Within **15%** of that high → **BULL** (risk-on)
> - More than 15% below → **CASH** (risk-off)
> - Re-entry requires **3 consecutive days** back under the 15% line (filters whipsaws).

Over 2010–2026 this gate is in BULL ~93% of the time — it isn't a frequent trader, it just steps aside in the worst stretches.

---

## Strategy Logic (one paragraph each)

**1. QQQ Buy & Hold (1×)** — Own the Nasdaq-100, never sell. The baseline everything else must beat.

**2. TQQQ Buy & Hold (3×)** — Own the 3× leveraged Nasdaq-100 ETF, never sell. Maximum exposure, maximum pain — shown to bound the "pure leverage" case.

**3. QQQ Gated (1×)** — Apply the v1 regime gate to plain QQQ: hold 100% QQQ in BULL, move to cash (earning T-bills) in CASH. No leverage. Purpose: reduce drawdown.

**4. QLD Overlay (2×)** — The v1 regime gate **plus volatility targeting** on QLD (2× Nasdaq-100), capped at 100% of cash (no margin — works in Roth/HSA). In BULL, hold `clip(0.45 / QLD_volatility, 0, 1.0)` of the account; delever when QLD gets choppy. The recommended no-margin retirement vehicle.

**5. Binary 4/25 Crossover (3×)** — Pure trend signal, no regime gate: hold 3× when the 4-day MA is above the 25-day MA, else cash. All-in / all-out.

**6. Pyramid 33/33/33 (3×)** — Scale a 3× position in equal thirds as three bullish tiers turn true: T1 = Close > MA3, T2 = Close > MA35, T3 = MA3 > MA35. Position = (tiers true)/3 → 0/33/67/100%. Reduces whipsaw vs the binary by entering/exiting in stages.

**7. Pyramid 25/35/40 (3×)** — Same three tiers, but weighted toward the most-confirmed signal: T1 = **25%**, T2 = **35%**, T3 (the crossover) = **40%**. Puts less weight on the noisy fast tier. Best-returning pyramid variant.

**8. v1 (3× TQQQ)** — The original "Tushar strategy": the v1 regime gate driving **real TQQQ** — hold TQQQ in BULL, cash in CASH. Aggressive single-regime bet; ~93% just holding TQQQ.

**9. v2 defensive (3×)** — v1's regime gate **plus volatility targeting** on TQQQ: in BULL, exposure = `clip(0.45 / TQQQ_volatility, 0, 1.0)`. Delevers automatically into volatile crashes and does not add margin on top of TQQQ. `target_vol = 0.45` is the defensive setting.

**10. v2 aggressive (3×)** — Identical to v2 defensive but `target_vol = 0.75`, still capped at 100% TQQQ. More return and deeper drawdown; the cap prevents margin on top of the fund.

---

## Annual Returns (%)

| Year | QQQ B&H | TQQQ B&H | QQQ Gated | QLD Overlay | Binary 4/25 | Pyr 33/33/33 | Pyr 25/35/40 | v1 | v2 def | v2 aggr |
|------|--------:|---------:|----------:|------------:|------------:|-------------:|-------------:|----:|-------:|--------:|
| 2010 | 25.9 | 78.1 | 20.5 | 44.8 | 16.7 | 27.4 | 27.3 | 57.3 | 71.4 | 65.2 |
| 2011 | 3.5 | −8.0 | −4.8 | −14.9 | −9.9 | −2.6 | −7.9 | −26.4 | −17.8 | −28.0 |
| 2012 | 18.1 | 52.3 | 18.1 | 34.8 | 69.1 | 43.9 | 44.1 | 52.3 | 45.5 | 52.3 |
| 2013 | 36.6 | 139.7 | 36.6 | 82.1 | 45.6 | 67.3 | 70.3 | 139.7 | 131.7 | 139.7 |
| 2014 | 19.2 | 57.1 | 19.2 | 37.6 | 26.6 | 34.1 | 34.4 | 57.1 | 45.1 | 57.1 |
| 2015 | 9.4 | 17.2 | 9.4 | 13.8 | −35.5 | 1.7 | −4.1 | 17.2 | 9.4 | 16.9 |
| 2016 | 7.1 | 11.4 | 1.0 | 1.2 | 16.4 | −5.1 | −3.1 | −6.1 | −1.0 | −3.1 |
| 2017 | 32.7 | 118.1 | 32.7 | 70.3 | 49.2 | 65.1 | 69.1 | 118.1 | 117.4 | 118.1 |
| 2018 | −0.1 | −19.8 | 1.7 | −0.9 | −23.5 | 1.6 | −0.4 | −13.2 | −3.0 | −9.3 |
| 2019 | 39.0 | 133.8 | 33.3 | 62.5 | 125.4 | 90.8 | 96.1 | 108.3 | 79.1 | 104.1 |
| 2020 | 48.4 | 110.1 | 37.1 | 67.3 | 187.5 | 71.2 | 86.5 | 108.5 | 80.6 | 111.8 |
| 2021 | 27.4 | 83.0 | 27.4 | 49.6 | 48.5 | 11.3 | 13.5 | 83.0 | 57.5 | 79.6 |
| 2022 | −32.6 | −79.1 | −18.8 | −34.1 | −55.6 | −46.8 | −46.3 | −52.9 | −35.1 | −50.3 |
| 2023 | 54.9 | 198.0 | 43.4 | 90.4 | 96.7 | 97.6 | 100.5 | 139.4 | 109.9 | 140.5 |
| 2024 | 25.6 | 58.3 | 25.6 | 40.6 | 20.0 | 39.2 | 40.6 | 58.3 | 49.7 | 54.3 |
| 2025 | 20.8 | 34.4 | 15.6 | 19.1 | 64.3 | 52.0 | 54.7 | 26.0 | 20.8 | 21.2 |
| 2026* | 19.5 | 46.9 | 19.5 | 34.8 | 21.6 | 23.6 | 24.9 | 46.9 | 29.9 | 50.6 |

\*2026 is partial (through August 13).

---

## Summary ($100,000 start)

| Strategy | Leverage | Total | CAGR | Sharpe | Max DD | Final $ |
|----------|:--------:|------:|-----:|-------:|-------:|--------:|
| QQQ Buy & Hold | 1× | 1,834% | 19.7% | 0.97 | −35.1% | $1.93M |
| TQQQ Buy & Hold | 3× | 37,428% | 43.3% | 0.90 | −81.7% | $37.5M |
| QQQ Gated | 1× | 1,448% | 18.1% | **1.04** | **−22.8%** | $1.55M |
| QLD Overlay | 2× | 9,229% | 31.7% | 1.01 | −39.1% | $9.33M |
| Binary 4/25 | 3× | 5,564% | 27.8% | 0.83 | −66.9% | $5.66M |
| Pyramid 33/33/33 | 3× | 6,386% | 28.8% | 0.91 | −59.8% | $6.49M |
| Pyramid 25/35/40 | 3× | 7,250% | 29.8% | 0.92 | −59.9% | $7.35M |
| v1 (TQQQ) | 3× | 36,251% | 43.0% | 0.95 | −57.3% | $36.4M |
| **v2 defensive** | 3× | **25,565%** | **40.0%** | **1.03** | **−42.5%** | **$25.7M** |
| v2 aggressive | 3× | 39,859% | 43.9% | 0.98 | −55.2% | $40.0M |

---

## Key Takeaways

1. **Drawdown is driven by leverage, not cleverness.** The 1× strategies sit at −23% to −35%, the 2× at −39%, and every 3× strategy at −47% to −82%. No amount of signal design escapes this.

2. **v2 defensive is the best risk-adjusted leveraged strategy.** It has the **highest Sharpe (1.03)** and the **shallowest drawdown of the 3× group (−42.5%)**. It gives up CAGR versus v1 in exchange for much lower drawdown and no account-level margin.

3. **More return only comes from more risk.** Raising the target from 0.45 to 0.75 increases CAGR from 40.0% to 43.9% while worsening drawdown from −42.5% to −55.2%. The cap remains 1.0×, so the change comes from staying fully invested more often, not borrowing.

4. **At low leverage, the regime gate costs return.** QQQ Gated and the QLD Overlay both *underperform* their buy-and-hold on total return — their value is risk reduction (higher Sharpe, lower drawdown), not extra money. The gate's return edge only appears at 3×, where avoiding crashes compounds enough to win.

5. **For Roth / HSA / 401k (no margin, no TQQQ):** the **QLD Overlay (2×)** is the recommended active vehicle (31.8% CAGR, −39% DD, Sharpe 1.02). But plain QLD buy & hold ends richer ($10.0M vs $9.06M) if you can hold through its −64% drawdown — the overlay is for those who'd otherwise panic-sell.

6. **Every one of these is a single-asset Nasdaq bet** with brutal drawdowns and 1.5–2.3 year underwater stretches. The numbers are one historical path, not a promise. Position-size to a drawdown you can actually survive without selling — that decision matters more than the choice of strategy.

---

*Generated from `all_strategies_backtest.py`. Strategy implementations live in: `tusharStrategyDev.py` (v1), `tushar_v2_backtest.py` / `tushar_v2_signal.py` (v2), `tushar_v2_qld_signal.py` (QLD), `qqq_pyramid_*` (pyramid/binary). Stress/validation: `tushar_v2_walkforward.py`, `tushar_v2_stresstest.py`.*
