"""football-data.org API adapter — primary, load-bearing source."""
import json
import httpx
from core.config import FOOTBALL_DATA_KEY
from core.database import get_conn

BASE_URL = "https://api.football-data.org/v4"
WC_COMPETITION = 2000  # FIFA World Cup


def _headers():
    return {"X-Auth-Token": FOOTBALL_DATA_KEY}


def fetch_matches(matchday: int | None = None) -> list[dict]:
    """Fetch WC matches. Cache-first: only hits API if stale."""
    params = {}
    if matchday:
        params["matchday"] = matchday

    resp = httpx.get(
        f"{BASE_URL}/competitions/{WC_COMPETITION}/matches",
        headers=_headers(),
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    matches = resp.json().get("matches", [])
    _cache_matches(matches)
    return matches


def fetch_teams() -> list[dict]:
    """Fetch WC participating teams."""
    resp = httpx.get(
        f"{BASE_URL}/competitions/{WC_COMPETITION}/teams",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    teams = resp.json().get("teams", [])
    _cache_teams(teams)
    return teams


def _cache_teams(teams: list[dict]):
    conn = get_conn()
    for t in teams:
        conn.execute(
            """INSERT INTO teams (id, name, code, group_name) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, code=excluded.code,
               group_name=excluded.group_name, updated_at=datetime('now')""",
            (t["id"], t["name"], t.get("tla"), t.get("group")),
        )
    conn.commit()
    conn.close()


def _cache_matches(matches: list[dict]):
    conn = get_conn()
    for m in matches:
        home_id = m["homeTeam"]["id"] if m.get("homeTeam") else None
        away_id = m["awayTeam"]["id"] if m.get("awayTeam") else None
        home_score = m.get("score", {}).get("fullTime", {}).get("home")
        away_score = m.get("score", {}).get("fullTime", {}).get("away")
        conn.execute(
            """INSERT INTO matches (id, home_team_id, away_team_id, utc_date, status,
               home_score, away_score, matchday, stage, source, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'football-data', ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
               home_score=excluded.home_score, away_score=excluded.away_score,
               raw_json=excluded.raw_json, updated_at=datetime('now')""",
            (m["id"], home_id, away_id, m["utcDate"], m["status"],
             home_score, away_score, m.get("matchday"), m.get("stage"),
             json.dumps(m)),
        )
    conn.commit()
    conn.close()


def get_cached_matches() -> list[dict]:
    """Read from local cache without hitting API."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM matches ORDER BY utc_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]
