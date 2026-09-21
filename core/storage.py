"""收藏与检索历史的本地 JSON 持久化"""
import json
import os
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
FAV_FILE = os.path.join(DATA_DIR, "favorites.json")
HIST_FILE = os.path.join(DATA_DIR, "history.json")


def _load(path: str) -> list:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(path: str, items: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


# ---------- 收藏 ----------
def list_favorites() -> list[dict]:
    return _load(FAV_FILE)


def is_favorited(pmid: str) -> bool:
    return any(f.get("pmid") == pmid for f in list_favorites())


def add_favorite(article: dict):
    favs = list_favorites()
    if not is_favorited(article.get("pmid", "")):
        article = dict(article)
        article["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        favs.insert(0, article)
        _save(FAV_FILE, favs)


def remove_favorite(pmid: str):
    favs = [f for f in list_favorites() if f.get("pmid") != pmid]
    _save(FAV_FILE, favs)


# ---------- 检索历史 ----------
def list_history(limit: int = 50) -> list[dict]:
    return _load(HIST_FILE)[:limit]


def add_history(query: str, n_results: int):
    hist = _load(HIST_FILE)
    entry = {
        "query": query,
        "n_results": n_results,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    hist.insert(0, entry)
    _save(HIST_FILE, hist[:200])
