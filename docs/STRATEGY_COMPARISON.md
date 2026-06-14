# Strategy Comparison — Backtest Results & Logic (2010–2026)

All strategies discussed, on one common date range (**2010-02-11 → 2026-06-12**), $100,000 start.
Reproduce any time with `python all_strategies_backtest.py` (pulls QQQ/TQQQ/QLD live from yfinance).

> **How to read this — bases & caveats (important):**
> - **v1 / v2** trade the **real TQQQ ETF** (its fees and volatility decay are already in the price). "After-cost" = margin financing on any exposure above 1.0× plus T-bill yield on idle cash.
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

**9. v2 defensive (3×)** — v1's regime gate **plus volatility targeting** on TQQQ: in BULL, exposure = `clip(0.45 / TQQQ_volatility, 0, 1.5)`. Delevers automatically into volatile crashes. `target_vol = 0.45` is the walk-forward-endorsed setting. **The all-round best of the leveraged strategies.**

**10. v2 aggressive (3×)** — Identical to v2 defensive but `target_vol = 0.75` (runs more leverage, avg ~1.26× TQQQ). More return, deeper drawdown — same Sharpe (it's purely a risk dial).

---

## Annual Returns (%)

| Year | QQQ B&H | TQQQ B&H | QQQ Gated | QLD Overlay | Binary 4/25 | Pyr 33/33/33 | Pyr 25/35/40 | v1 | v2 def | v2 aggr |
|------|--------:|---------:|----------:|------------:|------------:|-------------:|-------------:|----:|-------:|--------:|
| 2010 | 25.9 | 78.1 | 20.5 | 44.8 | 16.7 | 27.4 | 27.3 | 57.3 | 101.6 | 109.1 |
| 2011 | 3.5 | −8.0 | −4.8 | −14.9 | −9.9 | −2.6 | −7.9 | −26.4 | −15.3 | −36.4 |
| 2012 | 18.1 | 52.3 | 18.1 | 34.8 | 69.1 | 43.9 | 44.1 | 52.3 | 59.7 | 63.8 |
| 2013 | 36.6 | 139.7 | 36.6 | 82.1 | 45.6 | 67.3 | 70.3 | 139.7 | 143.5 | 245.4 |
| 2014 | 19.2 | 57.1 | 19.2 | 37.6 | 26.6 | 34.1 | 34.4 | 57.1 | 44.7 | 67.2 |
| 2015 | 9.4 | 17.2 | 9.4 | 13.8 | −35.5 | 1.7 | −4.1 | 17.2 | −4.0 | 8.2 |
| 2016 | 7.1 | 11.4 | 1.0 | 1.2 | 16.4 | −5.1 | −3.1 | −6.1 | −9.6 | −9.0 |
| 2017 | 32.7 | 118.1 | 32.7 | 70.3 | 49.2 | 65.1 | 69.1 | 118.1 | 179.6 | 206.5 |
| 2018 | −0.1 | −19.8 | 1.7 | −0.9 | −23.5 | 1.8 | −0.3 | −13.2 | −3.4 | −15.1 |
| 2019 | 39.0 | 133.8 | 33.3 | 62.5 | 125.4 | 90.8 | 96.1 | 108.3 | 81.0 | 135.6 |
| 2020 | 48.4 | 110.1 | 37.1 | 67.3 | 187.5 | 71.2 | 86.5 | 108.5 | 91.3 | 129.7 |
| 2021 | 27.4 | 83.0 | 27.4 | 49.6 | 48.5 | 11.3 | 13.5 | 83.0 | 62.9 | 89.6 |
| 2022 | −32.6 | −79.1 | −18.8 | −34.1 | −55.6 | −46.8 | −46.3 | −52.9 | −35.1 | −53.8 |
| 2023 | 54.9 | 198.0 | 43.4 | 90.4 | 96.7 | 97.6 | 100.5 | 139.4 | 116.8 | 192.8 |
| 2024 | 25.6 | 58.3 | 25.6 | 40.6 | 20.0 | 39.5 | 40.8 | 58.3 | 47.0 | 68.0 |
| 2025 | 20.8 | 34.4 | 15.6 | 19.1 | 64.3 | 52.0 | 54.7 | 26.0 | 24.6 | 18.8 |
| 2026* | 17.6 | 47.3 | 17.6 | 31.0 | 29.6 | 40.7 | 40.4 | 47.3 | 23.6 | 37.8 |

\*2026 is partial (through June 12).

---

## Summary ($100,000 start)

| Strategy | Leverage | Total | CAGR | Sharpe | Max DD | Final $ |
|----------|:--------:|------:|-----:|-------:|-------:|--------:|
| QQQ Buy & Hold | 1× | 1,803% | 19.8% | 0.98 | −35.1% | $1.90M |
| TQQQ Buy & Hold | 3× | 37,521% | 43.9% | 0.90 | −81.7% | $37.6M |
| QQQ Gated | 1× | 1,423% | 18.2% | **1.05** | **−22.8%** | $1.52M |
| QLD Overlay | 2× | 8,963% | 31.8% | 1.02 | −39.1% | $9.06M |
| Binary 4/25 | 3× | 5,937% | 28.6% | 0.84 | −66.9% | $6.04M |
| Pyramid 33/33/33 | 3× | 7,310% | 30.2% | 0.94 | −59.8% | $7.41M |
| Pyramid 25/35/40 | 3× | 8,180% | 31.1% | 0.95 | −59.9% | $8.28M |
| v1 (TQQQ) | 3× | 36,341% | 43.6% | 0.96 | −57.3% | $36.4M |
| **v2 defensive** | 3× | **40,413%** | **44.5%** | **1.03** | **−46.5%** | **$40.5M** |
| v2 aggressive | 3× | 122,841% | 54.7% | 1.00 | −62.3% | $122.9M |

---

## Key Takeaways

1. **Drawdown is driven by leverage, not cleverness.** The 1× strategies sit at −23% to −35%, the 2× at −39%, and every 3× strategy at −47% to −82%. No amount of signal design escapes this.

2. **v2 defensive is the best risk-adjusted leveraged strategy.** It has the **highest Sharpe (1.03)**, the **shallowest drawdown of the 3× group (−46.5%)**, *and* the highest after-cost return of the realistic 3× set. It strictly dominates v1 (better on every metric). Vol-targeting earns this by delevering into crashes.

3. **More return only comes from more risk.** v2 aggressive triples the money ($40M → $123M) but at the *same Sharpe* (1.00) and a deeper −62% drawdown. The walk-forward confirmed the extra return is pure leverage compensation, not skill.

4. **At low leverage, the regime gate costs return.** QQQ Gated and the QLD Overlay both *underperform* their buy-and-hold on total return — their value is risk reduction (higher Sharpe, lower drawdown), not extra money. The gate's return edge only appears at 3×, where avoiding crashes compounds enough to win.

5. **For Roth / HSA / 401k (no margin, no TQQQ):** the **QLD Overlay (2×)** is the recommended active vehicle (31.8% CAGR, −39% DD, Sharpe 1.02). But plain QLD buy & hold ends richer ($10.0M vs $9.06M) if you can hold through its −64% drawdown — the overlay is for those who'd otherwise panic-sell.

6. **Every one of these is a single-asset Nasdaq bet** with brutal drawdowns and 1.5–2.3 year underwater stretches. The numbers are one historical path, not a promise. Position-size to a drawdown you can actually survive without selling — that decision matters more than the choice of strategy.

---

*Generated from `all_strategies_backtest.py`. Strategy implementations live in: `tusharStrategyDev.py` (v1), `tushar_v2_backtest.py` / `tushar_v2_signal.py` (v2), `tushar_v2_qld_signal.py` (QLD), `qqq_pyramid_*` (pyramid/binary). Stress/validation: `tushar_v2_walkforward.py`, `tushar_v2_stresstest.py`.*
