# Nasdaq ML Trading Signal System — User Guide

## What This Is and Why It Exists

Most retail traders face two problems:
1. **Noise vs signal** — every day the market moves; almost none of those moves are meaningful.
2. **Position sizing** — even when you have a good idea, sizing too large loses you sleep and too small makes the trade pointless.

This system addresses both. It watches the Nasdaq Composite Index (^IXIC) across 40 years of daily price history, trains three machine-learning models to recognise conditions that historically preceded large moves, and then — when it has enough conviction — tells you exactly how much to trade and why.

The output is simple: **BUY, SELL, or HOLD**, with a confidence score and a dollar allocation recommendation. You decide whether to act. The system never places orders.

---

## How It Works — The Full Pipeline

```
^IXIC daily prices (yfinance)
         |
         v
  [data/fetcher.py]          Download once, update incrementally.
  cache/ixic_ohlcv.parquet   ~10,400 bars from 1985 to today.
         |
         v
  [data/features.py]         Engineer 32 technical features:
                             momentum, trend, volatility, volume, returns.
         |
         v
  [models/trainer.py]        Walk-forward training over 71 rolling windows
                             (5yr train / 1yr test / 6mo step, no lookahead).
         |
         +--> Random Forest (rf_final.joblib)
         +--> XGBoost       (xgb_final.ubj)
         +--> LSTM           (lstm_final.pt)
         |
         v
  [models/ensemble.py]       Weighted average of all three models.
                             Weights optimised on validation Sharpe ratio.
         |
         v
  [signals/generator.py]     Today's signal: BUY / SELL / HOLD
                             with confidence and probability breakdown.
         |
         v
  [sizing/position_sizer.py] Three sizing methods run in parallel:
                             Fixed Fractional, ATR-based, Kelly Criterion.
```

### Why Three Models?

Each model sees the data differently:

| Model | Strength | Weakness |
|---|---|---|
| **Random Forest** | Robust to noise; fast; interpretable feature importance | Misses sequential patterns |
| **XGBoost** | Strong on tabular data; handles class imbalance well | Also misses time structure |
| **LSTM** | Learns from 60-day sequences; captures trend momentum | Slow to train; needs lots of data |

The **ensemble** combines their probability outputs, weighted by how much each model improved the out-of-sample Sharpe ratio during walk-forward validation. If a model file is missing, the ensemble automatically redistributes its weight to the others — you can run a working system with just RF + XGB.

### What Is Walk-Forward Validation?

This is the key protection against overfitting. A naive backtest trains on all history and tests on the same history — that tells you nothing real. Walk-forward validation works like this:

```
[Train on 1985-1990] → [Test on 1990-1991]
      shift 6 months
[Train on 1985-1990.5] → [Test on 1990.5-1991.5]
      ...repeat 71 times until present
```

Each test period is genuinely out-of-sample. The model has never seen the test data. This is the same discipline professional quant funds use.

### The Target: What Is the Model Predicting?

Each trading day is labelled by what the market does over the **next 5 trading days**:

- `BUY (1)` — close rises more than **+1.5%** over the next 5 days
- `SELL (2)` — close falls more than **-1.5%** over the next 5 days
- `HOLD (0)` — everything in between

The model outputs a probability for each class. The highest probability class is the signal. If the winning probability is below **55%** (the confidence threshold), the signal is downgraded to HOLD regardless of which class won.

---

## The 32 Features Explained

Features are the inputs the models learn from. Raw price is not used — instead everything is expressed as a ratio, percentage, or normalised value so the models work equally well in 1990 (Nasdaq ~500) and 2025 (Nasdaq ~20,000).

### Momentum (8 features)
| Feature | What it measures |
|---|---|
| `rsi_14` | Relative Strength Index, 14-day. Above 70 = overbought, below 30 = oversold. |
| `rsi_7` | Faster RSI for short-term mean-reversion signals. |
| `macd` | MACD line (12-day EMA minus 26-day EMA). Positive = uptrend momentum. |
| `macd_signal` | 9-day EMA of the MACD line. |
| `macd_hist` | MACD minus signal line. Sign change = momentum turning point. |
| `stoch_k` | Stochastic %K: today's close relative to recent high-low range (0-100). |
| `stoch_d` | 3-day smoothed stochastic. Crossovers signal entries. |
| `williams_r` | Williams %R: similar to stochastic, -100 to 0. Near -100 = oversold. |

### Trend (3 features)
| Feature | What it measures |
|---|---|
| `adx_14` | ADX trend strength. Above 25 = trending market; below 20 = directionless. |
| `di_plus` | Positive directional movement. Higher than di_minus = uptrend. |
| `di_minus` | Negative directional movement. |

### Volatility (5 features)
| Feature | What it measures |
|---|---|
| `atr_14` | Average True Range: daily dollar volatility. Used directly in position sizing. |
| `bb_upper` | Bollinger Band upper bound (20-day SMA + 2 standard deviations). |
| `bb_lower` | Bollinger Band lower bound. |
| `bb_pct` | Where today's close sits within the bands: 0 = at lower band, 1 = at upper. |
| `bb_width` | Band width as % of price: high = volatile market, low = quiet market. |

### Volume (3 features)
| Feature | What it measures |
|---|---|
| `obv_norm` | On-Balance Volume normalised by its 252-day average. >1 = accumulation. |
| `cmf` | Chaikin Money Flow: buying vs selling pressure from volume-weighted closes. |
| `vol_ratio` | Today's volume divided by 20-day average. >1.5 = unusual activity. |

### Price Position (5 features — EMA ratios)
| Feature | What it measures |
|---|---|
| `close_ema10_ratio` | (Close / 10-day EMA) - 1. Positive = above 10-day average. |
| `close_ema20_ratio` | Same for 20-day EMA. |
| `close_ema50_ratio` | Same for 50-day EMA. |
| `close_ema100_ratio` | Same for 100-day EMA. |
| `close_ema200_ratio` | Same for 200-day EMA. Key regime indicator. |

### Returns (5 features)
| Feature | What it measures |
|---|---|
| `ret_1d` | Yesterday's return. |
| `ret_3d` | 3-day cumulative return. |
| `ret_5d` | 5-day cumulative return. |
| `ret_10d` | 10-day cumulative return. |
| `ret_21d` | ~1 month return. |

### Market Regime (3 features)
| Feature | What it measures |
|---|---|
| `vol_21d` | Annualised realised volatility (21-day). High = fearful market. |
| `high_52w_pct` | How far below the 52-week high as a percentage. **This is the single most predictive feature.** A reading of 0.15 means the index is 15% below its 52-week high. |
| `low_52w_pct` | Distance above the 52-week low. |

> **Why is `high_52w_pct` so important?** This is the same metric used by the existing strategies in this project (called `pcthi`). Markets historically have a strong mean-reversion tendency: when close to all-time highs, momentum continues; when far below, downtrend risk is elevated.

---

## The Three Position Sizing Methods

Every signal runs all three methods simultaneously so you can compare them. You choose which to follow.

### Method 1: Fixed Fractional (simplest, default)

Risk a fixed percentage of your capital, scaled by confidence.

```
allocation = capital × 2% × confidence_scalar
confidence_scalar = (confidence - 0.55) / 0.45   (maps 55%-100% → 0-100%)
```

**Example:** $50,000 capital, 80% confidence:
```
confidence_scalar = (0.80 - 0.55) / 0.45 = 0.56
allocation = $50,000 × 0.02 × 0.56 = $556
```

Use this when you want predictable, small positions. Good for beginners.

### Method 2: ATR-Based (volatility-adjusted)

Size the position so that one average daily move equals a fixed dollar risk.

```
shares = floor($1,000 / ATR_14)
allocation = shares × price
(capped at 20% of capital)
```

**Example:** ATR = $2.50 (for a $480 ETF), $50,000 capital:
```
shares = floor($1,000 / $2.50) = 400 shares
allocation = 400 × $480 = $192,000 → capped at $10,000 (20% of $50k)
actual shares = floor($10,000 / $480) = 20 shares
```

In high-volatility markets (large ATR), you get fewer shares. In quiet markets, you get more. This keeps daily P&L swings roughly constant regardless of market conditions.

### Method 3: Kelly Criterion (advanced, uses trade history)

The Kelly formula finds the mathematically optimal fraction to risk given your historical win rate and average win/loss size.

```
Kelly_f = win_rate - (1 - win_rate) / (avg_win / avg_loss)
Half-Kelly = Kelly_f / 2   (safety factor — full Kelly is too aggressive)
allocation = capital × Half-Kelly
(capped at 25% of capital)
```

**Example:** 54% win rate, average win +2.2%, average loss -1.5%:
```
Kelly_f = 0.54 - 0.46 / (0.022/0.015) = 0.54 - 0.31 = 0.23
Half-Kelly = 0.115
allocation = $50,000 × 0.115 = $5,750
```

This method requires signal history to estimate win_rate and avg_win/loss accurately. Before 20+ trades are logged, the defaults (55% win rate, 2% avg win, 1.5% avg loss) are used as estimates.

---

## Setup and First Run

### Prerequisites

```bash
# Navigate to the project
cd E:\work\Stockdata\nasdaq_ml_trader

# Install dependencies (if not done already)
pip install ta xgboost
# Other packages (pandas, numpy, yfinance, torch, sklearn, rich, scipy) are likely already installed
```

### Step 1 — Download 40 years of data (30 seconds)

```bash
python main.py fetch
```

This downloads daily OHLCV for ^IXIC from 1985 to today and saves it to `cache/ixic_ohlcv.parquet`. On subsequent runs it only downloads the missing dates — it does not re-download the whole history.

### Step 2 — Verify feature engineering (optional, 10 seconds)

```bash
python main.py features
```

Prints a table showing all 32 features with their mean, standard deviation, min, and max across the full 40-year history. Also shows the label distribution (how many BUY / SELL / HOLD days historically). Use this to sanity-check that data loaded correctly.

### Step 3 — Train the models

**Option A: Fast (RF + XGB only, ~15 minutes)**
```bash
python main.py train --skip-lstm
```
Good for getting started. Produces a working signal within 15 minutes. The LSTM is optional — RF + XGB together already provide meaningful signals.

**Option B: Full training including LSTM (run overnight, ~17-28 hours first time)**
```bash
python main.py train
```
LSTM training across 71 walk-forward folds on CPU is slow. But the system caches each fold to disk — if you stop and restart, it picks up where it left off. Subsequent daily runs only train the newest fold (~20-25 minutes).

What `train` does in order:
1. Runs all 71 walk-forward folds (train RF, XGB, and optionally LSTM on each)
2. Evaluates each model on its out-of-sample test period
3. Optimises ensemble weights using scipy to maximise the walk-forward Sharpe ratio
4. Retrains final production models on all data except the last 30 days
5. Saves everything to `saved_models/`

### Step 4 — Generate your first signal

```bash
python main.py signal --capital 100000
```

Replace `100000` with your actual portfolio value in USD. The system will:
1. Load today's ^IXIC data (incremental update from cache)
2. Compute all 32 features on the latest bar
3. Run RF, XGB, and LSTM models
4. Compute the ensemble probability
5. Apply the confidence filter (must be above 55%)
6. Calculate all three position sizes
7. Print the result and log it to `signal_history.jsonl`

---

## Daily Workflow

After the initial setup, your daily routine is:

```bash
# Run after market close (or any time for HOLD markets)
cd E:\work\Stockdata\nasdaq_ml_trader
python main.py signal --capital YOUR_CAPITAL
```

That's it. The data fetcher automatically updates with today's prices. The models are already trained. The signal is generated in a few seconds.

If you want to retrain with newer data periodically (recommended monthly):
```bash
python main.py train --skip-lstm   # ~15 min
```

---

## Understanding the Signal Output

```
+-------------------------- NASDAQ ML Signal Engine --------------------------+
| BUY  Confidence: 78.0%                                                     |
|                                                                             |
| P(HOLD)=0.152   P(BUY)=0.780   P(SELL)=0.068                               |
| Models: RF | XGB | LSTM                                                     |
| Weights: RF=0.312  XGB=0.408  LSTM=0.280                                    |
| ^IXIC close: 19,823.00  |  Date: 2026-05-08                                 |
+-----------------------------------------------------------------------------+
```

| Field | Meaning |
|---|---|
| **Signal** | BUY / SELL / HOLD. HOLD means either no edge or confidence too low. |
| **Confidence** | The highest class probability. 78% means the ensemble is 78% sure about BUY. |
| `P(HOLD) / P(BUY) / P(SELL)` | Full probability breakdown across all three classes. |
| **Models** | Which model files were loaded. Missing files are handled gracefully. |
| **Weights** | How much each model contributed. Optimised on historical Sharpe ratio. |
| **^IXIC close** | Today's index value used for signal generation. |

```
              Position Sizing (Capital: $100,000)
+-----------------------------------------------------------+
| Method                       | Allocation ($) | % Capital |
|------------------------------+----------------+-----------|
| Fixed Fractional             |         $1,133 |      1.1% |
| ATR-Based (12 shares)        |         $5,880 |      5.9% |
| Kelly (f*=0.212, half-Kelly) |        $10,625 |     10.6% |
+-----------------------------------------------------------+
```

The ATR-Based and Kelly methods give you a specific share count for a Nasdaq ETF (like QQQ). The "12 shares" means: buy 12 shares of whatever Nasdaq ETF you use, with the system risking $1,000 of ATR movement per position.

**How to use the three numbers:**
- If you are new or risk-averse: use **Fixed Fractional** (smallest)
- If you want volatility-adjusted sizing: use **ATR-Based**
- If you have 20+ trades of history logged: use **Kelly** (mathematically optimal but requires calibration)

---

## What to Do With the Signal

This system tracks the Nasdaq Composite (^IXIC). You cannot buy the index directly, but you can trade ETFs that track it:

| ETF | Direction | Leverage |
|---|---|---|
| QQQ | Bullish (BUY signal) | 1x |
| TQQQ | Bullish (BUY signal) | 3x — much higher risk |
| PSQ | Bearish (SELL signal) | -1x (inverse) |
| SQQQ | Bearish (SELL signal) | -3x — much higher risk |

**Recommended approach:**
- BUY signal → buy QQQ (or TQQQ for leveraged exposure)
- SELL signal → buy PSQ (or SQQQ), or simply exit any long position
- HOLD signal → stay in cash or hold your current position
- Use the **ATR-Based share count** as your guide for QQQ; the IXIC ATR needs to be scaled to QQQ: `QQQ_ATR = IXIC_ATR × (QQQ_price / IXIC_level)`

**Important:** This system generates signals based on historical patterns. Past performance does not guarantee future results. Always use a stop loss and never risk more than you can afford to lose.

---

## All Commands Reference

### `python main.py fetch`
Downloads or updates the ^IXIC price cache. Runs automatically before `signal` — you rarely need to run this manually.

```bash
python main.py fetch              # incremental update (default)
python main.py fetch --refresh    # wipe cache and re-download full 40yr history
```

### `python main.py features`
Displays statistics for all 32 engineered features and the label distribution. Useful for:
- Verifying data integrity after fetch
- Understanding which market regimes occur most often
- Checking that no feature has a zero standard deviation (that would mean it carries no information)

### `python main.py train`
Runs the full walk-forward training pipeline. This is the longest command.

```bash
python main.py train              # RF + XGB + LSTM (17-28 hours first run)
python main.py train --skip-lstm  # RF + XGB only (~15 minutes)
```

Run at least once before using `signal`. Re-run monthly to keep models calibrated to recent market behaviour. Subsequent runs are fast because fold-level results are cached — only new folds since last run are trained.

### `python main.py backtest`
Re-runs the walk-forward simulation and reports performance metrics.

```bash
python main.py backtest                      # strategy metrics only
python main.py backtest --benchmark          # compare against buy-and-hold ^IXIC
python main.py backtest --skip-lstm          # backtest RF+XGB ensemble only
```

Metrics reported:
- **CAGR** — Compound Annual Growth Rate
- **Sharpe** — return per unit of risk (>1.0 is good, >1.5 is excellent)
- **Sortino** — like Sharpe but only penalises downside volatility
- **Calmar** — CAGR divided by max drawdown
- **Max Drawdown** — the worst peak-to-trough loss the strategy experienced
- **Win Rate** — percentage of trading days with positive P&L
- **Profit Factor** — gross profit divided by gross loss (>1.5 is healthy)

### `python main.py signal`
The main daily command. Generates today's BUY/SELL/HOLD signal.

```bash
python main.py signal                        # uses default $100,000 capital
python main.py signal --capital 50000        # your actual portfolio size
python main.py signal --history 20           # show last 20 signals from log
```

### `python main.py status`
Shows which model files exist and how large they are.

```bash
python main.py status
```

If a file shows MISSING, it means either training was skipped (`--skip-lstm` removes the LSTM) or training was interrupted. The ensemble works with any subset of models — a missing LSTM just means its weight is redistributed to RF and XGB.

---

## File Structure Reference

```
nasdaq_ml_trader/
|
|-- main.py                  Entry point. All commands start here.
|-- config.py                All tuneable parameters. Edit this to change thresholds.
|-- requirements.txt         Python dependencies.
|
|-- data/
|   |-- fetcher.py           Downloads ^IXIC from yfinance, manages parquet cache.
|   \-- features.py          Computes all 32 features from raw OHLCV.
|
|-- models/
|   |-- trainer.py           Walk-forward training logic. RF, XGB, LSTM classes.
|   |-- evaluator.py         Per-fold accuracy metrics and trading performance metrics.
|   \-- ensemble.py          Weighted ensemble with scipy weight optimisation.
|
|-- signals/
|   \-- generator.py         Daily signal generation and JSONL history logging.
|
|-- sizing/
|   \-- position_sizer.py    Three position sizing methods.
|
|-- backtest/
|   \-- engine.py            Walk-forward backtest simulation.
|
|-- utils/
|   |-- logger.py            File + stderr logging.
|   \-- display.py           Rich terminal tables and panels.
|
|-- cache/                   (auto-created)
|   \-- ixic_ohlcv.parquet   40-year ^IXIC price history (~2 MB).
|
|-- saved_models/            (auto-created by training)
|   |-- rf_final.joblib      Random Forest (production).
|   |-- xgb_final.ubj        XGBoost (production).
|   |-- lstm_final.pt        LSTM (production — only if trained with LSTM).
|   |-- scaler_final.joblib  Feature normalisation scaler.
|   |-- ensemble_weights.joblib  Optimised model weights.
|   |-- rf_fold{N}.joblib    Walk-forward fold cache (speeds up retraining).
|   |-- xgb_fold{N}.ubj      Walk-forward fold cache.
|   \-- lstm_fold{N}.pt      Walk-forward fold cache.
|
|-- logs/                    (auto-created)
|   |-- fetcher.log          Data download activity.
|   |-- trainer.log          Per-fold training accuracy.
|   |-- engine.log           Backtest results.
|   \-- generator.log        Daily signal generation events.
|
\-- signal_history.jsonl     (auto-created on first signal)
                             Every signal ever generated, one JSON per line.
                             Contains: date, signal, confidence, probabilities,
                             active models, weights, and all sizing outputs.
```

---

## Tuning the Parameters

All tuneable parameters are in `config.py`. The most useful ones to adjust:

### Signal sensitivity

```python
MIN_CONFIDENCE = 0.55   # raise to 0.65 for fewer but higher-conviction signals
                        # lower to 0.50 for more signals (more noise)

BUY_THRESH  = 0.015     # +1.5% = BUY label. Raise for stricter labels.
SELL_THRESH = -0.015    # -1.5% = SELL label.
FORWARD_DAYS = 5        # predict 5-day forward return. Change to 10 for longer horizon.
```

### Position sizing

```python
ATR_RISK_DOLLARS = 1_000.0  # dollar risk per ATR unit in ATR-based sizing
KELLY_MAX_FRAC   = 0.25     # maximum Kelly fraction (25% of portfolio cap)
DEFAULT_CAPITAL  = 100_000.0  # default if --capital not specified
```

### Model architecture (requires retraining)

```python
RF_N_ESTIMATORS = 500   # more trees = more robust but slower
RF_MAX_DEPTH    = 8     # deeper = can overfit; shallower = underfits
XGB_N_ESTIMATORS = 300  # more rounds = better fit + more overfit risk
LSTM_WINDOW     = 60    # days of history the LSTM sees per prediction
LSTM_EPOCHS     = 50    # training passes (early stopping usually stops before this)
```

After changing any parameter, retrain with `python main.py train`.

---

## Frequently Asked Questions

**Q: The signal says HOLD every day. What's wrong?**

The model's confidence is below 55% on every bar. This is expected during sideways or choppy markets — the models are designed to stay out when they have no edge. Run `python main.py signal` and look at the probability breakdown: if all three probabilities (P(HOLD), P(BUY), P(SELL)) are close to 33%, the model is genuinely uncertain. If P(BUY) is around 50-54%, you can lower `MIN_CONFIDENCE` in `config.py` to 0.50 to capture more signals at the cost of more false positives.

**Q: The models were trained with `--skip-lstm`. Should I retrain with LSTM?**

Yes, if you have time. The LSTM adds meaningful signal in trending markets by recognising sequential patterns that RF and XGB miss. But RF + XGB alone are a valid and faster production system. Run `python main.py train` overnight — the fold cache means you only pay the full training cost once.

**Q: How often should I retrain?**

Monthly is reasonable. Run `python main.py train --skip-lstm` — it will only re-train folds that have not been cached yet (roughly 2 new folds since the previous month), making it fast. The final production model is always retrained on all data up to 30 days ago.

**Q: The signal is BUY but I already hold a position. What do I do?**

HOLD your position. The HOLD signal means "no change recommended", and a repeated BUY signal in the same direction means the model still sees upside. You only need to act on a signal if it conflicts with your current position (e.g., you are long and the signal turns SELL).

**Q: Where are my past signals stored?**

In `signal_history.jsonl` — one JSON object per line. View them with:
```bash
python main.py signal --history 30
```
Or open the file in any text editor. Each entry contains the date, signal, confidence, all three model probabilities, active models, weights, and the full sizing output for all three methods.

**Q: Can I use this for other indices or ETFs?**

The system is designed for ^IXIC. To adapt it for another ticker, change `TICKER` in `config.py` and run `fetch` and `train` again. Feature engineering is generic enough to work with any liquid daily-bar instrument.
