import time
from datetime import datetime


class Context:
    """Per-execution context passed to cron and task handlers."""

    def __init__(self, execution_id: str, attempt: int, scheduled_at: datetime, payload=None):
        self.execution_id = execution_id
        self.attempt = attempt
        self.scheduled_at = scheduled_at
        self.payload = payload
        self._logs: list[dict] = []
        self._tasks: list[dict] = []

    def _add_log(self, level: str, message: str, **meta):
        entry = {
            "timestamp": int(time.time() * 1000),
            "level": level,
            "message": message,
        }
        if meta:
            entry["meta"] = meta
        self._logs.append(entry)

    def log(self, message: str, **meta):
        """Add an info-level log entry."""
        self._add_log("info", message, **meta)

    def warn(self, message: str, **meta):
        """Add a warn-level log entry."""
        self._add_log("warn", message, **meta)

    def error(self, message: str, **meta):
        """Add an error-level log entry."""
        self._add_log("error", message, **meta)

    def debug(self, message: str, **meta):
        """Add a debug-level log entry."""
        self._add_log("debug", message, **meta)

    def task(self, name: str, payload=None):
        """Queue a fan-out task to be dispatched after this handler completes."""
        self._tasks.append({"name": name, "payload": payload})
