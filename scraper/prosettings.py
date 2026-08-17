import logging

from bs4 import BeautifulSoup

from scraper.request_utils import get_with_retry

logger = logging.getLogger("scraper")


def clean_value(value):
    # 处理 None / 空字符串输入，避免把空值写进数据库
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    try:
        if "." in value:
            return float(value)
        return int(value)

    except (ValueError, TypeError):
        return value


def _normalize_key(key):
    """
    规范化键名，便于可靠匹配。

    处理:
        "DPI"      -> "dpi"
        "eDPI"     -> "edpi"
        "Max DPI"  -> "max dpi"
        "  Sniper Width  " -> "sniper width"

    统一为小写并压缩内部空白，消除因大小写/多余空格导致的匹配失败。
    """
    if key is None:
        return ""

    return " ".join(str(key).lower().split())


# 各设置类别的"强特征键"（规范化后的精确键名）
#
# 不再用硬编码表格索引，也不再依赖宽松的子串打分，
# 而是要求表格中【同时出现】该类别的强特征键，才判定为该类别。
#
# 依据 ProSettings 真实页面结构（实测 zywoo / donk / s1mple）：
#   - 游戏内鼠标表:  DPI / Sensitivity / eDPI / Zoom Sensitivity / Hz / Windows Sensitivity
#                     只需命中任意 2 个即识别（eDPI 等字段缺失时依然可靠，
#                     而鼠标硬件表只有 Max DPI，与 "dpi" 不精确相等，不会误判）
#   - 游戏内视频表:  Resolution + Aspect Ratio + Scaling Mode + Display Mode
#                     （显示器硬件表只有 Resolution/Aspect Ratio，缺 Scaling Mode/Display Mode）
#   - 准星表:        Style / Thickness / Sniper Width
#   - 视图模型表:    FOV / Presetpos / Offset X + 补充表(Lower Amt / Amt Lat)
CATEGORY_STRONG_KEYS = {
    "mouse": [
        "dpi",
        "sensitivity",
        "edpi",
        "zoom sensitivity",
        "hz",
        "windows sensitivity",
    ],
    "crosshair": ["style", "thickness", "sniper width"],
    "viewmodel": ["fov", "presetpos", "offset x", "lower amt", "amt lat"],
    "video": ["resolution", "aspect ratio", "scaling mode", "display mode"],
}

# 每类别归类所需的最少命中数
CATEGORY_MIN_HITS = {
    "mouse": 2,
    "crosshair": 2,
    "viewmodel": 1,
    "video": 3,
}

# 兜底用的宽松关键词（仅当强特征未命中时使用）
CATEGORY_KEYWORDS = {
    "mouse": ["dpi", "polling", "sensitivity", "edpi"],
    "crosshair": [
        "sniper width",
        "follow recoil",
        "deployed weapon gap",
        "split distance",
        "thickness",
        "outline",
        "dot",
    ],
    "viewmodel": [
        "presetpos",
        "viewmodel",
        "view model",
        "fov",
        "bob",
    ],
    "video": [
        "resolution",
        "aspect",
        "refresh",
        "brightness",
        "contrast",
        "display mode",
        "gamma",
        "sharpness",
        "color temperature",
    ],
}

# 硬件 / 显示器 / 外设专属键（规范化后）
#
# 这些键只出现在"设备硬件信息"表格中（鼠标硬件、显示器硬件、显示器画质、
# 键盘、耳机、鼠标垫、座椅等），不属于游戏内设置。
# 兜底识别时若表格包含这些键，直接判定为硬件表，不参与归类，
# 防止 Sensor / Max DPI / Refresh Rate / Picture Mode 等键污染游戏内设置数据。
#
# 注意: 该集合只用于【兜底关键词路径之前】的硬排除；
# 强特征精确匹配仍优先，保证含强特征的游戏内表先被识别。
#
# 另注意: 集合中少数键（"length" / "digital vibrance"）也会以【精确同名】形式
# 出现在游戏内设置表里（实测: 准星表含 "Length"，NVIDIA 视频设置表可能含
# "Digital Vibrance"）。因此硬排除使用其子集 EXCLUSIVE_HARDWARE_KEYS，
# 避免游戏内表因重名键被误判为硬件表而整表丢弃。
HARDWARE_KEYS = {
    "sensor",
    "max dpi",
    "max polling rate",
    "button switches",
    "connection",
    "shape",
    "form factor",
    "switches",
    "pcb",
    "rgb",
    "noise cancelling",
    "microphone",
    "refresh rate",
    "g-sync",
    "freesync",
    "panel tech",
    "size",
    "picture mode",
    "color temperature",
    "ama",
    "dyac",
    "black equalizer",
    "color vibrance",
    "low blue light",
    "digital vibrance",
    "adjustable seat height",
    "adjustable seat depth",
    "adjustable armrests",
    "adjustable backrest",
    "lumbar support",
    "max weight",
    "material",
    "stitched edges",
    "type",
    "length",
    "height",
    "weight",
    "width",
}

# 真正可用于"硬排除"的纯硬件专属键:
#
# 从 HARDWARE_KEYS 中剔除会与游戏内设置表精确重名的键:
#   - "length"          准星表真实含 "Length"（实测 zywoo/donk 等），
#                       若保留在硬排除集合，准星表一旦强特征未凑够
#                       （如缺 Style/Sniper Width）就会被整表误判丢弃。
#   - "digital vibrance" NVIDIA 数字振动设置，可能出现在游戏视频设置表，
#                       同理不能作为硬排除依据。
#
# 剔除后剩余键（sensor / max dpi / refresh rate / material / size ...）
# 只出现在外设、显示器、鼠标垫、座椅等硬件表中，游戏内设置表绝不出现，
# 可安全用于硬排除。
EXCLUSIVE_HARDWARE_KEYS = HARDWARE_KEYS - {"digital vibrance", "length"}


def classify_table(temp):
    """
    根据表格内容的键名识别设置类型。

    识别顺序:
        1. 强特征精确匹配: 规范化后的键名与 CATEGORY_STRONG_KEYS 做精确匹配，
           命中数达到 CATEGORY_MIN_HITS 即归类。这是最可靠的识别方式，
           能精确区分"游戏内设置表"与"硬件/显示器表"。
        2. 纯硬件专属键排除: 含 EXCLUSIVE_HARDWARE_KEYS 中任一键的表格
           （外设/显示器信息）直接排除，不参与兜底。
        3. 兜底关键词打分: 仅当强特征未命中时退回。要求命中至少 2 个关键词，
           且表格不含任何纯硬件专属键，避免外设/显示器表被误判为游戏内设置。

    返回:
        "mouse" / "crosshair" / "viewmodel" / "video"
        无法识别时返回 None
    """

    keys = {
        _normalize_key(k)
        for k in temp.keys()
    }

    # 1. 强特征精确匹配
    for category in CATEGORY_STRONG_KEYS:
        strong = CATEGORY_STRONG_KEYS[category]
        hits = sum(
            1
            for key in strong
            if key in keys
        )

        if hits >= CATEGORY_MIN_HITS[category]:
            return category

    # 含纯硬件专属键的表格（外设/显示器信息）直接排除
    if keys & EXCLUSIVE_HARDWARE_KEYS:
        return None

    # 2. 兜底：关键词打分（规范化后子串匹配）
    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0

        for keyword in keywords:
            if any(keyword in key for key in keys):
                score += 1

        # 至少命中 2 个关键词才认可，避免单键误判
        if score >= 2:
            scores[category] = score

    if not scores:
        return None

    # 平局时取首个最高分，顺序由 CATEGORY_KEYWORDS 插入顺序决定
    return max(scores, key=scores.get)


def scrape_prosettings(nickname):
    nickname = (nickname or "").strip()

    url = f"https://prosettings.net/players/{nickname}/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }

    response = get_with_retry(
        url,
        headers=headers,
        timeout=10,
    )

    if response is None:
        logger.warning(f"{nickname}: 网络请求失败（已重试）")
        return {
            "nickname": nickname,
            "source": "ProSettings",
            "error": "网络请求失败（已重试）",
        }

    if response.status_code != 200:
        logger.warning(f"{nickname}: HTTP {response.status_code}")
        return {
            "nickname": nickname,
            "source": "ProSettings",
            "error": f"HTTP {response.status_code}",
        }

    soup = BeautifulSoup(
        response.text,
        "lxml"
    )

    data = {
        "nickname": nickname,
        "source": "ProSettings",
        "mouse": {},
        "crosshair": {},
        "viewmodel": {},
        "video": {}
    }

    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")

        temp = {}

        for row in rows:
            cols = row.find_all(["th", "td"])

            if len(cols) < 2:
                continue

            key = cols[0].text.strip()
            value = cols[1].text.strip()

            temp[key] = clean_value(value)

        # 仅依据键名识别，不再依赖表格索引
        category = classify_table(temp)

        if category:
            # 同一类别可能出现多张表（如 viewmodel 主表 + 摇晃补充表），
            # 用 update 合并，避免后表覆盖前表导致数据丢失
            data[category].update(temp)

    # 准星代码不在页面表格里，而是由 ProSettings 的前端 JS 动态加载：
    # 页面元素带 data-player-id，再调用 crosshair-pipeline 接口
    # 拿到该选手最近一次被检测到的分享码（接口第一条就是最新的）。
    player_el = soup.select_one("[data-player-id]")
    player_id = player_el.get("data-player-id") if player_el else None
    code = _fetch_crosshair_code(player_id)
    if code and data["crosshair"]:
        data["crosshair"]["Code"] = code

    return data


def _fetch_crosshair_code(player_id):
    """从 ProSettings 的 crosshair-pipeline 接口取最近一次检测到的准星分享码。"""
    if not player_id:
        return None

    url = (
        "https://prosettings.net/wp-json/pro/v1/crosshair-pipeline/"
        f"history?player_id={player_id}"
    )

    try:
        response = get_with_retry(url, timeout=15)
        if response is None or response.status_code != 200:
            return None

        history = (response.json() or {}).get("history") or []
        if history and history[0].get("crosshair_code"):
            return history[0]["crosshair_code"]
    except Exception as e:
        logger.warning(f"crosshair pipeline failed for player {player_id}: {e}")

    return None


if __name__ == "__main__":
    result = scrape_prosettings("zywoo")

    import json

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False
        )
    )
