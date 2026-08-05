import sqlite3
import json
import sys

# Windows 控制台默认编码（如 cp950）打印不了部分简体中文，
# 这里把 stdout 重配为 UTF-8，遇到无法显示的字符用 ? 代替而不是崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 创建数据库（三表规范化结构，与 init_db.py 一致）
#
# 幂等性说明:
#   - players.nickname 有 UNIQUE 约束，INSERT OR REPLACE 可替换
#   - settings.player_id / statistics.player_id 也加 UNIQUE 约束，
#     保证 INSERT OR REPLACE 真正替换而非累积重复行
#   - 导入前清空三表，确保与 players.json 完全一致

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
    video TEXT,
    updated_at TEXT,
    crosshair_code TEXT,
    zoom_sensitivity REAL,
    hz INTEGER,
    display_mode TEXT

)


""")


# 比赛统计
cursor.execute("""
CREATE TABLE IF NOT EXISTS statistics(

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    player_id INTEGER UNIQUE,

    major_wins INTEGER,

    hltv_rating REAL,

    hltv_mvp INTEGER

)
""")
# 设置历史快照表
#
# 设计说明：
#   - settings 表永远只保留每个选手"最新一次"的设置（player_id 唯一）
#   - settings_history 表每次抓取成功都追加一行，用来回溯设置变化
#   - captured_at 默认取 SQLite 本地时间，也可以由调用方显式传入
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
""")

# 按 (选手, 时间) 建索引：查询某个选手的历史时会按这个顺序扫描
cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_settings_history_player
ON settings_history(player_id, captured_at)
""")

# 安全守卫：数据库已有数据时，默认拒绝重建，防止误删爬虫数据
if "--force" not in sys.argv:
    has_data = cursor.execute(
        "SELECT COUNT(*) FROM players"
    ).fetchone()[0] > 0

    if has_data:
        print("检测到 players 表已有数据，跳过重建。")
        print("create_database.py 会清空四张表并按 players.json 重建，")
        print("这会丢失爬虫抓取的最新数据和历史记录。")
        print("确认要重建请运行: python create_database.py --force")
        sys.exit(0)

# 清空三表，保证幂等（避免历史残留数据）
cursor.execute("DELETE FROM statistics")
cursor.execute("DELETE FROM settings")
cursor.execute("DELETE FROM settings_history")
cursor.execute("DELETE FROM players")


# 读取 JSON
with open(
    "database/players.json",
    encoding="utf-8"
) as f:

    players = json.load(f)


# 写入数据库
for nickname, player in players.items():

    # 1. 玩家基础信息
    cursor.execute(
        """
        INSERT OR REPLACE INTO players
        (nickname, real_name, country, team, role)
        VALUES (?,?,?,?,?)
        """,
        (
            nickname,
            player.get("real_name"),
            player.get("country"),
            player.get("team", {}).get("current"),
            ",".join(player.get("role", [])),
        )
    )

    player_id = cursor.lastrowid

    # 2. 设置数据
    mouse = player.get("settings", {}).get("mouse", {})
    video = player.get("settings", {}).get("video", {})
    crosshair = player.get("settings", {}).get("crosshair", {})

    cursor.execute(
        """
        INSERT OR REPLACE INTO settings
        (player_id, dpi, sensitivity, edpi, mouse,
         resolution, aspect_ratio, scaling_mode, crosshair, viewmodel, video,
         crosshair_code)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (player_id,
            mouse.get("dpi"),
            mouse.get("sensitivity"),
            mouse.get("edpi"),
            mouse.get("mouse"),
            video.get("resolution"),
            video.get("aspect_ratio"),
            video.get("scaling_mode"),
            json.dumps(crosshair, ensure_ascii=False) if crosshair else None,
            None,
            None,
            crosshair.get("code"),
        )
    )

    # 3. 比赛统计
    statistics = player.get("statistics", {})

    cursor.execute(
        """
        INSERT OR REPLACE INTO statistics
        (player_id, major_wins, hltv_rating, hltv_mvp)
        VALUES (?,?,?,?)
        """,
        (
            player_id,
            statistics.get("major_wins", 0),
            statistics.get("hltv_rating"),
            statistics.get("hltv_mvp", 0),
        )
    )


conn.commit()

conn.close()


print(f"Database created successfully! ({len(players)} players)")
