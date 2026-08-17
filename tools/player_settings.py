from langchain.tools import tool
from difflib import get_close_matches
from typing import Optional
from datetime import datetime
import sqlite3
import os
from difflib import get_close_matches
from typing import Optional
from database.db_manager import get_player_history

# 数据库路径锚定到项目根目录（基于模块自身位置推导），
# 而不是相对当前工作目录。这样无论工具从哪个目录被调用，
# 都能正确定位到 database/players.db。
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "players.db")

# 模糊匹配参数：
#   - MIN_QUERY_LEN：最短有效查询长度。过短的输入（如 "zy"）会误配到相似昵称，
#     而这类输入更可能是无意义的碎片，直接视为未找到。
#   - MATCH_CUTOFF：difflib.SequenceMatcher 的相似度阈值。
#     0.5 过低，"zoo"→zywoo(0.75)、"zy"→zywoo(0.571) 等无意义输入会被误配。
#     提高到 0.6 后 "ZYWO"→zywoo(≈0.889) 仍正常命中，测试不受影响。
MIN_QUERY_LEN = 3
MATCH_CUTOFF = 0.6
# 别名表：常见拼写 / 简称 → 数据库里的规范昵称
# 键必须小写（查询会被 lower()），命中后直接跳过模糊匹配
ALIASES = {
    "simple": "s1mple",
    "monesy": "m0nesy",
}

def _display(value):
    """None 统一显示为"未公开"，避免 Agent 拿到裸 None 瞎猜。"""
    return "未公开" if value is None else value

def _data_age_days(updated_at):
    """把 updated_at 字符串转成距今天数；无法解析返回 None。"""
    if not updated_at:
        return None

    try:
        captured = datetime.strptime(
            str(updated_at),
            "%Y-%m-%d %H:%M:%S",
        )
        return (datetime.now() - captured).days
    except ValueError:
        return None

def _build_pool(rows):
    """把 (昵称, 真名) 两列建成匹配池：小写名称 -> 规范昵称。

    只放昵称和真名，不放战队名——
    战队名走下面的"战队搜索"分支，返回整队选手。
    """
    pool = {}
    for nickname, real_name in rows:
        for name in (nickname, real_name):
            if name:
                pool[name.strip().lower()] = nickname
    return pool

def _match_pool(query, pool):
    """别名 → 精确 → 相似度 → 包含，返回规范昵称；找不到返回 None。"""
    nickname = ALIASES.get(query)

    if nickname is None and query in pool:
        nickname = pool[query]

    if nickname is None and len(query) >= MIN_QUERY_LEN:
        matches = get_close_matches(
            query,
            list(pool.keys()),
            n=1,
            cutoff=MATCH_CUTOFF
        )

        if not matches:
            contains = [key for key in pool if query in key]
            if contains:
                matches = [sorted(contains, key=len)[0]]

        if matches:
            nickname = pool[matches[0]]

    return nickname

@tool
def search_cs_player(player_name: Optional[str]):
    """
    Search CS2 professional player settings from database.
    Input player nickname, real name, or team name.
    Return player's configuration.
    """

    # 输入校验：非字符串（如 None）或空白字符串时优雅返回 "Player not found"，
    # 而不是在 player_name.strip() 处抛出未捕获的 AttributeError，
    # 破坏工具“不向 Agent 抛异常”的设计约定。
    if not isinstance(player_name, str) or not player_name.strip():
        return "Player not found"

    # 数据库文件不存在时直接返回，避免 sqlite3.connect 在缺失路径上
    # 自动创建一个空的 players.db 文件（副作用）。
    if not os.path.exists(DB_PATH):
        return "Player not found"

    conn = None

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # 获取所有选手昵称
        cursor.execute(
            "SELECT nickname, real_name FROM players"
        )
        rows = cursor.fetchall()
        if not rows:
            return "Player not found"
        pool = _build_pool(rows)
        # 别名 / 精确 / 相似度 / 包含 → 规范昵称
        query = player_name.strip().lower()
        nickname = _match_pool(query, pool)

        # 4. 都不是选手名 → 按战队名搜索，返回整队选手
        if nickname is None:
            cursor.execute(
                "SELECT nickname, team FROM players WHERE team LIKE ?",
                (f"%{query}%",),
            )
            team_rows = cursor.fetchall()

            if team_rows:
                return {
                    "team": team_rows[0][1],
                    "players": [row[0] for row in team_rows],
                }

            return "Player not found"


        # JOIN 三表查询完整信息

        cursor.execute(
            """
            SELECT
                p.nickname,
                p.real_name,
                p.country,
                p.team,
                p.role,
                s.dpi,
                s.sensitivity,
                s.edpi,
                s.mouse,
                s.resolution,
                s.aspect_ratio,
                s.crosshair,
                s.viewmodel,
                st.hltv_rating,
                st.major_wins,
                st.hltv_mvp,
                s.updated_at,
                s.crosshair_code,
                s.zoom_sensitivity,
                s.hz,
                s.display_mode

            FROM players p

            LEFT JOIN settings s
                ON s.player_id = p.id

            LEFT JOIN statistics st
                ON st.player_id = p.id

            WHERE p.nickname=?
            """,
            (nickname,)
        )


        player = cursor.fetchone()

        if player is None:
            return "Player not found"

        return { 
            "nickname": player[0],
            "name": player[1],
            "country": player[2],
            "team": player[3],
            "role": player[4],

            "dpi": _display(player[5]),
            "sensitivity": _display(player[6]),
            "edpi": _display(player[7]),

            "mouse": _display(player[8]),
            "resolution": _display(player[9]),
            "aspect_ratio": _display(player[10]),
            "crosshair": _display(player[11]),
            "viewmodel": _display(player[12]),

            "hltv_rating": _display(player[13]),
            "major_wins": _display(player[14]),
            "hltv_mvp": _display(player[15]),

            "updated_at": _display(player[16]),
            "data_age_days": _data_age_days(player[16]),
            "crosshair_code": _display(player[17]),
            "zoom_sensitivity": _display(player[18]),
            "hz": _display(player[19]),
            "display_mode": _display(player[20]),
        }

    except sqlite3.Error:
        # 数据库缺失、损坏或表不存在时，
        # 工具应优雅返回 "Player not found"，而不是向 Agent 抛异常。
        return "Player not found"

    finally:
        # 无论成功还是异常，都确保连接被关闭，避免连接泄漏。
        if conn is not None:
            conn.close()

def _resolve_player(query):
    """把用户输入解析成规范昵称；找不到返回 None。"""
    if not isinstance(query, str) or not query.strip():
        return None
    if not os.path.exists(DB_PATH):
        return None

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT nickname, real_name FROM players"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        return None

    return _match_pool(query.strip().lower(), _build_pool(rows))


def _resolve_player(query):
    """把用户输入解析成规范昵称；找不到返回 None。"""
    if not isinstance(query, str) or not query.strip():
        return None
    if not os.path.exists(DB_PATH):
        return None

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT nickname, real_name FROM players"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        return None

    return _match_pool(query.strip().lower(), _build_pool(rows))


@tool
def get_player_settings_history(player_name: str, limit: int = 10):
    """
    Query a player's past settings snapshots from the history table,
    most recent first.

    Input: player nickname or real name.
    Return: list of snapshot dicts.
    """
    nickname = _resolve_player(player_name)

    if nickname is None:
        return "Player not found"

    return get_player_history(
        nickname,
        limit=max(1, min(limit, 30)),
    )

