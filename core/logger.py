"""轻量日志系统（v2.4.0）。

背景：此前应用没有任何运行日志，线上或桌面端出问题时无法复现与定位，
只能靠用户描述猜测。本模块提供按天落盘的日志，记录关键步骤、外部调用
耗时与异常堆栈。

设计约束：
- 零新增依赖（仅标准库 logging）
- 日志写入失败绝不拖垮主流程（所有写操作均吞异常）
- 日志目录复用 storage.DATA_DIR 约定，桌面版自动落到用户数据目录
- 环境变量 MEDLIT_LOG=0 可完全关闭；MEDLIT_LOG_LEVEL 调整级别；
  MEDLIT_LOG_KEEP_DAYS 控制保留天数
"""
import logging
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta

from core import storage

LOG_DIR = os.path.join(storage.DATA_DIR, "logs")
_KEEP_DAYS = int(os.environ.get("MEDLIT_LOG_KEEP_DAYS", "14") or 14)
_ENABLED = os.environ.get("MEDLIT_LOG", "1") != "0"
_LEVEL = getattr(
    logging, str(os.environ.get("MEDLIT_LOG_LEVEL", "INFO")).upper(), logging.INFO
)

_logger = logging.getLogger("medlit")
_logger.setLevel(_LEVEL)
_logger.propagate = False

_ready = False
_day = ""
_lock = threading.Lock()


def _today_path() -> str:
    return os.path.join(LOG_DIR, f"app_{datetime.now():%Y-%m-%d}.log")


def _build_handler(path: str) -> logging.FileHandler:
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    )
    return fh


def _prune() -> None:
    """清理超过保留天数的旧日志，避免无限增长。"""
    try:
        cut = (datetime.now() - timedelta(days=_KEEP_DAYS)).strftime("%Y-%m-%d")
        for name in os.listdir(LOG_DIR):
            if name.startswith("app_") and name.endswith(".log"):
                if name[4:14] < cut:
                    try:
                        os.remove(os.path.join(LOG_DIR, name))
                    except Exception:
                        pass
    except Exception:
        pass


def setup(version: str = "") -> None:
    """初始化日志（幂等）。任何失败都静默忽略。"""
    global _ready, _day
    if not _ENABLED or _ready:
        return
    with _lock:
        if _ready:
            return
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            _logger.addHandler(_build_handler(_today_path()))
            _ready = True
            _day = datetime.now().strftime("%Y-%m-%d")
            _prune()
            _logger.info("=== 启动 %s (pid=%s) ===", version or "unknown", os.getpid())
        except Exception:
            _ready = False


def _rotate_if_needed() -> None:
    """进程长期运行时跨天切换日志文件。"""
    global _day
    if not _ready:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if today == _day:
        return
    with _lock:
        if today == _day:
            return
        try:
            for h in list(_logger.handlers):
                _logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
            _logger.addHandler(_build_handler(_today_path()))
            _day = today
            _prune()
        except Exception:
            pass


def _write(level: int, msg: str) -> None:
    if not _ENABLED or not _ready:
        return
    try:
        _rotate_if_needed()
        _logger.log(level, msg)
    except Exception:
        pass


def debug(msg: str) -> None:
    _write(logging.DEBUG, msg)


def info(msg: str) -> None:
    _write(logging.INFO, msg)


def warning(msg: str) -> None:
    _write(logging.WARNING, msg)


def error(msg: str, exc: BaseException | None = None) -> None:
    if exc is not None:
        _write(logging.ERROR, f"{msg} | {type(exc).__name__}: {exc}")
        _write(logging.DEBUG, traceback.format_exc())
    else:
        _write(logging.ERROR, msg)


@contextmanager
def span(name: str, **fields):
    """记录一段代码的耗时；异常时记录错误与堆栈后继续抛出。

    用法：
        with logger.span("检索 PubMed", query=q):
            results = pubmed.search(q)
    """
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    info(f"→ {name}" + (f" ({extra})" if extra else ""))
    t0 = time.time()
    failed = False
    try:
        yield
    except Exception as e:
        failed = True
        error(f"✗ {name} 失败", e)
        raise
    finally:
        ms = int((time.time() - t0) * 1000)
        info(f"← {name} {'失败' if failed else '完成'} · {ms}ms")


def install_excepthook() -> None:
    """把未捕获异常写入日志（不影响原有行为）。"""
    original = sys.excepthook

    def hook(etype, value, tb):
        try:
            error(f"未捕获异常 {etype.__name__}: {value}")
            _write(logging.ERROR, "".join(traceback.format_exception(etype, value, tb)))
        except Exception:
            pass
        if original is not None:
            original(etype, value, tb)

    sys.excepthook = hook


def tail(lines: int = 100) -> str:
    """读取最近若干行日志，便于页面内排障展示。失败返回提示文案。"""
    try:
        path = _today_path()
        if not os.path.exists(path):
            return "（暂无日志）"
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return "".join(content[-lines:])
    except Exception as e:
        return f"（读取日志失败：{e}）"
