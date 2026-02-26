import json
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Configuration
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
LOCAL_TZ = ZoneInfo("America/Los_Angeles")
HISTORY_FILE = Path(os.environ.get("HISTORY_FILE", "selection_history.json"))
UNAVAILABLE_FILE = Path(os.environ.get("UNAVAILABLE_FILE", "unavailable.json"))
UNAVAILABLE_RANGES_FILE = Path(os.environ.get("UNAVAILABLE_RANGES_FILE", "unavailable_ranges.json"))

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

# Day-based operations assignment rules
# Each day defines what task types everyone in operations gets
DAY_OPS_RULES = {
    "monday": ["onboarding", "imaging"],      # Onboarding Tickets + System Imaging
    "tuesday": ["imaging", "anyday"],         # System Imaging + 1 anyday task
    "wednesday": ["anyday", "anyday"],        # 2 anyday tasks only
    "thursday": ["onboarding", "imaging"],    # Onboarding Tickets + System Imaging
    "friday": ["onboarding", "anyday"],       # Onboarding Tickets + 1 anyday task
}


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


def find_task_by_name(operations, name_fragment):
    """Find task containing name fragment (case-insensitive)."""
    name_lower = name_fragment.casefold()
    for task in operations:
        if name_lower in extract_task_name(task).casefold():
            return task
    return None


def get_anyday_tasks(operations):
    """Return tasks that are not onboarding or system imaging."""
    excluded_names = {"onboarding", "system imaging"}
    available = []
    for task in operations:
        task_name = extract_task_name(task).casefold()
        if not any(excl in task_name for excl in excluded_names):
            available.append(task)
    return available


def pick_anyday_task(pool, used_tasks, yesterday_tasks):
    """Pick an unused anyday task, preferring ones not done yesterday.

    Args:
        pool: list of available anyday tasks
        used_tasks: set of task names (casefolded) already assigned today
        yesterday_tasks: list of task names (casefolded) this person did yesterday

    Returns: task string or None if no tasks available
    """
    yesterday_set = set(yesterday_tasks)

    # Filter out already-used tasks
    available = [t for t in pool if extract_task_name(t).casefold() not in used_tasks]
    if not available:
        return None

    # Prefer tasks not done yesterday
    fresh = [t for t in available if extract_task_name(t).casefold() not in yesterday_set]
    if fresh:
        return random.choice(fresh)

    # Fall back to any available task
    return random.choice(available)


def get_day_name(now=None):
    """Return the day name, or SIMULATE_DAY if set (for testing)."""
    simulated = os.environ.get("SIMULATE_DAY", "").strip()
    if simulated:
        logger.debug("Simulating day: %s", simulated)
        return simulated
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.strftime("%A")


def get_week_key(now=None):
    """Return ISO week identifier (YYYY-WNN format) for week reset detection."""
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.strftime("%G-W%V")


def get_remaining_workdays(now=None):
    """Return remaining workdays in week including today (Mon=5, Fri=1, Weekend=0)."""
    simulated = os.environ.get("SIMULATE_DAY", "").strip()
    if simulated:
        day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4}
        weekday = day_map.get(simulated.casefold(), 0)
    else:
        if now is None:
            now = datetime.now(LOCAL_TZ)
        weekday = now.weekday()
    if weekday > 4:
        return 0
    return 5 - weekday


def load_history():
    """Load selection history from file, including weekly ServiceDesk tracking.

    Returns: (selections, last_ops, weekly, preview, last_onboarding)
        preview is the next_day_selection dict or None.
        last_onboarding is the list of people from the last onboarding run.
    """
    current_week = get_week_key()
    default_weekly = {"week": current_week, "assignments": {}}

    if not HISTORY_FILE.exists():
        return [], {}, default_weekly, None, []
    try:
        data = json.loads(HISTORY_FILE.read_text())
        selections = data.get("last_selections", [])[-2:]
        last_ops = data.get("last_ops", {})
        if not isinstance(last_ops, dict):
            last_ops = {}

        weekly = data.get("weekly_servicedesk", {})
        if weekly.get("week") != current_week:
            weekly = default_weekly

        preview = data.get("next_day_selection")
        last_onboarding = data.get("last_onboarding", [])
        return selections, last_ops, weekly, preview, last_onboarding
    except (json.JSONDecodeError, OSError):
        return [], {}, default_weekly, None, []


def save_history(selected, history, assignments=None, prev_ops=None, weekly=None,
                 onboarding_people=None):
    """Save updated selection history, keeping only last 2."""
    new_history = (history + [selected])[-2:]
    if assignments:
        ops = {}
        for person, tasks in assignments.items():
            ops[person] = [extract_task_name(t).casefold() for t in tasks]
    else:
        ops = prev_ops or {}

    if weekly is None:
        weekly = {"week": get_week_key(), "assignments": {}}

    for person in selected:
        weekly["assignments"][person] = weekly["assignments"].get(person, 0) + 1

    data = {
        "last_selections": new_history,
        "last_ops": ops,
        "weekly_servicedesk": weekly,
        "last_onboarding": onboarding_people or [],
    }
    HISTORY_FILE.write_text(json.dumps(data))


def save_preview(preview_data):
    """Save next-day selection preview to history file without touching other fields."""
    try:
        data = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    data["next_day_selection"] = preview_data
    HISTORY_FILE.write_text(json.dumps(data))


def get_excluded_people(history):
    """Return people who were selected in both of the last 2 runs."""
    if len(history) < 2:
        return set()
    return set(history[0]) & set(history[1])


def get_date_overrides(target_date=None):
    """Read date-specific unavailability from unavailable.json.

    Args:
        target_date: datetime object for the date to check (defaults to today in LOCAL_TZ)

    Returns: set of names marked unavailable for that date
    """
    if not UNAVAILABLE_FILE.exists():
        return set()
    try:
        data = json.loads(UNAVAILABLE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    if target_date is None:
        target_date = datetime.now(LOCAL_TZ)
    date_key = target_date.strftime("%Y-%m-%d")
    return set(data.get(date_key, []))


def get_range_overrides(target_date=None):
    """Read range-based unavailability from unavailable_ranges.json.

    Args:
        target_date: datetime object for the date to check (defaults to today in LOCAL_TZ)

    Returns: set of names marked unavailable via ranges for that date
    """
    if not UNAVAILABLE_RANGES_FILE.exists():
        return set()
    try:
        data = json.loads(UNAVAILABLE_RANGES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(data, list):
        return set()
    if target_date is None:
        target_date = datetime.now(LOCAL_TZ)
    date_key = target_date.strftime("%Y-%m-%d")
    result = set()
    for entry in data:
        start = entry.get("start", "")
        end = entry.get("end", "")
        person = entry.get("person", "")
        if person and start <= date_key <= end:
            result.add(person)
    return result


def get_day_exclusions(now=None):
    """Return people excluded based on day-specific env vars and date overrides.

    Merges:
      1. Day-of-week env vars (MONDAY_EXCLUSIONS, etc.) -- recurring, static
      2. Date-specific overrides from unavailable.json -- ad-hoc, from web UI
      3. Range-based overrides from unavailable_ranges.json -- extended absences

    Returns: tuple of (set of original names for logging, set of lowercased names for matching)
    """
    day_name = get_day_name(now).upper()  # e.g., "MONDAY"
    env_var = f"{day_name}_EXCLUSIONS"
    default = DEFAULT_DAY_EXCLUSIONS.get(day_name, "")
    excluded_names = parse_env_list(os.environ.get(env_var, default))
    # Merge date-specific and range-based overrides
    date_overrides = get_date_overrides(now)
    range_overrides = get_range_overrides(now)
    all_excluded = set(excluded_names) | date_overrides | range_overrides
    # Return both original (for logging) and normalized (for matching)
    return all_excluded, {name.casefold() for name in all_excluded}


def get_people_needing_weekly_assignment(weekly, people):
    """Return set of people (lowercased) with 0 ServiceDesk assignments this week."""
    assignments = weekly.get("assignments", {})
    return {p.casefold() for p in people if assignments.get(p, 0) == 0}


def calculate_weekly_priority(eligible_keys, people_needing, remaining_days):
    """Determine selection strategy based on urgency.

    Returns: (must_prioritize: bool, priority_pool: list)
    - must_prioritize: True if we MUST select from people_needing (Thu/Fri urgency)
    - priority_pool: eligible people who need their weekly assignment
    """
    eligible_needing = [k for k in eligible_keys if k in people_needing]

    max_remaining_slots = remaining_days * 2
    if people_needing and len(people_needing) >= max_remaining_slots:
        return True, eligible_needing

    return False, eligible_needing


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


def select_onboarding(people, day_excluded_lower=None, last_onboarding=None):
    """Select 2 people for onboarding support.

    Independent selection - can overlap with HelpDesk/Operations.
    Day exclusions still apply. People from the last onboarding run are
    soft-excluded (re-included if the pool would be too small).
    """
    day_excluded_lower = day_excluded_lower or set()
    last_onboarding_lower = {p.casefold() for p in (last_onboarding or [])}

    # Filter out day-excluded people
    available = [p for p in people if p.casefold() not in day_excluded_lower]

    if len(available) == 0:
        return []

    # Soft-exclude people from last onboarding run
    eligible = [p for p in available if p.casefold() not in last_onboarding_lower]
    if len(eligible) < 2:
        eligible = available  # fallback: re-include if pool too small

    return random.sample(eligible, min(2, len(eligible)))


def should_run_now(now=None):
    if env_truthy("FORCE_RUN"):
        return True
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.weekday() < 5 and now.hour == 9 and now.minute < 10


def get_next_workday(now=None):
    """Return the next workday as a datetime (skips weekends).

    Mon→Tue, Tue→Wed, ..., Thu→Fri, Fri→Mon, Sat→Mon, Sun→Mon.
    """
    if now is None:
        now = datetime.now(LOCAL_TZ)
    next_day = now + timedelta(days=1)
    # Skip Saturday (5) and Sunday (6)
    while next_day.weekday() > 4:
        next_day += timedelta(days=1)
    return next_day


def should_run_preview(now=None):
    """Return True if we should run the next-day preview (5:30 PM Pacific, Mon-Fri)."""
    if env_truthy("FORCE_PREVIEW"):
        return True
    if now is None:
        now = datetime.now(LOCAL_TZ)
    return now.weekday() < 5 and now.hour == 17 and 25 <= now.minute < 40


def assign_operations_by_day(ops_people, operations, day_name, last_ops):
    """Assign operations tasks based on day rules.

    Everyone gets the same task types per day:
    - Mon: Onboarding + Imaging
    - Tue: Imaging + anyday
    - Wed: anyday + anyday
    - Thu: Onboarding + Imaging
    - Fri: Onboarding + anyday

    Args:
        ops_people: list of people assigned to operations today
        operations: list of all operation tasks
        day_name: current day name (e.g., "monday")
        last_ops: dict of {person: [task_names]} from last run

    Returns: assignments dict {person: [task1, task2]}
    """
    if not ops_people:
        return {}
    if not operations:
        raise ValueError("No operations configured")

    day_lower = day_name.casefold()
    rules = DAY_OPS_RULES.get(day_lower, ["anyday", "anyday"])
    last_ops = last_ops if isinstance(last_ops, dict) else {}

    assignments = {p: [] for p in ops_people}
    used_anyday = set()

    onboarding = find_task_by_name(operations, "onboarding")
    imaging = find_task_by_name(operations, "system imaging")
    anyday_pool = get_anyday_tasks(operations)

    logger.info("Day rules for %s: %s", day_name, rules)

    for person in ops_people:
        for slot_type in rules:
            if slot_type == "onboarding":
                if onboarding:
                    assignments[person].append(onboarding)
                else:
                    logger.warning("Onboarding task not found in operations list")
            elif slot_type == "imaging":
                if imaging:
                    assignments[person].append(imaging)
                else:
                    logger.warning("System Imaging task not found in operations list")
            else:  # anyday
                task = pick_anyday_task(anyday_pool, used_anyday, last_ops.get(person, []))
                if task:
                    assignments[person].append(task)
                    used_anyday.add(extract_task_name(task).casefold())
                else:
                    logger.warning("No more anyday tasks available for %s", person)

    return assignments


def run_selection(people, operations, history_excluded=None, day_excluded_lower=None,
                  reduced_ops=False, last_ops=None, weekly=None, remaining_days=5,
                  day_name=None):
    """Select 2 people for HelpDesk and assign operations to the rest.

    - history_excluded: soft exclusion (can be re-included for HelpDesk if short-staffed)
    - day_excluded_lower: hard exclusion set (lowercased, completely removed from rotation)
    - reduced_ops: if True, only assign 2 people to Operations (not all remaining)
    - last_ops: last run's operations assignments per person (for avoiding repeats)
    - weekly: weekly ServiceDesk tracking for minimum guarantee
    - remaining_days: workdays left in week for urgency calculation
    - day_name: current day name for day-based task assignment
    """
    history_excluded = history_excluded or set()
    day_excluded_lower = day_excluded_lower or set()
    weekly = weekly or {"week": get_week_key(), "assignments": {}}
    day_name = day_name or get_day_name()

    # Normalize once: map lowercased name -> original name
    name_lookup = {p.casefold(): p for p in people}
    history_excluded_lower = {n.casefold() for n in history_excluded}

    # Remove day-excluded people entirely from today's rotation
    available_keys = [k for k in name_lookup if k not in day_excluded_lower]

    # Get people who still need their weekly ServiceDesk assignment
    people_needing = get_people_needing_weekly_assignment(weekly, people)
    people_needing_available = people_needing - day_excluded_lower

    # Apply history exclusions (soft - can be overridden if short-staffed)
    eligible_keys = [k for k in available_keys if k not in history_excluded_lower]

    # Fallback: if <2 eligible, re-include history-excluded (but NOT day-excluded)
    if len(eligible_keys) < 2:
        eligible_keys = available_keys[:]

    # Calculate weekly priority
    must_prioritize, priority_pool = calculate_weekly_priority(
        eligible_keys, people_needing_available, remaining_days
    )

    num_helpdesk = min(2, len(eligible_keys))

    if must_prioritize and priority_pool:
        # MUST select from those who need weekly assignment (Thu/Fri urgency)
        num_from_priority = min(num_helpdesk, len(priority_pool))
        selected_keys = random.sample(priority_pool, num_from_priority)

        if num_from_priority < num_helpdesk:
            others = [k for k in eligible_keys if k not in selected_keys]
            if others:
                selected_keys.append(random.choice(others))

        logger.info(
            "Weekly minimum enforcement: prioritizing %s",
            [name_lookup[k] for k in selected_keys if k in priority_pool]
        )
    elif people_needing_available:
        # PREFER those needing assignment (weighted random, 3x weight)
        weighted_pool = []
        for k in eligible_keys:
            weight = 3 if k in people_needing_available else 1
            weighted_pool.extend([k] * weight)
        random.shuffle(weighted_pool)

        selected_keys = []
        for k in weighted_pool:
            if k not in selected_keys:
                selected_keys.append(k)
                if len(selected_keys) == num_helpdesk:
                    break
    else:
        # All have met weekly minimum - standard random selection
        shuffled_keys = random.sample(eligible_keys, len(eligible_keys))
        selected_keys = shuffled_keys[:num_helpdesk]

    selected = [name_lookup[k] for k in selected_keys]

    # Remaining people for Operations
    remaining_keys = [k for k in available_keys if k not in selected_keys]

    # On reduced ops days: only assign 2 people to Operations
    if reduced_ops and len(remaining_keys) > 2:
        remaining_keys = random.sample(remaining_keys, 2)

    remaining = [name_lookup[k] for k in remaining_keys]
    assignments = assign_operations_by_day(remaining, operations, day_name, last_ops)
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


def format_preview_message(selected, assignments, onboarding_people=None,
                           onboarding_type=None, target_day_name="Tomorrow"):
    """Format preview message for next-day assignments."""
    lines = [f"📋 *Tomorrow's Assignments ({target_day_name})*", ""]
    lines.append("🖥️ *Service Desk*")
    if selected:
        lines.extend([f"    {person}" for person in selected])
    else:
        lines.append("    (none)")
    lines.append("")
    lines.append("⚙️ *Operations*")

    if assignments:
        for person, ops in assignments.items():
            lines.append(f"    {person}")
            for task in ops:
                lines.append(f"        • {task}")
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


def run_preview():
    """Run next-day selection at 5:30 PM and post preview to Slack."""
    now = datetime.now(LOCAL_TZ)
    next_wd = get_next_workday(now)
    target_date = next_wd.strftime("%Y-%m-%d")
    target_day_name = next_wd.strftime("%A")
    day_name = target_day_name.casefold()

    logger.info("Running preview for %s (%s)", target_day_name, target_date)

    people = get_config_list("PEOPLE", PEOPLE)
    operations = get_config_list("OPERATIONS", OPERATIONS)

    if not people:
        logger.error("No PEOPLE configured; skipping preview.")
        return

    # Load current history (today's state)
    history, last_ops, weekly, _, last_onboarding = load_history()

    # Get exclusions for the TARGET day (tomorrow)
    day_excluded, day_excluded_lower = get_day_exclusions(next_wd)

    # Handle week boundary (e.g., Friday preview for Monday)
    target_week = get_week_key(next_wd)
    if weekly.get("week") != target_week:
        logger.info("Week boundary: resetting weekly counts for %s", target_week)
        weekly = {"week": target_week, "assignments": {}}

    history_excluded = get_excluded_people(history)
    if history_excluded:
        logger.info("Preview excluding from HelpDesk (selected 2x in a row): %s", history_excluded)
    if day_excluded:
        logger.info("Preview excluding from rotation (%s unavailable): %s", target_day_name, day_excluded)

    remaining_days = get_remaining_workdays(next_wd)
    logger.info("Preview remaining workdays in target week: %d", remaining_days)

    # Check reduced ops for target day
    reduced_ops_days = parse_env_list(os.environ.get("REDUCED_OPS_DAYS", DEFAULT_REDUCED_OPS_DAYS))
    reduced_ops_days_lower = {d.casefold() for d in reduced_ops_days}
    is_reduced_ops_day = day_name in reduced_ops_days_lower

    try:
        selected, assignments = run_selection(
            people, operations, history_excluded, day_excluded_lower,
            is_reduced_ops_day, last_ops, weekly, remaining_days, day_name
        )
    except ValueError as exc:
        logger.error("Configuration error during preview: %s", exc)
        return

    # Check onboarding for target day
    onboarding_type = get_onboarding_config(next_wd)
    onboarding_people = []
    if onboarding_type:
        onboarding_people = select_onboarding(people, day_excluded_lower, last_onboarding)
        logger.info("Preview onboarding (%s): %s", onboarding_type, onboarding_people)

    logger.info("Preview selected for Service Desk: %s", selected)

    # Save preview (preserves existing history fields)
    preview_data = {
        "target_date": target_date,
        "selected": selected,
        "assignments": {p: list(tasks) for p, tasks in assignments.items()},
        "onboarding_people": onboarding_people,
        "onboarding_type": onboarding_type,
    }
    try:
        save_preview(preview_data)
    except OSError:
        logger.warning("Could not save preview (read-only filesystem?)")

    message = format_preview_message(
        selected, assignments, onboarding_people, onboarding_type, target_day_name
    )
    send_to_slack(message)


def main():
    # Check for preview run first (5:30 PM)
    if should_run_preview():
        run_preview()
        return

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
    history, last_ops, weekly, preview, last_onboarding = load_history()
    logger.info("Weekly ServiceDesk counts: %s", weekly.get("assignments", {}))

    # Check for locked-in preview from last night's 5:30 PM run
    now = datetime.now(LOCAL_TZ)
    today_str = now.strftime("%Y-%m-%d")
    use_preview = (
        preview
        and preview.get("target_date") == today_str
        and not env_truthy("FORCE_RESELECT")
    )

    if use_preview:
        logger.info("Using locked-in preview for %s", today_str)
        selected = preview["selected"]
        assignments = preview["assignments"]
        onboarding_people = preview.get("onboarding_people", [])
        onboarding_type = preview.get("onboarding_type")

        message = format_message(selected, assignments, onboarding_people, onboarding_type)
        send_to_slack(message)

        # Save history to update last_selections and weekly counts (also clears preview)
        try:
            save_history(selected, history, assignments, prev_ops=last_ops, weekly=weekly,
                         onboarding_people=onboarding_people if onboarding_people else last_onboarding)
        except OSError:
            logger.warning("Could not save selection history (read-only filesystem?)")
        return

    if preview and preview.get("target_date") != today_str:
        logger.info("Stale preview found (target: %s, today: %s); running fresh selection",
                     preview.get("target_date"), today_str)
    elif env_truthy("FORCE_RESELECT"):
        logger.info("FORCE_RESELECT set; ignoring preview and re-randomizing")

    # Normal selection flow (no preview or stale/overridden preview)
    history_excluded = get_excluded_people(history)
    if history_excluded:
        logger.info("Excluding from HelpDesk (selected 2x in a row): %s", history_excluded)

    # Get day-specific exclusions (completely removed from rotation)
    day_excluded, day_excluded_lower = get_day_exclusions(now)
    if day_excluded:
        logger.info("Excluding from rotation (unavailable today): %s", day_excluded)

    # Calculate remaining workdays for weekly minimum enforcement
    remaining_days = get_remaining_workdays(now)
    logger.info("Remaining workdays this week: %d", remaining_days)

    # Check if today is a reduced operations day (2+2 instead of 2+3)
    reduced_ops_days = parse_env_list(os.environ.get("REDUCED_OPS_DAYS", DEFAULT_REDUCED_OPS_DAYS))
    reduced_ops_days_lower = {d.casefold() for d in reduced_ops_days}
    today_name = get_day_name(now).casefold()  # e.g., "monday"
    is_reduced_ops_day = today_name in reduced_ops_days_lower

    try:
        selected, assignments = run_selection(
            people, operations, history_excluded, day_excluded_lower,
            is_reduced_ops_day, last_ops, weekly, remaining_days,
            today_name
        )
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return

    # Check for onboarding today
    onboarding_type = get_onboarding_config(now)
    onboarding_people = []
    if onboarding_type:
        onboarding_people = select_onboarding(people, day_excluded_lower, last_onboarding)
        logger.info("Onboarding (%s): %s", onboarding_type, onboarding_people)

    message = format_message(selected, assignments, onboarding_people, onboarding_type)
    send_to_slack(message)

    # Save selection history (best-effort, don't crash if filesystem is read-only)
    try:
        save_history(selected, history, assignments, prev_ops=last_ops, weekly=weekly,
                     onboarding_people=onboarding_people if onboarding_people else last_onboarding)
    except OSError:
        logger.warning("Could not save selection history (read-only filesystem?)")


if __name__ == "__main__":
    main()
