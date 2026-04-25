import dataclasses
import inspect
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, get_type_hints

from pingback.context import Context
from pingback.hmac import verify_signature
from pingback.register import register as register_functions

logger = logging.getLogger("pingback")

DEFAULT_PLATFORM_URL = "https://api.pingback.lol"


def _resolve_payload(handler, raw_payload):
    """Inspect handler signature and deserialize payload if typed."""
    sig = inspect.signature(handler)
    params = list(sig.parameters.values())

    # No second parameter — call with just ctx
    if len(params) < 2:
        return None, False

    param = params[1]
    # No type annotation — pass raw dict
    hints = get_type_hints(handler) if hasattr(handler, '__annotations__') else {}
    annotation = hints.get(param.name)
    if annotation is None:
        return raw_payload, True

    # Pydantic model
    try:
        from pydantic import BaseModel
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation(**(raw_payload or {})), True
    except ImportError:
        pass

    # Dataclass
    if dataclasses.is_dataclass(annotation) and isinstance(annotation, type):
        return annotation(**(raw_payload or {})), True

    # Any other type — pass raw
    return raw_payload, True


class Pingback:
    """Pingback SDK client."""

    def __init__(
            self,
            api_key: str,
            cron_secret: str,
            platform_url: Optional[str] = None,
            base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.cron_secret = cron_secret
        self.platform_url = platform_url or DEFAULT_PLATFORM_URL
        self.base_url = base_url
        self._functions: dict = {}
        self._registered = False
        self._register_lock = threading.Lock()

    def cron(self, name: str, schedule: str, retries: int = 0, timeout: Optional[str] = None, concurrency: int = 1):
        """Decorator to register a cron job."""

        def decorator(fn):
            self._functions[name] = {
                "type": "cron",
                "schedule": schedule,
                "handler": fn,
                "retries": retries,
                "timeout": timeout,
                "concurrency": concurrency,
            }
            return fn

        return decorator

    def task(self, name: str, retries: int = 0, timeout: Optional[str] = None, concurrency: int = 1,
             unpack_payload=True):
        """Decorator to register a background task."""

        def decorator(fn):
            handler = fn
            if unpack_payload:
                sig = inspect.signature(fn)
                params = list(sig.parameters.values())
                extra = [p for p in params if p.name != 'ctx']
                needs_unpack = len(extra) > 1 or (len(extra) == 1 and extra[0].name != 'payload')
                has_ctx = any(p.name == 'ctx' for p in params)

                if needs_unpack:
                    def handler(ctx):
                        if has_ctx:
                            return fn(ctx, **(ctx.payload or {}))
                        return fn(**(ctx.payload or {}))

            self._functions[name] = {
                "type": "task",
                "schedule": None,
                "handler": handler,
                "retries": retries,
                "timeout": timeout,
                "concurrency": concurrency,
            }
            return fn

        return decorator

    def _ensure_registered(self):
        """Register functions with the platform once."""
        with self._register_lock:
            if not self._registered and self.api_key:
                self._registered = True
                try:
                    register_functions(self._functions, self.api_key, self.platform_url, self.base_url)
                except Exception as e:
                    logger.error(f"[pingback] Registration failed: {e}")

    def handle(self, body: bytes, headers: dict) -> dict:
        """Process an execution request. Framework-agnostic core method."""
        self._ensure_registered()

        body_str = body.decode("utf-8") if isinstance(body, bytes) else body

        sig = headers.get("X-Pingback-Signature") or headers.get("x-pingback-signature", "")
        ts = headers.get("X-Pingback-Timestamp") or headers.get("x-pingback-timestamp", "")
        try:
            verify_signature(sig, ts, body_str, self.cron_secret)
        except ValueError as e:
            return {"_status": 401, "error": f"unauthorized: {e}"}

        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            return {"_status": 400, "error": "invalid payload"}

        func_name = data.get("function", "")
        fn_def = self._functions.get(func_name)
        if not fn_def:
            return {"_status": 404, "error": f'function "{func_name}" not found'}

        scheduled_at = datetime.fromisoformat(data.get("scheduledAt", "").replace("Z", "+00:00"))
        ctx = Context(
            execution_id=data.get("executionId", ""),
            attempt=data.get("attempt", 1),
            scheduled_at=scheduled_at,
            payload=data.get("payload"),
        )

        handler = fn_def["handler"]
        payload, has_payload_param = _resolve_payload(handler, data.get("payload"))

        start = time.time()
        try:
            result = handler(ctx, payload) if has_payload_param else handler(ctx)
            duration_ms = int((time.time() - start) * 1000)
            return {
                "_status": 200,
                "status": "success",
                "result": result,
                "logs": ctx._logs,
                "tasks": ctx._tasks,
                "durationMs": duration_ms,
            }
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            return {
                "_status": 500,
                "status": "error",
                "error": str(e),
                "logs": ctx._logs,
                "tasks": ctx._tasks,
                "durationMs": duration_ms,
            }

    def register(self):
        """Eagerly register functions with the platform. Call after all functions are defined."""
        self._ensure_registered()

    def flask_handler(self):
        """Return a Flask view function."""
        self._ensure_registered()

        def handler():
            from flask import request, jsonify
            result = self.handle(request.data, dict(request.headers))
            status = result.pop("_status", 200)
            return jsonify(result), status

        return handler

    def fastapi_handler(self):
        """Return a FastAPI endpoint."""
        self._ensure_registered()

        async def handler(request):
            from fastapi.responses import JSONResponse
            body = await request.body()
            result = self.handle(body, dict(request.headers))
            status = result.pop("_status", 200)
            return JSONResponse(result, status_code=status)

        return handler

    def trigger(self, task_name: str, payload=None) -> str:
        """Trigger a task programmatically. Returns execution_id."""
        data = json.dumps({"task": task_name, "payload": payload}).encode()
        url = f"{self.platform_url}/api/v1/trigger"

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                return result["executionId"]
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"Trigger failed ({e.code}): {body}")
