import json
import sqlite3
import os
import sys
import time
import logging
import random
from logging_config import setup_logging
setup_logging()
logger = logging.getLogger("update")

# 保证能导入同目录下的 update_player
sys.path.insert(
    0,
    os.path.dirname(
        os.path.abspath(__file__)
    ),
)

from update_player import update_player, DB_PATH


# 名单文件就是"要跟踪哪些选手"的唯一入口：
# 想新增选手，往这个文件里加一行即可，不用改代码
ROSTER_PATH = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "players.txt",
)


def read_roster(path=ROSTER_PATH):
    """读取选手名单。

    规则：
      - 每行一个昵称
      - 空行跳过
      - # 开头的是注释，跳过
    """
    nicknames = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            nickname = line.strip()

            if nickname and not nickname.startswith("#"):
                nicknames.append(nickname)

    return nicknames

def _should_update(nickname, max_age_days=7):
    """上次更新距今 >= max_age_days 天才需要重新抓取；无记录时返回 True。"""
    from datetime import datetime

    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            """
            SELECT s.updated_at FROM players p
            LEFT JOIN settings s ON s.player_id = p.id
            WHERE p.nickname = ?
            """,
            (nickname,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row[0]:
        return True

    try:
        updated = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return True

    return (datetime.now() - updated).days >= max_age_days

def ensure_player_exists(nickname):
    """名单里的选手如果在 players 表里不存在，先插入一条空记录。

    INSERT OR IGNORE：存在就什么都不做，不存在才插入，
    所以这个函数可以放心地对所有选手调用。
    """
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute(
            "INSERT OR IGNORE INTO players (nickname) VALUES (?)",
            (nickname,),
        )
        conn.commit()
    finally:
        conn.close()

def backup_database():
    """更新前把 players.db 复制成带日期的备份，防止更新中途出错丢数据。"""
    import shutil

    if not os.path.exists(DB_PATH):
        logger.warning("players.db 不存在，跳过备份")
        return

    backup_dir = os.path.join(
        os.path.dirname(DB_PATH),
        "backups",
    )
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target = os.path.join(backup_dir, f"players_{timestamp}.db")

    shutil.copy2(DB_PATH, target)
    logger.info("已备份数据库到 %s", target)

def export_players_to_json(path=None):
    """把数据库当前数据回写成 players.json（与 create_database.py 的读取格式一致）。"""
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "players.json",
        )

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    players = {}

    rows = cur.execute(
        "SELECT id, nickname, real_name, country, team, role FROM players"
    ).fetchall()

    for pid, nickname, real_name, country, team, role in rows:
        settings_row = cur.execute(
            """
            SELECT dpi, sensitivity, edpi, mouse, resolution, aspect_ratio,
                   scaling_mode, crosshair, viewmodel, video, crosshair_code,
                   zoom_sensitivity, hz, display_mode
            FROM settings WHERE player_id=?
            """,
            (pid,),
        ).fetchone()

        stats_row = cur.execute(
            """
            SELECT major_wins, hltv_rating, hltv_mvp
            FROM statistics WHERE player_id=?
            """,
            (pid,),
        ).fetchone()

        mouse = {}
        if settings_row[0] is not None:
            mouse["dpi"] = settings_row[0]
        if settings_row[1] is not None:
            mouse["sensitivity"] = settings_row[1]
        if settings_row[2] is not None:
            mouse["edpi"] = settings_row[2]
        if settings_row[3] is not None:
            mouse["mouse"] = settings_row[3]
        if settings_row[11] is not None:
            mouse["zoom_sensitivity"] = settings_row[11]
        if settings_row[12] is not None:
            mouse["hz"] = settings_row[12]

        video = {}
        if settings_row[4] is not None:
            video["resolution"] = settings_row[4]
        if settings_row[5] is not None:
            video["aspect_ratio"] = settings_row[5]
        if settings_row[6] is not None:
            video["scaling_mode"] = settings_row[6]
        if settings_row[13] is not None:
            video["display_mode"] = settings_row[13]

        crosshair = {}
        if settings_row[7]:
            try:
                crosshair = json.loads(settings_row[7])
            except (TypeError, ValueError):
                pass
        if settings_row[10]:
            crosshair["code"] = settings_row[10]

        settings = {}
        if mouse:
            settings["mouse"] = mouse
        if video:
            settings["video"] = video
        if crosshair:
            settings["crosshair"] = crosshair

        statistics = {}
        if stats_row[1] is not None:
            statistics["hltv_rating"] = stats_row[1]
        if stats_row[0]:
            statistics["major_wins"] = stats_row[0]
        if stats_row[2]:
            statistics["hltv_mvp"] = stats_row[2]

        players[nickname] = {
            "nickname": nickname,
            "real_name": real_name,
            "country": country,
            "team": {"current": team, "previous": []},
            "role": [role] if role else [],
            "settings": settings,
            "statistics": statistics,
        }

    conn.close()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(players, f, ensure_ascii=False, indent=4)

    logger.info("已回写 %d 名选手到 %s", len(players), path)

if __name__ == "__main__":
    backup_database()
    # --only 参数：只更新名单中的某一名选手，例如:
    #   python database/update_all_players.py --only zywoo
    args = sys.argv[1:]
    only = None
    sync_json = "--sync-json" in args
    prosettings_only = "--prosettings-only" in args
    incremental = "--incremental" in args
    fill_missing = "--fill-missing" in args
    fill_stats = "--fill-stats" in args
    liquipedia_batch = "--liquipedia-batch" in args
    max_age = 7
    if "--max-age" in args:
        idx = args.index("--max-age")
        if idx + 1 < len(args):
            max_age = int(args[idx + 1])
    if "--only" in args:
        idx = args.index("--only")
        if idx + 1 < len(args):
            only = args[idx + 1].strip().lower()

    if fill_stats:
        # 只补统计字段：找还没有 Major/MVP 数据的选手
        # 注意：建库时手工种的老数据里 MVP/Major 是 0（占位），
        # 0 不算 NULL，所以这里要把 0 也当成"缺失"重新抓取
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute(
                """
                SELECT p.nickname FROM players p
                LEFT JOIN statistics s ON s.player_id = p.id
                WHERE s.player_id IS NULL
                   OR s.major_wins IS NULL
                   OR s.major_wins = 0
                   OR s.hltv_mvp IS NULL
                   OR s.hltv_mvp = 0
                ORDER BY p.nickname
                """
            ).fetchall()
        finally:
            conn.close()
        roster = [r[0] for r in rows]
        logger.info(f"Players missing statistics: {len(roster)}")
    elif fill_missing:
        # 补资料模式：挑出缺真实姓名或战队的选手。
        # 注意：不要要求"战绩记录"也齐全——大多数 Liquipedia 页面
        # 解析不出 major/MVP 数字，若把战绩算进名单条件，
        # 几乎所有选手都会永远留在名单里，每次重跑都白爬一遍。
        # 战绩仍会在抓取时尽力而为地写入，但不再阻塞名单缩减。
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute(
                """
                SELECT p.nickname FROM players p
                WHERE p.real_name IS NULL
                   OR p.team IS NULL
                ORDER BY p.nickname
                """
            ).fetchall()
            done = conn.execute(
                """
                SELECT COUNT(*) FROM players
                WHERE real_name IS NOT NULL AND team IS NOT NULL
                """
            ).fetchone()[0]
        finally:
            conn.close()
        roster = [r[0] for r in rows]
        logger.info(f"已有真实姓名+战队的选手: {done}")
    else:
        roster = read_roster()

    if only:
        roster = [n for n in roster if n.lower() == only]
        if not roster:
            print(f"名单中没有选手: {only}")
            sys.exit(0)

    logger.info(f"Found {len(roster)} players in roster")

    # ---- 批量模式：先用官方 API 一次性抓取所有选手的 Liquipedia 数据 ----
    # 每次请求最多 50 个页面，把上千次请求压缩到几十次，避开 429 限流
    wiki_cache = None
    if liquipedia_batch and not prosettings_only:
        from scraper.liquipedia_api import batch_scrape_liquipedia

        logger.info(f"Batch-fetching Liquipedia for {len(roster)} players...")
        wiki_cache = batch_scrape_liquipedia(roster)
        found_count = sum(
            1 for value in wiki_cache.values() if "error" not in value
        )
        logger.info(
            f"Liquipedia batch done: {found_count} found, "
            f"{len(roster) - found_count} missing"
        )

    ok_count = 0
    failed = []

    for nickname in roster:
        if incremental and not fill_missing and not _should_update(nickname, max_age):
            logger.info(f"跳过 {nickname}（{max_age} 天内已更新）")
            continue

        
        try:
            logger.info(f"Updating {nickname}...")

            ensure_player_exists(nickname)
            update_player(
                nickname,
                skip_liquipedia=prosettings_only or liquipedia_batch,
                skip_prosettings=fill_missing or fill_stats,
                wiki=(wiki_cache or {}).get(nickname) if liquipedia_batch else None,
            )

            ok_count += 1
            logger.info(f"Successfully updated {nickname}")

        except Exception as e:
            failed.append((nickname, str(e)))
            logger.error(f"Failed to update {nickname}: {e}")

        finally:
            # 礼貌原则：两个选手之间隔 3~6 秒，避免触发网站限流
            # （实测节奏太快（约 13 个请求）就会触发 Liquipedia 429）
            if liquipedia_batch and (fill_missing or fill_stats):
                # 批量模式下 Liquipedia 已抓完，只是写库，不需要长等待
                time.sleep(random.uniform(0.2, 0.5))
            else:
                time.sleep(random.uniform(3.0, 6.0))

    # 汇总报告
    logger.info("=" * 40)
    logger.info(
        f"Summary: {ok_count} ok, {len(failed)} failed, "
        f"{len(roster)} total"
    )
    for nickname, error in failed:
        logger.info(f"  - {nickname}: {error}")
    if sync_json:
        export_players_to_json()
