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
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def pingback_handler(request):
    result = pb.handle(request.body, dict(request.headers))
    status = result.pop("_status", 200)
    return JsonResponse(result, status=status)
```

### Any Framework

```python
result = pb.handle(body=request_body_bytes, headers=request_headers_dict)
```

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

### Fan-Out

```python
@pb.cron("send-emails", "*/15 * * * *")
def send_emails(ctx):
    pending = get_pending_emails()
    for email in pending:
        ctx.task("send-email", {"id": email.id})
    ctx.log("Dispatched emails", count=len(pending))
    return {"dispatched": len(pending)}
```

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
@pb.task("job", retries=3, timeout="30s", concurrency=5)
```

## Environment Variables

```
PINGBACK_API_KEY=pb_live_...        # From your Pingback project settings
PINGBACK_CRON_SECRET=...            # From your Pingback project settings
```

## How It Works

1. Define cron jobs and tasks with `@pb.cron()` and `@pb.task()` decorators
2. Mount the handler using your framework's routing
3. On the first request, the SDK registers your functions with the Pingback platform
4. The platform sends signed HTTP requests to your handler when jobs are due
5. The handler verifies the HMAC signature, executes the function, and returns results
6. Fan-out tasks are dispatched independently by the platform
