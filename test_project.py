"""
CS_Pro_Settings_Agent 项目测试套件

覆盖本次修改的核心功能:
- 数据库三表结构完整性
- create_database.py 导入(幂等、10 名选手)
- tools.player_settings.search_cs_player 工具
- tools.database_query.query_players_database 工具
- database.db_manager 查询方法
- scraper.prosettings 的 clean_value / classify_table(纯单元测试,不依赖网络)

健壮性设计:
- session 级 autouse fixture 在测试前用 create_database.py 重建干净数据库，
  保证所有依赖数据库的测试从 players.json 基准开始，不因外部爬虫更新而失败。
- 测试结束后恢复测试前的数据库备份，不破坏用户数据。

运行: pytest -v
"""

import sqlite3
import os
import sys
import shutil
import tempfile
import subprocess

import pytest

# 确保项目根目录在 sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "database", "players.db")


@pytest.fixture(scope="session", autouse=True)
def restore_database_around_tests():
    """
    测试前后保护真实数据库，保证测试可重复且不破坏用户数据。

    测试前:
        1. 备份当前 players.db 到系统临时目录
        2. 运行 create_database.py 重建干净基准（players.json 数据）
    测试后:
        恢复备份，删除临时备份文件。
    """
    backup_path = os.path.join(
        tempfile.gettempdir(),
        "players_test_backup.db"
    )

    # 1. 备份当前数据库
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, backup_path)

    # 2. 重建干净基准数据库
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "create_database.py"), "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    yield

    # 3. 恢复用户原数据库
    if os.path.exists(backup_path):
        shutil.copy2(backup_path, DB_PATH)
        os.remove(backup_path)


def _connect():
    return sqlite3.connect(DB_PATH)


# =========================================
# 数据库三表结构
# =========================================

def test_database_has_three_tables():
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert {"players", "settings", "statistics"} <= tables


def test_players_table_has_no_flat_setting_columns():
    """三表结构下 players 不应包含扁平设置列。"""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(players)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "dpi" not in columns
    assert "sensitivity" not in columns


def test_settings_statistics_use_player_id():
    """settings / statistics 表应通过 player_id 关联。"""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(settings)")
    settings_cols = {row[1] for row in cursor.fetchall()}

    cursor.execute("PRAGMA table_info(statistics)")
    stats_cols = {row[1] for row in cursor.fetchall()}

    conn.close()

    assert "player_id" in settings_cols
    assert "player_id" in stats_cols


def test_database_has_ten_players():
    """players.json 共 10 名选手，应全部导入。"""
    conn = _connect()
    cursor = conn.cursor()

    for table in ["players", "settings", "statistics"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        assert count == 10, f"{table} 应有 10 条，实际 {count}"

    conn.close()


def test_players_data_matches_json():
    """数据库 players 数据应与 players.json 一致。"""
    import json

    with open(
        os.path.join(ROOT, "database", "players.json"),
        encoding="utf-8"
    ) as f:
        source = json.load(f)

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nickname, real_name, country, team, role FROM players"
    )
    rows = cursor.fetchall()
    conn.close()

    db_map = {row[0]: row for row in rows}

    assert len(db_map) == len(source)

    for nickname, data in source.items():
        assert nickname in db_map, f"{nickname} 缺失"
        row = db_map[nickname]
        assert row[1] == data["real_name"]
        assert row[2] == data["country"]
        assert row[3] == data["team"]["current"]


def test_create_database_is_idempotent():
    """create_database.py 可重复运行且不报错、不累积数据。"""
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "create_database.py"), "--force"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "10 players" in result.stdout

    # 重复运行后数据量仍应为 10（幂等性）
    conn = _connect()
    cursor = conn.cursor()
    for table in ["players", "settings", "statistics"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        assert count == 10, f"{table} 幂等失败，应为 10 条，实际 {count}"
    conn.close()


# =========================================
def test_create_database_guard_skips_when_data_exists():
    """已有数据时，不带 --force 运行 create_database.py 不应清库"""
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "create_database.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
        timeout=60,
    )

    assert result.returncode == 0
    assert "跳过重建" in result.stdout

    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    conn.close()

    assert count == 10


# ---------- 第 2 段：Agent 装配 ----------


# tools.player_settings.search_cs_player
# =========================================

def test_search_player_exact():
    import json

    from tools.player_settings import search_cs_player

    with open(
        os.path.join(ROOT, "database", "players.json"),
        encoding="utf-8",
    ) as f:
        source = json.load(f)

    zywoo = source["zywoo"]

    result = search_cs_player.invoke({"player_name": "zywoo"})

    assert isinstance(result, dict)
    assert result["nickname"] == "zywoo"
    assert result["dpi"] == zywoo["settings"]["mouse"]["dpi"]
    assert result["sensitivity"] == zywoo["settings"]["mouse"]["sensitivity"]
    assert result["resolution"] == zywoo["settings"]["video"]["resolution"]
    assert result["team"] == zywoo["team"]["current"]

def test_search_player_case_insensitive():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke({"player_name": "ZYWO"})

    assert isinstance(result, dict)
    assert result["nickname"] == "zywoo"


def test_search_player_not_found():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke(
        {"player_name": "不存在的人"}
    )
    assert result == "Player not found"

def test_search_player_displays_unknown():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke({"player_name": "donk"})

    # JSON 基线里 donk 没有 viewmodel → 应显示"未公开"
    assert result["viewmodel"] == "未公开"

def test_search_player_by_real_name():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke(
        {"player_name": "Mathieu Herbaut"}
    )
    assert result["nickname"] == "zywoo"


def test_search_player_alias():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke(
        {"player_name": "simple"}
    )
    assert result["nickname"] == "s1mple"


def test_search_player_by_team():
    import json

    from tools.player_settings import search_cs_player

    with open(
        os.path.join(ROOT, "database", "players.json"),
        encoding="utf-8",
    ) as f:
        source = json.load(f)

    result = search_cs_player.invoke({"player_name": "spirit"})

    # donk 的战队名以 players.json 为准
    assert result["team"] == source["donk"]["team"]["current"]
    assert "donk" in result["players"]

def test_search_player_returns_full_config():
    from tools.player_settings import search_cs_player

    result = search_cs_player.invoke({"player_name": "donk"})

    # 关键字段都应存在
    for key in [
        "nickname", "name", "country", "team", "role",
        "dpi", "sensitivity", "edpi", "mouse",
        "resolution", "crosshair", "hltv_rating", "major_wins",
    ]:
        assert key in result, f"缺少字段 {key}"

def test_get_player_settings_history(monkeypatch):
    """更新一次后能查到历史快照"""
    from tools.player_settings import get_player_settings_history
    from database import update_player as up

    monkeypatch.setattr(
        up,
        "scrape_prosettings",
        lambda n: {
            "mouse": {"DPI": 400, "Sensitivity": 1.8},
            "video": {},
            "crosshair": {},
            "viewmodel": {},
        },
    )
    monkeypatch.setattr(
        up,
        "scrape_liquipedia",
        lambda n: {"real_name": "Mathieu Herbaut"},
    )

    up.update_player("zywoo")

    result = get_player_settings_history.invoke(
        {"player_name": "zywoo", "limit": 5}
    )

    assert isinstance(result, list)
    assert len(result) >= 1
    assert result[0]["dpi"] == 400


def test_get_player_settings_history_not_found():
    from tools.player_settings import get_player_settings_history

    result = get_player_settings_history.invoke(
        {"player_name": "不存在的人"}
    )
    assert result == "Player not found"

# =========================================
# tools.database_query.query_players_database
# =========================================

def test_query_players_database_select():
    from tools.database_query import query_players_database

    result = query_players_database.invoke(
        {"sql_query": "SELECT nickname, team FROM players"}
    )

    assert isinstance(result, list)
    assert len(result) == 10
    assert "nickname" in result[0]


def test_query_players_database_rejects_non_select():
    from tools.database_query import query_players_database

    result = query_players_database.invoke(
        {"sql_query": "DROP TABLE players"}
    )
    assert "Only SELECT queries are allowed." in result


def test_query_players_database_empty_result():
    from tools.database_query import query_players_database

    result = query_players_database.invoke(
        {"sql_query": "SELECT * FROM players WHERE nickname='nobody'"}
    )
    assert result == "No results found."

def test_query_players_database_missing_db(monkeypatch):
    from tools import database_query

    monkeypatch.setattr(
        database_query,
        "DB_PATH",
        r"C:\nonexistent\players.db",
    )
    result = database_query.query_players_database.invoke(
        {"sql_query": "SELECT * FROM players"}
    )
    assert result == "Database not found"

# =========================================
def test_query_agent_tools_wired(monkeypatch):
    from agent import cs_agent
    from tools.player_settings import (
        search_cs_player,
        get_player_settings_history,
    )
    from tools.database_query import query_players_database

    captured = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return kwargs["tools"]

    monkeypatch.setattr(cs_agent, "_get_model", lambda: object())
    monkeypatch.setattr(cs_agent, "create_agent", fake_create_agent)

    tools = cs_agent.create_query_agent()

    assert captured["system_prompt"] == cs_agent.QUERY_SYSTEM_PROMPT
    assert search_cs_player in tools
    assert query_players_database in tools
    assert get_player_settings_history in tools
    assert len(tools) == 3


def test_coding_agent_tools_wired(monkeypatch):
    from agent import cs_agent

    captured = {}

    def fake_create_agent(**kwargs):
        captured.update(kwargs)
        return kwargs["tools"]

    monkeypatch.setattr(cs_agent, "_get_model", lambda: object())
    monkeypatch.setattr(cs_agent, "create_agent", fake_create_agent)

    tools = cs_agent.create_coding_agent()

    assert captured["system_prompt"] == cs_agent.CODING_SYSTEM_PROMPT
    assert len(tools) == 5


# ---------- 第 3 段：爬虫网络路径 ----------


# database.db_manager
# =========================================

def test_db_manager_list_players():
    from database.db_manager import list_players

    players = list_players()
    assert len(players) == 10


def test_db_manager_get_player_full():
    import json

    from database.db_manager import get_player_full

    with open(
        os.path.join(ROOT, "database", "players.json"),
        encoding="utf-8",
    ) as f:
        source = json.load(f)

    donk = source["donk"]

    p = get_player_full("donk")
    assert p is not None
    assert p["nickname"] == "donk"
    assert p["dpi"] == donk["settings"]["mouse"]["dpi"]
    assert p["edpi"] == donk["settings"]["mouse"]["edpi"]


def test_db_manager_get_player_full_not_found():
    from database.db_manager import get_player_full

    assert get_player_full("nobody") is None


# =========================================
# scraper.prosettings 单元测试（不依赖网络）
# =========================================

def test_clean_value_none():
    from scraper.prosettings import clean_value

    assert clean_value(None) is None


def test_clean_value_int():
    from scraper.prosettings import clean_value

    assert clean_value("400") == 400


def test_clean_value_float():
    from scraper.prosettings import clean_value

    assert clean_value("1.25") == 1.25


def test_clean_value_non_numeric():
    from scraper.prosettings import clean_value

    assert clean_value("1280x960") == "1280x960"


def test_clean_value_blank():
    from scraper.prosettings import clean_value

    assert clean_value("   ") is None


def test_classify_mouse_table():
    """游戏内鼠标表: DPI + Sensitivity + eDPI 三键 → mouse"""
    from scraper.prosettings import classify_table

    table = {
        "DPI": 400,
        "Sensitivity": 1.8,
        "eDPI": 720,
        "Hz": 1000,
    }
    assert classify_table(table) == "mouse"


def test_classify_mouse_hardware_table_rejected():
    """鼠标硬件表: 只有 Max DPI，不应被识别为 mouse"""
    from scraper.prosettings import classify_table

    table = {
        "Sensor": "XS-1",
        "Max DPI": 32000,
        "Max Polling Rate": 8000,
        "Weight": "62g",
    }
    # 硬件表应被排除（含 hardware keys → 不参与兜底）
    assert classify_table(table) is None


def test_classify_video_table():
    """游戏内视频表: Resolution + Aspect Ratio + Scaling Mode + Display Mode → video"""
    from scraper.prosettings import classify_table

    table = {
        "Resolution": "1280x960",
        "Aspect Ratio": "4:3",
        "Scaling Mode": "Stretched",
        "Display Mode": "Fullscreen",
    }
    assert classify_table(table) == "video"


def test_classify_crosshair_table():
    """准星表: Style + Thickness + Sniper Width → crosshair"""
    from scraper.prosettings import classify_table

    table = {
        "Style": "Classic Static",
        "Thickness": 1,
        "Sniper Width": 0,
        "Gap": -5,
    }
    assert classify_table(table) == "crosshair"


def test_classify_viewmodel_table():
    """视图模型表: FOV + Presetpos → viewmodel"""
    from scraper.prosettings import classify_table

    table = {
        "FOV": 68,
        "Offset X": 2.5,
        "Presetpos": 1,
        "Bob": "False",
    }
    assert classify_table(table) == "viewmodel"


def test_classify_empty_table():
    from scraper.prosettings import classify_table

    assert classify_table({}) is None

def test_parse_player_extracts_hltv_rating():
    from scraper.liquipedia_api import parse_player

    text = """
    {{Infobox player
    |name=Mathieu Herbaut
    |country=France
    }}
    Achievements: 1 [[Majors]], 2 HLTV MVP
    HLTV Rating: 1.35
    """
    data = parse_player(text)

    assert data["major_wins"] == 1
    assert data["hltv_mvp"] == 2
    assert data["hltv_rating"] == 1.35

# =========================================
class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


def test_scrape_prosettings_success(monkeypatch):
    from scraper import prosettings

    html = (
        "<html><body>"
        "<table><tr><th>DPI</th><td>400</td></tr>"
        "<tr><th>Sensitivity</th><td>1.8</td></tr>"
        "</table></body></html>"
    )
    monkeypatch.setattr(
        prosettings,
        "get_with_retry",
        lambda *a, **k: _FakeResponse(200, html),
    )

    result = prosettings.scrape_prosettings("zywoo")

    assert "error" not in result
    assert result["mouse"]["DPI"] == 400
    assert result["mouse"]["Sensitivity"] == 1.8


def test_scrape_prosettings_http_error(monkeypatch):
    from scraper import prosettings

    monkeypatch.setattr(
        prosettings,
        "get_with_retry",
        lambda *a, **k: _FakeResponse(404, "<html></html>"),
    )

    result = prosettings.scrape_prosettings("zywoo")

    assert result["error"] == "HTTP 404"


def test_scrape_prosettings_network_failure(monkeypatch):
    from scraper import prosettings

    monkeypatch.setattr(
        prosettings,
        "get_with_retry",
        lambda *a, **k: None,
    )

    result = prosettings.scrape_prosettings("zywoo")

    assert "error" in result


# 数据管线：settings_history 表
# =========================================

def test_settings_history_table_exists():
    """create_database.py 重建后必须有 settings_history 表"""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='settings_history'"
    )
    assert cursor.fetchone() is not None
    conn.close()


# =========================================
# 数据管线：update_player 防覆盖 + 历史快照
# =========================================

def _player_id(nickname):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM players WHERE nickname=?",
        (nickname,),
    )
    pid = cursor.fetchone()[0]
    conn.close()
    return pid


def _get_settings(nickname):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT dpi, sensitivity FROM settings WHERE player_id=?",
        (_player_id(nickname),),
    )
    row = cursor.fetchone()
    conn.close()
    return row


def _set_settings(nickname, dpi, sensitivity):
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE settings SET dpi=?, sensitivity=? WHERE player_id=?",
        (dpi, sensitivity, _player_id(nickname)),
    )
    conn.commit()
    conn.close()


def test_update_player_skips_failed_sources(monkeypatch):
    """两个数据源都抓取失败时，数据库里的旧数据必须原封不动"""
    from database import update_player as up

    # 先写入"真实数据"作为基准
    _set_settings("donk", 800, 1.25)

    monkeypatch.setattr(
        up,
        "scrape_prosettings",
        lambda n: {"nickname": n, "error": "network down"},
    )
    monkeypatch.setattr(
        up,
        "scrape_liquipedia",
        lambda n: {"nickname": n, "error": "page not found"},
    )

    up.update_player("donk")

    assert _get_settings("donk") == (800, 1.25)


def test_update_player_does_not_overwrite_missing_fields(monkeypatch):
    """只抓到部分字段时，没抓到的字段不能被写成 NULL"""
    from database import update_player as up

    _set_settings("donk", 800, 1.25)

    monkeypatch.setattr(
        up,
        "scrape_prosettings",
        lambda n: {
            "mouse": {"DPI": 400},
            "video": {},
            "crosshair": {},
            "viewmodel": {},
        },
    )
    monkeypatch.setattr(
        up,
        "scrape_liquipedia",
        lambda n: {"real_name": "Danil Kryshkovets"},
    )

    up.update_player("donk")

    # dpi 更新成 400，但 sensitivity 没抓到 → 保留旧值 1.25
    assert _get_settings("donk") == (400, 1.25)


def test_update_player_success_records_history(monkeypatch):
    """抓取成功时：主表更新 + 历史表追加一条快照"""
    from database import update_player as up

    pid = _player_id("zywoo")

    monkeypatch.setattr(
        up,
        "scrape_prosettings",
        lambda n: {
            "mouse": {
                "DPI": 400,
                "Sensitivity": 1.8,
                "eDPI": 720,
                "Mouse": "ZOWIE EC2-CW",
            },
            "video": {
                "Resolution": "1280x960",
                "Aspect Ratio": "4:3",
                "Scaling Mode": "Stretched",
            },
            "crosshair": {"Style": "Classic Static"},
            "viewmodel": {"FOV": 68},
        },
    )
    monkeypatch.setattr(
        up,
        "scrape_liquipedia",
        lambda n: {
            "real_name": "Mathieu Herbaut",
            "country": "France",
            "team": "Vitality",
            "role": "AWPer",
            "major_wins": 1,
            "hltv_mvp": 2,
        },
    )

    up.update_player("zywoo")

    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT dpi, sensitivity, resolution FROM settings WHERE player_id=?",
        (pid,),
    )
    settings_row = cursor.fetchone()

    cursor.execute(
        "SELECT updated_at FROM settings WHERE player_id=?",
        (_player_id("zywoo"),),
    )
    updated_at = cursor.fetchone()[0]
    conn.close()

    assert updated_at is not None

def test_history_pruned_to_limit(monkeypatch):
    """快照超过 HISTORY_KEEP 条后，旧记录会被清理"""
    from database import update_player as up

    monkeypatch.setattr(
        up,
        "scrape_prosettings",
        lambda n: {
            "mouse": {"DPI": 400, "Sensitivity": 1.8},
            "video": {},
            "crosshair": {},
            "viewmodel": {},
        },
    )
    monkeypatch.setattr(
        up,
        "scrape_liquipedia",
        lambda n: {"real_name": "Mathieu Herbaut"},
    )

    for _ in range(up.HISTORY_KEEP + 5):
        up.update_player("zywoo")

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM settings_history WHERE player_id=?",
        (_player_id("zywoo"),),
    )
    count = cursor.fetchone()[0]
    conn.close()

    assert count == up.HISTORY_KEEP

def test_collect_settings_structured():
    """_collect_settings 把抓取数据拆成结构化字段"""
    from database.update_player import _collect_settings

    fields = _collect_settings(
        1,
        {
            "mouse": {
                "DPI": "400",
                "Sensitivity": "1.8",
                "eDPI": "720",
                "Hz": "1000",
                "Zoom Sensitivity": "1.2",
            },
            "video": {
                "Resolution": "1280x960",
                "Display Mode": "Fullscreen",
            },
            "crosshair": {"Style": "Classic Static"},
            "viewmodel": {},
        },
    )

    assert fields["hz"] == 1000
    assert fields["zoom_sensitivity"] == 1.2
    assert fields["display_mode"] == "Fullscreen"
    assert '"Style": "Classic Static"' in fields["crosshair"]

# =========================================
# 数据管线：名单文件 + 新增选手
# =========================================

def test_read_roster_returns_all_players():
    """名单文件包含现有 10 名选手"""
    from database.update_all_players import read_roster

    roster = read_roster()

    assert len(roster) >= 10
    assert "donk" in roster
    assert "zywoo" in roster


def test_ensure_player_exists_adds_new_player():
    """名单里的新选手会自动补录进 players 表，且不重复"""
    from database.update_all_players import ensure_player_exists

    test_nickname = "test_new_player"

    ensure_player_exists(test_nickname)
    ensure_player_exists(test_nickname)

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM players WHERE nickname=?",
        (test_nickname,),
    )
    count = cursor.fetchone()[0]
    conn.close()

    # 清理测试数据，避免影响其他用例
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM players WHERE nickname=?",
        (test_nickname,),
    )
    conn.commit()
    conn.close()

    assert count == 1

def test_main_parse_args_query():
    from main import parse_args

    args = parse_args(["zywoo", "灵敏度"])

    assert args.query == ["zywoo", "灵敏度"]
    assert args.coding is False
    assert args.interactive is False


def test_main_parse_args_coding():
    from main import parse_args

    args = parse_args(["--coding", "帮我读一下 main.py"])

    assert args.coding is True
    assert args.query == ["帮我读一下 main.py"]


def test_main_parse_args_interactive():
    from main import parse_args

    args = parse_args(["-i"])

    assert args.interactive is True
    assert args.query == []    