"""用户反馈与本地留档（P1 任务 6：反馈渠道）。

没有后端服务器时，"反馈闭环"不能只靠一个邮箱——用户往往不会主动发邮件。
这里的做法是**双轨**：

1. **本地留档**：一键把「诊断信息 + 用户描述」写进 `data/feedback/feedback_YYYY-MM-DD.json`，
   同一浏览器下次打开时能看到自己提过什么，也方便桌面版用户直接把这个文件发给作者。
2. **GitHub Issue 预填**：生成一个已经填好标题和正文的 Issue 链接，
   用户点一下只要再点一次"Submit new issue"即可，不需要复制粘贴、不需要账号知识。

刻意不做的事：不采集邮箱等身份信息，反馈内容一律由用户自己决定是否提交到 GitHub。
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

from core import logger, storage

REPO = "Fy66666-fy/medical-lit-system"
ISSUES = f"https://github.com/{REPO}/issues/new"
CONTACT = ""   # 预留：想加邮箱兜底填这里，留空则不展示

KINDS = ("bug", "feature", "question", "other")
_KIND_LABEL = {"bug": "报错", "feature": "建议", "question": "疑问", "other": "其他"}


def _dir() -> str:
    return os.path.join(storage.DATA_DIR, "feedback")


def _today() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


def _path(day: str | None = None) -> str:
    """按作用域分片，与收藏/历史一致——反馈内容可能含用户私有信息，不应互相可见。"""
    base = storage.DATA_DIR if storage.current_scope() == "local" else os.path.join(
        storage.DATA_DIR, "users", storage.current_scope())
    return os.path.join(base, "feedback", f"feedback_{day or _today()}.json")


def save(kind: str, content: str, diagnostics: str = "") -> bool:
    """把一条反馈追加到本地留档。返回是否成功（失败不影响主流程）。"""
    if not (content or "").strip():
        return False
    entry = {
        "time": _now(),
        "kind": kind if kind in KINDS else "other",
        "content": content.strip()[:4000],
        "diagnostics": (diagnostics or "")[:6000],
    }
    try:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        items = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    items = loaded
            except Exception:
                items = []
        items.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items[-200:], f, ensure_ascii=False, indent=2)
        logger.info(f"反馈已留档：{entry['kind']} · {len(content)} 字")
        return True
    except Exception:
        logger.warning("反馈留档失败")
        return False


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def local_count() -> int:
    """本地已留档条数（跨天累计）。"""
    try:
        d = os.path.dirname(_path())
        if not os.path.isdir(d):
            return 0
        n = 0
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                    data = json.load(f)
                n += len(data) if isinstance(data, list) else 0
            except Exception:
                continue
        return n
    except Exception:
        return 0


def issue_url(kind: str, content: str, diagnostics: str = "") -> str:
    """生成预填好标题/正文的 GitHub Issue 新建链接。

    用 URL 参数而不是拼 markdown，用户点开就是所见即所得的表单。
    正文里放诊断信息，用户报错时不用再手动截图描述环境。
    """
    label = _KIND_LABEL.get(kind, "其他")
    title = f"[{label}] 医学文献智能摘要系统"
    body = "\n".join([
        "### 描述",
        (content or "").strip() or "（请补充）",
        "",
        "### 环境与诊断信息",
        "```",
        (diagnostics or "（无）").strip(),
        "```",
        "",
        "<!-- 请勿在此填写邮箱、手机号等身份信息；本项目不收集个人身份数据。 -->",
    ])
    q = urllib.parse.urlencode({"title": title, "body": body})
    return f"{ISSUES}?{q}"


def sanitize(text: str) -> str:
    """去掉明显的身份信息，降低用户误贴的风险（本工具不收集个人身份数据）。"""
    if not text:
        return ""
    t = text
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[邮箱已隐去]", t)
    t = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[手机号已隐去]", t)
    return t


def summary_line() -> str:
    n = local_count()
    return f"已在本机留档 {n} 条" if n else "尚未留档"