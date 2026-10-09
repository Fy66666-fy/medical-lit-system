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


# ---------- 使用计数与问卷邀请（v3.7.0） ----------
#
# 纪律（写死在这里，防止将来被"顺手优化"掉）：
# 1. 计数只落本机数据目录，**绝不上传、绝不做画像**——落地页 FAQ 已向用户承诺
#    「不进行任何用户画像与行为追踪」，这个承诺必须继续成立。
# 2. 问卷纯自愿：到次数只弹邀请，用户可跳过、可"不再提醒"；提交的答案同样只存本机，
#    由用户自己决定是否点 GitHub Issue 按钮把结果发给开发者。

USAGE_FILE = "usage_state.json"
PROMPT_AT = 15        # 首次邀请的使用次数阈值
REPEAT_EVERY = 25     # 跳过后，每隔多少次再邀请一次
MAX_PROMPTS = 3       # 一辈子最多邀请 3 次，之后彻底安静

SURVEY_QUESTIONS = {
    "freq": "使用频率",
    "useful": "最有用的功能",
    "satisfaction": "总体满意度",
    "improve": "最想改进的一点",
    "recommend": "是否愿意推荐",
}
USEFUL_OPTIONS = (
    "中文摘要与原文定位", "综述工作台（对比表 / 冲突 / 初稿）", "本地 PDF 全文解析",
    "引用导出（.bib / .ris / ZIP）", "MeSH 词表联动", "偏倚与适用性提示",
)


def _usage_path() -> str:
    """与收藏 / 历史同作用域：云端按会话隔离，桌面版全机一份。"""
    return storage.scoped_path(USAGE_FILE)


def new_usage() -> dict:
    return {
        "count": 0,            # 有效检索次数（有结果的检索才 +1）
        "prompts": 0,          # 已经邀请过几次问卷
        "muted": False,        # 用户点了「不再提醒」
        "survey_done": False,  # 已经填过问卷
        "first_use": _now(),
        "last_use": _now(),
    }


def load_usage() -> dict:
    """读取使用计数；没有或损坏时返回全新计数（不抛异常）。"""
    try:
        path = _usage_path()
        if not os.path.exists(path):
            return new_usage()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return new_usage()
        u = new_usage()
        u.update({k: data[k] for k in u if k in data})
        return u
    except Exception:
        return new_usage()


def save_usage(u: dict) -> bool:
    try:
        path = _usage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(u, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def bump(u: dict, n: int = 1) -> dict:
    """纯函数版计数（不落盘，便于离线断言）。"""
    u["count"] = int(u.get("count", 0)) + n
    u["last_use"] = _now()
    return u


def bump_usage(n: int = 1) -> dict:
    """有效使用 +1 并落盘（检索成功后调用；失败静默，绝不影响主流程）。"""
    u = bump(load_usage(), n)
    save_usage(u)
    return u


def next_prompt_at(u: dict) -> int:
    """下一次该邀请的使用次数阈值：15 起，跳过一次再等 25 次。"""
    return PROMPT_AT + int(u.get("prompts", 0)) * REPEAT_EVERY


def should_prompt(u: dict) -> bool:
    """是否该弹问卷邀请：填过 / 静音 / 邀请满 3 次都不再弹。"""
    if u.get("muted") or u.get("survey_done"):
        return False
    if int(u.get("prompts", 0)) >= MAX_PROMPTS:
        return False
    return int(u.get("count", 0)) >= next_prompt_at(u)


def record_prompt(u: dict) -> dict:
    u["prompts"] = int(u.get("prompts", 0)) + 1
    save_usage(u)
    return u


def mute_prompts(u: dict) -> dict:
    u["muted"] = True
    save_usage(u)
    return u


def complete_survey(u: dict) -> dict:
    u["survey_done"] = True
    save_usage(u)
    return u


def save_survey(answers: dict, usage_count: int = 0) -> str | None:
    """把问卷答案存进本机 feedback 目录（与意见留档同处、同作用域）。

    返回落盘路径；失败返回 None。文本字段统一过 sanitize() 去身份信息。
    """
    if not isinstance(answers, dict) or not answers:
        return None
    entry = {
        "time": _now(),
        "usage_count": int(usage_count or 0),
    }
    for k in ("freq", "useful", "satisfaction", "recommend"):
        v = answers.get(k)
        entry[k] = sanitize(str(v))[:200] if v else ""
    entry["improve"] = sanitize(str(answers.get("improve") or ""))[:2000]
    entry["contact"] = sanitize(str(answers.get("contact") or ""))[:300]
    try:
        path = _path().replace("feedback_", "survey_")
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
            json.dump(items[-100:], f, ensure_ascii=False, indent=2)
        logger.info("问卷已存本机")
        return path
    except Exception:
        logger.warning("问卷存本机失败")
        return None


def render_survey_text(answers: dict, usage_count: int = 0) -> str:
    """把答案渲染成一段可读文本——用户下载或贴进 GitHub Issue 都用它。

    渲染层统一过 sanitize()：这段文本最可能被用户复制到公开渠道，
    在出口处兜底清洗，避免 save_survey 与渲染两层之间漏掉一层。
    """
    lines = [
        "## 使用体验问卷",
        f"- 使用次数：约 {usage_count} 次检索",
    ]
    mapping = {
        "freq": SURVEY_QUESTIONS["freq"],
        "useful": SURVEY_QUESTIONS["useful"],
        "satisfaction": SURVEY_QUESTIONS["satisfaction"],
        "recommend": SURVEY_QUESTIONS["recommend"],
    }
    for k, label in mapping.items():
        v = sanitize(str(answers.get(k) or "").strip())
        if v:
            lines.append(f"- {label}：{v}")
    imp = sanitize(str(answers.get("improve") or "").strip())
    if imp:
        lines.append(f"- 最想改进：{imp}")
    con = sanitize(str(answers.get("contact") or "").strip())
    if con:
        lines.append(f"- 联系方式：{con}")
    return "\n".join(lines)