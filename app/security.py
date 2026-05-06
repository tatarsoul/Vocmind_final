import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from .config import settings


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "exp": int(time.time()) + int(settings.auth_token_ttl_hours) * 3600,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64url_encode(raw)
    sig = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def decode_access_token(token: str) -> dict:
    body, sig = token.split(".", 1)
    expected = hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid token signature")

    payload = json.loads(_b64url_decode(body).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Token expired")

    return payload


def validate_telegram_init_data(init_data: str) -> dict:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise ValueError("Telegram hash is missing")

    auth_date = int(pairs.get("auth_date", "0") or "0")
    if int(time.time()) - auth_date > int(settings.telegram_auth_max_age_seconds):
        raise ValueError("Telegram init data is too old")

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(pairs.items())
    )

    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.strip().encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(received_hash, calculated_hash):
        print("TG HASH MISMATCH")
        print("BOT TOKEN REPR:", repr(settings.telegram_bot_token))
        print("DATA CHECK STRING:", data_check_string)
        print("RECEIVED HASH:", received_hash)
        print("CALCULATED HASH:", calculated_hash)
        raise ValueError("Telegram init data hash mismatch")

    user_raw = pairs.get("user")
    if not user_raw:
        raise ValueError("Telegram user is missing")

    user = json.loads(user_raw)
    if not isinstance(user, dict):
        raise ValueError("Telegram user payload is invalid")

    return user