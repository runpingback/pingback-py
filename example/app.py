"""
Example Flask app using the Pingback Python SDK.

Usage:
    pip install flask
    PINGBACK_API_KEY=... PINGBACK_CRON_SECRET=... python app.py
"""

import os
import time

from flask import Flask

from pingback import Pingback

app = Flask(__name__)

pb = Pingback(
    api_key=os.environ.get("PINGBACK_API_KEY", ""),
    cron_secret=os.environ.get("PINGBACK_CRON_SECRET", ""),
    platform_url=os.environ.get("PINGBACK_PLATFORM_URL"),
    base_url=os.environ.get("BASE_URL"),
)


@pb.cron("health-check", "* * * * *")
def health_check(ctx):
    ctx.log("Health check started")
    ctx.log("All systems operational", timestamp=int(time.time()))
    return {"status": "healthy"}


@pb.cron("daily-cleanup", "0 3 * * *", retries=2, timeout="60s")
def daily_cleanup(ctx):
    ctx.log("Starting cleanup")
    removed = 42  # simulate
    ctx.log("Cleanup complete", removed=removed)
    return {"removed": removed}


@pb.cron("send-emails", "*/15 * * * *")
def send_emails(ctx):
    emails = ["user1@example.com", "user2@example.com", "user3@example.com"]
    for email in emails:
        ctx.task("send-email", {"to": email})
    ctx.log("Dispatched emails", count=len(emails))
    return {"dispatched": len(emails)}


@pb.task("send-email", retries=3, timeout="15s")
def send_email(ctx):
    to = ctx.payload["to"]
    ctx.log("Sending email", to=to)
    time.sleep(0.1)  # simulate
    ctx.log("Email sent", to=to)
    return {"sent": to}


@pb.task("process-webhook", timeout="30s")
def process_webhook(ctx):
    ctx.log("Processing webhook", execution_id=ctx.execution_id)
    ctx.debug("Raw payload", payload=ctx.payload)
    return {"processed": True}


app.route("/api/pingback", methods=["POST"])(pb.flask_handler())


@app.route("/")
def index():
    return "Pingback Python Example"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting server on :{port}")
    app.run(host="0.0.0.0", port=port)
