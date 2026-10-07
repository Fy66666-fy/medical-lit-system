"""基础健康监控（P1）：按天统计错误与外部依赖成功率。

背景：应用对外公开后，出问题往往要等用户来反馈才知道。本模块把关键外部
依赖的成败与错误按天落盘，既能在侧边栏「🩺 运行诊断」当场查看近 7 天成功率，
也能在任何时候打开 data/stats/health_YYYY-MM-DD.json 复盘。

与 core/http.py 的分工：
- http.stats() 是**进程内累计**（次数/重试/平均耗时），用于看当下；
- health 是**按天落盘**（依赖维度成功率 + 错误计数），用于看趋势与复盘。

所有写入失败一律静默，绝不拖垮主流程。
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from datetime import datetime, timedelta

from core import storage

STATS_DIR = os.path.join(storage.DATA_DIR, "stats")

# 外部依赖标识（用于分类统计）
DEPS = ("pubmed", "epmc", "figures", "translate", "llm", "unpaywall")

_lock = threading.Lock()

# 图片批量下载等场景会在几秒内产生上百次调用，逐次写盘太重。
# 这里在内存里累积，按时间/条数阈值批量落盘，并在进程退出时补一次。
_pending: dict[tuple[str, bool], int] = {}
_last_flush = 0.0
_FLUSH_INTERVAL = 5.0
_FLUSH_THRESHOLD = 20


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _path(day: str) -> str:
    return os.path.join(STATS_DIR, f"health_{day}.json")


def _blank() -> dict:
    return {
        "day": _today(),
        "errors": 0,
        "last_error": "",
        "deps": {d: {"ok": 0, "fail": 0} for d in DEPS},
    }


def _load(day: str) -> dict:
    p = _path(day)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "deps" in data:
                # 补齐新增的依赖维度，避免旧文件缺键
                for d in DEPS:
                    data["deps"].setdefault(d, {"ok": 0, "fail": 0})
                return data
        except Exception:
            pass
    return _blank()


def _save(day: str, data: dict) -> None:
    try:
        os.makedirs(STATS_DIR, exist_ok=True)
        with open(_path(day), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def record(dep: str, ok: bool) -> None:
    """记录一次外部依赖调用结果（内存累积，按阈值批量落盘）。未知 dep 归到 'other'。"""
    key = (dep if dep in DEPS else "other", bool(ok))
    with _lock:
        _pending[key] = _pending.get(key, 0) + 1
        _save_pending_if_needed()



def _save_pending_if_needed(force: bool = False) -> None:
    """把内存里累积的增量写进当天文件（调用方需持有 _lock）。"""
    global _last_flush
    total = sum(_pending.values())
    now = time.time()
    if not _pending:
        return
    if not force and total < _FLUSH_THRESHOLD and now - _last_flush < _FLUSH_INTERVAL:
        return
    day = _today()
    data = _load(day)
    for (dep, ok), n in _pending.items():
        slot = data["deps"].setdefault(dep, {"ok": 0, "fail": 0})
        slot["ok" if ok else "fail"] = slot.get("ok" if ok else "fail", 0) + n
    data["day"] = day
    _save(day, data)
    _pending.clear()
    _last_flush = now


def flush() -> None:
    """立即落盘（进程退出前调用，避免丢掉最后几秒的统计）。"""
    with _lock:
        _save_pending_if_needed(force=True)


atexit.register(flush)


def record_error(detail: str) -> None:
    """记录一次用户可见的错误（异常兜底处调用）。"""
    if not detail:
        return
    day = _today()
    with _lock:
        data = _load(day)
        data["errors"] = data.get("errors", 0) + 1
        data["last_error"] = str(detail)[:200]
        data["day"] = day
        _save(day, data)


def today() -> dict:
    return _load(_today())


def summary(days: int = 7) -> dict:
    """近 N 天汇总：各依赖成功 / 失败数与成功率，以及错误总数。"""
    out = {
        "days": days,
        "errors": 0,
        "last_error": "",
        "deps": {d: {"ok": 0, "fail": 0, "rate": None} for d in DEPS + ("other",)},
    }
    base = datetime.now().date()
    for i in range(days):
        day = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        data = _load(day)
        out["errors"] += data.get("errors", 0) or 0
        if not out["last_error"] and data.get("last_error"):
            out["last_error"] = data["last_error"]
        for dep, slot in (data.get("deps") or {}).items():
            tgt = out["deps"].setdefault(dep, {"ok": 0, "fail": 0, "rate": None})
            tgt["ok"] += slot.get("ok", 0) or 0
            tgt["fail"] += slot.get("fail", 0) or 0
    for dep, slot in out["deps"].items():
        total = slot["ok"] + slot["fail"]
        slot["rate"] = round(slot["ok"] / total * 100, 1) if total else None
    return out


def success_rate(dep: str, days: int = 7) -> float | None:
    s = summary(days)["deps"].get(dep)
    return s["rate"] if s else None


def format_summary(days: int = 7) -> str:
    """诊断页展示用的一行摘要；无数据时返回简短说明。"""
    s = summary(days)
    parts = []
    for dep in DEPS:
        slot = s["deps"].get(dep) or {}
        total = (slot.get("ok") or 0) + (slot.get("fail") or 0)
        if total:
            parts.append(f"{dep} {slot['rate']}%({total})")
    if not parts:
        return f"近 {days} 天无外部调用记录"
    return f"近 {days} 天成功率 · " + " / ".join(parts) + f" · 错误 {s['errors']} 次"
