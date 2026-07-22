"""Post-match report generator. Checks for finished matches and creates report pages."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database import get_conn
from core.config import GCP_PROJECT, GCP_REGION, GCP_CREDENTIALS

REPORTS_DIR = "web/src/pages/matches"


def get_finished_unreported():
    """Find matches marked FINISHED that don't have a report page yet."""
    conn = get_conn()
    matches = conn.execute("""
        SELECT m.id, m.utc_date, m.home_score, m.away_score,
               t1.name as home, t2.name as away
        FROM matches m
        LEFT JOIN teams t1 ON m.home_team_id=t1.id
        LEFT JOIN teams t2 ON m.away_team_id=t2.id
        WHERE m.status='FINISHED' AND t1.name IS NOT NULL
        ORDER BY m.utc_date DESC
    """).fetchall()
    conn.close()

    unreported = []
    for m in matches:
        slug = f"{m['home'].lower().replace(' ','-')}-vs-{m['away'].lower().replace(' ','-')}-report"
        path = os.path.join(REPORTS_DIR, f"{slug}.md")
        if not os.path.exists(path):
            unreported.append(dict(m) | {"slug": slug})
    return unreported


def generate_report(match):
    """Generate post-match report using Gemini Flash via pydantic-ai."""
    try:
        from pydantic_ai import Agent
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google_cloud import GoogleCloudProvider
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(GCP_CREDENTIALS)
        provider = GoogleCloudProvider(project_id=GCP_PROJECT, region=GCP_REGION, credentials=creds)
        model = GoogleModel("gemini-2.0-flash", provider=provider)
        agent = Agent(model=model, system_prompt="You are a concise football match reporter. No gambling references.")

        prompt = (
            f"Write a 200-word post-match report for {match['home']} {match['home_score']}-{match['away_score']} {match['away']} "
            f"(FIFA World Cup 2026, {match['utc_date'][:10]}). "
            f"Cover key moments, standout performers, and what this means for both teams. Entertaining tone."
        )
        result = agent.run_sync(prompt)
        return result.output
    except Exception as e:
        print(f"  [WARNING] Gemini failed: {e}")
        winner = match['home'] if match['home_score'] > match['away_score'] else match['away'] if match['away_score'] > match['home_score'] else "Neither side"
        return (
            f"{winner} came out on top in this World Cup clash. "
            f"Final score: {match['home']} {match['home_score']}-{match['away_score']} {match['away']}. "
            f"Full tactical breakdown to follow."
        )


def create_report_page(match, content):
    """Write markdown report page."""
    slug = match["slug"]
    path = os.path.join(REPORTS_DIR, f"{slug}.md")
    md = f"""---
layout: ./_layout.astro
title: "{match['home']} {match['home_score']}-{match['away_score']} {match['away']} — Post-Match Report"
description: "Full report: {match['home']} {match['home_score']}-{match['away_score']} {match['away']} in FIFA World Cup 2026."
date: "{match['utc_date'][:10]}"
matchId: {match['id']}
homeTeam: "{match['home']}"
awayTeam: "{match['away']}"
homeWin: "0"
draw: "0"
awayWin: "0"
expectedHome: "{match['home_score']}"
expectedAway: "{match['away_score']}"
---

## Final Score: {match['home']} {match['home_score']} - {match['away_score']} {match['away']}

{content}
"""
    with open(path, "w") as f:
        f.write(md)
    print(f"  [OK] {slug}.md")


def run():
    unreported = get_finished_unreported()
    if not unreported:
        print("No new finished matches to report.")
        return

    print(f"Found {len(unreported)} match(es) to report:")
    for m in unreported:
        print(f"  -> {m['home']} {m['home_score']}-{m['away_score']} {m['away']}")
        content = generate_report(m)
        create_report_page(m, content)

    # Rebuild site
    print("Rebuilding site...")
    os.system("cd web && npm run build 2>&1 | tail -2")
    os.system("ln -sfn $(pwd)/tma/dist $(pwd)/web/dist/tma")
    print("[SUCCESS] Reports published.")


if __name__ == "__main__":
    run()
