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
