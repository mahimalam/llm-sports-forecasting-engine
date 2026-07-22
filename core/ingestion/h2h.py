"""Head-to-head ingestion from football-data.org /matches/{id}/head2head endpoint."""
import time
import httpx
from core.config import FOOTBALL_DATA_KEY
from core.database import get_conn

BASE_URL = "https://api.football-data.org/v4"


def ingest_h2h():
    """Pull H2H data for all scheduled WC matches and store in head2head table."""
    conn = get_conn()
    matches = conn.execute(
        "SELECT id, home_team_id, away_team_id FROM matches WHERE status IN ('TIMED','SCHEDULED')"
    ).fetchall()

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    processed = set()
    updated = 0

    for m in matches:
        pair = tuple(sorted([m["home_team_id"], m["away_team_id"]]))
        if pair in processed:
            continue
        processed.add(pair)

        try:
            resp = httpx.get(
                f"{BASE_URL}/matches/{m['id']}/head2head?limit=20",
                headers=headers, timeout=15
            )
            if resp.status_code != 200:
                time.sleep(6)  # Rate limit
                continue

            agg = resp.json().get("aggregates", {})
            n = agg.get("numberOfMatches", 0)
            home_data = agg.get("homeTeam", {})
            away_data = agg.get("awayTeam", {})

            # Determine who is team1 (lower id)
            t1, t2 = pair
            if t1 == home_data.get("id"):
                t1_wins = home_data.get("wins", 0)
                draws = home_data.get("draws", 0)
                t2_wins = away_data.get("wins", 0)
            else:
                t1_wins = away_data.get("wins", 0)
                draws = away_data.get("draws", 0)
                t2_wins = home_data.get("wins", 0)

            conn.execute(
                """INSERT INTO head2head (team1_id, team2_id, played, team1_wins, draws, team2_wins)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(team1_id, team2_id) DO UPDATE SET
                   played=excluded.played, team1_wins=excluded.team1_wins,
                   draws=excluded.draws, team2_wins=excluded.team2_wins""",
                (t1, t2, n, t1_wins, draws, t2_wins)
            )
            updated += 1
            print(f"  ✅ {m['home_team_id']} vs {m['away_team_id']}: {n} meetings")
            time.sleep(6)  # Respect rate limit (10 req/min free tier)

        except Exception as e:
            print(f"  ❌ Match {m['id']}: {e}")
            time.sleep(6)

    conn.commit()
    conn.close()
    print(f"\n✅ H2H data stored for {updated} matchups")


if __name__ == "__main__":
    ingest_h2h()
