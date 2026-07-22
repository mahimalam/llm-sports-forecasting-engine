"""ELO rating scraper — pulls from international-football.net (eloratings.net source)."""
import re
import httpx
from core.database import get_conn

# Homepage gives top 20; individual country pages give the rest
BASE_URL = "https://www.international-football.net"

# Name mapping: our DB name → eloratings.net name
NAME_MAP = {
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Czechia": "Czech Republic",
    "Congo DR": "Dem. Rep. of Congo",
    "Cape Verde Islands": "Cape Verde",
    "Curaçao": "Curaçao",
}


def scrape_homepage_ratings() -> dict[str, int]:
    """Scrape top 20 ELO ratings from homepage."""
    resp = httpx.get(BASE_URL, timeout=15)
    ratings = {}
    matches = re.findall(r'([A-Z][a-z][\w\s\.]+?)\s*[\│|]\s*(\d{4})', resp.text)
    for name, rating in matches:
        name = name.strip()
        if name and len(name) < 30 and "rating" not in name.lower():
            ratings[name] = int(rating)
    return ratings


def scrape_team_rating(team_name: str) -> int | None:
    """Get ELO for a specific team from its country page."""
    lookup = NAME_MAP.get(team_name, team_name)
    try:
        resp = httpx.get(f"{BASE_URL}/country?team={lookup}", timeout=10)
        matches = re.findall(r'Elo\s*(?:rating)?[:\s]*(\d{3,4})', resp.text)
        if matches:
            return int(matches[0])
        matches = re.findall(r'rating.*?(\d{4})', resp.text[:5000])
        return int(matches[0]) if matches else None
    except Exception:
        return None


def ingest_elo_ratings():
    """Scrape and store ELO ratings for all 48 WC teams."""
    conn = get_conn()
    teams = conn.execute("SELECT id, name FROM teams").fetchall()

    # Get homepage ratings first (fast, covers top 20)
    homepage = scrape_homepage_ratings()

    # Reverse name map for lookup
    reverse_map = {v: k for k, v in NAME_MAP.items()}

    updated = 0
    for team in teams:
        db_name = team["name"]
        elo_name = NAME_MAP.get(db_name, db_name)

        # Try homepage first
        elo = homepage.get(elo_name) or homepage.get(db_name)

        # If not in top 20, scrape individual page
        if not elo:
            elo = scrape_team_rating(db_name)

        if elo:
            conn.execute("UPDATE teams SET elo_rating=?, updated_at=datetime('now') WHERE id=?",
                         (elo, team["id"]))
            updated += 1
            print(f"  ✅ {db_name}: {elo}")
        else:
            # Assign a reasonable default for unknown teams
            conn.execute("UPDATE teams SET elo_rating=1500, updated_at=datetime('now') WHERE id=?",
                         (team["id"],))
            print(f"  ⚠️ {db_name}: default 1500")

    conn.commit()
    conn.close()
    print(f"\n{'='*40}\nUpdated {updated}/{len(teams)} teams with ELO ratings")


if __name__ == "__main__":
    ingest_elo_ratings()
