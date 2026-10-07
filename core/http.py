"""统一外部请求层（v2.5.0）。

背景：此前外部 HTTP 调用散落在 core/pubmed.py、core/translate.py、
core/summarizer.py，各自单独写 timeout / 重试 / 限流，带来三个实际问题：
1. 部分通道完全没有重试（Europe PMC 图片包、Unpaywall、MeSH 建议），
   偶发网络抖动或 429 就直接失败，用户看到的是"解析失败"而非可恢复错误；
2. 限流只有 NCBI 一条（且是全局锁），Europe PMC 并发抓取图片会被限流；
3. 没有任何统一埋点，线上出问题时无法判断是网络、限流还是接口改版。

本模块是所有对外 HTTP 调用的唯一出口，提供：
- 连接 / 读取超时分离，任何调用都有硬上限，杜绝界面卡死；
- 指数退避重试（网络异常 + 429 / 5xx），并尊重响应头的 Retry-After；
- 按域名的串行间隔（NCBI / Europe PMC / Unpaywall 各自按配额友好速率）；
- 统一 User-Agent、统一日志埋点与请求统计（诊断页可直接查看）。

环境变量（可选，用于调参 / 测试）：
  MEDLIT_HTTP_CONNECT / MEDLIT_HTTP_READ  连接 / 读取超时（秒）
  MEDLIT_HTTP_RETRIES                     最大重试次数（默认 3）
  MEDLIT_HTTP_BACKOFF                     退避基数（秒，默认 1.0）
  MEDLIT_HTTP_MAX_BACKOFF                 单次退避上限（秒，默认 8）
  MEDLIT_HTTP_LOG=0                       关闭请求日志
"""
import os
import random
import threading
import time
from urllib.parse import urlsplit

import requests

from core import logger

# ---------------- 默认参数 ----------------
_CONNECT_TIMEOUT = float(os.environ.get("MEDLIT_HTTP_CONNECT", "10") or 10)
_READ_TIMEOUT = float(os.environ.get("MEDLIT_HTTP_READ", "60") or 60)
_MAX_RETRIES = int(os.environ.get("MEDLIT_HTTP_RETRIES", "3") or 0)
_BACKOFF = float(os.environ.get("MEDLIT_HTTP_BACKOFF", "1.0") or 1.0)
_MAX_BACKOFF = float(os.environ.get("MEDLIT_HTTP_MAX_BACKOFF", "8") or 8)
_LOG_ENABLED = os.environ.get("MEDLIT_HTTP_LOG", "1") != "0"

USER_AGENT = "MedLitSummary/2.5 (+https://github.com/; medical literature assistant)"
BASE_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# 可重试的状态码：限流与服务端错误，重试有意义；4xx 语义错误重试无益
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# 按域名的最小请求间隔（秒）。NCBI 无 key 约 3 req/s；Europe PMC 与
# Unpaywall 没有官方硬限，但保持礼貌速率可显著降低 429 概率。
HOST_DELAYS = {
    "eutils.ncbi.nlm.nih.gov": 0.36,
    "www.ebi.ac.uk": 0.34,
    "europepmc.org": 0.34,
    "www.ncbi.nlm.nih.gov": 0.36,
    "pmc.ncbi.nlm.nih.gov": 0.36,
    "api.unpaywall.org": 1.0,
    "api.mymemory.translated.net": 0.20,
}
DEFAULT_HOST_DELAY = 0.0

# ---------------- 线程局部 Session（连接池复用） ----------------
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(BASE_HEADERS)
        _local.session = s
    return s


# ---------------- 域名限流 ----------------
_registry_lock = threading.Lock()
_host_locks: dict[str, threading.Lock] = {}
_host_last: dict[str, float] = {}


def _host_lock(host: str) -> threading.Lock:
    with _registry_lock:
        lk = _host_locks.get(host)
        if lk is None:
            lk = threading.Lock()
            _host_locks[host] = lk
        return lk


def _throttle(host: str, delay: float) -> None:
    """保证同一域名的两次请求间隔不小于 delay（跨线程生效）。"""
    if delay <= 0:
        return
    lk = _host_lock(host)
    with lk:
        now = time.time()
        wait = delay - (now - _host_last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.time()


# ---------------- 统计 ----------------
_stat_lock = threading.Lock()
_STATS = {"requests": 0, "retries": 0, "failures": 0, "bytes": 0, "ms": 0}


def stats() -> dict:
    """返回累计请求统计（供诊断页展示）。"""
    with _stat_lock:
        s = dict(_STATS)
    total = s["requests"]
    s["avg_ms"] = int(s["ms"] / total) if total else 0
    s["mb"] = round(s["bytes"] / 1048576, 2)
    return s


def reset_stats() -> None:
    with _stat_lock:
        for k in _STATS:
            _STATS[k] = 0


def _bump(key: str, value: int = 1) -> None:
    with _stat_lock:
        _STATS[key] = _STATS.get(key, 0) + value


# ---------------- 辅助 ----------------
def host_of(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except Exception:
        return ""


def _norm_timeout(timeout) -> tuple[float, float]:
    if timeout is None:
        return (_CONNECT_TIMEOUT, _READ_TIMEOUT)
    if isinstance(timeout, (tuple, list)):
        return (float(timeout[0]), float(timeout[1]))
    return (_CONNECT_TIMEOUT, float(timeout))


def _retry_after_seconds(resp: requests.Response | None) -> float:
    """解析 Retry-After（秒数或 HTTP 日期）；无法解析返回 0。"""
    if resp is None:
        return 0.0
    raw = (resp.headers.get("Retry-After") or "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        import datetime as _dt

        when = parsedate_to_datetime(raw)
        if when is None:
            return 0.0
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds())
    except Exception:
        return 0.0


def _backoff_seconds(attempt: int, retry_after: float = 0.0) -> float:
    """指数退避 + 抖动；Retry-After 优先（但不超过上限）。"""
    if retry_after > 0:
        return min(retry_after, _MAX_BACKOFF)
    raw = _BACKOFF * (2 ** attempt)
    jitter = raw * 0.2 * random.random()
    return min(raw + jitter, _MAX_BACKOFF)


def _log(msg: str) -> None:
    if _LOG_ENABLED:
        logger.debug(msg)


def _short(url: str) -> str:
    """日志用短标识：只保留 host + path，避免把查询串（可能含关键词）写满日志。"""
    try:
        parts = urlsplit(url)
        path = parts.path if len(parts.path) <= 60 else parts.path[:60] + "…"
        return f"{parts.netloc}{path}"
    except Exception:
        return url[:80]


# ---------------- 主入口 ----------------
def request(
    method: str,
    url: str,
    *,
    params=None,
    data=None,
    json=None,
    headers=None,
    timeout=None,
    retries: int | None = None,
    retry_status=RETRY_STATUS,
    host_delay: float | None = None,
    raise_for_status: bool = True,
    label: str = "",
) -> requests.Response:
    """发出一次 HTTP 请求，带超时、重试、域名限流与埋点。

    参数说明：
      timeout           读取超时秒数（连接超时统一用 MEDLIT_HTTP_CONNECT）；
                        也可直接传 (connect, read) 元组。
      retries           最大重试次数，None 表示用全局默认（MEDLIT_HTTP_RETRIES）。
      retry_status      需要重试的状态码集合；传空集可关闭状态码重试。
      host_delay        该域名的最小请求间隔；None 表示按 HOST_DELAYS 表，
                        显式传 0 表示不限流。
      raise_for_status  最终响应非 2xx 时是否抛 HTTPError（默认 True）。

    抛出的异常均为 requests.RequestException 子类，与直接调用 requests 一致，
    因此既有 `except requests.RequestException` 语义不变。
    """
    max_retries = _MAX_RETRIES if retries is None else max(0, int(retries))
    conn_to, read_to = _norm_timeout(timeout)
    host = host_of(url)
    if host_delay is None:
        host_delay = HOST_DELAYS.get(host, DEFAULT_HOST_DELAY)

    merged = None
    if headers:
        merged = dict(BASE_HEADERS)
        merged.update(headers)

    last_exc: Exception | None = None
    last_resp: requests.Response | None = None
    started = time.time()

    for attempt in range(max_retries + 1):
        if attempt:
            _bump("retries")
        try:
            _throttle(host, host_delay)
            t0 = time.time()
            resp = _session().request(
                method, url, params=params, data=data, json=json,
                headers=merged, timeout=(conn_to, read_to),
            )
            ms = int((time.time() - t0) * 1000)
            size = len(resp.content) if resp.content is not None else 0
            _bump("requests")
            _bump("bytes", size)
            _bump("ms", ms)
            _log(f"HTTP {method} {_short(url)} → {resp.status_code} · {ms}ms · {size}B")

            if resp.status_code in retry_status and attempt < max_retries:
                wait = _backoff_seconds(attempt, _retry_after_seconds(resp))
                _log(f"HTTP 重试 {attempt + 1}/{max_retries}（{resp.status_code}）等待 {wait:.1f}s")
                last_resp = resp
                time.sleep(wait)
                continue

            if raise_for_status:
                resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            retryable = status in retry_status if status else True  # 连接/超时类一律可重试
            if attempt < max_retries and retryable:
                wait = _backoff_seconds(attempt)
                _log(f"HTTP 重试 {attempt + 1}/{max_retries}（{type(e).__name__}）等待 {wait:.1f}s")
                time.sleep(wait)
                continue
            _bump("failures")
            total_ms = int((time.time() - started) * 1000)
            logger.warning(
                f"HTTP {method} {_short(url)} 失败 · {type(e).__name__} · {total_ms}ms"
                + (f" · {label}" if label else "")
            )
            raise

    # 重试次数耗尽但每次都拿到"可重试状态码"的响应
    _bump("failures")
    if last_resp is not None:
        if raise_for_status:
            last_resp.raise_for_status()
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise requests.RequestException(f"请求失败且无可用响应：{_short(url)}")


def get(url: str, **kw) -> requests.Response:
    return request("GET", url, **kw)


def post(url: str, **kw) -> requests.Response:
    return request("POST", url, **kw)


def get_json(url: str, **kw) -> dict:
    """GET 并解析 JSON；非 JSON 内容抛 ValueError。"""
    r = request("GET", url, **kw)
    return r.json()


def post_json(url: str, payload: dict, **kw) -> dict:
    """POST JSON 并解析响应 JSON。"""
    r = request("POST", url, json=payload, **kw)
    return r.json()


def ping(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """连通性自检：返回 (是否可达, 说明)。不抛异常，供诊断页使用。"""
    try:
        r = request("GET", url, timeout=timeout, retries=0, raise_for_status=False)
        return (r.status_code < 500, f"HTTP {r.status_code}")
    except Exception as e:
        return (False, f"{type(e).__name__}")
