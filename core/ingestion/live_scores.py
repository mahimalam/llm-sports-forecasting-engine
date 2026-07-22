"""Live score failover chain: ESPN → Yahoo → Playwright (best-effort, never load-bearing)."""
import httpx
from datetime import date

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
YAHOO_URL = "https://sports.yahoo.com/soccer/fifa-world-cup/scoreboard/"


def fetch_espn_live() -> list[dict] | None:
    """ESPN unauthenticated scoreboard. Returns None on failure."""
    try:
        resp = httpx.get(ESPN_URL, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("events", [])
        return [_parse_espn_event(e) for e in events]
    except Exception:
        return None


def fetch_yahoo_live() -> list[dict] | None:
    """Yahoo Sports fallback. Returns None on failure."""
    try:
        resp = httpx.get(YAHOO_URL, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return _parse_yahoo_html(resp.text)
    except Exception:
        return None


def fetch_live_scores() -> list[dict]:
    """Try failover chain: ESPN → Yahoo → Playwright. Return best available data."""
    result = fetch_espn_live()
    if result is not None:
        return result

    result = fetch_yahoo_live()
    if result is not None:
        return result

    result = fetch_playwright_live()
    if result is not None:
        return result

    return []


def fetch_playwright_live() -> list[dict] | None:
    """Last-resort Playwright scrape of Google live match snippet."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)
            page.goto("https://www.google.com/search?q=fifa+world+cup+2026+live+scores")
            cards = page.query_selector_all("[data-entityid]")
            scores = []
            for card in cards[:10]:
                text = card.inner_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if len(lines) >= 4:
                    scores.append({
                        "home_team": lines[0], "home_score": _safe_int(lines[1]),
                        "away_team": lines[2], "away_score": _safe_int(lines[3]),
                        "status": "STATUS_IN_PROGRESS", "clock": "",
                        "events": [], "stats": {},
                    })
            browser.close()
            return scores if scores else None
    except Exception:
        return None


def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _parse_espn_event(event: dict) -> dict:
    """Parse a full ESPN event with events, stats, and match details."""
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [{}, {}])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    home_id = home.get("team", {}).get("id")

    # Basic info
    result = {
        "home_team": home.get("team", {}).get("displayName"),
        "away_team": away.get("team", {}).get("displayName"),
        "home_score": int(home.get("score", 0)),
        "away_score": int(away.get("score", 0)),
        "status": event.get("status", {}).get("type", {}).get("name"),
        "clock": event.get("status", {}).get("displayClock"),
        "period": event.get("status", {}).get("period", 0),
        "start_time": event.get("date"),
    }

    # Match events (goals, cards, subs)
    details = comp.get("details", [])
    match_events = []
    for d in details:
        evt_type = d.get("type", {}).get("text", "")
        clock_val = d.get("clock", {}).get("displayValue", "")
        athletes = d.get("athletesInvolved", [])
        player = athletes[0].get("displayName", "") if athletes else ""
        team_id = d.get("team", {}).get("id")
        side = "home" if team_id == home_id else "away"

        # Categorize event
        if "Goal" in evt_type:
            category = "goal"
        elif "Yellow" in evt_type:
            category = "yellow_card"
        elif "Red" in evt_type:
            category = "red_card"
        elif "Substitution" in evt_type:
            category = "sub"
        else:
            category = evt_type.lower().replace(" ", "_")

        match_events.append({
            "type": category,
            "minute": clock_val,
            "player": player,
            "side": side,
            "detail": evt_type,
        })

    result["events"] = match_events

    # Stats (possession, shots, etc.)
    stats = {}
    for team_data, prefix in [(home, "home"), (away, "away")]:
        team_stats = team_data.get("statistics", [])
        for s in team_stats:
            name = s.get("name", "")
            value = s.get("displayValue", s.get("value", ""))
            stats[f"{prefix}_{name}"] = value

    result["stats"] = stats

    # Situation (ball possession if available in real-time)
    situation = comp.get("situation", {})
    if situation:
        result["possession_home"] = situation.get("homeTeam", {}).get("possession", "")
        result["possession_away"] = situation.get("awayTeam", {}).get("possession", "")

    return result


def _parse_yahoo_html(html: str) -> list[dict] | None:
    """Minimal extraction from Yahoo HTML. Best-effort."""
    import re
    scores = re.findall(r'"homeScore":(\d+).*?"awayScore":(\d+)', html)
    if not scores:
        return None
    return [{"home_score": int(h), "away_score": int(a), "events": [], "stats": {}} for h, a in scores]
