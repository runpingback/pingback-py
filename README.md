# pingback-py

Python SDK for [Pingback](https://pingback.lol) — reliable cron jobs and background tasks.

## Installation

```bash
pip install pingback-py
```

## Quick Start

```python
import os
from pingback import Pingback

pb = Pingback(
    api_key=os.environ["PINGBACK_API_KEY"],
    cron_secret=os.environ["PINGBACK_CRON_SECRET"],
)

@pb.cron("cleanup", "0 3 * * *", retries=2, timeout="60s")
def cleanup(ctx):
    removed = remove_expired_sessions()
    ctx.log("Removed sessions", count=removed)
    return {"removed": removed}

@pb.task("send-email", retries=3, timeout="15s")
def send_email(ctx):
    to = ctx.payload["to"]
    deliver_email(to)
    ctx.log("Sent email", to=to)
    return {"sent": to}
```

## Framework Integration

### Flask

```python
from flask import Flask

app = Flask(__name__)
app.route("/api/pingback", methods=["POST"])(pb.flask_handler())
```

### FastAPI

```python
from fastapi import FastAPI

app = FastAPI()
app.post("/api/pingback")(pb.fastapi_handler())
```

### Django

```python
# settings.py
from pingback import Pingback

pb = Pingback(
    api_key="pb_live_...",
    cron_secret="...",
    platform_url="https://api.pingback.lol",  # default
    base_url="https://myapp.com",              # your app's public URL
)

```

```python
# views.py
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from myproject.settings import pb

@csrf_exempt
def pingback_handler(request):
    result = pb.handle(request.body, dict(request.headers))
    status = result.pop("_status", 200)
    return JsonResponse(result, status=status)
```

Register your url:

```python
# urls.py
from django.urls import path
from myapp.views import pingback_handler

urlpatterns = [
    path("api/pingback", pingback_handler),
]
```

Register on startup in your `AppConfig`:

```python
# apps.py
from django.apps import AppConfig

class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self):
        from myprojct.settings import pb 
        pb.register()
```

### Any Framework

```python
result = pb.handle(body=request_body_bytes, headers=request_headers_dict)
```

> **Registration:** `flask_handler()` and `fastapi_handler()` automatically register your functions with the platform on startup. For Django or other frameworks, call `pb.register()` after all functions are defined. Registration only runs once.

## Defining Functions

### Cron Jobs

```python
@pb.cron("daily-report", "0 9 * * *", retries=3, timeout="60s")
def daily_report(ctx):
    report = generate_report()
    ctx.log("Report generated", rows=report.row_count)
    return report
```

### Background Tasks

```python
@pb.task("process-upload", retries=2, timeout="5m")
def process_upload(ctx):
    file_id = ctx.payload["file_id"]
    result = process_file(file_id)
    ctx.log("Processed file", file_id=file_id)
    return result
```

### Typed Payloads

Task handlers can accept a typed second parameter for autocomplete, validation, and self-documenting code. Works with dataclasses and Pydantic models:

```python
from dataclasses import dataclass

@dataclass
class EmailPayload:
    to: str
    subject: str
    priority: int = 1

@pb.task("send-email", retries=3)
def send_email(ctx, payload: EmailPayload):
    # payload.to, payload.subject — full autocomplete
    send_mail(payload.to, payload.subject)
    ctx.log("Sent", to=payload.to, priority=payload.priority)
```

With Pydantic (`pip install pydantic`):

```python
from pydantic import BaseModel

class OrderPayload(BaseModel):
    order_id: str
    amount: float
    email: str

@pb.task("process-order")
def process_order(ctx, payload: OrderPayload):
    # validated, with defaults and type coercion
    ctx.log("Processing", order_id=payload.order_id)
```

### Unpacked Kwargs

Task handlers can receive payload fields directly as keyword arguments — no need to extract from a `payload` object:

```python
@pb.task("send-password-reset", retries=3)
def send_password_reset(ctx, otp_code: str, user_email: list[str]):
    message = f"Your OTP is {otp_code}."
    send_mail(message=message, recipient_list=user_email)
    ctx.log("Sent reset email", to=user_email)
```

Triggered with:

```python
pb.trigger("send-password-reset", {"otp_code": "482910", "user_email": ["user@example.com"]})
```

This activates automatically when `unpack_payload=True` (the default) and the handler has **more than one parameter beyond `ctx`**, or a **single extra parameter not named `payload`**. The SDK unpacks `ctx.payload` as keyword arguments into the function. Set `unpack_payload=False` to disable this and use the raw dict or typed payload styles instead.

All four styles are supported:

| Style | Signature | Payload access |
|-------|-----------|----------------|
| No param | `def job(ctx)` | `ctx.payload["key"]` |
| Raw dict | `def job(ctx, payload)` | `payload["key"]` |
| Typed | `def job(ctx, payload: MyType)` | `payload.key` |
| Unpacked kwargs | `def job(ctx, field1, field2)` | `field1`, `field2` directly |

### Fan-Out

```python
@pb.cron("send-emails", "*/15 * * * *")
def send_emails(ctx):
    pending = get_pending_emails()
    for email in pending:
        ctx.task("send-email", {"to": email.recipient, "subject": email.subject})
    ctx.log("Dispatched emails", count=len(pending))
    return {"dispatched": len(pending)}
```

### Workflows (Task Chaining)

Tasks can call `ctx.task()` to chain into multi-step workflows with branching:

```python
@dataclass
class Order:
    order_id: str
    amount: float
    email: str

@pb.task("validate-order", retries=2)
def validate_order(ctx, order: Order):
    ctx.log("Validating", order_id=order.order_id)

    if order.amount <= 0:
        ctx.task("notify-failure", {"order_id": order.order_id, "reason": "Invalid amount"})
        return {"valid": False}

    ctx.task("charge-payment", {"order_id": order.order_id, "amount": order.amount, "email": order.email})
    return {"valid": True}

@pb.task("charge-payment", retries=3)
def charge_payment(ctx, payload: Order):
    charge = stripe.Charge.create(amount=int(payload.amount * 100))
    ctx.log("Charged", charge_id=charge.id)
    ctx.task("send-confirmation", {"email": payload.email, "order_id": payload.order_id})

@pb.task("send-confirmation", retries=2)
def send_confirmation(ctx, payload):
    send_email(payload["email"], "Order confirmed")
    ctx.log("Confirmation sent")
```

Each step runs as its own execution with independent retries and logging. The workflow graph in your dashboard visualizes the full chain.

## Programmatic Triggering

```python
exec_id = pb.trigger("send-email", {"to": "user@example.com"})
```

## Structured Logging

```python
ctx.log("message")                         # info
ctx.log("message", key="value")            # info with metadata
ctx.warn("slow query", ms=2500)            # warning
ctx.error("failed", code="E001")           # error
ctx.debug("cache stats", hits=847)         # debug
```

## Configuration

```python
pb = Pingback(
    api_key="pb_live_...",
    cron_secret="...",
    platform_url="https://api.pingback.lol",  # default
    base_url="https://myapp.com",              # your app's public URL
)
```

### Function Options

```python
@pb.cron("job", "* * * * *", retries=3, timeout="30s", concurrency=5)
@pb.task("job", retries=3, timeout="30s", concurrency=5, unpack_payload=True)
```

`unpack_payload` (default `True`) — when the handler has multiple parameters beyond `ctx`, or a single extra parameter not named `payload`, the SDK unpacks `ctx.payload` as keyword arguments. Set to `False` to always use the raw dict / typed payload styles.

## Environment Variables

```
PINGBACK_API_KEY=pb_live_...        # From your Pingback project settings
PINGBACK_CRON_SECRET=...            # From your Pingback project settings
```

## How It Works

1. Define cron jobs and tasks with `@pb.cron()` and `@pb.task()` decorators
2. Mount the handler using your framework's routing
3. Functions are registered with the platform on startup (`flask_handler()` and `fastapi_handler()` do this automatically; for Django or other frameworks, call `pb.register()`)
4. The platform sends signed HTTP requests to your handler when jobs are due
5. The handler verifies the HMAC signature, executes the function, and returns results
6. Fan-out tasks and workflow chains are dispatched independently by the platform
