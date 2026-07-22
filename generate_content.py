"""Generate Astro-compatible Markdown pages from DB matches + Poisson predictions via Gemini Flash."""
import hashlib
import json
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_cloud import GoogleCloudProvider
from google.oauth2 import service_account
from core.database import get_conn, init_db
from core.poisson import predict_match, compute_team_strengths
from core.form_tracker import run_form_update
from core.config import GCP_PROJECT, GCP_REGION, GCP_CREDENTIALS

MATCHES_DIR = Path(__file__).parent / "web/src/pages/matches"
TEAMS_DIR = Path(__file__).parent / "web/src/pages/teams"
MATCHES_DIR.mkdir(parents=True, exist_ok=True)
TEAMS_DIR.mkdir(parents=True, exist_ok=True)

_agent = None

def get_agent():
    """Lazy init Gemini Flash agent via Vertex AI."""
    global _agent
    if _agent is None:
        creds = service_account.Credentials.from_service_account_file(
            GCP_CREDENTIALS, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        provider = GoogleCloudProvider(credentials=creds, project=GCP_PROJECT, location=GCP_REGION)
        model = GoogleModel("gemini-2.5-flash", provider=provider)
        _agent = Agent(model=model, system_prompt="You are a concise football analyst. No gambling references.")
    return _agent


def content_hash(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()[:12]


def generate_match_pages():
    """Generate match preview .md files for all scheduled matches."""
    init_db()
    run_form_update()  # Update ELO + form from latest results
    conn = get_conn()
    matches = conn.execute(
        "SELECT m.id, m.utc_date, m.home_team_id, m.away_team_id, m.stage, "
        "t1.name as home, t2.name as away, "
        "t1.elo_rating as h_elo, t2.elo_rating as a_elo, "
        "t1.xg_for as h_xg, t1.xg_against as h_xga, "
        "t2.xg_for as a_xg, t2.xg_against as a_xga, "
        "t1.form_score as h_form, t2.form_score as a_form "
        "FROM matches m "
        "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
        "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
        "WHERE m.status IN ('SCHEDULED','TIMED') ORDER BY m.utc_date"
    ).fetchall()

    # Get H2H data
    h2h_data = {(r["team1_id"], r["team2_id"]): r
                for r in conn.execute("SELECT * FROM head2head").fetchall()}
    conn.close()

    if not matches:
        print("No scheduled matches found.")
        return

    goals_strengths = compute_team_strengths()
    agent = get_agent()
    generated = 0

    for m in matches:
        if not m["home"] or not m["away"]:
            continue
        slug = f"{m['home'].lower().replace(' ','-')}-vs-{m['away'].lower().replace(' ','-')}"
        filepath = MATCHES_DIR / f"{slug}.md"

        stage = m["stage"] or "GROUP_STAGE"
        pred = predict_match(m["home_team_id"], m["away_team_id"], stage, goals_strengths)

        # Use IST display date (UTC+5:30) for local audience
        from datetime import datetime, timedelta
        utc_dt = datetime.fromisoformat(m["utc_date"].replace("Z", "+00:00"))
        ist_dt = utc_dt + timedelta(hours=5, minutes=30)
        display_date = ist_dt.strftime("%Y-%m-%d")

        data_key = content_hash(f"{m['id']}{pred['home_win']:.1f}{pred['draw']:.1f}{display_date}")

        if filepath.exists() and data_key in filepath.read_text()[:200]:
            continue

        # Build rich context for AI
        pair = tuple(sorted([m["home_team_id"], m["away_team_id"]]))
        h2h = h2h_data.get(pair)
        h2h_text = f"H2H: {h2h['played']} meetings" if h2h and h2h["played"] > 0 else "No previous meetings"

        elo_gap = (m["h_elo"] or 1500) - (m["a_elo"] or 1500)
        elo_text = f"{m['home']} ELO {m['h_elo']}, {m['away']} ELO {m['a_elo']} (gap: {elo_gap:+d})"

        form_h = f"form {m['h_form']}/15" if m["h_form"] is not None else "no tournament form yet"
        form_a = f"form {m['a_form']}/15" if m["a_form"] is not None else "no tournament form yet"

        prompt = (
            f"Write a 200-word expert match preview for {m['home']} vs {m['away']} "
            f"(FIFA World Cup 2026, {stage.replace('_',' ').title()}, {m['utc_date'][:10]}).\n\n"
            f"CONTEXT (use to inform your opinion but DO NOT mention these numbers or methods):\n"
            f"- Confidence: {m['home']} {pred['home_win']:.1f}% / Draw {pred['draw']:.1f}% / {m['away']} {pred['away_win']:.1f}%\n"
            f"- Expected goals: {m['home']} {pred['exp_home_goals']:.2f} vs {m['away']} {pred['exp_away_goals']:.2f}\n"
            f"- ELO gap: {elo_gap:+d}\n"
            f"- {h2h_text}\n\n"
            f"WRITING STYLE: Write as if you're a football pundit giving YOUR personal take. "
            f"Talk about tactics, formations, player matchups, historical context, team mentality. "
            f"Sound opinionated and confident, like a columnist.\n\n"
            f"STRICT RULES:\n"
            f"- NEVER mention: ELO, xG, expected goals, confidence rating, percentages, "
            f"statistical models, data signals, Poisson, Dixon-Coles, algorithms, or any methodology.\n"
            f"- NEVER use: predict, odds, betting, gamble, probability, wager.\n"
            f"- DO NOT use any specific numbers or stats.\n"
            f"- Write as pure football opinion — tactical insight, team strengths/weaknesses, "
            f"key battles, likely approach, and your gut feel for the result.\n"
            f"- Use: 'I think', 'I fancy', 'my take', 'I expect', 'I'd back'."
        )
        try:
            result = agent.run_sync(prompt)
            analysis = result.output.strip()
        except Exception as e:
            print(f"  [WARNING] Gemini error for {slug}: {e}")
            analysis = f"Expert tactical breakdown for {m['home']} vs {m['away']} — analysis in progress."

        frontmatter = (
            f"---\n"
            f"layout: ./_layout.astro\n"
            f"title: \"{m['home']} vs {m['away']} Prediction — World Cup 2026\"\n"
            f"description: \"{m['home']} vs {m['away']} prediction & preview. "
            f"Win probability: {m['home']} {pred['home_win']:.0f}%, Draw {pred['draw']:.0f}%, {m['away']} {pred['away_win']:.0f}%. "
            f"Expert tactical breakdown for FIFA World Cup 2026.\"\n"
            f"date: \"{display_date}\"\n"
            f"time: \"{ist_dt.strftime('%H:%M')}\"\n"
            f"matchId: {m['id']}\n"
            f"homeTeam: \"{m['home']}\"\n"
            f"awayTeam: \"{m['away']}\"\n"
            f"homeWin: \"{pred['home_win']:.1f}\"\n"
            f"draw: \"{pred['draw']:.1f}\"\n"
            f"awayWin: \"{pred['away_win']:.1f}\"\n"
            f"expectedHome: \"{pred['exp_home_goals']:.2f}\"\n"
            f"expectedAway: \"{pred['exp_away_goals']:.2f}\"\n"
            f"hash: \"{data_key}\"\n"
            f"---\n\n"
        )
        filepath.write_text(frontmatter + analysis)
        generated += 1
        print(f"  [OK] {slug}")

    print(f"\n[INFO] Generated {generated} match preview(s).")


def generate_team_pages():
    """Generate team analysis .md files with rich structured data."""
    init_db()
    conn = get_conn()
    teams = conn.execute(
        "SELECT id, name, code, group_name, attack_strength, defense_strength FROM teams ORDER BY name"
    ).fetchall()
    conn.close()

    if not teams:
        print("No teams found.")
        return

    agent = get_agent()
    generated = 0

    # Team colors lookup (primary, secondary)
    COLORS = {
        "Algeria": ["#006233", "#ffffff"], "Argentina": ["#75aadb", "#ffffff"],
        "Australia": ["#00843d", "#ffcd00"], "Austria": ["#ed2939", "#ffffff"],
        "Belgium": ["#ed2939", "#fdda24"], "Bosnia-Herzegovina": ["#002395", "#fecb00"],
        "Brazil": ["#009c3b", "#ffdf00"], "Cameroon": ["#007a5e", "#ce1126"],
        "Canada": ["#ff0000", "#ffffff"], "Cape Verde Islands": ["#003893", "#cf2027"],
        "Colombia": ["#fcd116", "#003893"], "Costa Rica": ["#002b7f", "#ce1126"],
        "Croatia": ["#ff0000", "#ffffff"], "Curaçao": ["#002b7f", "#ffb81c"],
        "Czechia": ["#11457e", "#d7141a"], "DR Congo": ["#007fff", "#ce1021"],
        "Denmark": ["#c60c30", "#ffffff"], "Ecuador": ["#ffdd00", "#034ea2"],
        "Egypt": ["#ce1126", "#ffffff"], "England": ["#ffffff", "#cf081f"],
        "France": ["#002395", "#ed2939"], "Germany": ["#000000", "#ffce00"],
        "Ghana": ["#006b3f", "#fcd116"], "Haiti": ["#00209f", "#d21034"],
        "Honduras": ["#0073cf", "#ffffff"], "Hungary": ["#477050", "#ce2939"],
        "Indonesia": ["#ff0000", "#ffffff"], "Iran": ["#239f40", "#ffffff"],
        "Iraq": ["#007a3d", "#ffffff"], "Ireland": ["#169b62", "#ff883e"],
        "Italy": ["#0066b2", "#ffffff"], "Ivory Coast": ["#f77f00", "#009e60"],
        "Jamaica": ["#009b3a", "#fed100"], "Japan": ["#000080", "#ffffff"],
        "Jordan": ["#007a3d", "#000000"], "Mexico": ["#006847", "#ce1126"],
        "Morocco": ["#c1272d", "#006233"], "Netherlands": ["#ff6600", "#ffffff"],
        "New Zealand": ["#000000", "#ffffff"], "Nigeria": ["#008751", "#ffffff"],
        "Norway": ["#ef2b2d", "#002868"], "Panama": ["#005293", "#d21034"],
        "Paraguay": ["#d52b1e", "#0038a8"], "Peru": ["#d91023", "#ffffff"],
        "Poland": ["#dc143c", "#ffffff"], "Portugal": ["#006600", "#ff0000"],
        "Qatar": ["#8b1a32", "#ffffff"], "Saudi Arabia": ["#006c35", "#ffffff"],
        "Scotland": ["#003078", "#ffffff"], "Senegal": ["#00853f", "#fdee00"],
        "Serbia": ["#c6363c", "#ffffff"], "South Africa": ["#007749", "#ffb81c"],
        "South Korea": ["#cd2e3a", "#0047a0"], "Spain": ["#c60b1e", "#ffc400"],
        "Sweden": ["#006aa7", "#fecc00"], "Switzerland": ["#ff0000", "#ffffff"],
        "Trinidad and Tobago": ["#ce1126", "#000000"], "Tunisia": ["#e70013", "#ffffff"],
        "Turkey": ["#e30a17", "#ffffff"], "Ukraine": ["#005bbb", "#ffd500"],
        "United States": ["#002868", "#bf0a30"], "Uruguay": ["#0038a8", "#ffffff"],
        "Uzbekistan": ["#0099b5", "#1eb53a"], "Venezuela": ["#ffcc00", "#00247d"],
        "Wales": ["#c8102e", "#ffffff"],
    }

    for t in teams:
        slug = t["name"].lower().replace(" ", "-")
        filepath = TEAMS_DIR / f"{slug}.md"
        if filepath.exists():
            continue

        atk = t["attack_strength"] or 1.0
        dfn = t["defense_strength"] or 1.0
        colors = COLORS.get(t["name"], ["#00e87b", "#0a0a12"])

        prompt = f"""Generate a JSON object for {t['name']} World Cup 2026 team profile.

CONTEXT: Attack strength {atk:.2f}, Defense strength {dfn:.2f}, Group {t['group_name'] or 'TBD'}.

Return ONLY valid JSON with this exact structure:
{{
  "formation": "4-3-3",
  "players": [
    {{"name": "PlayerName", "pos": "GK", "role": "Shot-Stopper"}},
    {{"name": "PlayerName", "pos": "RB", "role": "Overlapping Full-Back"}},
    {{"name": "PlayerName", "pos": "CB", "role": "Ball-Playing Centre-Back"}},
    {{"name": "PlayerName", "pos": "CB", "role": "Aggressive Stopper"}},
    {{"name": "PlayerName", "pos": "LB", "role": "Inverted Full-Back"}},
    {{"name": "PlayerName", "pos": "CM", "role": "Deep-Lying Playmaker"}},
    {{"name": "PlayerName", "pos": "CM", "role": "Box-to-Box"}},
    {{"name": "PlayerName", "pos": "CM", "role": "Advanced Playmaker"}},
    {{"name": "PlayerName", "pos": "RW", "role": "Inside Forward"}},
    {{"name": "PlayerName", "pos": "ST", "role": "Target Man"}},
    {{"name": "PlayerName", "pos": "LW", "role": "Inverted Winger"}}
  ],
  "radar": {{"finishing": 7, "buildup": 8, "pressing": 6, "defense": 7, "transition": 8, "setPieces": 6}},
  "strengths": ["Strength 1", "Strength 2", "Strength 3"],
  "weaknesses": ["Weakness 1", "Weakness 2"],
  "keyPlayer": {{"name": "Player Name", "position": "Position", "desc": "25-word description of why they're key"}},
  "analysis": "150-word pundit-style tactical analysis. Write as expert giving personal opinion. Use 'I think', 'I expect'. No numbers, no methodology, no gambling references."
}}

RULES:
- Use REAL current players for {t['name']} national team (2025-2026 squad)
- Formation must match the number/positions of players listed (exactly 11)
- Radar values 1-10, calibrated to attack={atk:.2f} defense={dfn:.2f}
- Be realistic and football-accurate
- Return ONLY the JSON, no markdown fences"""

        try:
            result = agent.run_sync(prompt)
            raw = result.output.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(raw)
        except Exception as e:
            print(f"  [WARNING] Error for {slug}: {e}")
            continue

        players_yaml = "\n".join(
            f'  - name: "{p["name"]}"\n    pos: "{p["pos"]}"\n    role: "{p["role"]}"'
            for p in data.get("players", [])[:11]
        )
        radar = data.get("radar", {})
        strengths = data.get("strengths", [])
        weaknesses = data.get("weaknesses", [])
        kp = data.get("keyPlayer", {})

        frontmatter = f"""---
layout: ./_layout.astro
title: "{t['name']} — World Cup 2026"
description: "Tactical profile and scouting report for {t['name']} at FIFA World Cup 2026."
team: "{t['name']}"
group: "{t['group_name'] or 'TBD'}"
formation: "{data.get('formation', '4-4-2')}"
colors: ["{colors[0]}", "{colors[1]}"]
players:
{players_yaml}
radar:
  finishing: {radar.get('finishing', 5)}
  buildup: {radar.get('buildup', 5)}
  pressing: {radar.get('pressing', 5)}
  defense: {radar.get('defense', 5)}
  transition: {radar.get('transition', 5)}
  setPieces: {radar.get('setPieces', 5)}
strengths: {json.dumps(strengths)}
weaknesses: {json.dumps(weaknesses)}
keyPlayer:
  name: "{kp.get('name', 'TBD')}"
  position: "{kp.get('position', '')}"
  desc: "{kp.get('desc', '')}"
---

{data.get('analysis', '')}
"""
        filepath.write_text(frontmatter)
        generated += 1
        print(f"  [OK] {slug}")

    print(f"\n[INFO] Generated {generated} team page(s).")


if __name__ == "__main__":
    print("[INFO] Generating match previews...")
    generate_match_pages()
    print("\n[INFO] Generating team pages...")
    generate_team_pages()
    print("\n[SUCCESS] Done. Run 'cd web && npm run build' to rebuild the site.")
