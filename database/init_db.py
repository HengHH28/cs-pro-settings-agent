import sqlite3


conn = sqlite3.connect(
    "database/players.db"
)

cursor = conn.cursor()


# 玩家基础信息
cursor.execute("""
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


# 设置数据

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings(

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    player_id INTEGER,

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


# 比赛统计

cursor.execute("""
CREATE TABLE IF NOT EXISTS statistics(

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    player_id INTEGER,

    major_wins INTEGER,

    hltv_rating REAL,

    hltv_mvp INTEGER

)
""")

# 设置历史快照表：每次抓取成功追加一行，用于回溯设置变化
cursor.execute("""
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
    video TEXT,
    updated_at TEXT,
    crosshair_code TEXT,
    zoom_sensitivity REAL,
    hz INTEGER,
    display_mode TEXT

)

)

)
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_settings_history_player
ON settings_history(player_id, captured_at)
""")


conn.commit()

conn.close()


print("Database initialized")
