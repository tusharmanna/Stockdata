# Notification Setup Guide

This guide explains how to set up email and phone push notifications for the daily signals GitHub Actions workflow.

## Overview

The `run_daily_signals.py` script sends two types of notifications:
1. **Email**: Full signal report with all strategy details + `portfolio_dashboard.html` attached (self-contained copy)
2. **Phone push**: Short summary via [ntfy.sh](https://ntfy.sh)

> **History note**: Phone notifications originally used the AT&T email-to-SMS gateway
> (`PHONE_NUMBER@txt.att.net`). AT&T permanently shut that gateway down on
> **2025-06-17**, so it was replaced with ntfy.sh push notifications (2026-07-07).

## Prerequisites

- Gmail account (for sending emails via SMTP)
- The **ntfy** app on your phone (free, Play Store / App Store) for push notifications
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

## Step 2: Set Up ntfy Push

1. Install the **ntfy** app on your phone.
2. In the app, tap **+ Subscribe to topic** and enter the topic name (must match the
   `NTFY_TOPIC` secret — currently `tusharstrategy`).
3. That's it — no account needed. Anyone who knows the topic name can read/send to it,
   so treat the topic name like a lightweight password (use something unguessable if
   the content is sensitive).

## Step 3: Configure GitHub Secrets

GitHub Actions needs three **repository secrets** (Settings → Secrets and variables →
**Actions** → **Secrets** tab — NOT Variables, NOT Environment/Codespaces/Dependabot
secrets):

| Name | Value |
|---|---|
| `EMAIL_ADDRESS` | Your Gmail address |
| `EMAIL_PASSWORD` | The 16-character App Password from Step 1 (**remove spaces**) |
| `NTFY_TOPIC` | Your ntfy topic name (e.g. `tusharstrategy`) |

Via CLI:

```bash
gh secret set EMAIL_ADDRESS   # prompts for value
gh secret set EMAIL_PASSWORD
gh secret set NTFY_TOPIC
```

## Step 4: Verify Secrets

```bash
gh secret list
```

You should see:
```
EMAIL_ADDRESS    Updated YYYY-MM-DD
EMAIL_PASSWORD   Updated YYYY-MM-DD
NTFY_TOPIC       Updated YYYY-MM-DD
```

**Note**: GitHub never shows secret values for security reasons.

## Step 5: Test the Workflow

```bash
gh workflow run daily_run.yml
gh run watch
```

Or trigger via GitHub UI: Actions → "Daily Signals" → "Run workflow".

## Expected Notifications

### Email (to EMAIL_ADDRESS)
- **Subject**: `Daily Signal - YYYY-MM-DD | REGIME | TQQQ: X.XXx | QLD: XX%`
- **Body**: Regime status, QQQ close and 189d high, TQQQ/QLD target exposures,
  last 7 days exposure history
- **Attachment**: `portfolio_dashboard.html` — self-contained (signal data inlined),
  opens on any device

### Phone push (ntfy topic)
- **Title**: `REGIME | TQQQ X.XXx | QLD XX%`
- **Body**: `YYYY-MM-DD REGIME X.X% below 189d high | TQQQ: X.XXx (XX% vol) | QLD: XX%`

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
     (check they are *Repository secrets* under Actions, with exact names)
   - `SMTP error: 535` → Wrong password (use App Password)
   - `SMTP error: 530` → Authentication required (check App Password)

### Push not received

1. **Topic mismatch**: The topic in the ntfy app must exactly match the `NTFY_TOPIC` secret
2. **Log says `[notify] NTFY_TOPIC not set`** → secret missing
3. **Log says `[notify] ntfy error: ...`** → ntfy.sh unreachable or rate-limited; re-run
4. Messages are cached by ntfy.sh ~12h — subscribing shortly after a send still shows it

### Workflow fails but secrets are set

1. **View detailed logs**:
   ```bash
   gh run view $(gh run list --limit 1 --json databaseId -q '.[0].databaseId') --log
   ```
2. **Check for Python errors**: The script might fail before reaching notification code
3. **Test locally** (see below)

## Testing Locally

```bash
export EMAIL_ADDRESS="your-email@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export NTFY_TOPIC="tusharstrategy"

python run_daily_signals.py
```

Expected output:
```
[notify] Email sent to your-email@gmail.com
[notify] Push sent via ntfy.sh
```

## Security Notes

1. **Never commit secrets**: Secrets are in GitHub only - never in code
2. **App Password is safer**: App Passwords can be revoked without changing your main password
3. **Rotate regularly**: Generate a new App Password every 6-12 months
4. **Audit access**: Periodically review https://myaccount.google.com/apppasswords
5. **ntfy topic = password**: Anyone who knows the topic name can read the pushes;
   pick an unguessable name if that matters

## Workflow Schedule

The workflow runs automatically Monday-Friday at 3:30 PM EDT (19:30 UTC):

```yaml
on:
  schedule:
    - cron: "30 19 * * 1-5"   # 3:30 PM EDT (UTC-4)
```

**Note**: GitHub Actions uses UTC, so adjust for your timezone.

## Disabling Notifications

Set empty environment variables in the workflow:

```yaml
env:
  EMAIL_ADDRESS: ""
  EMAIL_PASSWORD: ""
  NTFY_TOPIC: ""
```

Or comment out the `send_notifications(signals, exposures)` call in `run_daily_signals.py`.
