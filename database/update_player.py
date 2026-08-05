import sys
import sqlite3
import os
import json
import logging
import re
from datetime import datetime

# 把项目根目录加进 sys.path，保证无论从哪里运行都能 import scraper
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

logger = logging.getLogger("update")
from logging_config import setup_logging
from scraper.prosettings import scrape_prosettings
from scraper.liquipedia_api import scrape_liquipedia


# 用基于 __file__ 的绝对路径定位数据库：
# 这样不管当前工作目录在哪，都能找到同一个数据库文件
DB_PATH = os.path.join(
    PROJECT_ROOT,
    "database",
    "players.db",
)
# 每个选手历史表最多保留的快照条数（超出自动清理旧快照）
HISTORY_KEEP = 20


def _safe_int(value, default=None):
    """把抓到的字符串安全转成 int。

    None / 非数字时返回 default(默认 None,表示"这次没有这个值").
    返回 None 的字段不会被写入数据库，避免用空值覆盖真实数据。
    """
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default

def _safe_float(value, default=None):
    """把抓到的字符串安全转成 float；失败返回 default。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _collect_settings(player_id, pro):
    """把 ProSettings 抓到的四个分类整理成一行的字段字典。

    返回的 dict 中值为 None 的字段表示这次没抓到，
    调用方绝不能拿 None 去覆盖数据库里已有的值。
    """
    mouse = pro.get("mouse") or {}
    video = pro.get("video") or {}
    crosshair = pro.get("crosshair") or {}
    viewmodel = pro.get("viewmodel") or {}

    fields = {
        "player_id": player_id,
        "dpi": _safe_int(mouse.get("DPI")),
        "sensitivity": mouse.get("Sensitivity"),
        "edpi": _safe_int(mouse.get("eDPI")),
        "mouse": mouse.get("Mouse"),
        "resolution": video.get("Resolution"),
        "aspect_ratio": video.get("Aspect Ratio"),
        "scaling_mode": video.get("Scaling Mode"),
        "display_mode": video.get("Display Mode"),
        "zoom_sensitivity": _safe_float(mouse.get("Zoom Sensitivity")),
        "hz": _safe_int(mouse.get("Hz")),
        "crosshair_code": crosshair.get("Code"),
        "crosshair": json.dumps(crosshair, ensure_ascii=False) if crosshair else None,
        "viewmodel": json.dumps(viewmodel, ensure_ascii=False) if viewmodel else None,
        "video": json.dumps(video, ensure_ascii=False) if video else None,
    }

    return _validate_collected(fields)

def _validate_collected(fields):
    """核心字段合理性校验：超范围/格式异常的直接丢弃（置 None）并记日志。"""
    logger = logging.getLogger("update")

    # (列名, 最小值, 最大值)
    for column, low, high in [
        ("dpi", 50, 20000),
        ("edpi", 50, 50000),
        ("hz", 100, 8000),
    ]:
        value = fields.get(column)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            logger.warning(f"{column} 不是数字: {value!r}，已丢弃")
            fields[column] = None
            continue
        if not (low <= number <= high):
            logger.warning(f"{column} 超出合理范围 {low}-{high}: {value!r}，已丢弃")
            fields[column] = None

    # 灵敏度
    sens = fields.get("sensitivity")
    if sens is not None:
        try:
            sens_number = float(sens)
        except (TypeError, ValueError):
            logger.warning(f"sensitivity 不是数字: {sens!r}，已丢弃")
            fields["sensitivity"] = None
        else:
            if not (0.01 <= sens_number <= 20):
                logger.warning(f"sensitivity 超出合理范围 0.01-20: {sens!r}，已丢弃")
                fields["sensitivity"] = None

    # 分辨率格式
    resolution = fields.get("resolution")
    if resolution is not None and not re.fullmatch(
        r"\d{3,5}x\d{3,5}", str(resolution)
    ):
        logger.warning(f"resolution 格式异常: {resolution!r}，已丢弃")
        fields["resolution"] = None

    # 一致性：eDPI ≈ DPI × 灵敏度（只警告，不丢弃）
    dpi = fields.get("dpi")
    edpi = fields.get("edpi")
    if dpi is not None and sens is not None and edpi is not None:
        expected = dpi * float(sens)
        if expected > 0 and abs(edpi - expected) / expected > 0.3:
            logger.warning(
                f"eDPI({edpi}) 与 DPI×灵敏度({expected:.0f}) 偏差超过 30%，请人工核对"
            )

    return fields

def _record_history(cursor, player_id, fields):
    """把这次抓到的设置快照追加进历史表。

    历史表记录"当时抓到的值"，所以允许 NULL 字段——
    它如实反映"这次没有抓到某字段"，而不是覆盖什么旧数据。
    """
    cursor.execute(
        """
        INSERT INTO settings_history
        (player_id, dpi, sensitivity, edpi, mouse, resolution,
         aspect_ratio, scaling_mode, crosshair, viewmodel, video)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            player_id,
            fields.get("dpi"),
            fields.get("sensitivity"),
            fields.get("edpi"),
            fields.get("mouse"),
            fields.get("resolution"),
            fields.get("aspect_ratio"),
            fields.get("scaling_mode"),
            fields.get("crosshair"),
            fields.get("viewmodel"),
            fields.get("video"),
        ),
    )

def _prune_history(cursor, player_id, keep=HISTORY_KEEP):
    """每个选手只保留最近 keep 条快照，防止历史表无限膨胀。"""
    cursor.execute(
        """
        DELETE FROM settings_history
        WHERE player_id = ?
          AND id NOT IN (
              SELECT id
              FROM settings_history
              WHERE player_id = ?
              ORDER BY captured_at DESC, id DESC
              LIMIT ?
          )
        """,
        (player_id, player_id, keep),
    )

def _upsert_settings(cursor, fields):
    """把这次抓到的设置写进 settings 主表。

    为什么不用 INSERT OR REPLACE:
    REPLACE 会先 DELETE 旧行再 INSERT,没传的列会被写成 NULL——
    等于用空值覆盖真实数据。

    这里改成：
      - 已有行：只 UPDATE 这次抓到的列(非 None)
      - 没有行:INSERT,缺的列留 NULL(本来就没有旧值可保护）

    注：表名/列名都是代码里写死的常量，不是用户输入，拼进 SQL 是安全的。
    """
    player_id = fields.pop("player_id")
    fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    non_null = {
        col: value
        for col, value in fields.items()
        if value is not None
    }

    if not non_null:
        return 0

    columns = list(non_null)

    cursor.execute(
        "SELECT 1 FROM settings WHERE player_id=?",
        (player_id,),
    )
    exists = cursor.fetchone() is not None

    if exists:
        sets = ", ".join(f"{col}=?" for col in columns)
        cursor.execute(
            f"UPDATE settings SET {sets} WHERE player_id=?",
            [non_null[col] for col in columns] + [player_id],
        )
    else:
        all_columns = ["player_id"] + columns
        placeholders = ", ".join("?" for _ in all_columns)
        cursor.execute(
            f"INSERT INTO settings ({', '.join(all_columns)}) "
            f"VALUES ({placeholders})",
            [player_id] + [non_null[col] for col in columns],
        )

    return cursor.rowcount


def _update_player_info(cursor, player_id, wiki):
    """更新 players 表的基本信息，只更新这次抓到的字段。"""
    fields = {}

    for column, key in [
        ("real_name", "real_name"),
        ("birth_date", "birth_date"),
        ("country", "country"),
        ("team", "team"),
        ("role", "role"),
    ]:
        value = wiki.get(key)
        if value is not None:
            fields[column] = value

    if not fields:
        return

    sets = ", ".join(f"{col}=?" for col in fields)
    cursor.execute(
        f"UPDATE players SET {sets} WHERE id=?",
        [fields[col] for col in fields] + [player_id],
    )


def _upsert_statistics(cursor, player_id, wiki):
    """更新 statistics 表，只更新这次抓到的字段（逻辑同 settings）。"""
    fields = {}

    for column, key in [
        ("major_wins", "major_wins"),
        ("hltv_mvp", "hltv_mvp"),
        ("hltv_rating", "hltv_rating"),
    ]:
        value = wiki.get(key)
        if value is not None:
            fields[column] = value

    if not fields:
        return

    columns = list(fields)

    cursor.execute(
        "SELECT 1 FROM statistics WHERE player_id=?",
        (player_id,),
    )
    exists = cursor.fetchone() is not None

    if exists:
        sets = ", ".join(f"{col}=?" for col in columns)
        cursor.execute(
            f"UPDATE statistics SET {sets} WHERE player_id=?",
            [fields[col] for col in columns] + [player_id],
        )
    else:
        all_columns = ["player_id"] + columns
        placeholders = ", ".join("?" for _ in all_columns)
        cursor.execute(
            f"INSERT INTO statistics ({', '.join(all_columns)}) "
            f"VALUES ({placeholders})",
            [player_id] + [fields[col] for col in columns],
        )


def _ensure_schema(conn):
    """确保历史表存在（幂等建表）。

    老数据库可能没有 settings_history 表，
    所以每次更新前都检查一次，表不存在就创建——
    这样升级 schema 时不需要手动重建整个数据库。
    """
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

        # 老库迁移：settings 表新增列（列已存在时静默跳过）
    for column in [
        "updated_at TEXT",
        "crosshair_code TEXT",
        "zoom_sensitivity REAL",
        "hz INTEGER",
        "display_mode TEXT",
    ]:
        try:
            conn.execute(f"ALTER TABLE settings ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass


def update_player(nickname, skip_liquipedia=False):
    """抓取并更新一名选手的数据。

    规则：
      1. 某个数据源返回 error 时，完全跳过该数据源（不写入任何字段）
      2. 抓到的字段为 None 时，不覆盖数据库里的旧值
      3. settings 更新成功后，把快照记进 settings_history
    """
    nickname = (nickname or "").strip().lower()

    conn = sqlite3.connect(DB_PATH)

    try:
        _ensure_schema(conn)

        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM players WHERE nickname=?",
            (nickname,),
        )
        row = cursor.fetchone()

        if row is None:
            logger.info(f"Player not found in database: {nickname}")
            return

        player_id = row[0]

        logger.info("Fetching ProSettings...")
        pro = scrape_prosettings(nickname)

        if skip_liquipedia:
            wiki = {}
        else:
            print("Fetching Liquipedia...")
            wiki = scrape_liquipedia(nickname)

        # ---------- ProSettings：鼠标 / 视频 / 准星 / 视角 ----------
        if pro.get("error"):
            logger.info(f"  [SKIP] ProSettings scrape failed: {pro['error']}")
        else:
            fields = _collect_settings(player_id, pro)

            non_null = {
                col: value
                for col, value in fields.items()
                if col != "player_id" and value is not None
            }

            if not non_null:
                logger.info("  [SKIP] ProSettings returned no settings fields")
            else:
                # 先记历史快照，再更新主表；
                # 两者在同一个事务里，任一步出错都会一起回滚
                _record_history(cursor, player_id, fields)
                _upsert_settings(cursor, fields)
                _prune_history(cursor, player_id)

        # ---------- Liquipedia：姓名 / 国家 / 战队 / 荣誉 ----------
        if wiki.get("error"):
            logger.info(f"  [SKIP] Liquipedia scrape failed: {wiki['error']}")
        else:
            _update_player_info(cursor, player_id, wiki)
            _upsert_statistics(cursor, player_id, wiki)

        conn.commit()
        logger.info(f"{nickname} updated successfully")

    finally:
        # 没走到 commit（比如上面抛异常）时，关闭连接会自动回滚，
        # 保证数据库不会出现"只写了一半"的状态
        conn.close()


if __name__ == "__main__":
    setup_logging()
    if len(sys.argv) < 2:
        logger.info("Usage: python update_player.py nickname")
        exit()

    update_player(sys.argv[1])
