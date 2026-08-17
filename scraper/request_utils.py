"""requests.get 的指数退避重试包装，两个爬虫共用。"""
import logging
import time
import random
import requests

logger = logging.getLogger("scraper")

# 复用同一个 HTTP 客户端：避免每次请求都新建连接（Liquipedia API 条款要求）
_SESSION = requests.Session()

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

def get_with_retry(url, *, attempts=3, base_delay=2.0, **kwargs):
    """GET 请求，随机 UA + 指数退避 + 抖动重试。

    成功（任意状态码）返回 Response；
    重试耗尽仍失败返回 None；
    其他 RequestException（如 5xx）返回 None 并记日志。
    """
    headers = dict(kwargs.pop("headers", {}))
    if "User-Agent" not in headers:
        headers["User-Agent"] = random.choice(USER_AGENTS)
    kwargs["headers"] = headers

    for attempt in range(1, attempts + 1):
        try:
            return _SESSION.get(url, **kwargs)
        except requests.exceptions.Timeout:
            logger.warning(f"{url} 请求超时 (attempt {attempt}/{attempts})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"{url} 连接失败 (attempt {attempt}/{attempts})")
        except requests.exceptions.RequestException as e:
            logger.warning(f"{url} 请求异常: {e}")
            return None

        if attempt < attempts:
            delay = base_delay * (2 ** (attempt - 1))
            delay *= random.uniform(0.8, 1.4)
            logger.info(f"{delay:.1f}s 后重试 {url}")
            time.sleep(delay)

    return None
