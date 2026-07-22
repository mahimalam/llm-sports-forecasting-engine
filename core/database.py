import sqlite3
from core.config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    code TEXT,
    group_name TEXT,
    attack_strength REAL,
    defense_strength REAL,
    elo_rating INTEGER,
    xg_for REAL,
    xg_against REAL,
    form_score REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS head2head (
    team1_id INTEGER,
    team2_id INTEGER,
    played INTEGER DEFAULT 0,
    team1_wins INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    team2_wins INTEGER DEFAULT 0,
    PRIMARY KEY (team1_id, team2_id)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    home_team_id INTEGER REFERENCES teams(id),
    away_team_id INTEGER REFERENCES teams(id),
    utc_date TEXT NOT NULL,
    status TEXT DEFAULT 'SCHEDULED',
    home_score INTEGER,
    away_score INTEGER,
    matchday INTEGER,
    stage TEXT,
    source TEXT DEFAULT 'football-data',
    raw_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER REFERENCES matches(id),
    home_win REAL NOT NULL,
    draw REAL NOT NULL,
    away_win REAL NOT NULL,
    expected_home_goals REAL,
    expected_away_goals REAL,
    model_version TEXT DEFAULT 'poisson_v1',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER REFERENCES matches(id),
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    meta_description TEXT,
    content_hash TEXT,
    published_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    velocity INTEGER,
    captured_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(utc_date);
CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
CREATE INDEX IF NOT EXISTS idx_articles_slug ON articles(slug);
CREATE INDEX IF NOT EXISTS idx_trends_keyword ON trends(keyword);

CREATE TABLE IF NOT EXISTS vip_users (
    telegram_id INTEGER PRIMARY KEY,
    activated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rewarded_users (
    telegram_id INTEGER PRIMARY KEY,
    unlocked_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rewarded_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    ads_watched INTEGER DEFAULT 0,
    unlocked INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(telegram_id, match_id)
);
CREATE INDEX IF NOT EXISTS idx_rewarded_sessions_user ON rewarded_sessions(telegram_id);

CREATE TABLE IF NOT EXISTS analytics_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    event TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analytics_event ON analytics_events(event, created_at);

CREATE TABLE IF NOT EXISTS user_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    predicted_winner TEXT NOT NULL,
    predicted_score TEXT,
    confidence INTEGER DEFAULT 50,
    reasoning TEXT,
    is_correct INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_posts_match ON user_posts(match_id);
CREATE INDEX IF NOT EXISTS idx_posts_user ON user_posts(telegram_id);

CREATE TABLE IF NOT EXISTS user_follows (
    follower_id INTEGER NOT NULL,
    followed_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (follower_id, followed_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_followed ON user_follows(followed_id);

CREATE TABLE IF NOT EXISTS user_profiles (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    total_posts INTEGER DEFAULT 0,
    correct_posts INTEGER DEFAULT 0,
    accuracy_pct REAL DEFAULT 0,
    follower_count INTEGER DEFAULT 0,
    rank_position INTEGER,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room TEXT NOT NULL DEFAULT 'global',
    telegram_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    is_vip INTEGER DEFAULT 0,
    message TEXT NOT NULL,
    reply_to_id INTEGER,
    reactions TEXT DEFAULT '{}',
    is_system INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_room_id ON chat_messages(room, id);
"""


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.close()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def log_event(telegram_id: int | None, event: str, metadata: str | None = None):
    """Log an analytics event. Fire-and-forget."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO analytics_events (telegram_id, event, metadata) VALUES (?, ?, ?)",
            (telegram_id, event, metadata),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
