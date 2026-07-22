"""
Daily prediction refresh — run before each match day.
Pipeline: ELO update → form update → team strengths → predict all upcoming
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.form_tracker import run_form_update
from core.poisson import compute_team_strengths, predict_all_upcoming

def run():
    print("=== vexp.me Prediction Refresh ===")

    # 1. Update ELO ratings from all finished matches
    print("1/3 Updating ELO + form scores...")
    n = run_form_update()
    print(f"    → {n} finished matches processed")

    # 2. Recompute attack/defense strengths from WC goals data
    print("2/3 Computing team strengths from WC results...")
    strengths = compute_team_strengths()
    print(f"    → {len(strengths)} teams with goals-based strength data")

    # 3. Re-run Poisson model for all upcoming matches
    print("3/3 Regenerating predictions for all upcoming matches...")
    results = predict_all_upcoming()
    print(f"    → {len(results)} predictions updated in DB")

    print("=== Done ===")
    for r in results[:5]:
        print(f"    Match {r['match_id']}: home={r['home_win']:.1f}% draw={r['draw']:.1f}% away={r['away_win']:.1f}%")
    if len(results) > 5:
        print(f"    ...and {len(results)-5} more")

if __name__ == "__main__":
    run()
