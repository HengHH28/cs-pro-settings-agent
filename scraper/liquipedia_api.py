"""Liquipedia API 抓取模块。

提供两种方式从 Liquipedia 的 MediaWiki API 拉取 wikitext：
- scrape_liquipedia(nickname)      : 单个选手抓取（原有逻辑，保留兼容）
- batch_scrape_liquipedia(nicknames): 批量抓取（官方 API 每次最多 50 个页面，
  把一千多次请求压缩到几十次，绕开 429 限流）
"""

import logging
import re
import time

from scraper.request_utils import get_with_retry

logger = logging.getLogger("scraper")


API_URL = "https://liquipedia.net/counterstrike/api.php"

HEADERS = {
    "User-Agent": "CS-Pro-Settings-Agent/1.0 fjh20051228@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# 标记"仍然被限流"，避免和"页面不存在"混淆
RATE_LIMITED = object()

# 429 之后进入冷却，防止继续打 IP
_cooldown_until = 0.0
COOLDOWN_SECONDS = 60      # 冷却时长
BACKOFF_SECONDS = 30       # 429 重试间隔
MAX_429_RETRIES = 3        # 429 最大重试次数

# 批量查询时一次最多携带的页面标题数（MediaWiki API 上限 50）
BATCH_SIZE = 50

# Liquipedia MediaWiki API 条款：
# 普通请求不超过 1 个/2 秒，action=parse 不超过 1 个/30 秒
MIN_REQUEST_INTERVAL = 2.0
PARSE_REQUEST_INTERVAL = 30.0

_last_request_ts = 0.0
_last_parse_ts = 0.0


def _throttle(params):
    """按条款控制请求间隔，避免触发限流封禁。"""
    global _last_request_ts, _last_parse_ts
    is_parse = params.get("action") == "parse"
    min_ts = (
        _last_parse_ts + PARSE_REQUEST_INTERVAL
        if is_parse
        else _last_request_ts + MIN_REQUEST_INTERVAL
    )
    now = time.time()
    if now < min_ts:
        wait = min_ts - now
        logger.info(f"Liquipedia 限速中，等待 {wait:.1f}s...")
        time.sleep(wait)
    _last_request_ts = time.time()
    if is_parse:
        _last_parse_ts = _last_request_ts

# 用于把昵称解析成 Liquipedia 页面名的候选分类
CATEGORY_CANDIDATES = ["Players", "Active players", "Player"]


def _wait_for_cooldown():
    """如果正处于 429 冷却期，先等冷却结束。"""
    global _cooldown_until
    now = time.time()
    if now < _cooldown_until:
        wait = _cooldown_until - now
        logger.warning(f"Liquipedia 限流冷却中 {wait:.0f}s...")
        time.sleep(wait)
    _cooldown_until = 0.0


def _set_cooldown():
    """进入 429 冷却：一段时间内不再发起任何请求。"""
    global _cooldown_until
    _cooldown_until = time.time() + COOLDOWN_SECONDS


def _api_get(params, label):
    """统一请求入口：冷却等待 + 随机延时 + 429 重试。

    返回 JSON 数据；彻底失败返回 None；持续被限流返回 RATE_LIMITED。
    """
    _wait_for_cooldown()

    # Liquipedia 对请求频率敏感，按条款控制间隔
    _throttle(params)

    for attempt in range(1, MAX_429_RETRIES + 1):
        response = get_with_retry(
            API_URL,
            params=params,
            headers=HEADERS,
            timeout=10,
        )

        if response is None:
            logger.warning(f"{label}: 请求失败")
            return None

        if response.status_code == 429:
            logger.warning(
                f"{label}: 429 Too Many Requests "
                f"(attempt {attempt}/{MAX_429_RETRIES}), waiting {BACKOFF_SECONDS}s..."
            )
            time.sleep(BACKOFF_SECONDS)
            continue

        if response.status_code != 200:
            logger.warning(f"{label}: HTTP {response.status_code}")
            return None

        return response.json()

    logger.warning(f"{label}: still rate limited")
    _set_cooldown()
    return RATE_LIMITED


def _page_candidates(nickname):
    """根据昵称生成候选页面名。

    Liquipedia 页面名大小写不固定，例如 zywoo 实际是 ZywOo，
    所以把昵称的几种常见大小写都作为候选。
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


def _normalize_title(title):
    """把页面标题归一化，用于大小写/下划线无关的比较。"""
    return (title or "").replace("_", " ").strip().casefold()


def _match_title(candidate, pages):
    """在批量返回的 pages 里找和 candidate 对应的规范页面名。"""
    needle = _normalize_title(candidate)
    for title in pages:
        if _normalize_title(title) == needle:
            return title
    return None


def _first_plain_link(text):
    """从消歧义页里挑出第一个普通页面链接（跳过分类/文件等命名空间）。"""
    for match in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", text):
        target = match.group(1).strip()
        if not target or ":" in target:
            continue
        return target.replace("_", " ")
    return None


def _fetch_wikitext(page):
    """抓取单个页面的 wikitext；页面不存在返回 None。"""
    params = {
        "action": "parse",
        "page": page,
        "prop": "wikitext",
        "format": "json",
    }

    data = _api_get(params, f"page:{page}")
    if data is RATE_LIMITED:
        return RATE_LIMITED
    if data is None:
        return None
    if "error" in data:
        # 页面不存在 / 无权限
        return None
    return data["parse"]["wikitext"]["*"]


def _search_page(nickname):
    """用 opensearch 搜索昵称对应的页面名。"""
    params = {
        "action": "opensearch",
        "search": nickname,
        "limit": 1,
        "format": "json",
    }

    data = _api_get(params, f"search:{nickname}")
    if data is RATE_LIMITED or data is None:
        if data is RATE_LIMITED:
            logger.warning("Liquipedia Search still rate limited")
        return None

    # opensearch 返回 [query, [page_title, ...], ...]
    if data and len(data) > 1 and data[1]:
        return data[1][0]

    return None


def get_player_text(nickname):
    """获取单个选手的 wikitext。"""
    for page in _page_candidates(nickname):
        text = _fetch_wikitext(page)

        if text is RATE_LIMITED:
            # 限流太严重，直接放弃本轮
            return None

        if text is not None:
            return text

    # 候选页面名都失败，改用搜索解析
    resolved = _search_page(nickname)

    if resolved:
        logger.info(f"Liquipedia: resolved page name -> {resolved}")
        return _fetch_wikitext(resolved)

    logger.error("Liquipedia Error: all page candidates failed")
    return None


def _fetch_pages_batch(titles):
    """一次请求最多 50 个页面，返回 {规范页面名: wikitext}。

    持续限流返回 RATE_LIMITED，请求失败返回 None。
    """
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "redirects": 1,
        "titles": "|".join(titles),
        "format": "json",
    }

    data = _api_get(params, f"batch:{len(titles)} titles")
    if data is RATE_LIMITED or data is None:
        return data

    pages = {}
    raw_pages = (data.get("query") or {}).get("pages") or {}

    # formatversion 不同时 pages 可能是 dict(按 pageid 索引) 或 list
    if isinstance(raw_pages, dict):
        raw_pages = raw_pages.values()

    for page in raw_pages:
        if page.get("missing"):
            continue
        revisions = page.get("revisions") or []
        if not revisions:
            continue
        rev = revisions[0]
        text = (
            rev.get("content")
            or rev.get("*")
            or ((rev.get("slots") or {}).get("main") or {}).get("content")
        )
        if text:
            pages[page.get("title")] = text

    return pages


def _fetch_category_pages(category):
    """抓取某个分类下的全部页面标题（自动翻页）。"""
    titles = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmlimit": 500,
        "cmtype": "page",
        "format": "json",
    }

    while True:
        data = _api_get(params, f"category:{category}")
        if data is RATE_LIMITED or data is None:
            break

        members = (data.get("query") or {}).get("categorymembers") or []
        for member in members:
            title = (member or {}).get("title")
            if title:
                titles.append(title)

        cont = data.get("continue") or {}
        if "cmcontinue" not in cont:
            break
        params["cmcontinue"] = cont["cmcontinue"]

    return titles


def _fetch_category_title_map():
    """用分类成员表把昵称解析成页面名（处理大小写差异）。

    返回 {归一化昵称: 规范页面名}。分类抓不到时返回空 dict。
    """
    title_map = {}

    for category in CATEGORY_CANDIDATES:
        titles = _fetch_category_pages(category)
        if not titles:
            continue
        for title in titles:
            title_map.setdefault(_normalize_title(title), title)
        # 拿到足够多的页面就停止尝试下一个分类
        if len(titles) >= 100:
            break

    return title_map


def get_players_text_batch(nicknames):
    """批量获取多个选手的 wikitext。

    步骤：
      1. 用分类成员表把昵称解析成页面名（覆盖大小写不同的情况）
      2. 剩余昵称按候选页面名批量查询（50 个一批）
      3. 仍未解析的用 opensearch 逐个兜底
      4. 对解析出的页面名批量拉取正文

    返回 (found, missing)：
      found : {昵称: wikitext}
      missing: 没有找到页面的昵称列表
    """
    nicknames = [n.strip().lower() for n in nicknames if n and n.strip()]
    resolved = {}  # 昵称 -> 规范页面名

    if not nicknames:
        return {}, []

    # 1) 分类解析（一次几组请求解决大部分大小写问题）
    title_map = _fetch_category_title_map()
    if title_map:
        for nickname in nicknames:
            canonical = title_map.get(_normalize_title(nickname))
            if canonical:
                resolved[nickname] = canonical

    # 2) 候选页面名批量查询
    unresolved = [n for n in nicknames if n not in resolved]
    candidates = []
    seen = set()
    for nickname in unresolved:
        for cand in _page_candidates(nickname):
            if cand not in seen:
                seen.add(cand)
                candidates.append((nickname, cand))

    for i in range(0, len(candidates), BATCH_SIZE):
        chunk = candidates[i:i + BATCH_SIZE]
        pages = _fetch_pages_batch([cand for _, cand in chunk])
        if pages is RATE_LIMITED or pages is None:
            continue
        for nickname, cand in chunk:
            if nickname in resolved:
                continue
            canonical = _match_title(cand, pages)
            if canonical:
                resolved[nickname] = canonical

    # 3) opensearch 兜底（只针对仍未解析的少量昵称）
    still_missing = [n for n in nicknames if n not in resolved]
    for nickname in still_missing:
        page = _search_page(nickname)
        if page:
            logger.info(f"Liquipedia: resolved page name -> {page}")
            resolved[nickname] = page

    # 4) 批量拉取正文
    unique_titles = list(dict.fromkeys(resolved.values()))
    content_by_title = {}
    for i in range(0, len(unique_titles), BATCH_SIZE):
        chunk = unique_titles[i:i + BATCH_SIZE]
        pages = _fetch_pages_batch(chunk)
        if pages is RATE_LIMITED or pages is None:
            continue
        content_by_title.update(pages)

    # 5) 重定向壳/消歧义页兜底：页面本身没有选手信息时，
    #    取它指向的第一个普通页面再抓一次（例如 device -> Dev1ce）
    follow_targets = {}
    for nickname, title in resolved.items():
        raw = content_by_title.get(title)
        if not raw:
            continue
        target = None
        redirect = re.search(r"#\s*REDIRECT\s*\[\[([^\]|]+)", raw, re.I)
        if redirect:
            target = redirect.group(1).strip().replace("_", " ")
        elif re.search(r"\{\{\s*disambiguation", raw, re.I):
            target = _first_plain_link(raw)
        if target:
            follow_targets[nickname] = target

    if follow_targets:
        extra_titles = list(dict.fromkeys(follow_targets.values()))
        extra_content = {}
        for i in range(0, len(extra_titles), BATCH_SIZE):
            chunk = extra_titles[i:i + BATCH_SIZE]
            pages = _fetch_pages_batch(chunk)
            if pages is RATE_LIMITED or pages is None:
                continue
            extra_content.update(pages)

        for nickname, target in follow_targets.items():
            canonical = _match_title(target, extra_content) or target
            if canonical in extra_content:
                content_by_title[canonical] = extra_content[canonical]
                resolved[nickname] = canonical

    found = {}
    missing = []
    for nickname in nicknames:
        title = resolved.get(nickname)
        if title and title in content_by_title:
            found[nickname] = content_by_title[title]
        else:
            missing.append(nickname)

    return found, missing


def extract_infobox(text):
    """从 wikitext 中提取 {{Infobox player}} 的字段。"""
    info = {}

    matches = re.findall(
        r"\|([^=\n]+)=([^\n|]+)",
        text,
    )

    for key, value in matches:
        info[key.strip()] = value.strip()

    return info


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}


def _to_number(token):
    """把数字或英文数字词转成 int；无法识别返回 None。"""
    token = (token or "").strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _extract_statistics(text):
    """从新版 Liquipedia 页面提取统计字段。

    页面改版后，Major 冠军 / HLTV MVP 等信息写在叙述文字和
    ===MVPs=== / ===Records=== 段落里，旧的正则已经失效。
    这里按优先级尝试多种写法，提取不到就留空，绝不瞎猜。
    """
    stats = {}

    # ---------- HLTV MVP 次数 ----------
    mvp = None

    # 1) ===MVPs=== 段落里的结构化计数行
    m = re.search(
        r"Was named the \[\[HLTV/MVP[_ ]?Awards\|HLTV MVP\]\] of (\d+) tournaments",
        text,
    )
    if m:
        mvp = int(m.group(1))
    else:
        # 2) 介绍段落："won N HLTV MVP awards/medals"
        m = re.search(
            r"won (?:a record )?(\d+) \[\[HLTV/MVP[_ ]?Awards\|HLTV MVP\]\]",
            text,
        )
        if m:
            mvp = int(m.group(1))
        else:
            # 3) ===Records=== 段落："Most MVP awards (N)" / "2nd most MVP awards (N)"
            m = re.search(
                r"(?:\d+(?:st|nd|rd|th)?\s+)?most "
                r"\[\[HLTV/MVP[_ ]?Awards\|HLTV MVP\]\] awards? \((\d+)\)",
                text,
                re.I,
            )
            if m:
                mvp = int(m.group(1))
            else:
                # 4) 逐条列出的 MVP 列表："*Was named the MVP of ... by [[HLTV]]."
                count = len(re.findall(
                    r"\*Was named the MVP of \[\[[^\]]+\]\] by \[\[HLTV\]\]",
                    text,
                ))
                if count:
                    mvp = count
                else:
                    # 5) 叙述里的纯文本写法，如 "2 HLTV MVP"（无链接）
                    m = re.search(r"\b(\d+)\s+HLTV\s+MVP\b", text, re.I)
                    if m:
                        mvp = int(m.group(1))

    if mvp:
        stats["hltv_mvp"] = mvp

    # ---------- Major 冠军次数 ----------
    majors = None

    # 1) 叙述里的数量：
    #    "three [[Majors|Major]] championships" / "including two [[Majors]]"
    #    / "four [[Majors|Major championships]]"
    #    故意不包含 a/an——"a [[Majors|Major]] victory" 这类写法不代表总冠军数
    m = re.search(
        r"(?:including\s+)?("
        r"one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|\d+"
        r")\s+\[\[Majors(?:\|Major[^\]]*)?\]\](?!\s+MVP)"
        r"(?:\s+(?:championships?|titles?|trophies?|wins?))?",
        text,
        re.I,
    )
    if m:
        majors = _to_number(m.group(1))
    else:
        # 2) "a [[PGL Major Stockholm 2021|Major]]" 这类单冠军写法
        m = re.search(
            r"\b(?:a|an)\s+\[\[(?!Majors)[^\]|]+\|Major\]\]",
            text,
        )
        if m:
            majors = 1

    if majors:
        stats["major_wins"] = majors

    # ---------- HLTV Rating ----------
    # 新版页面已不提供职业生涯 Rating 字段，保留旧规则以防个别页面仍有
    rating = re.search(r"HLTV Rating[:\s]*([\d.]+)", text)
    if rating:
        stats["hltv_rating"] = float(rating.group(1))

    return stats


def parse_player(text):
    """从 wikitext 解析选手信息字段。"""
    info = extract_infobox(text)

    data = {}

    # 真实姓名
    if "name" in info:
        data["real_name"] = info["name"]

    # 生日
    if "birth_date" in info:
        data["birth_date"] = info["birth_date"]

    # 国籍
    if "country" in info:
        data["country"] = info["country"]

    # 战队（去掉 "Team " 前缀）
    if "team" in info:
        team = info["team"]
        data["team"] = team.replace("Team ", "")

    # 位置（roles 里含 awp/rifle 关键词）
    if "roles" in info:
        roles = info["roles"].lower()

        if "awp" in roles:
            data["role"] = "AWPer"
        elif "rifle" in roles:
            data["role"] = "Rifler"

    # 统计字段（Major 冠军 / HLTV MVP / Rating）
    data.update(_extract_statistics(text))

    return data


def scrape_liquipedia(nickname):
    """抓取并解析单个选手（返回与批量版本相同的 dict 结构）。"""
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


def batch_scrape_liquipedia(nicknames):
    """批量抓取并解析多个选手。

    返回 {昵称: 结果 dict}，结果结构同 scrape_liquipedia：
    找不到的选手会带 "error": "Player not found"。
    """
    found, missing = get_players_text_batch(nicknames)

    results = {}

    for nickname, raw in found.items():
        data = {
            "nickname": nickname,
            "source": "Liquipedia",
            "text": raw[:2000],
        }
        data.update(parse_player(raw))
        results[nickname] = data

    for nickname in missing:
        results[nickname] = {
            "nickname": nickname,
            "source": "Liquipedia",
            "error": "Player not found",
        }

    return results


if __name__ == "__main__":
    result = scrape_liquipedia("ZywOo")

    print("================")
    print("PARSED DATA")
    print("================")

    for key, value in result.items():
        print(key, ":", value)
