import json
import logging
import urllib.request
from typing import Optional

logger = logging.getLogger("pingback")


def register(functions: dict, api_key: str, platform_url: str, base_url: Optional[str]):
    """Register functions with the Pingback platform."""
    funcs = []
    for name, fn_def in functions.items():
        entry = {
            "name": name,
            "type": fn_def["type"],
            "options": {
                "retries": fn_def["retries"],
                "timeout": fn_def["timeout"],
                "concurrency": fn_def["concurrency"],
            },
        }
        if fn_def["type"] == "cron":
            entry["schedule"] = fn_def["schedule"]
        entry["options"] = {k: v for k, v in entry["options"].items() if v is not None and v != 0}
        funcs.append(entry)

    payload = {"functions": funcs}
    if base_url:
        payload["endpoint_url"] = base_url

    body = json.dumps(payload).encode()
    url = f"{platform_url}/api/v1/register"

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            jobs = result.get("jobs", [])
            logger.info(f"[pingback] Registered {len(jobs)} function(s) with platform")
    except Exception as e:
        logger.error(f"[pingback] Registration failed: {e}")
