"""统一日志配置：控制台 + 轮转文件。

- logs/app.log：所有模块
- logs/scraper.log：爬虫（scraper.*）
- logs/update.log：数据更新（database.update_player / update_all_players）
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

_configured = False


def setup_logging():
    """初始化日志（幂等：重复调用不会重复加 handler）。"""
    global _configured
    if _configured:
        return
    _configured = True

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    os.makedirs(LOGS_DIR, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    general = RotatingFileHandler(
        os.path.join(LOGS_DIR, "app.log"),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    general.setFormatter(formatter)
    root.addHandler(general)

    for name, filename in [
        ("scraper", "scraper.log"),
        ("update", "update.log"),
    ]:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            os.path.join(LOGS_DIR, filename),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # 抑制第三方库的 INFO 噪音（httpx 请求、langchain 内部日志等）
    for noisy in [
        "httpx",
        "httpcore",
        "openai",
        "langchain_openai",
        "langchain",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)