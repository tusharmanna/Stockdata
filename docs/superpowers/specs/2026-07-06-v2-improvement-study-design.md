# Tushar v2 Improvement Study — Design

**Date:** 2026-07-06
**Goal:** Find changes that improve *out-of-sample risk-adjusted* returns (Sharpe, max DD)
over current v2 (`target_vol=0.45`, 20d rolling vol, cap 1.5), using the same honest
protocol that validated v2 itself. Return-only improvements (raising target_vol) are
explicitly out of scope — the walk-forward already showed that dial is Sharpe-neutral.

## Protocol (identical for every candidate)

- Fit any parameters on **2010–2018 only**; judge on **2019–2026** (matches
  `tushar_v2_walkforward.py`).
- After-cost returns (financing on exposure > 1.0, T-bill yield on idle cash),
  causal `shift(1)`, leverage cap 1.5.
- **Adoption bar:** OOS Sharpe must beat current v2's OOS Sharpe, and OOS max DD must
  not be more than ~2 pp deeper. Flat-across-params OOS results count as robust;
  peaky ones are rejected as overfit.

## Experiments

1. **Vol estimator** — replace the 20d rolling std with (a) EWMA (RiskMetrics-style,
   alpha≈0.06), (b) downside semi-volatility, (c) 10d/60d blend. Each estimator gets
   its own target grid on IS (scales differ); best-IS target judged OOS.
2. **CASH-regime defensive assets** — in CASH regime hold TLT, GLD, or 50/50 instead
   of T-bills. Bull-regime idle cash stays at T-bill.
3. **Graded regime** — replace the binary 15%-from-high cliff (with 3-day re-entry)
   with a linear ramp: full weight within X% of the 189d high, scaling to 0 at Y%.
   Grid X/Y on IS only.
4. **VIX crash filter** — scale exposure down when VIX term structure inverts
   (^VIX > ^VIX3M) and/or VIX exceeds a level threshold. Variants gridded on IS.

## Combination step

Candidates that individually clear the bar are then combined and re-validated on the
same IS/OOS split — improvements that work alone can cancel out together. Only after
a combined survivor emerges would `tushar_v2_signal.py` (and later the QLD variant)
be touched.

## Deliverable

`tushar_v2_improvement_study.py` — one script, reuses `_load` / `compute_signal_v1`
from `tusharStrategyDev.py`, prints an IS/OOS comparison table per experiment plus a
final verdict per candidate and for the combination.

## Results (2026-07-06 run)

Methodology note: the first run used raw-return Sharpe, which let T-bill carry on idle
cash masquerade as edge (every estimator's IS grid slammed to the lowest target).
Fixed to **excess-return Sharpe** (over T-bill) before drawing conclusions.

Baseline (bar): v2 current — OOS Sharpe 1.01, OOS max DD −43.3%.

| Experiment | Best variant | OOS Sharpe | OOS DD | Verdict |
|---|---|---|---|---|
| 1. Vol estimator | ewma / semi / blend | 0.92–0.98 | — | **FAIL** — none beat roll20 |
| 2. CASH defensive | GLD | 1.02 | −52.1% | **FAIL** — DD far past tolerance |
| 3. Graded regime | X=12% Y=25% | 0.94 | −48.8% | **FAIL** |
| 4. VIX filter | inv & VIX>25 → 0 | 1.01 | −43.0% | nominal PASS by <0.01 Sharpe |

**Conclusion: no adoption.** The lone "pass" (1 of 6 VIX variants, margin under 0.01
Sharpe, OOS CAGR actually lower than baseline) is multiple-comparisons noise, not edge.
The study confirms the walk-forward's original finding from the other direction:
v2 (regime gate + 20d vol-target) already sits at this system's risk-adjusted frontier.
More return requires accepting more drawdown (raise `TARGET_VOL`); more Sharpe would
require genuinely new, uncorrelated return sources — not better filtering of TQQQ.

`tushar_v2_signal.py` and the QLD variant remain unchanged.

## Expectations (stated up front to keep us honest)

- Vol estimator and VIX filter target the same effect (faster crash reaction); at most
  one likely survives combination.
- Defensive assets are the most plausible genuine Sharpe add (diversification), but
  2022 hurt bonds and stocks together.
- Graded regime is the most likely to die in walk-forward.
