import hashlib
import hmac as _hmac
import time


MAX_CLOCK_SKEW = 300  # 5 minutes in seconds


def compute_hmac(timestamp: str, body: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for the given timestamp and body."""
    message = f"{timestamp}.{body}"
    return _hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()


def verify_signature(signature: str, timestamp: str, body: str, secret: str):
    """Verify HMAC signature. Raises ValueError if invalid."""
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid timestamp: {timestamp}")

    age = abs(int(time.time()) - ts)
    if age > MAX_CLOCK_SKEW:
        raise ValueError(f"Timestamp expired: {age}s old")

    expected = compute_hmac(timestamp, body, secret)
    if not _hmac.compare_digest(expected, signature):
        raise ValueError("Signature mismatch")
