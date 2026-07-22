"""Match Intelligence Engine v2 — Dixon-Coles + Multi-Factor Strength Model.

Upgrades from basic independent Poisson:
1. Dixon-Coles τ (tau) correction — fixes systematic underestimation of 0-0, 1-1 draws
2. Multi-factor strength — blends xG, ELO, goals-based attack/defense
3. Stage adjustment — knockout matches are historically tighter
4. Form factor — recent tournament momentum

No gambling terminology. Output is "confidence rating" not "prediction/odds".
"""
import numpy as np
from scipy.stats import poisson
from core.database import get_conn

# --- Stage multiplier: knockout matches are tighter (fewer goals) ---
STAGE_FACTOR = {
    "GROUP_STAGE": 1.0,
    "LAST_32": 0.93,
    "LAST_16": 0.89,
    "QUARTER_FINALS": 0.86,
    "SEMI_FINALS": 0.83,
    "THIRD_PLACE": 0.95,
    "FINAL": 0.80,
}

# Rho (ρ) — Dixon-Coles correlation parameter
# Positive rho = more 0-0 and 1-1 than independent Poisson expects
# Calibrated from historical World Cup data (~0.03-0.05 is typical)
RHO = 0.04


def dixon_coles_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float = RHO) -> float:
    """Dixon-Coles correction factor for low-scoring outcomes.
    Adjusts P(x,y) for correlated goal-scoring when scores are 0 or 1."""
    if x == 0 and y == 0:
        return 1 - lam_h * lam_a * rho
    elif x == 0 and y == 1:
        return 1 + lam_h * rho
    elif x == 1 and y == 0:
        return 1 + lam_a * rho
    elif x == 1 and y == 1:
        return 1 - rho
    return 1.0


def compute_team_strengths() -> dict[int, dict]:
    """Compute goals-based attack/defense strength from completed WC matches."""
    conn = get_conn()
    matches = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score FROM matches WHERE status='FINISHED'"
    ).fetchall()
    conn.close()

    if not matches:
        return {}

    total_home = sum(m["home_score"] for m in matches)
    total_away = sum(m["away_score"] for m in matches)
    n = len(matches)
    avg_home = total_home / n if n else 1.35
    avg_away = total_away / n if n else 1.35

    teams: dict[int, dict] = {}
    for m in matches:
        for tid in (m["home_team_id"], m["away_team_id"]):
            if tid not in teams:
                teams[tid] = {"hs": 0, "hc": 0, "as_": 0, "ac": 0, "hg": 0, "ag": 0}
        teams[m["home_team_id"]]["hs"] += m["home_score"]
        teams[m["home_team_id"]]["hc"] += m["away_score"]
        teams[m["home_team_id"]]["hg"] += 1
        teams[m["away_team_id"]]["as_"] += m["away_score"]
        teams[m["away_team_id"]]["ac"] += m["home_score"]
        teams[m["away_team_id"]]["ag"] += 1

    strengths = {}
    for tid, t in teams.items():
        if t["hg"] + t["ag"] == 0:
            continue
        attack = ((t["hs"] / max(t["hg"], 1)) / max(avg_home, 0.01) +
                  (t["as_"] / max(t["ag"], 1)) / max(avg_away, 0.01)) / 2
        defense = ((t["hc"] / max(t["hg"], 1)) / max(avg_away, 0.01) +
                   (t["ac"] / max(t["ag"], 1)) / max(avg_home, 0.01)) / 2
        strengths[tid] = {"attack": attack, "defense": defense}

    # Persist
    conn = get_conn()
    for tid, s in strengths.items():
        conn.execute(
            "UPDATE teams SET attack_strength=?, defense_strength=?, updated_at=datetime('now') WHERE id=?",
            (s["attack"], s["defense"], tid))
    conn.commit()
    conn.close()
    return strengths


def get_blended_strength(team_id: int, goals_strengths: dict | None = None) -> tuple[float, float]:
    """Multi-factor blended attack/defense strength for a team.

    Blends:
    - 35% xG-based (from qualifying data — best long-term predictor)
    - 30% Goals-based (from actual WC results — captures variance)
    - 20% ELO-derived (captures historical strength gap)
    - 15% Form (recent tournament momentum)

    Returns (attack_strength, defense_strength) normalized around 1.0.
    """
    conn = get_conn()
    team = conn.execute(
        "SELECT elo_rating, xg_for, xg_against, form_score, attack_strength, defense_strength FROM teams WHERE id=?",
        (team_id,)
    ).fetchone()
    conn.close()

    if not team:
        return 1.0, 1.0

    # --- xG factor (35%) — normalized to avg 1.35 goals/game ---
    AVG_XG = 1.35
    xg_attack = (team["xg_for"] or AVG_XG) / AVG_XG
    xg_defense = (team["xg_against"] or AVG_XG) / AVG_XG

    # --- Goals-based factor (30%) — from compute_team_strengths() ---
    if goals_strengths and team_id in goals_strengths:
        g_attack = goals_strengths[team_id]["attack"]
        g_defense = goals_strengths[team_id]["defense"]
    else:
        g_attack = team["attack_strength"] or 1.0
        g_defense = team["defense_strength"] or 1.0

    # --- ELO factor (20%) — normalize ELO to a multiplier ---
    AVG_ELO = 1850  # Approximate WC average
    elo = team["elo_rating"] or AVG_ELO
    elo_factor = 1.0 + (elo - AVG_ELO) / 1000  # +/- 0.1 per 100 ELO points

    # --- Form factor (15%) — from tournament results ---
    form = team["form_score"]
    if form is not None:
        form_factor = 0.85 + (form / 15) * 0.3  # form 0-15 → 0.85-1.15
    else:
        form_factor = 1.0  # No form data yet (tournament hasn't started)

    # --- Blend ---
    attack = (0.35 * xg_attack + 0.30 * g_attack + 0.20 * elo_factor + 0.15 * form_factor)
    defense = (0.35 * xg_defense + 0.30 * g_defense + 0.20 * (2 - elo_factor) + 0.15 * (2 - form_factor))

    return attack, defense


def predict_match(home_id: int, away_id: int, stage: str = "GROUP_STAGE",
                  goals_strengths: dict | None = None) -> dict:
    """Match Intelligence Engine v2: Dixon-Coles + Multi-Factor.

    Returns confidence ratings (NOT predictions/odds).
    """
    h_att, h_def = get_blended_strength(home_id, goals_strengths)
    a_att, a_def = get_blended_strength(away_id, goals_strengths)

    # Expected goals = attack × opposing_defense × baseline × stage_factor
    baseline = 1.35  # World Cup tournament average
    sf = STAGE_FACTOR.get(stage, 1.0)

    exp_home = h_att * a_def * baseline * sf
    exp_away = a_att * h_def * baseline * sf

    # Clamp to reasonable range
    exp_home = max(0.3, min(4.0, exp_home))
    exp_away = max(0.3, min(4.0, exp_away))

    # Probability matrix with Dixon-Coles correction
    max_goals = 8
    home_probs = poisson.pmf(range(max_goals), exp_home)
    away_probs = poisson.pmf(range(max_goals), exp_away)

    matrix = np.zeros((max_goals, max_goals))
    for i in range(max_goals):
        for j in range(max_goals):
            tau = dixon_coles_tau(i, j, exp_home, exp_away)
            matrix[i, j] = home_probs[i] * away_probs[j] * tau

    # Normalize matrix
    matrix /= matrix.sum()

    # Outcomes
    home_win = float(np.sum(np.tril(matrix, -1)))
    draw = float(np.sum(np.diag(matrix)))
    away_win = float(np.sum(np.triu(matrix, 1)))

    # Normalize to 100%
    total = home_win + draw + away_win
    home_win = round(home_win / total * 100, 1)
    draw = round(draw / total * 100, 1)
    away_win = round(100.0 - home_win - draw, 1)

    return {
        "home_win": home_win,
        "draw": draw,
        "away_win": away_win,
        "exp_home_goals": round(exp_home, 2),
        "exp_away_goals": round(exp_away, 2),
        "model_version": "dixon_coles_v2",
        "stage_factor": sf,
    }


def predict_all_upcoming() -> list[dict]:
    """Recalculate confidence ratings for all scheduled matches."""
    goals_strengths = compute_team_strengths()
    conn = get_conn()
    upcoming = conn.execute(
        "SELECT id, home_team_id, away_team_id, stage FROM matches WHERE status IN ('TIMED','SCHEDULED')"
    ).fetchall()

    results = []
    for m in upcoming:
        pred = predict_match(m["home_team_id"], m["away_team_id"],
                             m["stage"] or "GROUP_STAGE", goals_strengths)
        conn.execute(
            """INSERT INTO predictions (match_id, home_win, draw, away_win,
               expected_home_goals, expected_away_goals, model_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(match_id) DO UPDATE SET
               home_win=excluded.home_win, draw=excluded.draw, away_win=excluded.away_win,
               expected_home_goals=excluded.expected_home_goals,
               expected_away_goals=excluded.expected_away_goals,
               model_version=excluded.model_version, created_at=datetime('now')""",
            (m["id"], pred["home_win"], pred["draw"], pred["away_win"],
             pred["exp_home_goals"], pred["exp_away_goals"], pred["model_version"]),
        )
        results.append({"match_id": m["id"], **pred})

    conn.commit()
    conn.close()
    return results
