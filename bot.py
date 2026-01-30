import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Configuration
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "WEBOOK HERE")
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "selection_history.json"))

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PEOPLE = [
    "Alex", 
    "Ed", 
    "Gibran", 
    "Mirage", 
    "Paul",
]

OPERATIONS = [
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642315/Bayside+-+Daily+Operations+-+System+Imaging|System Imaging FTE/Contract>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642318/Bayside+-+Daily+Operations+-+Offboard+Checks|Offboard Hold Checks>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642316/Bayside+-+Daily+Operations+-+Audit+Idle+Hardware|Audit Idle Hardware>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642317/Bayside+-+Daily+Operations+-+Stockroom+Cage+Cleanup|Stockroom & Cage Clean up>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642324/Bayside+-+Daily+Operations+-+RMA+Checks+Laptops|RMA Checks Laptops>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642325/Bayside+-+Daily+Operations+-+RMA+Checks+Monitors|RMA Checks Monitors>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642319/Bayside+-+Daily+Operations+-+E-waste+Checks+Laptops|E-waste Checks Laptops>",
    "<https://confluence.zooxlabs.com/spaces/ITINT/pages/564642320/Bayside+-+Daily+Operations+-+E-waste+Checks+Desktops|E-waste Checks Desktop>",
    "<https://zoox.service-now.com/$pa_dashboard.do?sysparm_dashboard=fc872865fb432e90aa12f76255efdcde&sysparm_tab=875b3fa393ffae50e196383efaba10bb&sysparm_cancelable=true&sysparm_editable=undefined&sysparm_active_panel=false|Onboarding Tickets>",
]

# Day-specific defaults (can be overridden by env vars)
DEFAULT_DAY_EXCLUSIONS = {
    "MONDAY": "Alex",
}
DEFAULT_REDUCED_OPS_DAYS = "Monday"
DEFAULT_ONBOARDING_SCHEDULE = "Monday:FTE,Tuesday:Contractor"


def parse_env_list(value):
    if not value:
        return []
    parts = [item.strip() for item in value.replace("\n", ",").split(",")]
    return [item for item in parts if item]


def get_config_list(env_var, default_list):
    items = parse_env_list(os.environ.get(env_var, ""))
    return items if items else default_list


def env_truthy(env_var):
    value = os.environ.get(env_var, "")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def extract_task_name(task):
    """Extract display name from a task (handles Slack hyperlink format)."""
    if "|" in task and task.startswith("<"):
        return task.rsplit("|", 1)[-1].rstrip(">").strip()
    return task.strip()


def get_day_name(now=None):
    """Return the day name, or SIMULATE_DAY if set (for testing)."""
    simulated = os.environ.get("SIMULATE_DAY", "").strip()
    if simulated:
        logger.debug("Simulating day: %s", simulated)
        return simulated
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.strftime("%A")


def load_history():
    """Load selection history from file."""
    if not HISTORY_FILE.exists():
        return [], {}
    try:
        data = json.loads(HISTORY_FILE.read_text())
        selections = data.get("last_selections", [])[-2:]
        last_ops = data.get("last_ops", {})
        if not isinstance(last_ops, dict):
            last_ops = {}
        return selections, last_ops
    except (json.JSONDecodeError, OSError):
        return [], {}


def save_history(selected, history, assignments=None, prev_ops=None):
    """Save updated selection history, keeping only last 2."""
    new_history = (history + [selected])[-2:]
    if assignments:
        ops = {}
        for person, tasks in assignments.items():
            ops[person] = [extract_task_name(t).casefold() for t in tasks]
    else:
        ops = prev_ops or {}
    HISTORY_FILE.write_text(json.dumps({
        "last_selections": new_history,
        "last_ops": ops,
    }))


def get_excluded_people(history):
    """Return people who were selected in both of the last 2 runs."""
    if len(history) < 2:
        return set()
    return set(history[0]) & set(history[1])


def get_day_exclusions(now=None):
    """Return people excluded based on day-specific env vars.

    Env vars: MONDAY_EXCLUSIONS, TUESDAY_EXCLUSIONS, etc.
    Format: comma-separated names (e.g., "Alex,Ed")
    Matching is case-insensitive.
    Returns: tuple of (set of original names for logging, set of lowercased names for matching)
    """
    day_name = get_day_name(now).upper()  # e.g., "MONDAY"
    env_var = f"{day_name}_EXCLUSIONS"
    default = DEFAULT_DAY_EXCLUSIONS.get(day_name, "")
    excluded_names = parse_env_list(os.environ.get(env_var, default))
    # Return both original (for logging) and normalized (for matching)
    return set(excluded_names), {name.casefold() for name in excluded_names}


def get_onboarding_config(now=None):
    """Return onboarding type for today, or None if no onboarding.

    Parses ONBOARDING_SCHEDULE env var (format: "Monday:FTE,Tuesday:Contractor")
    Returns: str like "FTE" or "Contractor", or None if no onboarding today
    """
    schedule_str = os.environ.get("ONBOARDING_SCHEDULE", DEFAULT_ONBOARDING_SCHEDULE)
    today = get_day_name(now).casefold()

    for entry in schedule_str.split(","):
        entry = entry.strip()
        if ":" in entry:
            day, onb_type = entry.split(":", 1)
            if day.strip().casefold() == today:
                return onb_type.strip()
    return None


def select_onboarding(people, day_excluded_lower=None):
    """Select 2 people for onboarding support.

    Independent selection - can overlap with HelpDesk/Operations.
    Day exclusions still apply.
    """
    day_excluded_lower = day_excluded_lower or set()

    # Filter out day-excluded people
    available = [p for p in people if p.casefold() not in day_excluded_lower]

    if len(available) == 0:
        return []

    return random.sample(available, min(2, len(available)))


def should_run_now(now=None):
    if env_truthy("FORCE_RUN"):
        return True
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.weekday() < 5 and now.hour == 9 and now.minute < 10


def assign_operations(remaining, operations, last_ops=None):
    if not remaining:
        return {}
    if not operations:
        raise ValueError("No operations configured")

    if len(operations) == 1:
        return {person: [operations[0], operations[0]] for person in remaining}

    last_ops = last_ops if isinstance(last_ops, dict) else {}
    assignments = {}

    for person in remaining:
        # last_ops values are already normalized (casefolded) from save_history
        prev_tasks = set(last_ops.get(person, []))
        fresh = [op for op in operations if extract_task_name(op).casefold() not in prev_tasks]

        if len(fresh) >= 2:
            picked = random.sample(fresh, 2)
        elif len(fresh) == 1:
            # Guarantee the 1 fresh task, pick second from full list
            second = random.choice([op for op in operations if op != fresh[0]])
            picked = [fresh[0], second]
            random.shuffle(picked)
        else:
            # All tasks were done yesterday — fall back to full list
            picked = random.sample(operations, 2)

        assignments[person] = picked

    return assignments


def run_selection(people, operations, history_excluded=None, day_excluded_lower=None, reduced_ops=False, last_ops=None):
    """Select 2 people for HelpDesk and assign operations to the rest.

    - history_excluded: soft exclusion (can be re-included for HelpDesk if short-staffed)
    - day_excluded_lower: hard exclusion set (lowercased, completely removed from rotation)
    - reduced_ops: if True, only assign 2 people to Operations (not all remaining)
    - last_ops: yesterday's operations assignments per person (for avoiding repeats)
    """
    history_excluded = history_excluded or set()
    day_excluded_lower = day_excluded_lower or set()

    # Normalize once: map lowercased name -> original name
    name_lookup = {p.casefold(): p for p in people}
    history_excluded_lower = {n.casefold() for n in history_excluded}

    # Remove day-excluded people entirely from today's rotation
    available_keys = [k for k in name_lookup if k not in day_excluded_lower]

    # Apply history exclusions (soft - can be overridden if short-staffed)
    eligible_keys = [k for k in available_keys if k not in history_excluded_lower]

    # Fallback: if <2 eligible, re-include history-excluded (but NOT day-excluded)
    if len(eligible_keys) < 2:
        eligible_keys = available_keys[:]

    # Select up to 2 for HelpDesk
    num_helpdesk = min(2, len(eligible_keys))
    shuffled_keys = random.sample(eligible_keys, len(eligible_keys))
    selected_keys = shuffled_keys[:num_helpdesk]
    selected = [name_lookup[k] for k in selected_keys]

    # Remaining people for Operations
    remaining_keys = [k for k in available_keys if k not in selected_keys]

    # On reduced ops days: only assign 2 people to Operations
    if reduced_ops and len(remaining_keys) > 2:
        remaining_keys = random.sample(remaining_keys, 2)

    remaining = [name_lookup[k] for k in remaining_keys]
    assignments = assign_operations(remaining, operations, last_ops)
    return selected, assignments


def format_message(selected, assignments, onboarding_people=None, onboarding_type=None):
    lines = ["🖥️ *Service Desk*"]
    if selected:
        lines.extend([f"    {person}" for person in selected])
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("⚙️ *Operations*")

    if assignments:
        for person, operations in assignments.items():
            lines.append(f"    {person}")
            lines.append(f"        • {operations[0]}")
            lines.append(f"        • {operations[1]}")
    else:
        lines.append("    (none)")

    if onboarding_people:
        lines.append("")
        lines.append(f"👋 *Onboarding Support ({onboarding_type}):*")
        for person in onboarding_people:
            lines.append(f"    {person}")
        lines.append("ℹ️ _Class ≤8: 1 support needed | Class 9+: 2 support needed_")

    return "\n".join(lines)


def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        logger.warning("No SLACK_WEBHOOK_URL set. Message would be:\n%s", message)
        return

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": message},
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Message sent to Slack")
    except requests.RequestException:
        logger.exception("Failed to send message to Slack")


def main():
    if not should_run_now():
        logger.info(
            "Skipping run; not scheduled local time. Set FORCE_RUN=1 to override."
        )
        return

    people = get_config_list("PEOPLE", PEOPLE)
    operations = get_config_list("OPERATIONS", OPERATIONS)

    if not people:
        logger.error("No PEOPLE configured; skipping.")
        return

    # Load history and get exclusions
    history, last_ops = load_history()
    history_excluded = get_excluded_people(history)
    if history_excluded:
        logger.info("Excluding from HelpDesk (selected 2x in a row): %s", history_excluded)

    # Get day-specific exclusions (completely removed from rotation)
    now = datetime.now(LOCAL_TZ)
    day_excluded, day_excluded_lower = get_day_exclusions(now)
    if day_excluded:
        logger.info("Excluding from rotation (unavailable today): %s", day_excluded)

    # Check if today is a reduced operations day (2+2 instead of 2+3)
    reduced_ops_days = parse_env_list(os.environ.get("REDUCED_OPS_DAYS", DEFAULT_REDUCED_OPS_DAYS))
    reduced_ops_days_lower = {d.casefold() for d in reduced_ops_days}
    today_name = get_day_name(now).casefold()  # e.g., "monday"
    is_reduced_ops_day = today_name in reduced_ops_days_lower

    try:
        selected, assignments = run_selection(
            people, operations, history_excluded, day_excluded_lower, is_reduced_ops_day, last_ops
        )
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return

    # Check for onboarding today
    onboarding_type = get_onboarding_config(now)
    onboarding_people = []
    if onboarding_type:
        onboarding_people = select_onboarding(people, day_excluded_lower)
        logger.info("Onboarding (%s): %s", onboarding_type, onboarding_people)

    message = format_message(selected, assignments, onboarding_people, onboarding_type)
    send_to_slack(message)

    # Save selection history (best-effort, don't crash if filesystem is read-only)
    try:
        save_history(selected, history, assignments, prev_ops=last_ops)
    except OSError:
        logger.warning("Could not save selection history (read-only filesystem?)")


if __name__ == "__main__":
    main()
