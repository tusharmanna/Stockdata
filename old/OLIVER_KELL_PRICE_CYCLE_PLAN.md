# Oliver Kell Price Cycle — Strategy Reference Plan
**Source:** *Victory in Stock Trading* by Oliver Kell (2020 US Investing Champion, +941%)  
**Purpose:** Reference document for building a TQQQ strategy using Kell's price cycle framework

---

## Core Tools / Indicators

| Tool | Setting | Role |
|---|---|---|
| EMA 10 | All timeframes | Primary trailing stop; support/resistance |
| EMA 20 | All timeframes | Secondary trailing stop; key regime line |
| SMA 50 | Daily | Major intermediate support |
| SMA 200 | Daily | Long-term trend filter |
| Volume | Daily | Confirms institutional activity ("Bull Snorts" = massive relative volume) |
| Multiple Timeframes | 5min / 15min / 1hr / Daily / Weekly / Monthly | Higher TF sets direction; lower TF sets entry risk |

**Key principle:** Higher timeframe sets the trade direction and context. Lower timeframe provides the specific entry point to minimize risk.

---

## The Price Cycle — Full Model

Price moves through a repeating sequence in both directions. The cycle is a framework, not a rigid formula — steps can be skipped or repeated.

### Uptrend Build (Bottoming → Trending Higher)
```
Reversal Extension  →  Wedge Pop  →  EMA Crossback  →  Base n' Break  →  Exhaustion Extension
     (bottom)           (1st push)    (1st pullback)     (continuation)        (topping)
```

### Downtrend Build (Topping → Trending Lower)
```
Exhaustion Extension  →  Wedge Drop  →  EMA Crossback  →  Base n' Break  →  Reversal Extension
      (top)               (1st push)    (1st rally back)    (continuation)        (bottom)
```

---

## Stage-by-Stage: Entry, Exit, and Notes

---

### STAGE 1 — Reversal Extension (Capitulation / Bottoming)

**What it is:** Violent sell-off approaching a major support level; price extends far from the 10 EMA with "air" between price and the moving average. Heavy volume panic selling. This is the bottoming signal.

**Entry conditions (ALL required):**
1. Price approaching a defined support level on a HIGHER timeframe chart
2. Price is extended far from the 10 EMA on the TRADING timeframe (large gap between price and EMA)
3. Price begins to form a reversal bar (closes off the lows; bullish engulfing; hammer; outside reversal)
4. Heavy capitulation volume on the reversal bar (essential — confirms institutional buyers stepping in)

**Entry execution:** Go long on the reversal bar close or next-day open when conditions met.

**Stop:** Below the low of the reversal bar / reversal area.

**First profit target:** The 20 EMA on the trading timeframe.

**Stop management:** Move stop to cost basis when first partial profits are taken; use discretion to exit remaining shares.

**Notes:**
- Also valid as an ADD signal when an uptrending stock pulls back to its Daily 20 EMA — execute the Reversal Extension entry on the intraday (5-min) chart while the Daily 20 EMA is the higher-TF support
- This is the earliest possible entry; highest risk but also highest reward
- "Be a-buyin' when they cryin'" — this is the crying moment

---

### STAGE 2 — Wedge Pop (First Recovery Through MAs)

**What it is:** After a Reversal Extension bottom, price works its way back up through the 10/20 EMA for the first time. The stock has been in a tight, lower-trending range (the "wedge") and then "pops" through the moving averages. This is the first clean, safe buy area.

**Entry conditions (ALL required):**
1. Prior Reversal Extension has occurred (confirmed bottom)
2. Price has been trading in a tight, declining range (lower highs, lower lows — the wedge shape)
3. The 10 EMA and 20 EMA are tightening/converging (shows lack of downside momentum)
4. Stock shows RELATIVE STRENGTH vs the underlying index (holding up better during the wedge)
5. Price recaptures (closes above) the tight 10/20 EMA cluster

**Entry execution:** Buy on the candle that recaptures the 10/20 EMA. Stop goes below the near-term price consolidation.

**Stop:** Below the near-term consolidation base; use the EMAs as trailing stops once the trade triggers.

**Exit signals:**
- Close back below 10/20 EMA after entry = exit
- Moving averages as trailing stops — ride them higher

**Notes:**
- This is the first clean buy area without needing to pick the absolute bottom
- Confirmation: a prior Reversal Extension that holds gives confidence in the Wedge Pop
- "From failed moves come fast moves" — if the Wedge Drop failed on higher TF, this pop is powerful
- Can be also interpreted as a Wedge Pop within a larger Base n' Break on the daily

---

### STAGE 3 — EMA Crossback (First Pullback After Wedge Pop)

**What it is:** After the Wedge Pop pushes price above the 10/20 EMA, price pulls back into those moving averages for the first time. This is the first safe add/re-entry opportunity in a developing trend.

**Entry conditions:**
1. Price has already established itself above the 10/20 EMA (Wedge Pop is confirmed)
2. Price pulls back INTO the 10/20 EMA for the first time
3. Price shows support at or near the EMA (doesn't close far below it)

**Entry execution:** Buy against the 10/20 EMA. This is a low-risk, high-reward entry — either the EMA holds and you're on a trend, or it breaks and you take a small defined loss.

**Stop:** Below the EMA that is being tested (place stops below the relevant moving average).

**Stop management:** Raise stops in trailing format with the 10/20 EMA as the trend develops.

**Notes:**
- Opposite for short sales (in downtrends, EMA Crossback = rally back into EMAs = short opportunity)
- This setup is also described as "EMA Pullback Entry" — a shorter 1-3 day pullback vs the longer Base n' Break
- The EMA Crossback should NOT be used when price is very extended in a trend (lower odds)

---

### STAGE 4 — Base n' Break (Continuation Breakout)

**What it is:** After the trend is established, price builds a multi-day/multi-week consolidation above the 10/20 EMA (the base), then breaks out to new highs (the break). This is the highest-quality, most reliable continuation pattern and the primary buy point in a trend.

**Entry conditions:**
1. Price is in an uptrend above the 10/20 EMA
2. Price consolidates for multiple days/weeks, finding SUPPORT at the 10/20 EMA on dips
3. Volatility contracts during the base (tighter daily ranges)
4. Price breaks out above the top of the base — especially on volume

**Entry execution (two approaches):**
- **Conservative:** Buy the actual breakout above the base top; stop below the base breakout day's low
- **Aggressive:** Buy against the EMA during the base with a tighter stop; add on the breakout

**Stop:** Loss of the 10/20 EMA; or below the base breakout day's low.

**Exit — ride the trend:**
- Raise stops in trailing format with the 10/20 EMA
- Sell into POPS away from the 10 EMA (partial sells on extensions)
- Final exits: loss of the relevant EMA

**Notes:**
- "Bigger the Base, the Higher in Space" — longer consolidations lead to bigger moves
- Ignition bars during the base (wide-range, heavy volume bars) are signs of strength — stop goes below that bar's low
- Base n' Break can repeat multiple times in a trend (TSLA example: 3+ bases before topping)
- A failed Base n' Break (price breaks out then immediately fails back below the base) is a RED FLAG

---

### STAGE 5 — Exhaustion Extension (Blowoff / Topping)

**What it is:** Price extends aggressively from the 10 EMA, often with gap-ups, on euphoric volume. This is a TOPPING signal, not an entry signal. The more extensions you see, the more likely a significant top or re-base.

**Extension count rules:**
- **1st extension from 10 EMA:** Can usually hold through (normal strength)
- **2nd extension from 10 EMA:** Good time to take significant partial/full profits; higher probability of a top
- **3rd extension from 10 EMA:** Very late in the trend; be aggressive in taking profits
- **Also check:** If also extended from the WEEKLY 10 EMA = major topping signal across timeframes

**Topping patterns to watch for:**
- Gap up + reversal (closes near lows) on the extension day = Exhaustion Gap
- Bearish engulfing candle on the extension
- Shooting star candle (open near lows, close near lows with long upper wick)
- Very heavy volume with price rejection (closes off highs)

**Action:**
- SELL into the extension pops (not after the drop)
- "Sell When You Can, Not When You Have To"
- "Sell into Strength or You Will Sell into Weakness"

---

### STAGE 6 — Wedge Drop (First Loss of MAs After Top)

**What it is:** After an Exhaustion Extension, price "wedges" back toward the MAs in a tight, rising range (makes it look like a bullish consolidation), then "drops" through the 10/20 EMA. This confirms the Exhaustion Extension was a real top and an intermediate downtrend is beginning.

**Sell/Exit trigger:**
- Close below the 10/20 EMA (the "drop" after the wedge)
- Confirmed when lower highs + lower lows appear below the EMAs

**Short entry (optional — use cautiously):**
- After price loses the 20 EMA, a bounce/rally back to the 20 EMA from below = short entry
- Stop above the 20 EMA

**Notes:**
- The Wedge Drop is the most important SELL signal in the system
- In a downtrend, the EMA Crossback (rally back to MAs) is a short entry, not a buy
- Expect more volatility shorting: biggest daily rallies occur during corrections
- If below the QQQ 20 EMA: go to cash, reduce/eliminate margin, be cautious

---

## Traditional Chart Patterns

### Cup + Handle
- **Shape:** U-shaped base (cup) + tight consolidation near the highs (handle)
- **Entry:** Breakout above the handle resistance
- **Stop:** Below the handle low; below the 10/20 EMA
- **Note:** Handle = volatility contraction; volume should dry up in the handle, spike on breakout

### Double Bottom Base
- **Shape:** Two lows at roughly the same level with a rally in between; second low often has a 2B Reversal shakeout (briefly undercuts the first low then snaps back)
- **Entry:** Breakout above the middle rally peak ("middle of the W")
- **Stop:** Below the second bottom
- **Note:** The 2B Reversal shakeout shakes out weak hands; makes the subsequent breakout more powerful

### Flat Base (Large Base / Monthly Base)
- **Shape:** Multi-week or multi-month tight sideways consolidation; the longer the better
- **Entry:** Breakout above the flat top on volume, especially if it's also a weekly/monthly breakout
- **Stop:** Below the breakout day's low; below EMAs
- **Note:** "Bigger the Base, the Higher in Space" — a monthly base breakout = major move

### Bull Flag
- **Shape:** Sharp advance (flagpole) + short declining channel (flag) of lower highs and lower lows
- **Entry:** Breakout through the upper declining trendline (lower highs)
- **Stop:** Below the flag low (bottom of the channel)
- **Note:** Also called a "mini-channel"; shorter-term continuation pattern; strong conviction if flagpole was on heavy volume

### Bull Pennant
- **Shape:** Sharp advance + symmetrical triangle of lower highs and higher lows, declining volatility
- **Entry:** Breakout to the upside from the triangle
- **Stop:** Below the pennant low

### Descending Channel (on daily = bull flag on weekly)
- **Shape:** Multi-week pattern of lower highs and lower lows in a parallel channel; may look like a bull flag on the weekly chart
- **Entry:** Pop up through the upper channel trendline, especially with a catalyst
- **Stop:** Below the breakout day's low

---

## Little Tricks / Special Setups

### Inside Bars
- Bar trades entirely within previous bar's range = volatility contraction
- On very light volume = even more powerful signal (trade has dried up before a move)
- Multiple consecutive inside bars = amplified setup
- **Action:** Buy the breakout from the inside bar sequence; stop below the inside bar low

### 2B Reversal (Pivot Low/High Failure)
- Price breaks through a key support low (or resistance high), then immediately reverses back through it
- "From failed moves come fast moves" — the failure triggers a fast move in the opposite direction
- **Bullish 2B:** Price undercuts a prior swing low, then closes back above it = buy signal; stop below the new low
- **Bearish 2B:** Price breaks to new high, then closes back below the prior high = sell/short signal

### Wick Play
- Previous session closes with a wick (closes off the highs — upper wick)
- Next day gaps higher, opening inside that wick
- If price stays positive and holds within the wick = sign of strength
- **Action:** Use as a buy signal in context of a larger bullish pattern

### Outside Reversal (Bullish)
- Uptrending stock pulls back for a few days
- A bar opens below the prior day's low (or trades through it), then closes back above
- Buyers have stepped in; pullback likely over
- **Action:** Buy the outside reversal bar; stop below its low

### Gap Up = Street Caught Off Guard
- A major gap above resistance with heavy volume = institutions were positioned wrong
- "Gap Ups = Street Caught Off Guard"
- **Buyable gap up:** If the gap is through a major level (weekly/monthly resistance), the gap day's low is the stop
- **Extended gap up:** If price was already extended from 10 EMA AND gaps up = reduce/sell, not buy

### Too Tight For Too Long (TTFTL)
- A pattern that is basing in an overly tight, obvious formation while underperforming the index
- This can be a TRAP — everyone sees it, but sellers use it to distribute
- **Action:** Be suspicious when something is too obvious and has shown relative weakness; avoid until it proves itself

---

## Stop Loss Rules (Summary)

| Scenario | Stop Placement |
|---|---|
| Breakout buy | Below the breakout day's low |
| Ignition bar (wide range, heavy volume) | Below the ignition bar low |
| EMA trailing | Below the 10 EMA (or 20 EMA depending on what the stock respects) |
| Rising trendline (3+ touchpoints) | Below the trendline on a close |
| Buyable gap up | Below the gap day's low |
| Weekly 10 EMA extension | Take partial/full profits; don't add |
| 2nd Exhaustion Extension | Take profits aggressively; start reducing |
| Wedge Drop (close below 20 EMA) | SELL signal — exit position |

**Managing winning trades:**
- "Sell Some, Hold Some" — when you have 5x+ your initial risk, take partials and hold a core
- Raise stops with each new "Reconfirming Price Strength Confirmation" (new higher swing low)
- Use ignition bar lows to ratchet stops up
- When position is profitable, add on EMA pullbacks while raising stops — size can grow with zero added principal risk

---

## Avoiding Bad Markets — Market Regime Filter

**Bearish regime (reduce exposure / go to cash):**
- QQQ/NASDAQ closes below its 20 EMA
- Confirmed downtrend: Exhaustion Extension top + Wedge Drop through 20 EMA
- No margin; smaller position sizes; tighter stops
- Avoid new longs; if shorting, take profits faster and use smaller size

**Bullish regime (full exposure, add on pullbacks):**
- QQQ/NASDAQ above its 20 EMA
- Trend established: Wedge Pop confirmed + EMA Crossback held + Base n' Break triggering

**Transition signal (re-entry into bullish regime):**
1. Reversal Extension off a higher-timeframe support = capitulation bottom
2. Wedge Pop through the 20 EMA = first clean buy
3. EMA Crossback holds = trend confirmation
4. Base n' Break = add / full position

**Relative Strength during corrections:**
- The next big leaders are found DURING corrections
- Look for stocks (or in our case TQQQ) that hold up better than the index
- A stock making higher lows while the index makes lower lows = "Stubborn to the downside" = leadership
- When the index turns up, these relative strength names move first and fastest

---

## Position Sizing Framework

### Account structure (margin account):
| Position | Size | Type | Management |
|---|---|---|---|
| Top Idea #1 | 25–35% | Highest conviction, breaking large base | Reduce to 20–25% on 1st extension from 10 EMA |
| Top Idea #2 | 25–35% | Same as above | Same |
| Conviction Core #3 | 15–20% | High conviction, slightly later | Hold through EMA pullbacks |
| Conviction Core #4 | 15–20% | Same | Same |
| Volatile Core #5 | 10–12% | High conviction, higher vol | Smaller due to volatility; similar P&L impact |
| Core #6 | 10–12% | Good setup, second tier | More active profit taking |
| Swing #7–#12 | 7–8% | Shorter patterns (flags, EMA pullbacks) | Book profits quickly on extensions |

### Buying in pieces:
- Start smaller at initial breakout with tighter stop
- Add on EMA pullbacks as position proves itself
- Raise stops with each add so total principal risk decreases even as position size grows
- Goal: large position with lower-than-original capital at risk if properly managed

---

## Key Aphorisms (Trading Rules)

| Saying | Meaning |
|---|---|
| Price is News | Trust the price chart over any narrative |
| From Failed Moves Come Fast Moves | 2B Reversals and failed breakdowns create explosive opposite moves |
| Gap Ups = Street Caught Off Guard | Large gaps through resistance = institutional short-covering or conviction buying |
| Bigger the Base, the Higher in Space | Longer consolidations precede larger moves |
| Sell When You Can, Not When You Have To | Sell into strength; don't wait for the drop |
| Don't Trust Your Stocks, Trust Your Stops | Pre-defined stops override conviction |
| Buy Right, Sit Tight | Enter at low-risk pivot; hold through normal EMA pullbacks |
| Losers Average Losers | Never add to losing positions |
| Take Small Losses or You Will Take Big Losses | Honor stops immediately |

---

## TQQQ-Specific Application Notes

TQQQ is a 3x leveraged daily-reset ETF tracking the NASDAQ-100. These adjustments apply:

### What to watch:
- **Underlying:** QQQ / NASDAQ Composite (IXIC) for regime and pattern signals
- **TQQQ own chart:** For timing entries and exits (TQQQ often leads QQQ on reversals due to leveraged flows)

### Amplification effects:
- Every Exhaustion Extension in QQQ = 3x+ extension in TQQQ — the 2nd extension rule is CRITICAL; don't wait for the 3rd
- A Wedge Drop on QQQ that is -5% = -15%+ on TQQQ; Wedge Drop signals must trigger fast exits
- A Reversal Extension capitulation in QQQ at -10% = -25–30% in TQQQ; the capitulation is extreme and visible

### Regime mapping to existing Tushar v1 logic:
| Oliver Kell Signal | Tushar v1 Equivalent | TQQQ Action |
|---|---|---|
| QQQ Exhaustion Extension + Wedge Drop below 20 EMA | QQQ drops 15%+ from 252d high | EXIT to cash |
| QQQ Wedge Pop (recaptures 20 EMA, 3 days) | QQQ returns within 15% of high, 3 consecutive days | RE-ENTER TQQQ |
| QQQ Base n' Break above 10/20 EMA | QQQ well within threshold, uptrend | HOLD TQQQ |
| QQQ Reversal Extension at 200 SMA | QQQ at major crash low (well below threshold) | CASH; watch for Wedge Pop |

### Key pattern to build a strategy around:
The **Wedge Pop + EMA Crossback + Base n' Break** sequence on the QQQ/IXIC daily chart is the optimal re-entry framework for TQQQ after a correction:
1. QQQ finds capitulation low (Reversal Extension) at major support / 200 SMA
2. QQQ pops through 20 EMA = first TQQQ re-entry signal (partial position)
3. QQQ pulls back to 10/20 EMA and holds (EMA Crossback) = add TQQQ
4. QQQ breaks above the Base n' Break = full TQQQ position with stops at EMA loss

### Exit framework for TQQQ:
1. **Fast exit:** QQQ loses its 20 EMA on the daily chart (Wedge Drop confirmed)
2. **Profit taking:** QQQ 2nd Exhaustion Extension from daily 10 EMA + extended from weekly 10 EMA = reduce TQQQ significantly
3. **Trailing:** Use QQQ's 10 EMA as trailing stop once in a sustained trend

### Timeframes to watch:
- **Monthly QQQ:** Regime context — is QQQ above/below its 10/20 monthly EMA?
- **Weekly QQQ:** Extension from weekly 10 EMA = caution; below weekly 20 EMA = bearish
- **Daily QQQ:** Primary signal timeframe for regime entries/exits
- **Daily TQQQ:** Entry timing, stop placement, pattern execution

---

## Strategy Development Priorities (Ordered)

When building the TQQQ strategy from this framework, implement in this order:

1. **Market regime filter** (QQQ above/below 20 EMA daily) — binary HOLD/CASH
2. **Exhaustion Extension detector** (count extensions from 10 EMA; 2nd = reduce, Wedge Drop = sell)
3. **Wedge Pop re-entry** (first close above 20 EMA after being below it)
4. **EMA Crossback add** (first pullback to 10/20 EMA after Wedge Pop that holds)
5. **Base n' Break entry** (consolidation above EMA breaks out on volume)
6. **Relative strength filter** (QQQ or TQQQ showing RS vs SPY during corrections)
7. **Volume confirmation** (heavy volume on breakout bars = higher conviction)

---

*Document based on: Victory in Stock Trading by Oliver Kell, 2021 First Edition*  
*Prepared as TQQQ strategy development reference — May 2026*
