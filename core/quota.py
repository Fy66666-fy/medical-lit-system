"""配额与成本开关（P1）：防止额度被刷穿，并在耗尽时引导用户自带密钥。

背景：翻译用腾讯云 TMT（每月 500 万字符免费额度），LLM 摘要是用户自带 Key。
一旦把链接公开，如果不设限，少数人反复跑批量就能把月额度在一天内烧光，
届时所有访客都只能用质量较差的免费兜底接口。

设计：
- **两级配额**：会话级（防单用户无意识滥用）+ 全局每日级（防总量失控）；
- **软失败**：超限不抛异常吓人，而是返回 (False, 提示文案)，由界面决定降级方式；
- **自带 Key 免配额**：用户在侧边栏填了自己的密钥 / 填了自己的 LLM 配置时，
  只消耗 TA 自己的额度，不受宿主配额限制（这是成本可控的关键）；
- 单机会话计数在内存，全局每日计数按天落盘到 data/stats/，重启不丢当日用量。

环境变量（部署时可覆盖）：
  MEDLIT_QUOTA_SESSION_CHARS   单会话翻译字符上限（默认 200000）
  MEDLIT_QUOTA_SESSION_LLM     单会话 LLM 调用上限（默认 50）
  MEDLIT_QUOTA_DAILY_CHARS     全局每日翻译字符上限（默认 150000）
  MEDLIT_QUOTA_DAILY_LLM       全局每日 LLM 调用上限（默认 300）
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from core import storage

# ---------------- 限额配置 ----------------
SESSION_CHARS = int(os.environ.get("MEDLIT_QUOTA_SESSION_CHARS", "200000"))
SESSION_LLM = int(os.environ.get("MEDLIT_QUOTA_SESSION_LLM", "50"))
DAILY_CHARS = int(os.environ.get("MEDLIT_QUOTA_DAILY_CHARS", "150000"))
DAILY_LLM = int(os.environ.get("MEDLIT_QUOTA_DAILY_LLM", "300"))

# 翻译按字符计、LLM 按次计
KINDS = ("trans_chars", "llm_calls")

_LIMITS = {
    "trans_chars": {"session": SESSION_CHARS, "daily": DAILY_CHARS, "unit": "字符"},
    "llm_calls": {"session": SESSION_LLM, "daily": DAILY_LLM, "unit": "次"},
}

# 会话级用量（进程内；Streamlit 每个会话独立进程内 Store，但多会话同进程，
# 故按 scope 分开存）。桌面版/本地 scope="local"。
_session_lock = threading.Lock()
_session_usage: dict[str, dict[str, int]] = {}

# 全局每日用量：按天落盘
STATS_DIR = os.path.join(storage.DATA_DIR, "stats")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _daily_path(day: str | None = None) -> str:
    return os.path.join(STATS_DIR, f"quota_{day or _today()}.json")


def _load_daily(day: str | None = None) -> dict:
    path = _daily_path(day)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {k: 0 for k in KINDS}


def _save_daily(data: dict, day: str | None = None) -> None:
    try:
        os.makedirs(STATS_DIR, exist_ok=True)
        with open(_daily_path(day), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 配额统计失败绝不能影响主流程


def limits() -> dict:
    """返回当前限额配置（供界面展示）。"""
    return {
        k: {
            "session": v["session"],
            "daily": v["daily"],
            "unit": v["unit"],
        }
        for k, v in _LIMITS.items()
    }


def session_usage(scope: str = "local") -> dict:
    with _session_lock:
        return dict(_session_usage.get(scope, {k: 0 for k in KINDS}))


def daily_usage(day: str | None = None) -> dict:
    return _load_daily(day)


def reset_session(scope: str = "local") -> None:
    with _session_lock:
        _session_usage.pop(scope, None)


def _bump_session(scope: str, kind: str, amount: int) -> None:
    with _session_lock:
        cur = _session_usage.setdefault(scope, {k: 0 for k in KINDS})
        cur[kind] = cur.get(kind, 0) + amount


def _bump_daily(kind: str, amount: int) -> None:
    data = _load_daily()
    data[kind] = data.get(kind, 0) + amount
    data["day"] = _today()
    _save_daily(data)


def check(kind: str, amount: int = 1, scope: str = "local",
          own_key: bool = False) -> tuple[bool, str]:
    """检查是否允许消耗 amount。返回 (是否允许, 提示文案)。

    own_key=True 表示用户用了自己的密钥（腾讯 / LLM），此时只记用量、不受宿主配额限制。
    """
    cfg = _LIMITS.get(kind)
    if cfg is None:
        return True, ""
    if amount <= 0:
        return True, ""

    if not own_key:
        used_s = session_usage(scope).get(kind, 0)
        if used_s + amount > cfg["session"]:
            return False, (
                f"本次会话的{cfg['unit']}用量已到上限（{cfg['session']}{cfg['unit']}）。"
                "刷新页面即可重新计数；若在侧边栏填入自己的密钥则不受此限制。"
            )
        used_d = _load_daily().get(kind, 0)
        if used_d + amount > cfg["daily"]:
            return False, (
                f"今日宿主额度已用尽（{cfg['daily']}{cfg['unit']}/天），"
                "免费翻译暂时不可用。可在侧边栏「🌐 翻译设置」填入自己的腾讯云密钥继续使用，"
                "或明天再来。"
            )
    return True, ""


def consume(kind: str, amount: int = 1, scope: str = "local",
            own_key: bool = False) -> tuple[bool, str]:
    """先检查后记账：允许则累加用量并返回 (True, "")，否则返回 (False, 提示)。"""
    ok, msg = check(kind, amount, scope, own_key)
    if not ok:
        note_block(kind, msg)   # 让界面能解释"为什么这次没翻译/不能用 LLM"
        return False, msg
    _bump_session(scope, kind, amount)
    _bump_daily(kind, amount)
    return True, ""


# 最近一次被配额拦截的原因（供界面提示"为什么这次没翻译"）
_last_block: dict = {}


def note_block(kind: str, message: str) -> None:
    _last_block.update({
        "kind": kind,
        "message": message,
        "time": datetime.now().strftime("%H:%M:%S"),
    })


def last_block() -> dict:
    return dict(_last_block)


def clear_block() -> None:
    _last_block.clear()


def remaining(kind: str, scope: str = "local", own_key: bool = False) -> int | None:
    """剩余可用量；自带密钥返回 None（不限）。"""
    cfg = _LIMITS.get(kind)
    if cfg is None or own_key:
        return None
    used_s = session_usage(scope).get(kind, 0)
    used_d = _load_daily().get(kind, 0)
    return max(0, min(cfg["session"] - used_s, cfg["daily"] - used_d))
