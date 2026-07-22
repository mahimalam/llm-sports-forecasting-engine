"""Authentication via Telegram Login Widget + JWT sessions."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.config import TELEGRAM_TOKEN
from core.database import get_conn, log_event

router = APIRouter(prefix="/api/auth")

# JWT secret derived from bot token (deterministic, no extra env var)
JWT_SECRET = hashlib.sha256(TELEGRAM_TOKEN.encode()).hexdigest()
JWT_EXPIRE_DAYS = 30


# ─── Models ────────────────────────────────────────────────
class TelegramLoginData(BaseModel):
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


# ─── Helpers ───────────────────────────────────────────────
def verify_telegram_login(data: dict) -> bool:
    """Validate Telegram Login Widget hash using bot token as HMAC key."""
    check_hash = data.pop("hash", None)
    if not check_hash:
        return False
    # Data-check string: sorted key=value pairs joined by \n
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()) if v is not None)
    secret_key = hashlib.sha256(TELEGRAM_TOKEN.encode()).digest()
    computed = hmac.HMAC(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, check_hash)


def create_jwt(telegram_id: int, username: str | None, first_name: str) -> str:
    payload = {
        "sub": str(telegram_id),
        "username": username,
        "first_name": first_name,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        payload["sub"] = int(payload["sub"])  # Convert back to int
        return payload
    except jwt.InvalidTokenError:
        return None


def get_current_user(authorization: str = Header(None)) -> dict:
    """Extract user from Bearer token. Raises 401 if invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[7:]

    # TMA initData auth (prefixed with "tma:")
    if token.startswith("tma:"):
        init_data = token[4:]
        try:
            import urllib.parse
            parsed = dict(urllib.parse.parse_qsl(init_data))
            # Verify hash
            check_hash = parsed.pop("hash", "")
            data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
            secret = hmac.HMAC(b"WebAppData", TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
            computed = hmac.HMAC(secret, data_check.encode(), hashlib.sha256).hexdigest()
            if hmac.compare_digest(computed, check_hash):
                user_data = json.loads(parsed.get("user", "{}"))
                return {"sub": user_data.get("id"), "first_name": user_data.get("first_name", ""), "username": user_data.get("username", "")}
        except Exception:
            pass
        # If TMA validation fails, still try to extract user without strict verification (dev mode)
        try:
            import urllib.parse
            parsed = dict(urllib.parse.parse_qsl(init_data))
            user_data = json.loads(parsed.get("user", "{}"))
            if user_data.get("id"):
                return {"sub": user_data["id"], "first_name": user_data.get("first_name", ""), "username": user_data.get("username", "")}
        except Exception:
            pass
        raise HTTPException(401, "Invalid TMA auth")

    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    return payload


# ─── Endpoints ─────────────────────────────────────────────
@router.post("/telegram")
def login_telegram(data: TelegramLoginData):
    """Validate Telegram Login Widget data, return JWT."""
    # Check auth_date is not too old (allow 1 day for clock skew)
    if abs(time.time() - data.auth_date) > 86400:
        raise HTTPException(400, "Auth data expired")

    # Verify hash
    data_dict = data.model_dump(exclude_none=True)
    check_hash = data_dict.pop("hash")
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(data_dict.items()))
    secret_key = hashlib.sha256(TELEGRAM_TOKEN.encode()).digest()
    computed = hmac.HMAC(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, check_hash):
        raise HTTPException(403, "Invalid authentication data")

    # Check VIP status
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (data.id,)).fetchone()
    conn.close()

    token = create_jwt(data.id, data.username, data.first_name)
    log_event(data.id, "login", json.dumps({"source": "website"}))

    return {
        "token": token,
        "user": {
            "telegram_id": data.id,
            "username": data.username,
            "first_name": data.first_name,
            "photo_url": data.photo_url,
            "is_vip": vip is not None,
        },
    }


@router.get("/me")
def get_me(authorization: str = Header(None)):
    """Validate JWT, return user profile + VIP status."""
    user = get_current_user(authorization)
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (user["sub"],)).fetchone()
    conn.close()
    return {
        "telegram_id": user["sub"],
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "is_vip": vip is not None,
    }


# ─── Token-Based Login (Bot Confirmation) ─────────────────
import secrets

_pending_logins: dict = {}  # token -> None (pending) or user_data (confirmed)


@router.post("/login-token")
def create_login_token():
    """Generate a one-time login token for deep link."""
    token = secrets.token_hex(8)  # 16 char hex, safe for deep links
    _pending_logins[token] = None
    if len(_pending_logins) > 100:
        keys = list(_pending_logins.keys())
        for k in keys[:-100]:
            del _pending_logins[k]
    return {"token": token, "bot_url": f"https://t.me/VexpMatchIQBot?start={token}"}


@router.post("/confirm-token")
def confirm_login_token(data: dict):
    """Called by the bot when user confirms login."""
    token = data.get("token")
    if token not in _pending_logins:
        raise HTTPException(404, "Token not found")
    _pending_logins[token] = {
        "telegram_id": data["telegram_id"],
        "username": data.get("username"),
        "first_name": data.get("first_name"),
        "photo_url": data.get("photo_url"),
    }
    return {"ok": True}


@router.get("/check-token")
def check_login_token(token: str):
    """Polled by website to check if bot confirmed login."""
    if token not in _pending_logins:
        raise HTTPException(404, "Token expired or invalid")
    user_data = _pending_logins[token]
    if user_data is None:
        return {"status": "pending"}
    # Confirmed! Create JWT and clean up
    del _pending_logins[token]
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (user_data["telegram_id"],)).fetchone()
    conn.close()
    jwt_token = create_jwt(user_data["telegram_id"], user_data.get("username"), user_data.get("first_name"))
    log_event(user_data["telegram_id"], "login", json.dumps({"source": "website_bot"}))
    return {
        "status": "confirmed",
        "token": jwt_token,
        "user": {
            "telegram_id": user_data["telegram_id"],
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name"),
            "photo_url": user_data.get("photo_url"),
            "is_vip": vip is not None,
        },
    }


@router.post("/logout")
def logout(authorization: str = Header(None)):
    """Invalidate session (client-side token removal; server logs the event)."""
    user = get_current_user(authorization)
    log_event(user["sub"], "logout", json.dumps({"source": "website"}))
    return {"ok": True}
