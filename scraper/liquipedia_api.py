import logging
import random
import re
import time

from scraper.request_utils import get_with_retry

logger = logging.getLogger("scraper")


API_URL = "https://liquipedia.net/counterstrike/api.php"

HEADERS = {
    "User-Agent": "CS-Pro-Settings-Agent/1.0 contact@example.com",
}

# 哨兵值：用来区分"页面不存在"和"被限流"
# （普通返回值 None 表示页面不存在，遇到限流则返回这个特殊对象）
RATE_LIMITED = object()


def _page_candidates(nickname):
    """生成页面名的常见写法（去重、保序）。

    Liquipedia 页面名区分大小写（zywoo 的页面是 ZywOo），
    先试几种常见写法，找不到再走搜索接口。
    """
    candidates = []

    for name in [
        nickname,
        nickname.capitalize(),
        nickname.title(),
        nickname.lower(),
    ]:
        if name and name not in candidates:
            candidates.append(name)

    return candidates


def _fetch_wikitext(page):
    """请求单个页面，返回 wikitext；页面不存在或其他错误都返回 None。"""
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
    }

    # 礼貌原则：任何两次 Liquipedia 请求之间至少隔 1 秒，
    # 避免被限流（429 Too Many Requests）
    time.sleep(random.uniform(0.8, 1.5))

    for attempt in range(2):
        response = get_with_retry(
            API_URL,
            params=params,
            headers=HEADERS,
            timeout=10,
        )

        if response is None:
            logger.warning(f"{page}: 请求失败（已重试）")
            return None

        if response.status_code == 429:
            # 被限流：等 10 秒重试一次；还不行就返回哨兵值
            logger.warning(f"{page}: 429 Too Many Requests, waiting 10s...")
            time.sleep(10)
            continue

        if response.status_code != 200:
            logger.warning(f"{page}: HTTP {response.status_code}")
            return None

        data = response.json()

        if "error" in data:
            # 页面不存在 / 参数错误，统一按"找不到"处理
            return None

        return data["parse"]["wikitext"]["*"]

    logger.warning(f"{page}: still rate limited")
    return RATE_LIMITED


def _search_page(nickname):
    params = {
        "action": "opensearch",
        "search": nickname,
        "limit": 1,
        "format": "json",
    }

    response = get_with_retry(
        API_URL,
        params=params,
        headers=HEADERS,
        timeout=10,
    )

    if response is None:
        logger.warning("Liquipedia Search failed")
        return None

    if response.status_code != 200:
        logger.warning(f"Liquipedia Search HTTP {response.status_code}")
        return None

    data = response.json()

    # opensearch 返回结构：[query, [page_title, ...], ...]
    if data and len(data) > 1 and data[1]:
        return data[1][0]

    return None


def get_player_text(nickname):
    """按顺序尝试页面名，直到拿到 wikitext。"""
    for page in _page_candidates(nickname):
        text = _fetch_wikitext(page)

        if text is RATE_LIMITED:
            # 被限流：再试其他候选大概率还是 429，直接放弃
            return None

        if text is not None:
            return text

    # 常见写法都失败 → 用搜索解析标准页面名，再试一次
    resolved = _search_page(nickname)

    if resolved:
        logger.info(f"Liquipedia: resolved page name -> {resolved}")
        return _fetch_wikitext(resolved)

    logger.error("Liquipedia Error: all page candidates failed")
    return None


def extract_infobox(text):
    """从 wikitext 里提取 {{Infobox player}} 的键值对。"""
    info = {}

    matches = re.findall(
        r"\|([^=\n]+)=([^\n|]+)",
        text,
    )

    for key, value in matches:
        info[key.strip()] = value.strip()

    return info


def parse_player(text):
    info = extract_infobox(text)

    data = {}

    # 真实姓名
    if "name" in info:
        data["real_name"] = info["name"]

    # 出生日期
    if "birth_date" in info:
        data["birth_date"] = info["birth_date"]

    # 国家
    if "country" in info:
        data["country"] = info["country"]

    # 战队（去掉 "Team " 前缀，让名称更简洁）
    if "team" in info:
        team = info["team"]
        data["team"] = team.replace("Team ", "")

    # 位置：根据 roles 里的关键词判断
    if "roles" in info:
        roles = info["roles"].lower()

        if "awp" in roles:
            data["role"] = "AWPer"
        elif "rifle" in roles:
            data["role"] = "Rifler"

    # 荣誉：从 wikitext 里的成就区正则提取
    major = re.search(r"(\d+)\s+\[\[Majors\]\]", text)
    if major:
        data["major_wins"] = int(major.group(1))

    mvp = re.search(r"(\d+)\s+HLTV MVP", text)
    if mvp:
        data["hltv_mvp"] = int(mvp.group(1))
    # HLTV Rating：尽力而为——Liquipedia 通常不给这个指标，
    # 但若未来页面含 "HLTV Rating: 1.25" 之类文本就能抓到
    rating = re.search(r"HLTV Rating[:\s]*([\d.]+)", text)
    if rating:
        data["hltv_rating"] = float(rating.group(1))
    return data


def scrape_liquipedia(nickname):
    raw = get_player_text(nickname)

    if raw is None:
        return {
            "nickname": nickname,
            "source": "Liquipedia",
            "error": "Player not found",
        }

    data = {
        "nickname": nickname,
        "source": "Liquipedia",
        "text": raw[:2000],
    }

    data.update(parse_player(raw))

    return data


if __name__ == "__main__":
    result = scrape_liquipedia("ZywOo")

    print("================")
    print("PARSED DATA")
    print("================")

    for key, value in result.items():
        print(key, ":", value)
