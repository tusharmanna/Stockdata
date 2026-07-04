# Notification Setup Guide

This guide explains how to set up email and SMS notifications for the daily signals GitHub Actions workflow.

## Overview

The `run_daily_signals.py` script sends two types of notifications:
1. **Email**: Full signal report with all strategy details
2. **SMS**: Short summary (via AT&T email-to-SMS gateway)

## Prerequisites

- Gmail account (for sending emails via SMTP)
- AT&T phone number (for SMS via email-to-SMS gateway)
- GitHub repository access to configure secrets

## Step 1: Generate Gmail App Password

Gmail requires an App Password for SMTP authentication (regular passwords won't work).

1. **Enable 2-Factor Authentication on your Google account**:
   - Go to https://myaccount.google.com/security
   - Under "How you sign in to Google", enable "2-Step Verification"

2. **Generate an App Password**:
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" as the app
   - Select "Other" as the device and enter "GitHub Actions"
   - Click "Generate"
   - **Copy the 16-character password** (it will look like: `xxxx xxxx xxxx xxxx`)
   - **Important**: Save this password securely - you won't be able to see it again

## Step 2: Configure GitHub Secrets

GitHub Actions needs three secrets to send notifications:

1. **Go to your repository settings**:
   - Navigate to: `https://github.com/tusharmanna/Stockdata/settings/secrets/actions`
   - Click "New repository secret"

2. **Add EMAIL_ADDRESS**:
   - Name: `EMAIL_ADDRESS`
   - Value: Your Gmail address (e.g., `tusharmanna@gmail.com`)
   - Click "Add secret"

3. **Add EMAIL_PASSWORD**:
   - Name: `EMAIL_PASSWORD`
   - Value: The 16-character App Password from Step 1 (remove spaces)
   - Click "Add secret"

4. **Add PHONE_NUMBER**:
   - Name: `PHONE_NUMBER`
   - Value: Your 10-digit AT&T phone number (e.g., `5551234567`)
   - **Note**: No dashes, spaces, or country code - just 10 digits
   - Click "Add secret"

## Step 3: Verify Secrets

To verify secrets are configured correctly:

```bash
gh secret list
```

You should see:
```
EMAIL_ADDRESS    Updated YYYY-MM-DD
EMAIL_PASSWORD   Updated YYYY-MM-DD
PHONE_NUMBER     Updated YYYY-MM-DD
```

**Note**: GitHub never shows secret values for security reasons.

## Step 4: Test the Workflow

Trigger a manual workflow run to test notifications:

```bash
gh workflow run daily_run.yml
```

Then monitor the run:

```bash
gh run watch
```

Or trigger via GitHub UI:
1. Go to https://github.com/tusharmanna/Stockdata/actions
2. Click "Daily Signals" workflow
3. Click "Run workflow" button
4. Click green "Run workflow" button

## Expected Notifications

If configured correctly, you should receive:

### Email (to EMAIL_ADDRESS)
- **Subject**: `Daily Signal - YYYY-MM-DD | REGIME | TQQQ: X.XXx | QLD: XX%`
- **Body**: Full signal report including:
  - Regime status (BULL/CASH)
  - QQQ close price and 189d high
  - TQQQ v2 and QLD v2 target exposures
  - Last 7 days exposure history

### SMS (to PHONE_NUMBER@txt.att.net)
- **Format**: `MM/DD REGIME X.X%|TQQQ:X.XXx(XX%vol)|QLD:XX%`
- **Example**: `07/03 BULL 4.4%|TQQQ:0.44x(102%vol)|QLD:65%`
- **Character limit**: 160 characters (standard SMS)

## Troubleshooting

### Email not received

1. **Check spam folder**: Gmail might filter automated emails
2. **Verify App Password**: Make sure you used the App Password, not your regular Gmail password
3. **Check GitHub Actions logs**:
   ```bash
   gh run view --log
   ```
   Look for errors like:
   - `[notify] EMAIL_ADDRESS or EMAIL_PASSWORD not set` → Secrets not configured
   - `SMTP error: 535` → Wrong password (use App Password)
   - `SMTP error: 530` → Authentication required (check App Password)

### SMS not received

1. **Verify AT&T gateway**: The email-to-SMS format is `PHONENUMBER@txt.att.net`
   - AT&T: `@txt.att.net`
   - Verizon: `@vtext.com`
   - T-Mobile: `@tmomail.net`
   - Sprint: `@messaging.sprintpcs.com`

2. **Check phone number format**: Must be exactly 10 digits (no dashes, spaces, or country code)

3. **Carrier blocking**: Some carriers block automated messages - check carrier settings

### Workflow fails but secrets are set

1. **View detailed logs**:
   ```bash
   gh run view $(gh run list --limit 1 --json databaseId -q '.[0].databaseId') --log
   ```

2. **Check for Python errors**: The script might fail before reaching notification code

3. **Test locally** (see below)

## Testing Locally

To test notifications without running the full workflow:

```bash
# Set environment variables (use your actual values)
export EMAIL_ADDRESS="your-email@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export PHONE_NUMBER="5551234567"

# Run the script
python run_daily_signals.py
```

Expected output:
```
[notify] Email sent to your-email@gmail.com
[notify] SMS sent to 5551234567@txt.att.net
```

## Security Notes

1. **Never commit secrets**: Secrets are in GitHub only - never in code
2. **App Password is safer**: App Passwords can be revoked without changing your main password
3. **Rotate regularly**: Generate a new App Password every 6-12 months
4. **Audit access**: Periodically review https://myaccount.google.com/apppasswords

## Alternative Carriers

If you're not on AT&T, update line 268 in `run_daily_signals.py`:

```python
# Current (AT&T):
sms_addr = f"{phone}@txt.att.net"

# Verizon:
sms_addr = f"{phone}@vtext.com"

# T-Mobile:
sms_addr = f"{phone}@tmomail.net"

# Sprint:
sms_addr = f"{phone}@messaging.sprintpcs.com"
```

Or create a new secret `SMS_GATEWAY` and update the script to use it.

## Workflow Schedule

The workflow runs automatically Monday-Friday at 3:30 PM EDT (19:30 UTC):

```yaml
on:
  schedule:
    - cron: "30 19 * * 1-5"   # 3:30 PM EDT (UTC-4)
```

**Note**: GitHub Actions uses UTC, so adjust for your timezone.

## Disabling Notifications

To disable notifications without removing secrets:

1. **Email only**: Comment out lines 256-262 in `run_daily_signals.py`
2. **SMS only**: Comment out lines 265-276 in `run_daily_signals.py`
3. **Both**: Comment out the entire `send_notifications(signals, exposures)` call on line 370

Or set empty environment variables in the workflow:

```yaml
env:
  EMAIL_ADDRESS: ""
  EMAIL_PASSWORD: ""
  PHONE_NUMBER: ""
```
