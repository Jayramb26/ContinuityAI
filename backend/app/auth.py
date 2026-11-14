"""Small signed demo-session tokens using only the Python standard library."""
import base64
import hashlib
import hmac
import json
import time

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def issue_token(subject: str, secret: str, ttl_seconds: int = 28800) -> str:
    payload = {"sub": subject, "role": "owner", "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + signature

def verify_token(token: str, secret: str):
    if not token or not secret or "." not in token:
        return None
    body, signature = token.split(".", 1)
    expected = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + padding))
        if int(payload.get("exp", 0)) <= int(time.time()) or not payload.get("sub"):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
