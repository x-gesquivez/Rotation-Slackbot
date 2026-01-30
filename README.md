# Slack Duty Assignment Bot (Railway Hosted)

Automatically selects 2 people for **Service Desk** and assigns 2 **Operations** tasks each to the remaining members, every weekday at 9am Pacific time.

## Features

- Random selection for Service Desk duty
- Random assignment of operations tasks to remaining team members
- **Consecutive selection protection**: No one can be selected for Service Desk more than 2 days in a row
- 10-minute scheduling window to handle delayed cron execution

## Setup

### 1. Create a Slack Webhook

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Create a new app → "From scratch"
3. Select your workspace
4. Go to **Incoming Webhooks** → Toggle it ON
5. Click **Add New Webhook to Workspace**
6. Select the channel where messages should post
7. Copy the webhook URL

### 2. Deploy to Railway

1. Push this code to a GitHub repo
2. Go to [railway.app](https://railway.app) and sign in
3. Click **New Project** → **Deploy from GitHub repo**
4. Select your repo
5. Once deployed, go to **Variables** tab
6. Add variables:
   - `SLACK_WEBHOOK_URL` = your webhook URL from step 1
   - `PEOPLE` = comma-separated list of names (optional, falls back to defaults in `bot.py`)
   - `OPERATIONS` = comma-separated list of operations tasks (optional, falls back to defaults in `bot.py`)

### 3. Customize

Either update variables in Railway or edit `bot.py` to change defaults:

- `PEOPLE` — Team member names or Slack handles
- `OPERATIONS` — List of operations tasks to assign

### 4. Test

In Railway, go to **Settings** → Click **Run** to trigger manually.

Or run locally:
```bash
FORCE_RUN=1 python bot.py
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL | Yes |
| `PEOPLE` | Comma-separated list of names | No (uses defaults) |
| `OPERATIONS` | Comma-separated list of tasks | No (uses defaults) |
| `FORCE_RUN` | Set to `1` to bypass schedule check | No |
| `HISTORY_FILE` | Path to selection history JSON | No (defaults to `selection_history.json`) |
| `MONDAY_EXCLUSIONS` | People unavailable on Mondays (comma-separated, case-insensitive) | No |
| `TUESDAY_EXCLUSIONS` | People unavailable on Tuesdays | No |
| `WEDNESDAY_EXCLUSIONS` | People unavailable on Wednesdays | No |
| `THURSDAY_EXCLUSIONS` | People unavailable on Thursdays | No |
| `FRIDAY_EXCLUSIONS` | People unavailable on Fridays | No |
| `REDUCED_OPS_DAYS` | Days with 2+2 pattern instead of 2+3 (e.g., "Monday" or "Monday,Friday") | No |
| `ONBOARDING_SCHEDULE` | Days and types for onboarding support (format: `Day:Type,Day:Type`). Default: `Monday:FTE,Tuesday:Contractor` | No |
| `SIMULATE_DAY` | Simulate a specific day for testing (e.g., `Monday`, `Tuesday`) | No |

## Notes

- Runs at 9:00-9:09am Pacific time (PST/PDT) Monday-Friday
- Railway's cron uses UTC; `railway.toml` runs at 16:00 and 17:00 UTC with a local-time guard in `bot.py`
- Selection history is stored in `selection_history.json` to track consecutive selections

## To Use Slack @mentions

Replace names with Slack member IDs:

```python
PEOPLE = [
    "<@U01ABC123>",  # Alice
    "<@U02DEF456>",  # Bob
    # etc.
]
```

To find member IDs: Click on a user in Slack → View profile → Click "..." → Copy member ID.

