"""收藏与检索历史的本地 JSON 持久化（P1：支持会话级数据隔离）

为什么需要作用域：云端部署时所有访客共用同一个进程与同一份 data/ 目录，
A 用户的检索记录和收藏会直接出现在 B 用户界面上（串号）。现在按作用域分片：

- 桌面版 / 本地单机：作用域固定为 `local`，文件路径与旧版完全一致（平滑升级）
- 云端：每个浏览器会话一个作用域，数据写到 `data/users/<scope>/` 下，互不可见

作用域由 app.py 在启动时通过 set_scope() 注入；未注入时按环境变量
MEDLIT_SCOPE，再没有则退回 local。
"""
import json
import os
import re
import secrets
import shutil
from datetime import datetime

DATA_DIR = os.environ.get("MEDLIT_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)

# 当前数据作用域；"local" 表示不分片（沿用旧路径）
_SCOPE = os.environ.get("MEDLIT_SCOPE", "").strip() or "local"


def set_scope(scope: str) -> None:
    """设置当前作用域（app.py 启动时调用一次）。空值视作 local。"""
    global _SCOPE
    _SCOPE = (scope or "").strip() or "local"


def current_scope() -> str:
    return _SCOPE


def _dir_for(scope: str) -> str:
    """某个作用域对应的目录。local 用原目录（保证旧数据可读），其余按作用域分片。"""
    if not scope or scope == "local":
        return DATA_DIR
    return os.path.join(DATA_DIR, "users", scope)


def _scope_dir() -> str:
    return _dir_for(_SCOPE)


def _path(filename: str) -> str:
    return os.path.join(_scope_dir(), filename)


def scoped_path(filename: str) -> str:
    """当前作用域下某个数据文件的绝对路径。

    其它 core 模块（如 library.py）需要落盘自己的数据文件时统一走这里，
    避免各自重拼一遍「local 用旧目录、云端按会话分片」的规则而写岔。
    """
    return _path(filename)


def _load(filename: str) -> list:
    path = _path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(filename: str, items: list):
    path = _path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ---------- 收藏 ----------
def list_favorites() -> list[dict]:
    return _load("favorites.json")


def is_favorited(pmid: str) -> bool:
    return any(f.get("pmid") == pmid for f in list_favorites())


def add_favorite(article: dict):
    favs = list_favorites()
    if not is_favorited(article.get("pmid", "")):
        article = dict(article)
        # 全文字段体积远大于摘要，收藏文件只需服务书目与会话恢复；
        # 全文仍可经 pubmed.fetch_fulltext_any 的缓存（或重新解析 PDF）取回，
        # 因此入库前剔除，避免 favorites.json 被几百篇全文撑大。
        article.pop("fulltext_sections", None)
        article["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        favs.insert(0, article)
        _save("favorites.json", favs)


def remove_favorite(pmid: str):
    favs = [f for f in list_favorites() if f.get("pmid") != pmid]
    _save("favorites.json", favs)


# ---------- 检索历史 ----------
def list_history(limit: int = 50) -> list[dict]:
    return _load("history.json")[:limit]


def add_history(query: str, n_results: int):
    hist = _load("history.json")
    entry = {
        "query": query,
        "n_results": n_results,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    hist.insert(0, entry)
    _save("history.json", hist[:200])


def clear_history():
    """清空检索历史（原实现调用方直接写 storage.HIST_FILE，该常量并不存在会抛异常）"""
    _save("history.json", [])


# ---------- 最近一次检索（v3.7.1） ----------
# Streamlit 的输入框值只活在会话里：浏览器刷新 / 云端预览重载 / 桌面版重启后
# session_state 全部清空，检索页的主副关键词和条数一并消失，用户只能重打一遍。
# 这里把最近一次成功检索的原始条件落盘，新会话进检索页时自动回填。
_LAST_SEARCH_FILE = "last_search.json"


def save_last_search(data: dict) -> bool:
    """保存最近一次检索的原始条件（主/副关键词、条数上限、检索式、命中总数）。"""
    try:
        payload = dict(data)
        payload["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = _path(_LAST_SEARCH_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_last_search() -> dict:
    """读取最近一次检索条件；没有或损坏时返回空字典（不抛异常）。"""
    path = _path(_LAST_SEARCH_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------- 综述工作区（v2.9.0） ----------
# 综述不是一次点击就能完成的操作：选题、勾选文献、记录筛除理由会跨多次刷新。
# 因此把工作区状态按作用域落盘（云端仍是每个会话一份），用户刷新或来回切页不丢进度。
_REVIEW_FILE = "review_state.json"


def load_review_state() -> dict:
    """读取综述工作区状态；没有或损坏时返回空字典（不抛异常）。"""
    path = _path(_REVIEW_FILE)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_review_state(state: dict) -> bool:
    path = _path(_REVIEW_FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_review_state():
    try:
        os.remove(_path(_REVIEW_FILE))
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ---------- 作用域令牌与搬迁（2026-10-13：可选的跨刷新保留） ----------
# 云端默认按「浏览器会话 id」分片：刷新页面就是换了一个会话、换了一个数据目录，
# 收藏与检索历史看起来"消失了"。这是隔离与隐私的必然结果，不是故障；但对文献工具来说
# 代价偏高——辛苦攒一个文献库，按一次 F5 就没了。
# 因此给一条**显式可选**的出路：把一个匿名令牌写进网址（?sid=…），之后刷新 / 新标签 /
# 存书签都落回同一份数据。默认关闭，网址保持干净——推广时到处贴的链接不会带上会话号。
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")

# 开启跨刷新保留时要搬过去的文件（用户真正在乎的那几份）
USER_FILES = ("favorites.json", "history.json", "library.json", "last_search.json")


def is_valid_token(token: str) -> bool:
    r"""令牌是否合法：只允许 [A-Za-z0-9_-]，长度 8–32。

    这个值来自网址、又要拼进目录名，所以校验只有这一道、必须严：
    `..`、`/`、`\`、`:` 一个都不能进，否则一个 `?sid=../..` 就能读到作用域之外的文件。
    非法输入一律当"没有"，绝不做"清洗后仍使用"（那才会漏）。
    """
    return bool(_TOKEN_RE.match((token or "").strip()))


def new_token() -> str:
    """生成一个新的作用域令牌（12 字符，URL 安全）。"""
    return secrets.token_urlsafe(9)


def promote_scope(target_scope: str, filenames: tuple = USER_FILES) -> list:
    """把当前作用域的用户数据搬到 `target_scope`，返回实际搬过去的文件名。

    场景：用户在临时会话里攒了收藏，之后才点「开启跨刷新保留」——不搬的话新作用域是空的，
    看起来像"开启之后反而丢了"。两条规则：

    - **只复制、不删除**：原目录留着（会话结束自然作废），搬迁途中出错也不会把数据弄丢；
    - **目标已有同名文件就跳过**：绝不覆盖既有数据——重复点击、或另一个标签页已开过，都不会冲掉。

    桌面版（scope == local）直接返回空：`local` 就是全量数据目录，复制过去等于把整库摊一份。
    """
    target_scope = (target_scope or "").strip()
    if not (target_scope.startswith("u") and is_valid_token(target_scope[1:])):
        return []
    if _SCOPE == "local":
        return []
    src_dir, dst_dir = _scope_dir(), _dir_for(target_scope)
    if os.path.abspath(src_dir) == os.path.abspath(dst_dir):
        return []
    moved = []
    for name in filenames:
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        try:
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copyfile(src, dst)
            moved.append(name)
        except OSError:
            continue      # 搬迁失败不抛：宁可少搬一个文件，也不能让「开启保留」这个按钮炸掉
    return moved
