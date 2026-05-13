# TusharStrategy

**A momentum-based TQQQ/CASH rotation strategy driven by QQQ's distance from its 1-year high.**

---

## What Is This Strategy?

TusharStrategy watches one number every day: how far has QQQ fallen from its 252-day (1-year) rolling high?

- If QQQ is **within 15%** of that high → the market is in a bull regime → hold **TQQQ**
- If QQQ is **more than 15%** below that high → the market is in a crash/bear regime → hold **CASH**

The core idea: TQQQ (3× leveraged QQQ) is very powerful during sustained uptrends but destroys capital quickly in prolonged drawdowns. By stepping to cash during deep corrections, you avoid the worst drawdowns while capturing the full uptrend with 3× leverage.

**No daily rebalancing.** When a BUY signal fires, you buy 100% of your capital into TQQQ and hold those fixed shares until a SELL signal fires. This lets winners run and avoids constant friction costs.

---

## Signal Logic

```
pctHigh = (QQQ 252-day rolling high  -  QQQ close) / QQQ 252-day rolling high  x  100

if pctHigh < 15%   =>  REGIME: BUY_TQQQ  (hold TQQQ)
if pctHigh >= 15%  =>  REGIME: CASH      (hold nothing)
```

**3-day re-entry confirmation:**
After a CASH period, the strategy does NOT immediately re-enter TQQQ when pctHigh dips back below 15%. It waits for 3 consecutive trading days below the 15% threshold before signaling BUY again.

Why: During a crash, QQQ bounces erratically around the 15% line. Without confirmation, you'd buy TQQQ on each bounce, only to sell again the next day. The 3-day filter prevents this whipsawing.

---

## Parameters

| Parameter         | Value   | Meaning                                      |
|-------------------|---------|----------------------------------------------|
| HIGH_PERIOD       | 252     | Rolling window for 1-year high (trading days)|
| SIGNAL_THRESHOLD  | 15.0%   | pctHigh threshold for regime switch          |
| REENTRY_DAYS      | 3       | Consecutive days below threshold for re-entry|
| Signal ticker     | QQQ     | What we measure the drawdown on              |
| Trade ticker      | TQQQ    | What we buy when in bull regime              |
| Bear holding      | CASH    | Nothing held during bear regime              |

---

## Daily Usage

### Step 1 — Run at 3:30 PM ET (while market is still open)

```bash
python tushar_strategy.py
```

A Task Scheduler task does this automatically — see **Automation** section below.

When run during market hours (9:30 AM – 4:00 PM ET), the script fetches the **live price** of QQQ and TQQQ via yfinance and computes the signal in real time. The output header shows `(LIVE)` and timestamps the fetch.

### Step 2 — Read the output

The output shows one of three actions:

```
ACTION:  *** BUY TQQQ ***        <- Regime just turned bullish
ACTION:  *** SELL ALL TQQQ ***   <- Regime just turned bearish
ACTION:  HOLD                    <- No change, do nothing
```

### Step 3 — Execute before 4:00 PM ET close (same day)

- **BUY**: Place a market order for the share count shown. It fills at or near the closing price.
- **SELL**: Place a market order to sell your entire TQQQ position before 4 PM. Move proceeds to cash.
- **HOLD**: Do nothing. Come back tomorrow.

> **Tip**: A market order placed by 3:55 PM ET almost always fills at the 4 PM closing price or very close to it. Limit orders near the current price also work but risk not filling if the stock moves away.

### Custom capital

By default the script shows share counts for **all accounts** defined in the `ACCOUNTS` list at the top of `tushar_strategy.py`. To override with a single capital amount:

```bash
python tushar_strategy.py --capital 94715
```

To update account balances, edit the `ACCOUNTS` list in `tushar_strategy.py` directly.

### Automation — Task Scheduler (one-time setup)

Run this once from PowerShell as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_tushar_schedule.ps1
```

This registers a task called `TusharStrategy330` that opens `run_tushar_330.bat` every weekday at 3:30 PM. A terminal window pops up showing the signal. Review the output and act before 4 PM.

**Your PC must be set to Eastern Time** (or adjust the trigger time in `setup_tushar_schedule.ps1` to match your local clock offset).

| Command | Purpose |
|---------|---------|
| `schtasks /run /tn "TusharStrategy330"` | Trigger manually |
| `schtasks /delete /tn "TusharStrategy330" /f` | Remove task |
| `taskschd.msc` | Open Task Scheduler UI |

---

## How to Interpret the Output

### Example BUY signal

```
=================================================================
  TUSHAR STRATEGY  --  Daily Signal  (LIVE)
  Monday, [date]  [03:31 PM ET]
=================================================================
  QQQ Price:        $  578.40  (live)
  252-Day High:     $  650.00
  % Below High:       11.0%   [###########----] (limit 15%)

  REGIME:  BUY TQQQ  (QQQ within 15% of 1-year high)
  Confirmation days below 15%: 3 / 3 needed

-----------------------------------------------------------------
  ACTION:  *** BUY TQQQ ***  (regime just changed to BUY_TQQQ)

  TQQQ Price:  $67.39/share  (live)

  Account                Acct#       Balance   Shares        Cost   Cash Left
  ---------------------------------------------------------------------------
  Interactive Brokers    7581     $   94,715    1,405  $   94,683  $    32.05
  Fidelity               4838     $  320,313    4,753  $  320,305  $     8.33
  Fidelity               2305     $   76,873    1,140  $   76,825  $    48.40
  Fidelity               4262     $   25,773      382  $   25,743  $    30.02
  Fidelity               8549     $    8,525      126  $    8,491  $    33.86
  Wells Fargo            1539     $   37,438      555  $   37,401  $    36.55
  Charles Schwab HSA     042      $   23,000      341  $   22,980  $    20.01
  Fidelity 401(k)        Color    $  348,926    5,177  $  348,878  $    47.97
  ---------------------------------------------------------------------------
  TOTAL                           $  935,563   13,879  $  935,306

  Execute NOW -- place a market order before 4:00 PM ET close.
=================================================================
```

**What each line means:**

- **QQQ Price (live)** — QQQ's last traded price fetched at the moment you ran the script
- **252-Day High** — the highest QQQ close over the past 252 trading days (~1 year)
- **% Below High** — how far QQQ is below that high. The `#` bar fills toward 15%. When it hits the edge, you're near the switch point.
- **Regime** — current market state: `BUY_TQQQ` = hold TQQQ; `CASH` = hold nothing.
- **Confirmation days** — consecutive days pctHigh has been below 15%. Must reach 3 to re-enter TQQQ after a cash period.
- **ACTION** — what to do before 4:00 PM ET close today
- **Share count** — exact shares to buy based on your capital and TQQQ's live price

### Example SELL signal

```
  REGIME:  CASH  (QQQ is 16.3% below 1-year high)

  ACTION:  *** SELL ALL TQQQ ***  (regime changed to CASH)

  Sell your entire TQQQ position NOW -- place a market order before 4:00 PM ET close.
  Move all proceeds to cash / money market.
  Wait for re-entry signal (3 consecutive days below 15%).
```

This means QQQ crossed below the 1-year high by more than 15% today. Place a market sell order before 4 PM and move to cash.

### Example HOLD in CASH with countdown

```
  REGIME:  CASH  (QQQ is 13.2% below 1-year high)
  ACTION:  HOLD CASH  --  Remain in cash, no trade needed.
  Re-entry: need 2 more day(s) below 15% for confirmation.
```

QQQ is back below 15% but the 3-day counter isn't full yet. Stay in cash, check again tomorrow.

### Recent history table

The last 7 trading days are always shown at the bottom:

```
  Recent pctHi history (last 7 trading days):
  Date         QQQ    pctHi   Regime       Action
  -------------------------------------------------------
  2026-04-27  664.23    0.0%  BUY_TQQQ     HOLD
  2026-04-28  657.55    1.0%  BUY_TQQQ     HOLD
  2026-04-29  661.57    0.4%  BUY_TQQQ     HOLD
  2026-04-30  667.74    0.0%  BUY_TQQQ     HOLD
  2026-05-01  674.15    0.0%  BUY_TQQQ     HOLD
  2026-05-04  672.88    0.2%  BUY_TQQQ     HOLD
  2026-05-05  681.61    0.0%  BUY_TQQQ     HOLD <-- TODAY
```

The last row is today's close. QQQ hit a new 1-year high on May 5, 2026 — pctHigh = 0.0%, firmly in BUY_TQQQ regime.

---

## Running a Backtest

### Current year

```bash
python tushar_strategy.py --backtest
```

### Specific year

```bash
python tushar_strategy.py --backtest --year 2024
```

### All years (2016 to present)

```bash
python tushar_strategy.py --backtest --all
```

The backtest table shows monthly % returns for QQQ buy-and-hold vs TusharStrategy vs the Collective2 reference portfolio (C2 Target). The annual summary at the bottom shows Total % and CAGR — no dollar amounts.

---

## Historical Performance Summary

Starting capital: $100,000. Results are from a simulation using split-adjusted yfinance data (`python tushar_strategy.py --backtest --all`).

| Year  | QQQ B&H | TusharStrategy | C2 Target |
|-------|---------|----------------|-----------|
| 2016  | +7.1%   | -6.1%          | N/A       |
| 2017  | +32.7%  | +117.8%        | N/A       |
| 2018  | -0.2%   | -13.1%         | N/A       |
| 2019  | +39.0%  | +108.3%        | N/A       |
| 2020  | +48.2%  | +107.9%        | N/A       |
| 2021  | +27.6%  | +83.0%         | N/A       |
| 2022  | -32.5%  | -54.7%         | N/A       |
| 2023  | +54.7%  | +82.7%         | +77.0%    |
| 2024  | +25.7%  | +58.5%         | +9.9%     |
| 2025  | +20.8%  | +25.6%         | +38.3%    |
| 2026* | +11.2%  | +28.0%         | +10.2%    |

*2026 is a partial year through May.

**10-year totals from $100k (2016-2026):**
- QQQ buy-and-hold: +557% total, CAGR +20.0%
- TusharStrategy: +2872% total, CAGR +38.8%
- Annual CAGR edge over QQQ: ~19 percentage points per year on average

> **Note on 2022**: Strategy was in TQQQ through Jan–Mar (QQQ was less than 15% below its 252-day high), then moved to cash in April and held cash for the rest of the year. The -54.7% loss came entirely from those first three months.

---

## Why It Works

1. **TQQQ amplifies trends** — 3× leverage is extremely powerful when QQQ is in a sustained uptrend. Capturing most of the bull market years with 3× leverage builds wealth very fast.

2. **Cash prevents ruin** — TQQQ can lose 50-70% in a single bear market. The 15% threshold gives enough early warning to exit before the worst damage. In 2022, the signal triggered in April; after that, TusharStrategy held cash the entire rest of the year while QQQ fell another 20%+.

3. **Fixed shares, not fixed %** — When you buy a fixed number of shares and hold, your effective % exposure grows as price rises (concentration effect). This means in months like November 2024 you automatically have more shares worth more money, amplifying gains without any action.

4. **3-day filter** — Eliminates false re-entries during crash bounces. The April 2025 Liberation Day crash is a perfect example: QQQ bounced repeatedly around the 15% line. Without the filter, you'd re-enter during the bounce and sell during each dip, losing 25%+. With the filter, you stay in cash through the whole volatile period.

---

## Why This Does Not Exactly Match C2 Returns

The Collective2 "Whitelight" strategy uses a different signal (EMA crossover, more reactive) and sometimes holds SQQQ in bear mode. Month-by-month it can differ significantly:

- **June 2024**: C2 went bearish (SQQQ), earned +1.7%. TusharStrategy stayed in TQQQ, earned +18.5%.
- **Nov 2024**: C2 held SQQQ through the post-election rally, lost -9.1%. TusharStrategy held TQQQ, earned +5.5%.
- **March 2025**: C2 target -21.2% requires SF > 1.0 (only possible with concentrated fixed-share positions). Our model earned -23.3% (still in TQQQ for the full month).
- **April 2025**: C2 somehow earned +2.6% by timing SQQQ correctly before Liberation Day. End-of-day signals always enter SQQQ too late to capture this.

The 2024 full-year divergence is the starkest: TusharStrategy +58.5% vs C2 +9.9%. The EMA signal caused C2 to miss the biggest TQQQ months.

---

## Risks and Limitations

**What can go wrong:**

1. **Slow-motion bear markets** — If QQQ drops gradually, staying in TQQQ while it falls toward the 15% threshold will cost money. The strategy exits late in slow-moving corrections.

2. **V-shaped crashes** — Very fast crashes followed by fast recoveries (e.g., March 2020 COVID) may cause you to sell near the bottom and miss the recovery. The 3-day filter actually helps here.

3. **TQQQ tracking error** — TQQQ rebalances daily, which causes volatility decay. In high-volatility sideways markets, TQQQ can underperform even when QQQ goes nowhere.

4. **Split-adjusted history** — TQQQ had a 2:1 forward split in November 2025. Historical prices are halved accordingly. The % returns are unchanged, but share counts and per-share prices in old backtest runs will look different from what you'd have traded at the time.

5. **Live price vs actual close** — At 3:30 PM the market has 30 minutes left. The live price used for the signal may differ from the 4 PM close. A BUY or SELL signal at 3:30 PM could theoretically reverse by 4 PM if QQQ moves sharply in the last 30 minutes. This is rare but possible near the 15% boundary.

**Limitations of the backtest:**
- Does not model commissions (minimal impact with modern brokers)
- Does not model slippage (shares are filled at closing price of the signal day)
- The 252-day warmup period (full year of data needed before first reliable signal) means the 2016 results use a 252-day window starting Jan 2015

---

## Files Reference

| File                        | Purpose                                              |
|-----------------------------|------------------------------------------------------|
| `tushar_strategy.py`        | **Daily signal + backtest** — core script            |
| `run_tushar_330.bat`        | Launcher opened by Task Scheduler at 3:30 PM ET     |
| `setup_tushar_schedule.ps1` | One-time Task Scheduler registration (run as Admin) |
| `backtest_tqqq_strategy.py` | TQQQ Strategy with daily ADX-scaled rebalancing      |
| `strategy_comparison.py`    | 4-column side-by-side: QQQ, TQQQ Strat, TusharStrategy, C2 |
| `_run_10yr.py`              | Full 10-year backtest (2016-present) single table    |

---

## Quick Reference Card

```
Every weekday at 3:30 PM ET  (task runs automatically via Task Scheduler):

  python tushar_strategy.py

BUY  ->  Buy TQQQ NOW -- market order before 4:00 PM ET  (use share count shown)
SELL ->  Sell all TQQQ NOW -- market order before 4:00 PM ET; move to cash
HOLD ->  Do nothing

If HOLD CASH, note the countdown: "need N more day(s) below 15%"
When it reaches 0, that day's run will print BUY.
```

---

## Account Balances (as of May 2026)

| Institution            | Account / Type                      | Balance    |
|------------------------|-------------------------------------|------------|
| Interactive Brokers    | 7581 — **Trading (TusharStrategy)** | $94,715    |
| Fidelity Investments   | 401(k) — Color Intermediate         | $348,926   |
| Fidelity Investments   | 4838                                | $320,313   |
| Fidelity Investments   | 2305                                | $76,873    |
| Fidelity Investments   | 4262                                | $25,773    |
| Fidelity Investments   | 8549                                | $8,525     |
| Fidelity Investments   | 2029                                | $525       |
| Wells Fargo            | 1539                                | $37,438    |
| Charles Schwab         | HSA Brokerage (042)                 | $23,000    |
| Optum                  | HSA (5340)                          | $21,000    |
| my529                  | 7208 — Tushar                       | $3,880     |
| my529                  | 7209 — Shreyaan                     | $2,339     |
| **Total**              |                                     | **$962,307** |

> TusharStrategy trades from the **Interactive Brokers** account ($94,715).
> Use `python tushar_strategy.py --capital 94715` to size positions correctly.
