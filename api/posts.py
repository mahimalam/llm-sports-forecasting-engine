"""Post-prediction system: VIP users post their predictions, follow others, leaderboard."""
import json
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from api.auth import get_current_user
from core.database import get_conn, log_event

router = APIRouter(prefix="/api/posts")


class CreatePostBody(BaseModel):
    match_id: int
    predicted_winner: str  # 'home' | 'draw' | 'away'
    predicted_score: str | None = None
    confidence: int = 50
    reasoning: str | None = None


@router.post("/create")
def create_post(body: CreatePostBody, authorization: str = Header(None)):
    """VIP-only: create a prediction post for a match."""
    user = get_current_user(authorization)
    tg_id = user["sub"]

    # Check VIP
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (tg_id,)).fetchone()
    if not vip:
        conn.close()
        raise HTTPException(403, "VIP required to post predictions")

    # Check rate limit (max 3 per matchday)
    existing = conn.execute(
        "SELECT COUNT(*) as c FROM user_posts WHERE telegram_id=? AND match_id=?", (tg_id, body.match_id)
    ).fetchone()
    if existing["c"] > 0:
        conn.close()
        raise HTTPException(409, "Already posted for this match")

    # Validate predicted_winner
    if body.predicted_winner not in ("home", "draw", "away"):
        conn.close()
        raise HTTPException(400, "predicted_winner must be home, draw, or away")

    conn.execute(
        "INSERT INTO user_posts (telegram_id, match_id, predicted_winner, predicted_score, confidence, reasoning) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tg_id, body.match_id, body.predicted_winner, body.predicted_score, body.confidence, body.reasoning),
    )
    # Update profile
    conn.execute(
        "INSERT INTO user_profiles (telegram_id, username, first_name, total_posts) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(telegram_id) DO UPDATE SET total_posts = total_posts + 1, updated_at = datetime('now')",
        (tg_id, user.get("username"), user.get("first_name")),
    )
    conn.commit()
    conn.close()
    log_event(tg_id, "post_created", json.dumps({"match_id": body.match_id}))
    return {"ok": True}


@router.get("/match/{match_id}")
def get_match_posts(match_id: int, authorization: str = Header(None)):
    """Get all prediction posts for a match. Requires auth (gated access)."""
    user = get_current_user(authorization)
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.*, up.username, up.first_name, up.accuracy_pct, up.follower_count "
        "FROM user_posts p LEFT JOIN user_profiles up ON p.telegram_id = up.telegram_id "
        "WHERE p.match_id=? ORDER BY p.created_at DESC",
        (match_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/user/{telegram_id}")
def get_user_posts(telegram_id: int):
    """Get a user's post history (public)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_posts WHERE telegram_id=? ORDER BY created_at DESC LIMIT 20",
        (telegram_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/follow/{target_id}")
def follow_user(target_id: int, authorization: str = Header(None)):
    """Follow/unfollow a predictor (toggle)."""
    user = get_current_user(authorization)
    tg_id = user["sub"]
    if tg_id == target_id:
        raise HTTPException(400, "Cannot follow yourself")

    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM user_follows WHERE follower_id=? AND followed_id=?", (tg_id, target_id)
    ).fetchone()

    if existing:
        conn.execute("DELETE FROM user_follows WHERE follower_id=? AND followed_id=?", (tg_id, target_id))
        conn.execute("UPDATE user_profiles SET follower_count = MAX(0, follower_count - 1) WHERE telegram_id=?", (target_id,))
        action = "unfollowed"
    else:
        conn.execute("INSERT INTO user_follows (follower_id, followed_id) VALUES (?, ?)", (tg_id, target_id))
        conn.execute(
            "INSERT INTO user_profiles (telegram_id, follower_count) VALUES (?, 1) "
            "ON CONFLICT(telegram_id) DO UPDATE SET follower_count = follower_count + 1",
            (target_id,),
        )
        action = "followed"

    conn.commit()
    conn.close()
    return {"ok": True, "action": action}


@router.get("/leaderboard")
def leaderboard(limit: int = 20):
    """Ranked list of top predictors by accuracy × followers."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT telegram_id, username, first_name, total_posts, correct_posts, accuracy_pct, follower_count "
        "FROM user_profiles WHERE total_posts >= 3 "
        "ORDER BY (accuracy_pct * follower_count) DESC, accuracy_pct DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
