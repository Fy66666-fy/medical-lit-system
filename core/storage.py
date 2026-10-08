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


def _scope_dir() -> str:
    """local 用原目录（保证旧数据可读），其余按作用域分片。"""
    if _SCOPE == "local":
        return DATA_DIR
    return os.path.join(DATA_DIR, "users", _SCOPE)


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
