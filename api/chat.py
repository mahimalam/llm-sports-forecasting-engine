"""Chat system: per-match rooms, in-memory buffer, polling API, invisible rate limiting."""
import json
import time
import threading
from collections import deque, defaultdict

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from api.auth import get_current_user
from core.database import get_conn, log_event

router = APIRouter(prefix="/api/chat")

# ─── In-Memory Buffer ──────────────────────────────────────
# Recent messages per room (fast reads, no DB hit)
_buffers: dict[str, deque] = {}
_write_queue: list = []
_lock = threading.Lock()
_typing: dict[str, dict] = defaultdict(dict)  # room -> {telegram_id: expire_ts}

# Rate limiting: {telegram_id: [timestamps]}
_rate_log: dict[int, list] = defaultdict(list)

BUFFER_SIZE = 200
FLUSH_INTERVAL = 2.0
SPAM_THRESHOLD = 30  # msgs in 60s = shadowban
SPAM_WINDOW = 60

# Keyword moderation filter
_BANNED_WORDS = {"fuck", "shit", "nigger", "faggot", "retard", "cunt", "bitch", "asshole", "dick", "pussy"}


def _moderate(msg: str) -> str:
    """Replace banned words with asterisks."""
    words = msg.split()
    return " ".join("***" if w.lower().strip(".,!?") in _BANNED_WORDS else w for w in words)


def _get_buffer(room: str) -> deque:
    if room not in _buffers:
        _buffers[room] = deque(maxlen=BUFFER_SIZE)
    return _buffers[room]


def _flush():
    """Background thread: batch-write queued messages to DB every 2s."""
    while True:
        time.sleep(FLUSH_INTERVAL)
        with _lock:
            batch = list(_write_queue)
            _write_queue.clear()
        if batch:
            try:
                conn = get_conn()
                conn.executemany(
                    "INSERT INTO chat_messages (room, telegram_id, username, first_name, is_vip, message, reply_to_id, is_system) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                conn.commit()
                conn.close()
            except Exception:
                pass


# Start background flusher
_flush_thread = threading.Thread(target=_flush, daemon=True)
_flush_thread.start()


def _is_spam(telegram_id: int) -> bool:
    """Invisible rate limiting. Returns True if user is spamming."""
    now = time.time()
    log = _rate_log[telegram_id]
    # Prune old entries
    _rate_log[telegram_id] = [t for t in log if now - t < SPAM_WINDOW]
    return len(_rate_log[telegram_id]) >= SPAM_THRESHOLD


# ─── Models ────────────────────────────────────────────────
class SendMessageBody(BaseModel):
    room: str = "global"
    message: str
    reply_to_id: int | None = None


class ReactBody(BaseModel):
    message_id: int
    emoji: str


# ─── Endpoints ─────────────────────────────────────────────
@router.get("/messages")
def get_messages(room: str = "global", after_id: int = 0, limit: int = 50):
    """Poll for messages. Serves from buffer if possible, falls back to DB."""
    buf = _get_buffer(room)

    # If buffer has messages and after_id is within buffer range, serve from memory
    if buf and after_id > 0:
        msgs = [m for m in buf if m["id"] > after_id]
        if msgs:
            return msgs[-limit:]

    # Fallback: DB query (scroll-back or first load)
    conn = get_conn()
    if after_id > 0:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE room=? AND id>? ORDER BY id ASC LIMIT ?",
            (room, after_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE room=? ORDER BY id DESC LIMIT ?",
            (room, limit),
        ).fetchall()
        rows = list(reversed(rows))
    conn.close()
    return [dict(r) for r in rows]


@router.post("/send")
def send_message(body: SendMessageBody, authorization: str = Header(None)):
    """Send a chat message. Invisible rate limiting."""
    user = get_current_user(authorization)
    tg_id = user["sub"]

    # Validate message
    msg = body.message.strip()
    if not msg or len(msg) > 500:
        raise HTTPException(400, "Message must be 1-500 characters")

    # Invisible spam check — silently drop if spamming
    if _is_spam(tg_id):
        # User thinks it's sent, but it's dropped (shadowban)
        return {"ok": True, "id": 0}

    # Record rate
    _rate_log[tg_id].append(time.time())

    # Check VIP for is_vip flag
    conn = get_conn()
    vip_row = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (tg_id,)).fetchone()
    conn.close()
    is_vip = 1 if vip_row else 0

    # Non-VIP: strip links
    if not is_vip and ("http://" in msg or "https://" in msg):
        msg = "[link removed — VIP only]"

    # Keyword moderation
    msg = _moderate(msg)

    # Create message object
    # Get next ID from buffer or DB
    buf = _get_buffer(body.room)
    next_id = (buf[-1]["id"] + 1) if buf else 1

    msg_obj = {
        "id": next_id,
        "room": body.room,
        "telegram_id": tg_id,
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "is_vip": is_vip,
        "message": msg,
        "reply_to_id": body.reply_to_id,
        "reactions": "{}",
        "is_system": 0,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Add to buffer
    buf.append(msg_obj)

    # Queue for DB write
    with _lock:
        _write_queue.append((
            body.room, tg_id, user.get("username"), user.get("first_name"),
            is_vip, msg, body.reply_to_id, 0,
        ))

    return {"ok": True, "id": next_id}


@router.post("/react")
def react_message(body: ReactBody, authorization: str = Header(None)):
    """Toggle an emoji reaction on a message."""
    user = get_current_user(authorization)
    allowed = {"🔥", "⚽", "😂", "👏", "👑", "💎", "🏆"}
    if body.emoji not in allowed:
        raise HTTPException(400, "Invalid emoji")

    conn = get_conn()
    row = conn.execute("SELECT reactions FROM chat_messages WHERE id=?", (body.message_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Message not found")

    reactions = json.loads(row["reactions"] or "{}")
    reactions[body.emoji] = reactions.get(body.emoji, 0) + 1
    conn.execute("UPDATE chat_messages SET reactions=? WHERE id=?", (json.dumps(reactions), body.message_id))
    conn.commit()
    conn.close()
    return {"ok": True, "reactions": reactions}


@router.post("/typing")
def set_typing(room: str = "global", authorization: str = Header(None)):
    """Mark user as typing (expires in 3s)."""
    user = get_current_user(authorization)
    _typing[room][user.get("first_name", "Someone")] = time.time() + 3
    return {"ok": True}


@router.get("/typing")
def get_typing(room: str = "global"):
    """Get users currently typing."""
    now = time.time()
    active = [name for name, exp in _typing.get(room, {}).items() if exp > now]
    return {"users": active}
