import argparse
import hashlib
import json
import logging
import os
import sys
import time

from agent.cs_agent import create_query_agent, create_coding_agent
from logging_config import setup_logging

__version__ = "1.0.0"

logger = logging.getLogger("main")

# 交互历史文件（放项目根目录，会加进 .gitignore）
HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".cs_agent_history",
)
# 回答缓存（相同问题 24 小时内直接复用，省 API 调用）
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "answers.json")
CACHE_TTL_SECONDS = 24 * 3600

# Windows 控制台默认编码（如 cp950）打印不了部分简体中文，
# 这里把 stdout 重配为 UTF-8，遇到无法显示的字符用 ? 代替而不是崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def _load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def ask(agent, query, mode="query", use_cache=True):
    cache_key = hashlib.sha256(
        f"{mode}|{query}".encode("utf-8")
    ).hexdigest()

    if use_cache:
        cache = _load_cache()
        entry = cache.get(cache_key)

        if entry and time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            logger.info("cache hit: %s", query)
            print("\nAI answer:")
            print(entry["answer"])
            return

    logger.info("ask: %s", query)

    try:
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": query,
                    }
                ]
            }
        )
    except Exception as e:
        logger.exception("agent invoke failed: %s", e)
        print(f"\nAI answer failed: {e}")
        return

    answer = result["messages"][-1].content

    if use_cache:
        cache = _load_cache()
        cache[cache_key] = {"ts": time.time(), "answer": answer}
        _save_cache(cache)

    print("\nAI answer:")
    print(answer)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="CS2 professional player settings query agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--coding",
        action="store_true",
        help="use the coding agent (file read/write/run tools)",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="force interactive mode even when a query is given",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="disable the answer cache",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="one-shot query text, e.g. zywoo 的设置是什么",
    )
    return parser.parse_args(argv)


def _player_nicknames():
    """从数据库取全部选手昵称，用于 Tab 补全。"""
    try:
        from database.db_manager import list_players

        return [row[0] for row in list_players()]
    except Exception:
        return []


def _print_help():
    print("""
可用命令:
  help / h / ?   显示本帮助
  q / exit       退出

示例问题:
  zywoo 灵敏度是多少
  Mathieu Herbaut 的设置
  simple 是谁
  zywoo 之前的灵敏度是多少

提示: 按 Tab 可补全选手名；上下方向键浏览历史。
""")


def setup_readline(nicknames):
    try:
        import readline
    except ImportError:
        try:
            import pyreadline3 as readline
        except ImportError:
            logger.error(
                "提示: 当前 Python 无 readline，Tab 补全不可用。"
                "可运行 pip install pyreadline3 启用。"
            )
            return None


    """启用 readline（历史 + Tab 补全）；不可用时返回 None。"""
    try:
        import readline
    except ImportError:
        return None

    try:
        readline.read_history_file(HISTORY_FILE)
    except (OSError, ValueError):
        pass

    commands = ["q", "exit", "help", "h", "?"]

    def completer(text, state):
        lowered = text.lower()
        options = [n for n in nicknames if n.lower().startswith(lowered)]
        options += [c for c in commands if c.startswith(lowered)]
        seen = []
        for option in options:
            if option not in seen:
                seen.append(option)
        return seen[state] if state < len(seen) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")

    return readline


def interactive_loop(agent, mode="query", use_cache=True):
    nicknames = _player_nicknames()
    rl = setup_readline(nicknames)

    print("CS Pro Settings Agent started")
    print("Type 'q' to quit, 'help' for help.")

    try:
        while True:
            query = input("\nAsk about a player (q to quit): ")

            if query in ("q", "exit"):
                break

            if query in ("help", "h", "?"):
                _print_help()
                continue

            ask(agent, query, mode=mode, use_cache=use_cache)
    finally:
        if rl is not None:
            try:
                rl.write_history_file(HISTORY_FILE)
            except OSError:
                pass


def main(argv=None):
    setup_logging()
    args = parse_args(argv)

    agent = create_coding_agent() if args.coding else create_query_agent()
    mode = "coding" if args.coding else "query"
    use_cache = not args.no_cache

    # 一行命令模式：python main.py zywoo 的设置是什么
    if args.query and not args.interactive:
        ask(agent, " ".join(args.query), mode=mode, use_cache=use_cache)
        return

    interactive_loop(agent, mode=mode, use_cache=use_cache)


if __name__ == "__main__":
    main()