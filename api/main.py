"""FastAPI gateway: predictions + matches + health endpoints."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from core.database import init_db, get_conn
from core.poisson import predict_match, compute_team_strengths
from core.ingestion.live_scores import fetch_live_scores


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Background task: sync finished match scores from football-data.org every 5 min
    async def score_sync_loop():
        import asyncio
        import httpx
        from core.config import FOOTBALL_DATA_KEY
        while True:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        "https://api.football-data.org/v4/competitions/2000/matches",
                        headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                    )
                    if resp.status_code == 200:
                        from core.ingestion.football_data import _cache_matches
                        _cache_matches(resp.json().get("matches", []))
            except Exception:
                pass
            await asyncio.sleep(300)  # every 5 minutes

    import asyncio
    asyncio.create_task(score_sync_loop())
    yield


app = FastAPI(title="EAP-Sports API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vexp.me", "http://localhost:4321", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Live scores SSE
from api.live import router as live_router
app.include_router(live_router)

# Auth (Telegram Login Widget)
from api.auth import router as auth_router
app.include_router(auth_router)

# Post-predictions (VIP social feed)
from api.posts import router as posts_router
app.include_router(posts_router)

# Chat (per-match rooms, polling)
from api.chat import router as chat_router
app.include_router(chat_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "eap-sports"}


@app.get("/api/matches")
def get_matches(status: str | None = None):
    conn = get_conn()
    query = "SELECT m.*, t1.name as home_team, t2.name as away_team FROM matches m LEFT JOIN teams t1 ON m.home_team_id=t1.id LEFT JOIN teams t2 ON m.away_team_id=t2.id"
    if status:
        query += f" WHERE m.status=?"
        rows = conn.execute(query, (status,)).fetchall()
    else:
        rows = conn.execute(query + " ORDER BY utc_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/matches/live")
def get_live_scores(demo: bool = False):
    if demo:
        return [
            {
                "home_team": "Mexico", "away_team": "Canada",
                "home_score": 2, "away_score": 1,
                "status": "STATUS_IN_PROGRESS", "clock": "67'", "period": 2,
                "possession_home": "58%", "possession_away": "42%",
                "events": [
                    {"type": "goal", "minute": "23'", "player": "Lozano", "side": "home", "detail": "Goal"},
                    {"type": "yellow_card", "minute": "34'", "player": "Davies", "side": "away", "detail": "Yellow Card"},
                    {"type": "goal", "minute": "41'", "player": "David", "side": "away", "detail": "Goal"},
                    {"type": "goal", "minute": "56'", "player": "Jiménez", "side": "home", "detail": "Goal"},
                    {"type": "sub", "minute": "60'", "player": "Álvarez", "side": "home", "detail": "Substitution"},
                ],
                "stats": {
                    "home_shotsOnTarget": "6", "away_shotsOnTarget": "3",
                    "home_totalShots": "12", "away_totalShots": "8",
                    "home_cornerKicks": "5", "away_cornerKicks": "2",
                }
            },
            {
                "home_team": "Brazil", "away_team": "Argentina",
                "home_score": 1, "away_score": 1,
                "status": "STATUS_IN_PROGRESS", "clock": "38'", "period": 1,
                "possession_home": "52%", "possession_away": "48%",
                "events": [
                    {"type": "goal", "minute": "12'", "player": "Vinicius Jr", "side": "home", "detail": "Goal"},
                    {"type": "goal", "minute": "29'", "player": "Messi", "side": "away", "detail": "Goal"},
                    {"type": "yellow_card", "minute": "33'", "player": "Casemiro", "side": "home", "detail": "Yellow Card"},
                ],
                "stats": {
                    "home_shotsOnTarget": "4", "away_shotsOnTarget": "5",
                    "home_totalShots": "9", "away_totalShots": "10",
                    "home_cornerKicks": "3", "away_cornerKicks": "4",
                }
            },
            {
                "home_team": "Germany", "away_team": "France",
                "home_score": 3, "away_score": 2,
                "status": "STATUS_FINAL", "clock": "FT",
                "events": [
                    {"type": "goal", "minute": "15'", "player": "Musiala", "side": "home", "detail": "Goal"},
                    {"type": "goal", "minute": "28'", "player": "Mbappé", "side": "away", "detail": "Goal"},
                    {"type": "goal", "minute": "52'", "player": "Havertz", "side": "home", "detail": "Goal"},
                    {"type": "goal", "minute": "71'", "player": "Griezmann", "side": "away", "detail": "Goal"},
                    {"type": "red_card", "minute": "78'", "player": "Upamecano", "side": "away", "detail": "Red Card"},
                    {"type": "goal", "minute": "88'", "player": "Wirtz", "side": "home", "detail": "Goal"},
                ],
                "stats": {}
            },
            {
                "home_team": "United States", "away_team": "England",
                "home_score": 0, "away_score": 0,
                "status": "STATUS_SCHEDULED", "clock": "0'",
                "events": [], "stats": {}
            },
        ]
    return fetch_live_scores()


@app.get("/api/predictions/stats")
def prediction_stats():
    """Compute accuracy from finished matches vs predictions."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.home_win, p.draw, p.away_win, m.home_score, m.away_score,
               t1.name as home_team, t2.name as away_team, m.utc_date
        FROM predictions p
        JOIN matches m ON p.match_id = m.id
        LEFT JOIN teams t1 ON m.home_team_id = t1.id
        LEFT JOIN teams t2 ON m.away_team_id = t2.id
        WHERE m.status = 'FINISHED' AND m.home_score IS NOT NULL
        ORDER BY m.utc_date ASC
    """).fetchall()
    conn.close()
    if not rows:
        return {"total_predictions": 0, "correct": 0, "accuracy_pct": 0, "current_streak": 0, "best_streak": 0, "last_wrong": None}
    correct = 0
    streak = 0
    best_streak = 0
    last_wrong = None
    for r in rows:
        probs = {"home": r["home_win"], "draw": r["draw"], "away": r["away_win"]}
        predicted = max(probs, key=probs.get)
        if r["home_score"] > r["away_score"]:
            actual = "home"
        elif r["away_score"] > r["home_score"]:
            actual = "away"
        else:
            actual = "draw"
        if predicted == actual:
            correct += 1
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
            last_wrong = {"match": f"{r['home_team']} vs {r['away_team']}", "date": r["utc_date"][:10]}
    total = len(rows)
    return {
        "total_predictions": total,
        "correct": correct,
        "accuracy_pct": round(correct / total * 100, 1) if total else 0,
        "current_streak": streak,
        "best_streak": best_streak,
        "last_wrong": last_wrong,
    }


@app.get("/api/predictions/{match_id}")
def get_prediction(match_id: int):
    """Enhanced prediction with full intelligence factors."""
    import json
    conn = get_conn()
    match = conn.execute(
        "SELECT m.*, t1.name as home_team, t2.name as away_team, "
        "t1.elo_rating as h_elo, t2.elo_rating as a_elo, "
        "t1.xg_for as h_xg, t1.xg_against as h_xga, "
        "t2.xg_for as a_xg, t2.xg_against as a_xga, "
        "t1.form_score as h_form, t2.form_score as a_form "
        "FROM matches m "
        "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
        "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
        "WHERE m.id=?", (match_id,)
    ).fetchone()
    if not match:
        conn.close()
        raise HTTPException(404, "Match not found")

    # Get H2H
    pair = tuple(sorted([match["home_team_id"], match["away_team_id"]]))
    h2h = conn.execute(
        "SELECT * FROM head2head WHERE team1_id=? AND team2_id=?", pair
    ).fetchone()
    conn.close()

    stage = match["stage"] or "GROUP_STAGE"
    pred = predict_match(match["home_team_id"], match["away_team_id"], stage)

    return {
        "match_id": match_id,
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "confidence_rating": {
            "home": pred["home_win"],
            "draw": pred["draw"],
            "away": pred["away_win"],
        },
        "expected_goals": {
            "home": pred["exp_home_goals"],
            "away": pred["exp_away_goals"],
        },
        "engine_version": pred["model_version"],
        "stage_factor": pred["stage_factor"],
        "factors": {
            "elo_home": match["h_elo"],
            "elo_away": match["a_elo"],
            "elo_gap": (match["h_elo"] or 0) - (match["a_elo"] or 0),
            "xg_home": match["h_xg"],
            "xg_away": match["a_xg"],
            "xga_home": match["h_xga"],
            "xga_away": match["a_xga"],
            "form_home": match["h_form"],
            "form_away": match["a_form"],
            "h2h": {
                "played": h2h["played"] if h2h else 0,
                "team1_wins": h2h["team1_wins"] if h2h else 0,
                "draws": h2h["draws"] if h2h else 0,
                "team2_wins": h2h["team2_wins"] if h2h else 0,
            } if h2h else None,
        },
    }


@app.get("/api/teams")
def get_teams():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/articles")
def get_articles(limit: int = 20):
    conn = get_conn()
    rows = conn.execute("SELECT id, slug, title, meta_description, published_at FROM articles ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/articles/{slug}")
def get_article(slug: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM articles WHERE slug=?", (slug,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Article not found")
    return dict(row)


@app.get("/api/user/{telegram_id}/tier")
def get_user_tier(telegram_id: int):
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (telegram_id,)).fetchone()
    rewarded = conn.execute("SELECT 1 FROM rewarded_users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return {"is_vip": vip is not None, "rewarded_unlocked": rewarded is not None}


@app.get("/api/adsgram/reward")
def adsgram_reward(user_id: int):
    """Callback from Adsgram when user completes rewarded ad."""
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO rewarded_users (telegram_id, unlocked_at) VALUES (?, datetime('now'))",
        (user_id,),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


from pydantic import BaseModel

class ScoreBody(BaseModel):
    telegram_id: int
    correct: int
    total: int


@app.post("/api/quiz/score")
def save_quiz_score(body: ScoreBody):
    """Save quiz score from TMA."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO quiz_scores (telegram_id, correct, total, updated_at) VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT(telegram_id) DO UPDATE SET correct=?, total=?, updated_at=datetime('now')",
        (body.telegram_id, body.correct, body.total, body.correct, body.total),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/quiz/score/{telegram_id}")
def get_quiz_score(telegram_id: int):
    conn = get_conn()
    row = conn.execute("SELECT correct, total FROM quiz_scores WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    if not row:
        return {"correct": 0, "total": 0}
    return dict(row)


@app.get("/api/standings")
def get_standings():
    """Return group standings computed from finished matches."""
    import json
    conn = get_conn()
    matches = conn.execute("""
        SELECT m.*, t1.name as home_team, t2.name as away_team, m.raw_json
        FROM matches m
        LEFT JOIN teams t1 ON m.home_team_id=t1.id
        LEFT JOIN teams t2 ON m.away_team_id=t2.id
        WHERE m.stage='GROUP_STAGE'
        ORDER BY m.utc_date
    """).fetchall()
    conn.close()

    groups = {}
    for m in matches:
        raw = json.loads(m["raw_json"]) if m["raw_json"] else {}
        group = raw.get("group", "UNKNOWN")
        if group not in groups:
            groups[group] = {}

        for team, is_home in [(m["home_team"], True), (m["away_team"], False)]:
            if team not in groups[group]:
                groups[group][team] = {"team": team, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}

        if m["status"] in ("FINISHED", "STATUS_FINAL", "STATUS_FULL_TIME") and m["home_score"] is not None:
            hs, aws = m["home_score"], m["away_score"]
            ht, at = m["home_team"], m["away_team"]
            groups[group][ht]["p"] += 1
            groups[group][at]["p"] += 1
            groups[group][ht]["gf"] += hs
            groups[group][ht]["ga"] += aws
            groups[group][at]["gf"] += aws
            groups[group][at]["ga"] += hs
            if hs > aws:
                groups[group][ht]["w"] += 1; groups[group][ht]["pts"] += 3
                groups[group][at]["l"] += 1
            elif aws > hs:
                groups[group][at]["w"] += 1; groups[group][at]["pts"] += 3
                groups[group][ht]["l"] += 1
            else:
                groups[group][ht]["d"] += 1; groups[group][ht]["pts"] += 1
                groups[group][at]["d"] += 1; groups[group][at]["pts"] += 1

    # Sort each group by pts, then gd, then gf
    result = {}
    for g in sorted(groups.keys()):
        teams = sorted(groups[g].values(), key=lambda t: (-t["pts"], -(t["gf"]-t["ga"]), -t["gf"]))
        result[g] = teams
    return result


@app.get("/api/leaderboard")
def get_leaderboard(limit: int = 20):
    """Top quiz players."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT q.telegram_id, q.correct, q.total,
                  COALESCE(p.first_name, p.username, 'Anon') as name,
                  CASE WHEN v.telegram_id IS NOT NULL THEN 1 ELSE 0 END as is_vip
           FROM quiz_scores q
           LEFT JOIN user_profiles p ON q.telegram_id = p.telegram_id
           LEFT JOIN vip_users v ON q.telegram_id = v.telegram_id
           WHERE q.total >= 1
           ORDER BY q.correct DESC, q.total ASC LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/quiz/profile/{telegram_id}")
def get_quiz_profile(telegram_id: int):
    """Public profile for a user — score + name + VIP status."""
    conn = get_conn()
    row = conn.execute(
        """SELECT q.telegram_id, q.correct, q.total,
                  COALESCE(p.first_name, p.username, 'Anon') as name,
                  CASE WHEN v.telegram_id IS NOT NULL THEN 1 ELSE 0 END as is_vip
           FROM quiz_scores q
           LEFT JOIN user_profiles p ON q.telegram_id = p.telegram_id
           LEFT JOIN vip_users v ON q.telegram_id = v.telegram_id
           WHERE q.telegram_id = ?""",
        (telegram_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row)


# ─── Prediction Gating (Per-Match Ad Unlock) ──────────────
class AdWatchedBody(BaseModel):
    telegram_id: int
    match_id: int


@app.post("/api/adsgram/watched")
def adsgram_watched(body: AdWatchedBody):
    """Increment ad watch count for a user/match. Unlock at 2."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO rewarded_sessions (telegram_id, match_id, ads_watched) VALUES (?, ?, 1) "
        "ON CONFLICT(telegram_id, match_id) DO UPDATE SET ads_watched = ads_watched + 1",
        (body.telegram_id, body.match_id),
    )
    conn.execute(
        "UPDATE rewarded_sessions SET unlocked = 1 WHERE telegram_id = ? AND match_id = ? AND ads_watched >= 2",
        (body.telegram_id, body.match_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT ads_watched, unlocked FROM rewarded_sessions WHERE telegram_id = ? AND match_id = ?",
        (body.telegram_id, body.match_id),
    ).fetchone()
    conn.close()
    return {"ads_watched": row["ads_watched"], "unlocked": bool(row["unlocked"]), "ads_remaining": max(0, 2 - row["ads_watched"])}


@app.get("/api/predictions/access/{telegram_id}/{match_id}")
def check_prediction_access(telegram_id: int, match_id: int):
    """Check if user can access predictions for a specific match."""
    conn = get_conn()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if vip:
        conn.close()
        return {"granted": True, "reason": "vip", "ads_remaining": 0}
    row = conn.execute(
        "SELECT ads_watched, unlocked FROM rewarded_sessions WHERE telegram_id=? AND match_id=?",
        (telegram_id, match_id),
    ).fetchone()
    conn.close()
    if row and row["unlocked"]:
        return {"granted": True, "reason": "rewarded", "ads_remaining": 0}
    watched = row["ads_watched"] if row else 0
    return {"granted": False, "reason": "locked", "ads_remaining": max(0, 2 - watched)}
