# V2.1 volatility-strategy research

Status: **shadow only; production V2 is unchanged**. Results use market data
through 2026-08-14.

## Decision

No tested rule produced both maximum return and minimum drawdown; those goals
conflict. The balanced V2.1 candidate reduced observed drawdown, but its advantage
was not stable enough to replace production V2. It is therefore implemented only
as an isolated shadow signal.

| Test | Production V2 | Balanced V2.1 |
|---|---:|---:|
| Actual TQQQ CAGR, 2010-present | 38.8% | 34.5% |
| Actual TQQQ max drawdown | -42.8% | -37.4% |
| Actual TQQQ Sharpe | 0.97 | 0.96 |
| 1999-present synthetic stress max drawdown | -54.2% | -47.4% |
| 2019-present CAGR | 43.2% | 39.3% |
| 2019-present max drawdown | -42.3% | -36.4% |
| Turnover per year | 3.5x | 4.1x |

The fixed finalist used a 40% volatility target, the greater of 20-day total
volatility and normalized 20-day downside volatility, a 3-point rebalance band,
and a five-day half-exposure cooldown after QQQ loses at least 8% over five days.
The 189-day/15% regime gate, three-day re-entry, and 1.0x cap are unchanged.

## Robustness findings

- At a one-day execution lag and 2-10 bp trading cost, V2.1 drawdown was about
  -37.4% to -37.7%. At a two-day lag it worsened to about -41.1% to -41.4%.
- In 2,000 paired 20-day block-bootstrap trials, the median CAGR difference was
  -4.2 points and median drawdown improvement was 4.4 points. Only 25.1% of trials
  jointly retained CAGR within five points, improved drawdown by four points, and
  improved Calmar ratio. This is below the promotion bar.
- Anchored train-only selection from 2015-present produced 32.9% CAGR, 0.88 Sharpe,
  and -38.9% drawdown versus 35.8%, 0.90, and -42.3% for baseline V2.
- Under the conservative annual tax stress, balanced V2.1 CAGR was 25.9% at 24%,
  22.9% at 32%, and 20.0% at 40% tax rates. This is a stress approximation, not a
  tax-lot calculation or forecast.
- On the latest bar, baseline target exposure was 0.64x and V2.1 was 0.55x. For an
  instantaneous approximate TQQQ loss of 45%, those exposures imply first-order
  portfolio losses of roughly 28.7% and 24.6%, before gaps, tracking differences,
  or rebalancing.

## Files and commands

- `v2_1_research.py`: causal candidate research, strict acceptance checks, Pareto
  frontier, extended proxy, costs, cash yield, and tax stress.
- `v2_1_validate.py`: fixed-finalist execution, regime, bootstrap, tax, and sudden-
  gap validation.
- `v2_1_walkforward.py`: anchored train-only selection followed by two-year tests.
- `v2_1_shadow_signal.py`: side-by-side daily signal. It is not called by the daily
  production runner and cannot alter orders or account targets.
- `test_v2_1_research.py`: deterministic causality and behavior tests.

Run the shadow signal without writing:

```bash
python v2_1_shadow_signal.py
```

Append or replace that market day's research row:

```bash
python v2_1_shadow_signal.py --log
```

Production promotion should require genuinely unseen shadow history and another
predeclared review. A minimum of six months is useful operationally; twelve months
or a meaningful volatility event provides stronger evidence. Do not select a new
candidate repeatedly from the same historical sample.
