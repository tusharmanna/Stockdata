# Whitelight Strategy

Trend-following system on 3x leveraged Nasdaq ETFs, reverse-engineered from the
Collective2 "Whitelight" trading record (88 trades, 2022–2026).

---

## Strategy Logic

| Attribute | Detail |
|---|---|
| Universe | TQQQ (ProShares UltraPro QQQ, 3x long) and SQQQ (ProShares UltraPro Short QQQ, 3x bearish) |
| Signal | QQQ close **above** MA10 → Long TQQQ. QQQ close **at or below** MA10 → Long SQQQ |
| Entry timing | Near market close, **3:45–4:00 PM ET**, on the day a signal flip is detected |
| Hold period | Until the signal flips again (days to weeks, signal-driven not time-driven) |
| Always invested | Always long one of the two ETFs — never in cash |

### Position Sizing

Size is driven by a **StageFactor** (0.0–1.0) computed from three inputs each day:

| Input | Definition |
|---|---|
| RSI_Today | 14-period Wilder RSI of QQQ |
| RSI_Average | Average RSI since the current trade entry date |
| PercentHigh | % that QQQ sits below its rolling 52-week high |

```
Result      = RSI_Today × (RSI_Today / RSI_Average)² × (100 - PercentHigh) / 100
StageFactor = Result / 100   (capped 0–1)
EffectiveCapital = YourCapital × 2 × StageFactor × RiskFactors
Shares      = floor(EffectiveCapital / ETF_price)
```

**What this means in practice:**

| Market condition | RSI | PercentHigh | StageFactor | Position at $3k |
|---|---|---|---|---|
| QQQ at 52-wk high, RSI > 70 | 75 | ~0% | 1.00 | ~$6,000 |
| Uptrend softening | 60 | 5% | ~0.52 | ~$3,100 |
| Weak / recovering (screenshot) | 55 | 13% | ~0.30 | ~$1,800 |
| QQQ below MA10 → SQQQ | 40 | 20% | ~0.14 | ~$840 |

Four additional **risk-reduction factors** (breakoutFailureFactor, currRSIBreakFactor,
currMADownFactor, currRSIROCFactor) multiply the StageFactor down when conditions
deteriorate (e.g. RSI < 40, QQQ below MA200). They are 1.00 in healthy markets.

> **Note:** The Result formula is a best-fit approximation from a single published
> data point (Result=30 when RSI=55.34, RSI_avg=67.87, PercentHigh=12.89). It
> produces values within ~2 points of the real strategy. The signal direction
> (TQQQ vs SQQQ) and flip timing are exact.

---

## Files

| File | Purpose |
|---|---|
| `whitelight_strategy.py` | Main script — downloads data, computes signal, prints output |
| `whitelight_signal.txt` | Machine-readable signal written after every run |
| `run_whitelight.bat` | Wrapper that runs the script, logs output, shows Windows notification |
| `setup_whitelight_schedule.ps1` | Registers the Task Scheduler job (run once as Admin) |

---

## Prerequisites

```bash
pip install yfinance pandas
```

Python 3.10+ required (uses `match`-style type hints).

---

## Running Manually

```bash
# Default: $10k reference capital, $3k your capital, MA10, 30-day table
python whitelight_strategy.py

# Show more history
python whitelight_strategy.py --lookback 60

# Set your actual capital (changes the "YOUR POSITION" block)
python whitelight_strategy.py --my-capital 5000

# Skip the historical trade log (faster output)
python whitelight_strategy.py --no-trade-log
```

Run at **3:45 PM ET on any weekday** to get that day's actionable signal before close.
Running earlier uses the previous day's close; that is still valid for planning.

---

## Automated Daily Run

The script is scheduled via Windows Task Scheduler to run at **3:45 PM ET, Mon–Fri**.

### One-time setup (PowerShell as Administrator)

```powershell
powershell -ExecutionPolicy Bypass -File E:\work\Stockdata\setup_whitelight_schedule.ps1
```

### Manual trigger / management

```bat
schtasks /run /tn WhitelightSignal          :: trigger now
schtasks /delete /tn WhitelightSignal /f    :: remove task
taskschd.msc                                :: open Task Scheduler UI
```

Logs are saved to `logs\whitelight_YYYY-MM-DD.log`.

A **Windows desktop notification** pops up after each run showing your share count
and whether there is a flip.

---

## Understanding the Output

### Signal Table
Shows the last N trading days. Columns:
- **RSI** — 14-period RSI of QQQ for that day
- **Signal** — TQQQ or SQQQ
- **ETF Px / Shares / ~Cost** — reference position (based on `--capital`, default $10k)
- **`<< FLIP`** — signal changed direction that day

### Extra Info block (Collective2 factors)
```
PercentHigh     : 0.09%   QQQ is 0.09% below its 52-week high
RSI_Today       : 74.92
RSI_Average     : 63.71   average RSI since current trade entry
Result          : 100     computed 0-100 score (~approx)
StageFactor     : 1.00    Result / 100
breakoutFailureFactor : 1.00   \
currRSIBreakFactor    : 1.00    > risk multipliers; reduce size in bad conditions
currMADownFactor      : 1.00    |
currRSIROCFactor      : 1.00   /
EffectiveStageFactor  : 1.00   final multiplier = StageFactor x all four factors
```

### YOUR POSITION block
```
*** YOUR POSITION  ($3,000 capital) ***
Effective Cap   : $6,000  (2x $3,000 x 1.00)
Shares to Buy   : 95 TQQQ
Estimated Cost  : $5,943
ACTION  -->  BUY 95 TQQQ near market close (3:45-4:00 PM ET)
```
This is the only number you need to act on. Change capital with `--my-capital`.

---

## Signal File (`whitelight_signal.txt`)

Written after every run. Key fields:

```
signal=TQQQ
etf_price=62.5600
is_flip=False
rsi_today=74.92
rsi_average=63.71
percent_high=0.09
result=100
stage_factor=1.00
effective_stage_factor=1.00
my_capital=3000.00
my_shares=95
my_estimated_cost=5943.20
generated_at=2026-04-27T15:45:01
```

`is_flip=True` means the signal switched today — exit the old position and enter the new one.

---

## Trade Management Rules

| Situation | Action |
|---|---|
| `is_flip=True` | Sell entire current position, buy new ETF at `my_shares` |
| `is_flip=False` | Already in the right ETF. If not yet in, enter at `my_shares` |
| StageFactor rises day-over-day | Consider adding shares to scale up to new share count |
| StageFactor falls day-over-day | Hold current shares (do not sell partial unless flip) |
| QQQ closes below MA10 (TQQQ signal) | Next run will show a flip to SQQQ |

---

## Changing Your Capital

```bash
python whitelight_strategy.py --my-capital 10000   # scale up to $10k
python whitelight_strategy.py --my-capital 5000    # mid-range trial
```

To make the change permanent for the scheduled task, edit `run_whitelight.bat`:
```bat
python "%~dp0whitelight_strategy.py" --my-capital 10000 ...
```
