"""SSE endpoint for live match scores. Polls ESPN + football-data.org, pushes to all connected clients."""
import asyncio
import time
import json
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from core.config import FOOTBALL_DATA_KEY
from core.database import get_conn

def _persist_scores(matches: list[dict]):
    """Write live/finished scores back to the matches DB so standings compute correctly."""
    FINAL_STATUSES = {"STATUS_FINAL", "STATUS_FULL_TIME", "FINISHED"}
    finals = [m for m in matches if m.get("status") in FINAL_STATUSES and m.get("home_score") is not None]
    if not finals:
        return
    try:
        conn = get_conn()
        for m in finals:
            # Match by team names (case-insensitive)
            row = conn.execute(
                "SELECT m.id FROM matches m "
                "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
                "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
                "WHERE LOWER(t1.name)=LOWER(?) AND LOWER(t2.name)=LOWER(?)",
                (m["home_team"], m["away_team"])
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE matches SET status=?, home_score=?, away_score=? WHERE id=?",
                    ("STATUS_FINAL", m["home_score"], m["away_score"], row["id"])
                )
        conn.commit()
        conn.close()
    except Exception:
        pass

router = APIRouter()

# In-memory state
_live_state: dict = {"matches": [], "updated_at": 0}
_poll_task: asyncio.Task | None = None

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
FD_URL = "https://api.football-data.org/v4/competitions/WC/matches?status=LIVE"


def _parse_espn(data: dict) -> list[dict]:
    matches = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        status = event.get("status", {})
        state = status.get("type", {}).get("state", "pre")  # pre, in, post
        matches.append({
            "home_team": home.get("team", {}).get("displayName", ""),
            "away_team": away.get("team", {}).get("displayName", ""),
            "home_score": int(home.get("score", 0)),
            "away_score": int(away.get("score", 0)),
            "clock": status.get("displayClock", ""),
            "period": status.get("period", 0),
            "state": state,
            "detail": status.get("type", {}).get("detail", ""),
        })
    return [m for m in matches if m["state"] == "in"]


def _parse_fd(data: dict) -> list[dict]:
    matches = []
    for m in data.get("matches", []):
        score = m.get("score", {}).get("fullTime", {})
        matches.append({
            "home_team": m.get("homeTeam", {}).get("name", ""),
            "away_team": m.get("awayTeam", {}).get("name", ""),
            "home_score": score.get("home", 0) or 0,
            "away_score": score.get("away", 0) or 0,
            "clock": str(m.get("minute", "")) + "'",
            "period": 0,
            "state": "in",
            "detail": f"{m.get('minute', '?')}'",
        })
    return matches


async def _poll_sources():
    """Background task: poll ESPN every 15s, football-data every 20s (staggered)."""
    global _live_state
    espn_counter = 0
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                # ESPN every cycle (15s)
                resp = await client.get(ESPN_URL)
                if resp.status_code == 200:
                    espn_matches = _parse_espn(resp.json())
                    if espn_matches:
                        _live_state = {"matches": espn_matches, "updated_at": time.time(), "source": "espn"}
                        _persist_scores(espn_matches)
            except Exception:
                pass

            # football-data.org every 3rd cycle (~45s, within their rate limit)
            espn_counter += 1
            if espn_counter % 3 == 0 and FOOTBALL_DATA_KEY:
                try:
                    resp = await client.get(FD_URL, headers={"X-Auth-Token": FOOTBALL_DATA_KEY})
                    if resp.status_code == 200:
                        fd_matches = _parse_fd(resp.json())
                        if fd_matches and (not _live_state["matches"] or time.time() - _live_state["updated_at"] > 30):
                            _live_state = {"matches": fd_matches, "updated_at": time.time(), "source": "football-data"}
                            _persist_scores(fd_matches)
                except Exception:
                    pass

            await asyncio.sleep(15)


def _ensure_poll_task():
    global _poll_task
    if _poll_task is None or _poll_task.done():
        _poll_task = asyncio.create_task(_poll_sources())


async def _event_stream():
    """SSE generator: send current state immediately, then push on change."""
    _ensure_poll_task()
    last_sent = ""
    while True:
        current = json.dumps(_live_state)
        if current != last_sent:
            yield f"data: {current}\n\n"
            last_sent = current
        await asyncio.sleep(5)  # check for changes every 5s


@router.get("/api/live/stream")
async def live_stream():
    """SSE endpoint for live scores."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/live")
async def live_snapshot():
    """One-shot snapshot of current live state (for initial page load)."""
    _ensure_poll_task()
    return _live_state
