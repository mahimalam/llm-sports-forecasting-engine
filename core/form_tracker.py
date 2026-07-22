"""Form tracker — auto-updates ELO and form_score after each finished match.

Called by the content timer (every 30 min) or manually after match results come in.
ELO uses K=60 (World Cup importance), form is rolling last 5 tournament results.
"""
from core.database import get_conn


def _elo_expected(ra: int, rb: int) -> float:
    """Expected score for team A against team B."""
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400))


def _elo_update(rating: int, expected: float, actual: float, k: int = 60) -> int:
    """Update ELO rating. K=60 for World Cup matches (high importance)."""
    return round(rating + k * (actual - expected))


def update_elo_from_results():
    """Recalculate ELO ratings based on all finished WC matches (in order)."""
    conn = get_conn()

    # Get base ELO ratings
    teams = {r["id"]: r["elo_rating"] or 1500
             for r in conn.execute("SELECT id, elo_rating FROM teams").fetchall()}

    # Process finished matches in chronological order
    matches = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score "
        "FROM matches WHERE status='FINISHED' ORDER BY utc_date"
    ).fetchall()

    for m in matches:
        h_id, a_id = m["home_team_id"], m["away_team_id"]
        h_elo, a_elo = teams.get(h_id, 1500), teams.get(a_id, 1500)

        # Actual result (1=win, 0.5=draw, 0=loss)
        if m["home_score"] > m["away_score"]:
            h_actual, a_actual = 1.0, 0.0
        elif m["home_score"] < m["away_score"]:
            h_actual, a_actual = 0.0, 1.0
        else:
            h_actual, a_actual = 0.5, 0.5

        h_exp = _elo_expected(h_elo, a_elo)
        a_exp = 1.0 - h_exp

        teams[h_id] = _elo_update(h_elo, h_exp, h_actual)
        teams[a_id] = _elo_update(a_elo, a_exp, a_actual)

    # Persist updated ELOs
    for tid, elo in teams.items():
        conn.execute("UPDATE teams SET elo_rating=?, updated_at=datetime('now') WHERE id=?", (elo, tid))
    conn.commit()
    conn.close()
    return len(matches)


def update_form_scores():
    """Calculate form_score for each team from their last 5 tournament results.
    W=3, D=1, L=0. Max possible = 15 (5 wins)."""
    conn = get_conn()
    teams = conn.execute("SELECT id FROM teams").fetchall()

    for team in teams:
        tid = team["id"]
        # Get last 5 results for this team (chronological)
        results = conn.execute(
            """SELECT home_team_id, home_score, away_score FROM matches
               WHERE status='FINISHED' AND (home_team_id=? OR away_team_id=?)
               ORDER BY utc_date DESC LIMIT 5""",
            (tid, tid)
        ).fetchall()

        form = 0
        for r in results:
            if r["home_team_id"] == tid:
                if r["home_score"] > r["away_score"]:
                    form += 3
                elif r["home_score"] == r["away_score"]:
                    form += 1
            else:
                if r["away_score"] > r["home_score"]:
                    form += 3
                elif r["away_score"] == r["home_score"]:
                    form += 1

        if results:
            conn.execute("UPDATE teams SET form_score=?, updated_at=datetime('now') WHERE id=?",
                         (form, tid))

    conn.commit()
    conn.close()


def run_form_update():
    """Full form + ELO update. Call after new results come in."""
    n = update_elo_from_results()
    update_form_scores()
    print(f"✅ Form tracker: processed {n} matches, updated ELO + form for all teams")
    return n


if __name__ == "__main__":
    run_form_update()
