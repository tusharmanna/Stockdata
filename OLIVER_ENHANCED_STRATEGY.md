# Oliver Enhanced Strategy — TQQQ

**Based on:** Oliver Kell's *Victory in Stock Trading* price cycle framework  
**Instrument:** TQQQ (3x leveraged Nasdaq ETF)  
**Signal source:** QQQ (tracks Nasdaq-100)  
**File:** `oliver_strategy.py --mode enhanced`

---

## Summary

Hold TQQQ during bull markets. Exit when QQQ suffers a major structural breakdown. Re-enter only when both the macro recovery and upside momentum confirm simultaneously.

| Metric | Result (2010–2026) |
|---|---|
| CAGR | **42.8%** |
| Max Drawdown | **-52.4%** |
| Total exits | **8** |
| Final value ($100k start) | **$34,007,940** |

*Benchmark: TQQQ Buy & Hold = 43.6% CAGR, -81.7% max DD*  
*Tushar v1 = 40.5% CAGR, -61.8% max DD*

---

## The Three Rules

### Rule 1 — EXIT

**Exit TQQQ immediately when:**

> QQQ closes more than **15%** below its **252-day rolling high**

This is a single-bar trigger — no consecutive day requirement. The moment QQQ crosses the 15% threshold, exit at the next available price.

**Why 15% and 252 days?**  
The 252-day window is one trading year — the longest reasonable lookback for a trend. A 15% pullback from the yearly high is the boundary between a normal correction and a structural breakdown. In practice this fires only during genuine bear markets (2022, rate-hike cycle) or sharp crashes (2020 COVID), not during normal bull-market volatility.

**What this avoids:**  
All the false exits that plagued the original Oliver modes. In 2013, 2019, 2021, and 2024 (slow grinding bull years), QQQ never fell 15% from its rolling high. The exit never fired. The strategy stayed in TQQQ for the full run.

---

### Rule 2 — RE-ENTRY

**Re-enter TQQQ only when both conditions are true on the same day:**

> **Condition A (Macro Recovery):** QQQ has closed within 15% of its 252-day high for 3 or more consecutive days

> **Condition B (Oliver Wedge Pop):** QQQ has closed above its 20-day EMA for 2 or more consecutive days

Both gates must be satisfied simultaneously before re-entering.

**Why two conditions?**

Condition A alone (the v1 re-entry rule) can fire during dead-cat bounces — a brief 3-day snap-back during a bear market where QQQ rallies but the downtrend resumes. Adding Condition B means QQQ must also be showing upside momentum (above the 20 EMA), which dead-cat bounces usually don't sustain.

Condition B alone (Oliver's Wedge Pop) is too aggressive in bear markets — QQQ can bounce above the 20 EMA for 2 days during a downtrend and then immediately resume falling. This is what caused 130–220 whipsaws in the original Oliver modes.

Together they require the market to have genuinely recovered from the drawdown (Condition A) and be showing real upside momentum (Condition B). In practice this means re-entry comes a few weeks into a genuine recovery — not at the absolute bottom, but early enough to capture most of the move.

---

### Rule 3 — EXTENSION COUNT (Informational)

Track how many times QQQ extends **3% or more above its 10-day EMA** during the current invested period:

- **1st extension:** Normal trend strength — hold
- **2nd extension:** Caution zone — consider taking partial profits
- **3rd extension:** Very late in the trend — be aggressive about taking profits

This does **not** trigger an exit. It is a warning system based on Oliver Kell's "Exhaustion Extension" concept. After each exit, the count resets to zero.

**The logic:** Each time price pushes far above the 10 EMA on momentum (euphoria), institutional players typically use that strength to distribute shares. The second extension is historically when the risk/reward shifts. You still hold, but you know you are in the mature phase of the move.

---

## How the Book Maps to This Strategy

Oliver Kell describes a five-stage price cycle:

```
Reversal Extension → Wedge Pop → EMA Crossback → Base n' Break → Exhaustion Extension
     (bottom)          (entry)    (first pullback)  (continuation)      (topping)
```

**Stage mapping for this strategy:**

| Book Stage | Strategy interpretation |
|---|---|
| Exhaustion Extension | Extension count 2+ → warning active |
| Wedge Drop | 15% below 252d high → EXIT (the true Wedge Drop, at macro scale) |
| Wedge Pop | QQQ recaptures 20 EMA for 2 days → RE-ENTRY condition B |
| EMA Crossback | QQQ dipping to/below 20 EMA in a bull market — **not an exit**, just normal noise |
| Base n' Break | Holding TQQQ while below the 2nd extension level |

**Key insight from the book:** The 20 EMA exit is valid for individual growth stocks where every EMA break is meaningful. For a 3x leveraged index ETF, the 20 EMA is crossed constantly in normal bull markets — these are EMA Crossbacks (buy zones in Kell's framework), not sell signals. This strategy applies Kell's intent at the correct timeframe for TQQQ.

---

## Trade History (2010–2026)

| Date | Action | TQQQ Price | Notes |
|---|---|---|---|
| Jun 30, 2010 | EXIT | $0.18 | |
| Jul 12, 2010 | ENTRY | $0.21 | |
| Aug 08, 2011 | EXIT | $0.28 | 2011 correction |
| Aug 30, 2011 | ENTRY | $0.34 | |
| Feb 08, 2016 | EXIT | $1.42 | Feb 2016 selloff |
| Feb 18, 2016 | ENTRY | $1.63 | |
| Dec 17, 2018 | EXIT | $4.78 | Q4 2018 crash |
| Jan 09, 2019 | ENTRY | $4.96 | |
| Mar 09, 2020 | EXIT | $7.31 | COVID crash |
| Apr 15, 2020 | ENTRY | $7.38 | V-recovery confirmed |
| Jan 27, 2022 | EXIT | $24.62 | Rate-hike cycle begins |
| Mar 21, 2022 | ENTRY | $25.21 | Brief recovery (whipsaw) |
| Apr 11, 2022 | EXIT | $23.00 | Downtrend resumes |
| Apr 03, 2023 | ENTRY | $13.55 | 2023 bull market confirmed |
| Apr 03, 2025 | EXIT | $24.98 | Tariff shock |
| Apr 28, 2025 | ENTRY | $26.72 | Recovery confirmed |

8 exits over 16 years.

---

## Annual Performance

| Year | TQQQ B&H | Tushar v1 | Oliver Enhanced | vs v1 |
|---|---|---|---|---|
| 2010 | +78.0% | +57.1% | +55.4% | -1.7% |
| 2011 | -8.0% | -26.4% | -25.1% | +1.3% |
| 2012 | +52.6% | +52.6% | +52.6% | +0.0% |
| 2013 | +139.4% | +139.4% | +139.4% | +0.0% |
| 2014 | +57.1% | +57.1% | +57.1% | +0.0% |
| 2015 | +17.2% | +17.2% | +17.2% | +0.0% |
| 2016 | +11.5% | -6.1% | -2.8% | +3.3% |
| 2017 | +117.8% | +117.8% | +117.8% | +0.0% |
| 2018 | -19.7% | -13.1% | -13.1% | +0.0% |
| 2019 | +133.9% | +108.3% | +108.3% | +0.0% |
| 2020 | +110.0% | +107.9% | +107.9% | +0.0% |
| 2021 | +83.0% | +83.0% | +83.0% | +0.0% |
| 2022 | -79.1% | -54.7% | **-43.4%** | **+11.3%** |
| 2023 | +198.0% | +82.7% | +82.7% | +0.0% |
| 2024 | +58.5% | +58.5% | +58.5% | +0.0% |
| 2025 | +34.5% | +25.6% | +25.6% | +0.0% |
| 2026 | +44.9% | +44.9% | +44.9% | +0.0% |
| **CAGR** | **43.6%** | **40.5%** | **42.8%** | **+2.3%** |
| Max DD | -81.7% | -61.8% | **-52.4%** | |

The strategy matches v1 in most years (same exit rule) and outperforms in years with sharp crashes and recoveries where the dual re-entry gate times re-entry better.

---

## Daily Usage

```bash
# Today's signal (enhanced mode is the default)
python oliver_strategy.py

# Full comparison vs Tushar v1 and TQQQ buy-and-hold
python oliver_strategy.py --compare --all

# Single year
python oliver_strategy.py --compare --year 2022
```

**Reading the daily signal output:**

- **252d High / pcthi**: Shows how far QQQ is from the exit trigger. A 15% margin means QQQ can fall 15% before exit fires.
- **Extension count**: 0–1 = normal. 2+ = profit-taking warning per Kell's framework.
- **HOLD TQQQ**: Stay in. Exit condition not met.
- **BUY TQQQ**: Both re-entry gates just fired. Enter at next open.
- **SELL TQQQ**: Exit condition fired. Exit at next open.

---

## Parameters (in `oliver_strategy.py`)

| Parameter | Default | Meaning |
|---|---|---|
| `SIGNAL_THRESHOLD` | 15.0% | pcthi exit threshold |
| `HIGH_PERIOD` | 252 | Days for rolling high |
| `V1_REENTRY_DAYS` | 3 | Days pcthi must stay < 15% for re-entry gate A |
| `REENTRY_DAYS` | 2 | Days above 20 EMA for re-entry gate B (Wedge Pop) |
| `EXT_THRESHOLD` | 3.0% | % above 10 EMA to count as an extension |

All parameters are at the top of `oliver_strategy.py`. Change `SIGNAL_THRESHOLD` to tighten or loosen the exit (lower = more sensitive, higher = fewer exits).
