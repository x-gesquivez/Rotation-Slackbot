import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import bot

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
UNAVAILABLE_FILE = Path(os.environ.get("UNAVAILABLE_FILE", "unavailable.json"))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")


@app.before_request
def require_auth():
    if not PANEL_PASSWORD:
        return  # No password configured, allow all
    if request.endpoint in ("health", "login"):
        return  # Health check and login must stay open
    if session.get("authenticated"):
        return  # Already logged in
    return redirect(url_for("login"))


def load_unavailable():
    """Load the unavailability data from disk."""
    if not UNAVAILABLE_FILE.exists():
        return {}
    try:
        return json.loads(UNAVAILABLE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_unavailable(data):
    """Save unavailability data, pruning past dates."""
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in data.items() if k >= today and v}
    UNAVAILABLE_FILE.write_text(json.dumps(pruned, indent=2))


# ---- Routes ----

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == PANEL_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"), code=303)
        error = "Wrong password"
    return render_template("login.html", error=error)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/people", methods=["GET"])
def get_people():
    people = bot.get_config_list("PEOPLE", bot.PEOPLE)
    return jsonify(people)


@app.route("/api/unavailable", methods=["GET"])
def get_unavailable():
    return jsonify(load_unavailable())


@app.route("/api/unavailable", methods=["POST"])
def set_unavailable():
    body = request.get_json()
    date_str = body.get("date")
    people = body.get("people", [])

    if not date_str:
        return jsonify({"error": "date is required"}), 400

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Invalid date format, use YYYY-MM-DD"}), 400

    data = load_unavailable()
    if people:
        data[date_str] = people
    else:
        data.pop(date_str, None)

    save_unavailable(data)
    return jsonify({"ok": True, "date": date_str, "people": people})


@app.route("/api/unavailable/<date_str>", methods=["DELETE"])
def delete_unavailable(date_str):
    data = load_unavailable()
    data.pop(date_str, None)
    save_unavailable(data)
    return jsonify({"ok": True})


@app.route("/health")
def health():
    return "ok"


# ---- Scheduler ----

def run_bot_job():
    """Wrapper to call the bot's main() from APScheduler."""
    logger.info("APScheduler triggering bot main()")
    try:
        bot.main()
    except Exception:
        logger.exception("Bot run failed")


def start_scheduler():
    scheduler = BackgroundScheduler(timezone="UTC")
    # Replicate the Railway cron: 0,30 0,1,16,17 * * 1-6 UTC
    # The bot's should_run_now() and should_run_preview() guards filter to correct Pacific times
    scheduler.add_job(
        run_bot_job,
        CronTrigger(
            minute="0,30",
            hour="0,1,16,17",
            day_of_week="mon-sat",
            timezone="UTC",
        ),
        id="bot_cron",
        name="Duty Bot Cron",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler started with bot cron job")
    return scheduler


# ---- Startup ----

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)

scheduler = start_scheduler()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
