import os
import sqlite3
import sys

# 基于 __file__ 的绝对路径：不管当前工作目录在哪都能找到数据库
DB_PATH = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
    "database",
    "players.db",
)



def get_connection():

    return sqlite3.connect(DB_PATH)



def list_players():

    conn = get_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
        nickname,
        real_name,
        team
        FROM players
        """
    )


    rows = cursor.fetchall()

    conn.close()


    return rows



def search_player(keyword):

    conn = get_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT *
        FROM players
        WHERE nickname LIKE ?
        """,
        (
            f"%{keyword}%",
        )
    )


    result = cursor.fetchall()

    conn.close()

    return result



def get_player_full(nickname):

    """
    查询选手完整信息(基础信息 + 设置 + 统计):JOIN 三表.

    返回 dict; 未找到返回 None.
    """

    conn = get_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            p.nickname,
            p.real_name,
            p.birth_date,
            p.country,
            p.team,
            p.role,

            s.dpi,
            s.sensitivity,
            s.edpi,
            s.mouse,
            s.resolution,
            s.aspect_ratio,
            s.scaling_mode,
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

        WHERE p.nickname = ?
        """,
        (nickname,)
    )


    row = cursor.fetchone()

    conn.close()


    if row is None:
        return None


    return {

        "nickname": row[0],
        "real_name": row[1],
        "birth_date": row[2],
        "country": row[3],
        "team": row[4],
        "role": row[5],

        "dpi": row[6],
        "sensitivity": row[7],
        "edpi": row[8],
        "mouse": row[9],
        "resolution": row[10],
        "aspect_ratio": row[11],
        "scaling_mode": row[12],
        "crosshair": row[13],
        "viewmodel": row[14],

        "hltv_rating": row[15],
        "major_wins": row[16],
        "hltv_mvp": row[17],
        "updated_at": row[18],
        "crosshair_code": row[19],
        "zoom_sensitivity": row[20],
        "hz": row[21],
        "display_mode": row[22],

    

    }



def get_player_history(nickname, limit=30):
    """返回某选手最近的设置快照（最新在前）。

    历史表 settings_history 在每次成功抓取后追加一行，
    这里按 captured_at 倒序取最近 limit 条。
    """

    conn = get_connection()
    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT
            h.captured_at,
            h.dpi,
            h.sensitivity,
            h.edpi,
            h.mouse,
            h.resolution,
            h.aspect_ratio,
            h.crosshair

        FROM settings_history h

        JOIN players p
            ON p.id = h.player_id

        WHERE p.nickname = ?

        ORDER BY h.captured_at DESC

        LIMIT ?
        """,
        (
            nickname,
            limit,
        )
    )


    rows = cursor.fetchall()

    conn.close()


    return [
        {
            "captured_at": row[0],
            "dpi": row[1],
            "sensitivity": row[2],
            "edpi": row[3],
            "mouse": row[4],
            "resolution": row[5],
            "aspect_ratio": row[6],
            "crosshair": row[7],
        }
        for row in rows
    ]



if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("===== CS Database =====")


    players = list_players()


    for p in players:
        print(
            p
        )
