"""迁移 0001：初始四表结构（幂等，CREATE TABLE IF NOT EXISTS）。"""


def upgrade(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT UNIQUE,
        real_name TEXT,
        birth_date TEXT,
        country TEXT,
        team TEXT,
        role TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER UNIQUE,
        dpi INTEGER,
        sensitivity REAL,
        edpi INTEGER,
        mouse TEXT,
        resolution TEXT,
        aspect_ratio TEXT,
        scaling_mode TEXT,
        crosshair TEXT,
        viewmodel TEXT,
        video TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS statistics(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER UNIQUE,
        major_wins INTEGER,
        hltv_rating REAL,
        hltv_mvp INTEGER
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        captured_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        dpi INTEGER,
        sensitivity REAL,
        edpi INTEGER,
        mouse TEXT,
        resolution TEXT,
        aspect_ratio TEXT,
        scaling_mode TEXT,
        crosshair TEXT,
        viewmodel TEXT,
        video TEXT
    )
    """)

    conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_settings_history_player
    ON settings_history(player_id, captured_at)
    """)