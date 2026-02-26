# Slack Duty Assignment Bot

Automatically selects 2 people for **Service Desk** and assigns 2 **Operations** tasks each to the remaining members. Runs twice daily: a **next-day preview at 5:30 PM** that locks in tomorrow's assignments, and a **morning announcement at 9:00 AM** that re-posts the locked-in result. Includes a **web control panel** for marking people as unavailable on specific dates without editing code.

## Features

### Core Selection
- **Random Service Desk selection**: Picks 2 team members for Service Desk duty
- **Random operations assignment**: Assigns 2 operations tasks to remaining team members
- **Consecutive selection protection**: No one can be selected for Service Desk more than 2 days in a row

### Next-Day Preview
- **5:30 PM preview**: At 5:30 PM Mon-Fri, runs the selection for the next workday and posts a preview to Slack
- **Lock-in**: The preview result is saved and reused at 9:00 AM the next morning — no re-randomization
- **Fallback**: If the preview didn't run (e.g., outage), the 9:00 AM run falls back to a fresh random selection
- **Override**: Set `FORCE_RESELECT=1` to ignore the locked-in preview and re-randomize at 9:00 AM (e.g., if someone calls in sick overnight)
- **Week boundaries**: Friday's preview correctly targets Monday with fresh weekly counts

### Fairness Guarantees
- **Weekly minimum guarantee**: Ensures every team member gets at least one Service Desk assignment per week
- **Weighted random selection**: People who haven't been on Service Desk this week get 3x higher selection weight
- **Thursday/Friday urgency**: If someone still needs their weekly assignment and time is running out, they're prioritized

### Unavailability Control Panel
- **Web UI**: Simple control panel to mark people as unavailable for specific dates — no code changes needed
- **Date picker**: Defaults to the next business day; select any future date
- **Upcoming view**: Shows all future unavailability at a glance with clear buttons
- **Automatic integration**: The bot reads date-based overrides at runtime alongside day-of-week exclusions
- **Password protected**: Optional shared password via `PANEL_PASSWORD` env var to prevent unauthorized access

### Scheduling & Exclusions
- **Day-specific exclusions**: Remove specific people from rotation on specific days via env vars (e.g., Alex unavailable Mondays)
- **Date-specific exclusions**: Mark people as unavailable for specific dates via the web control panel
- **Reduced operations days**: Configure days with 2+2 pattern (2 desk, 2 ops) instead of 2+all remaining
- **Time guards**: Only executes at 9:00-9:09 AM Pacific (morning) or 5:25-5:39 PM Pacific (preview)

### Onboarding Support
- **Onboarding rotation**: Optional separate rotation for onboarding support with FTE/Contractor types
- **Independent selection**: Onboarding assignments can overlap with Service Desk/Operations
- **Consecutive exclusion**: People selected for onboarding are soft-excluded from the next onboarding run (e.g., Monday's picks won't be picked again Tuesday)

### Day-Based Operations Assignment
Everyone in operations gets the same task types per day:

| Day | Task 1 | Task 2 |
|-----|--------|--------|
| Monday | Onboarding Tickets | System Imaging |
| Tuesday | System Imaging | 1 anyday task |
| Wednesday | 1 anyday task | 1 anyday task |
| Thursday | Onboarding Tickets | System Imaging |
| Friday | Onboarding Tickets | 1 anyday task |

- **Anyday tasks**: Assigned uniquely (1 person per task per day)
- **Task repetition avoidance**: Tries to assign different anyday tasks than last run

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
5. Once deployed, go to **Variables** tab and add:
   - `SLACK_WEBHOOK_URL` = your webhook URL from step 1
   - `PEOPLE` = comma-separated list of names (optional, falls back to defaults in `bot.py`)
   - `OPERATIONS` = comma-separated list of operations tasks (optional, falls back to defaults in `bot.py`)
6. Go to **Settings** → **Networking** → **Generate Domain** to get a public URL for the control panel

### 3. Persistent Storage (Recommended)

By default, Railway's filesystem is ephemeral — files like `selection_history.json` and `unavailable.json` are lost on redeploy. To persist data across deploys:

1. Railway dashboard → Service → **Volumes** → **Add Volume**
2. Set mount path to `/app/data`
3. Add env vars: `HISTORY_FILE=/app/data/selection_history.json` and `UNAVAILABLE_FILE=/app/data/unavailable.json`

### 4. Test

Run locally:
```bash
# Start the web server (control panel + scheduled bot)
python server.py

# Or test the bot directly:
SLACK_WEBHOOK_URL="" FORCE_RUN=1 python bot.py

# Test the next-day preview
SLACK_WEBHOOK_URL="" FORCE_PREVIEW=1 python bot.py

# Morning run ignoring preview (re-randomize)
SLACK_WEBHOOK_URL="" FORCE_RUN=1 FORCE_RESELECT=1 python bot.py
```

Setting `SLACK_WEBHOOK_URL=""` logs the message instead of posting to Slack.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL | **Required** |
| `PEOPLE` | Comma-separated list of team member names | `Alex,Ed,Gibran,Mirage,Paul` |
| `OPERATIONS` | Comma-separated list of operations tasks (supports Slack hyperlink format) | 9 Confluence-linked tasks |
| `FORCE_RUN` | Set to `1`, `true`, or `yes` to bypass the 9:00 AM schedule check | Not set |
| `FORCE_PREVIEW` | Set to `1`, `true`, or `yes` to bypass the 5:30 PM schedule check | Not set |
| `FORCE_RESELECT` | Set to `1`, `true`, or `yes` to ignore the locked-in preview and re-randomize at 9:00 AM | Not set |
| `HISTORY_FILE` | Path to selection history JSON file | `selection_history.json` |
| `UNAVAILABLE_FILE` | Path to date-based unavailability JSON file (written by control panel) | `unavailable.json` |
| `LOG_LEVEL` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `PANEL_PASSWORD` | Shared password for the control panel. If not set, no login required. | Not set |
| `SECRET_KEY` | Flask session secret key. Auto-generated if not set (sessions reset on restart). | Auto-generated |

### Day-Specific Exclusions

| Variable | Description | Default |
|----------|-------------|---------|
| `MONDAY_EXCLUSIONS` | People unavailable on Mondays (comma-separated, case-insensitive) | `Alex` |
| `TUESDAY_EXCLUSIONS` | People unavailable on Tuesdays | None |
| `WEDNESDAY_EXCLUSIONS` | People unavailable on Wednesdays | None |
| `THURSDAY_EXCLUSIONS` | People unavailable on Thursdays | None |
| `FRIDAY_EXCLUSIONS` | People unavailable on Fridays | None |

### Scheduling Options

| Variable | Description | Default |
|----------|-------------|---------|
| `REDUCED_OPS_DAYS` | Days with 2+2 pattern instead of 2+remaining (e.g., `Monday` or `Monday,Friday`) | `Monday` |
| `ONBOARDING_SCHEDULE` | Days and types for onboarding support. Format: `Day:Type,Day:Type` | `Monday:FTE,Tuesday:Contractor` |
| `SIMULATE_DAY` | Simulate a specific day for testing (e.g., `Monday`, `Tuesday`). Useful for testing exclusions and scheduling. | Not set |

## How It Works

### Daily Flow

1. **5:30 PM (Mon-Fri)**: The bot runs the selection algorithm for the **next workday** (Friday targets Monday). It posts a preview to Slack and saves the result to `selection_history.json`.
2. **9:00 AM (Mon-Fri)**: The bot checks for a locked-in preview matching today's date. If found, it re-posts the same assignments as the official morning announcement. If not found (or `FORCE_RESELECT=1`), it runs a fresh random selection.

### Selection Algorithm

**Service Desk Selection:**
1. **Exclude unavailable people**: Anyone excluded for the target day — via day-of-week env vars (e.g., `MONDAY_EXCLUSIONS`) or date-specific overrides from the control panel — is removed from the rotation entirely
2. **Apply consecutive protection**: Anyone selected for Service Desk 2 days in a row becomes ineligible (soft exclusion — can be overridden if short-staffed)
3. **Calculate weekly priority**:
   - People with 0 Service Desk assignments this week get 3x selection weight
   - On Thursday/Friday, if someone still needs their minimum and slots are running out, they're guaranteed a spot
4. **Select 2 for Service Desk**: Using weighted random selection

**Operations Assignment (Day-Based):**
Everyone gets the same task types based on the day:
- **Mon/Thu**: Onboarding Tickets + System Imaging
- **Tue**: System Imaging + 1 anyday task (unique)
- **Wed**: 2 anyday tasks (unique)
- **Fri**: Onboarding Tickets + 1 anyday task (unique)

**Onboarding Selection:**
1. Remove day-excluded people
2. Soft-exclude anyone from the last onboarding run (re-included if the pool would drop below 2)
3. Select 2 people randomly from the eligible pool

### History Tracking

The bot maintains state in `selection_history.json`:

```json
{
  "last_selections": [["Ed", "Alex"], ["Paul", "Alex"]],
  "last_ops": {
    "Ed": ["stockroom & cage clean up", "e-waste checks laptops"],
    "Gibran": ["system imaging fte/contract", "stockroom & cage clean up"]
  },
  "weekly_servicedesk": {
    "week": "2026-W07",
    "assignments": {"Mirage": 1, "Paul": 3, "Gibran": 2, "Ed": 2, "Alex": 2}
  },
  "last_onboarding": ["Ed", "Gibran"],
  "next_day_selection": {
    "target_date": "2026-02-25",
    "selected": ["Ed", "Gibran"],
    "assignments": {"Mirage": ["Task A", "Task B"], "Paul": ["Task C", "Task D"]},
    "onboarding_people": ["Alex"],
    "onboarding_type": "FTE"
  }
}
```

- `last_selections`: Last 2 days of Service Desk picks (for consecutive protection)
- `last_ops`: Last run's operations per person (for anyday task variety)
- `weekly_servicedesk`: Service Desk assignments per week (resets on new ISO week)
- `last_onboarding`: People from the most recent onboarding run (soft-excluded from the next onboarding selection)
- `next_day_selection`: Locked-in preview for the next workday (cleared after the 9:00 AM run uses it)

## Architecture

The project runs as a single Flask web service on Railway:

- **`server.py`** — Flask web server that serves the control panel UI and runs the bot on schedule via APScheduler
- **`bot.py`** — Core selection logic, Slack messaging, and history tracking
- **`templates/index.html`** — Control panel UI (vanilla HTML/JS, no build step)

### Scheduling

APScheduler inside `server.py` replicates the bot's schedule (minutes 0/30 at hours 0, 1, 16, 17 UTC, Mon-Sat). The bot's internal time guards (`should_run_now` and `should_run_preview`) filter to the correct Pacific time windows — only the 9:00 AM and 5:30 PM runs execute, extra fires are ignored.

### Data Files

Both are runtime artifacts (gitignored), created automatically:

- **`selection_history.json`** — Bot state: last selections, weekly counts, locked-in previews
- **`unavailable.json`** — Date-based unavailability entries from the control panel

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

## Example Output

### Next-Day Preview (5:30 PM)

**Monday evening previewing Tuesday:**
```
📋 *Tomorrow's Assignments (Tuesday)*

🖥️ *Service Desk*
    Ed
    Paul

⚙️ *Operations*
    Alex
        • System Imaging FTE/Contract
        • E-waste Checks Laptops
    Gibran
        • System Imaging FTE/Contract
        • Audit Idle Hardware
    Mirage
        • System Imaging FTE/Contract
        • Stockroom & Cage Clean up

👋 *Onboarding Support (Contractor):*
    Gibran
    Alex
ℹ️ _Class ≤8: 1 support needed | Class 9+: 2 support needed_
```

### Morning Announcement (9:00 AM)

**Thursday (Onboarding + Imaging):**
```
🖥️ *Service Desk*
    Ed
    Gibran

⚙️ *Operations*
    Alex
        • Onboarding Tickets
        • System Imaging FTE/Contract
    Mirage
        • Onboarding Tickets
        • System Imaging FTE/Contract
    Paul
        • Onboarding Tickets
        • System Imaging FTE/Contract
```

**Tuesday (Imaging + anyday):**
```
🖥️ *Service Desk*
    Ed
    Paul

⚙️ *Operations*
    Alex
        • System Imaging FTE/Contract
        • E-waste Checks Laptops
    Gibran
        • System Imaging FTE/Contract
        • Audit Idle Hardware
    Mirage
        • System Imaging FTE/Contract
        • Stockroom & Cage Clean up

👋 *Onboarding Support (Contractor):*
    Gibran
    Alex
ℹ️ _Class ≤8: 1 support needed | Class 9+: 2 support needed_
```

**Wednesday (anyday + anyday):**
```
🖥️ *Service Desk*
    Paul
    Mirage

⚙️ *Operations*
    Alex
        • Offboard Hold Checks
        • RMA Checks Laptops
    Ed
        • Audit Idle Hardware
        • RMA Checks Monitors
    Gibran
        • Stockroom & Cage Clean up
        • E-waste Checks Laptops
```

## Cost

Railway's Hobby plan is sufficient. The service runs as an always-on web process (for the control panel), with APScheduler handling the bot's twice-daily schedule internally.
