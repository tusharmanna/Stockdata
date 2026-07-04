# Stockdata — Tushar v2 Daily Signals

Runs the TQQQ v2 and QLD v2 volatility-targeted strategy signals every weekday at 3:30 PM ET via GitHub Actions, then emails you a full report and texts a short summary.

---

## GitHub Secrets Required

Go to your repo on GitHub → **Settings → Secrets and variables → Actions → New repository secret** and add these three secrets:

| Secret Name | Value | What it is |
|---|---|---|
| `EMAIL_ADDRESS` | `tusharmanna@gmail.com` | Gmail address (sender and recipient) |
| `EMAIL_PASSWORD` | your 16-char app password | Gmail App Password (NOT your regular password) |
| `PHONE_NUMBER` | `6789943844` | Mobile number for SMS (digits only, no dashes) |

---

## How to Get a Gmail App Password

Your regular Gmail password will not work — you need a Google App Password.

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** in the left sidebar
3. Under "How you sign in to Google", click **2-Step Verification** (must be enabled)
4. Scroll to the bottom and click **App passwords**
5. Under "Select app" choose **Mail**, under "Select device" choose **Other** and type `GitHub Actions`
6. Click **Generate** — Google shows a 16-character password like `abcd efgh ijkl mnop`
7. Copy it (spaces are fine, Gmail accepts them) and paste it as the `EMAIL_PASSWORD` secret

> If you don't see "App passwords", 2-Step Verification is not enabled — enable it first.

---

## How to Manually Trigger the Workflow

1. Go to your repo on GitHub
2. Click the **Actions** tab
3. Click **Daily Signals** in the left sidebar
4. Click the **Run workflow** button (top right of the table)
5. Leave branch as `main` and click **Run workflow**

The run appears in the list within a few seconds. Click it to watch live logs.

---

## Schedule Details

The workflow runs **Monday–Friday at 3:30 PM EDT (19:30 UTC)**.

GitHub Actions cron uses UTC and does **not** auto-adjust for Daylight Saving Time:
- **Summer (Mar–Nov)**: fires at 3:30 PM EDT — correct
- **Winter (Nov–Mar)**: fires at 2:30 PM EST — one hour early

To keep it at 3:30 PM EST in winter, change the cron in `.github/workflows/daily_run.yml` to:
```
- cron: "30 20 * * 1-5"
```
This makes it 4:30 PM EDT in summer. Pick whichever offset matters more to you.

---

## What You Receive

**Email** — full report with:
- Regime gate status and QQQ price
- TQQQ v2 target exposure and volatility
- QLD v2 target allocation and volatility
- Last 7 days exposure history table

**SMS** (AT&T) — one line under 160 characters, e.g.:
```
2026-06-25 BULL 3.8%below189d|TQQQ:0.48x(93%vol)|QLD:71%
```

If the script crashes, you get a **failure email** with the full traceback instead.

---

## How to Check Logs If Something Goes Wrong

1. Go to **Actions** tab on GitHub
2. Click the failed run (red X)
3. Click **run-signals** job
4. Expand the **Run daily signals** step to see the full output and error

Common issues:
- **No email received**: check that `EMAIL_ADDRESS` and `EMAIL_PASSWORD` secrets are set correctly; verify the App Password is still valid at myaccount.google.com
- **yfinance error**: markets may be closed (holiday) or yfinance API changed; check the log
- **Script not found**: make sure all `.py` files are committed and pushed to `main`

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run signals + send email/SMS (requires env vars set)
set EMAIL_ADDRESS=tusharmanna@gmail.com
set EMAIL_PASSWORD=your_app_password
set PHONE_NUMBER=6789943844
python run_daily_signals.py

# Run just the TQQQ signal (no email)
python tushar_v2_signal.py

# Run just the QLD signal (no email)
python tushar_v2_qld_signal.py
```
