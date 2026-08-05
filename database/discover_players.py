"""从 ProSettings REST 接口抓取全部 CS2 选手名单，写入 players.txt。"""
import os
import re
import time

import requests

BASE = "https://prosettings.net/wp-json/pro/v2/players/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CS2_GAME_ID = 468
BATCH = 100
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players.txt")


def fetch_page(page, limit=BATCH, game_id=CS2_GAME_ID):
    time.sleep(1.5)
    r = requests.get(
        BASE,
        headers=HEADERS,
        params={"page": str(page), "limit": str(limit), "game": str(game_id)},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def slug_from_player(player):
    url = player.get("url") or ""
    m = re.search(r"/players/([a-z0-9_-]+)/?$", url)
    if m:
        return m.group(1)
    return (player.get("name") or "").strip().lower()


def main():
    slugs = []
    page = 1
    total = None

    while True:
        data = fetch_page(page)
        total = data.get("total_players")
        players = data.get("players") or []

        if not players:
            break

        for player in players:
            slug = slug_from_player(player)
            if slug and slug not in slugs:
                slugs.append(slug)

        print(f"page {page}: got {len(players)}, collected {len(slugs)}/{total}")

        if len(players) < BATCH or len(slugs) >= (total or 0):
            break

        page += 1

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for slug in slugs:
            f.write(slug + "\n")

    print(f"done: {len(slugs)} CS2 players -> {OUTPUT}")


if __name__ == "__main__":
    main()