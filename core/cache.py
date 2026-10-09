"""持久化缓存（P1 任务 4）：全文 / 摘要 / 译文 / LLM 结果。

为什么需要：这是**唯一能数量级抬高并发容量**的手段。
- NCBI 每IP 限速（无 key 3 req/s）决定了检索吞吐，同一篇文章被不同人反复检索
  就会重复消耗这份公共配额；命中缓存等于直接绕过限速。
- 翻译走腾讯云 TMT（每月 500 万字符免费额度），同一篇摘要被反复翻译是纯浪费。
- LLM 摘要消耗用户自己的 token，重复生成既慢又贵。

设计要点：
1. **全局共享，不按会话分片**（与 storage 刻意不同）：缓存内容全是 PubMed 公开
   文献，不含用户隐私；而云端所有会话共用一个进程，内存索引天然全局。
   分片会让"别人已经译过的文章"仍要重新调接口，白白消耗 NCBI 限速与翻译额度。
2. **小条目走单文件 JSON**（翻译 / LLM / 抽取摘要）：体积小、读写快，
   进程内再缓存一份索引，避免每次读盘。
3. **大条目走一物一文件**（PMC 全文 sections）：避免每次写一条就把整份大文件重写。
4. **TTL + LRU**：译文几乎不变（90 天），摘要 30 天，全文 7 天；
   每类有条数上限，超出按最久未用淘汰，防止云端容器磁盘被撑爆。
5. **命中即省钱**：缓存命中时上层直接跳过配额扣减与外部调用。
6. 所有读写吞异常——缓存出问题绝不能影响主流程（降级为"没有缓存"）。

环境变量：
  MEDLIT_CACHE=0            关闭全部缓存（排障用）
  MEDLIT_CACHE_MAX=<n>      条数上限倍数（默认 1.0，便于临时放宽）
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time

from core import logger


def _data_dir() -> str:
    """缓存根目录。

    **故意不做会话分片**（与 storage 不同）：缓存内容全部来自 PubMed 公开文献
    （译文 / 抽取摘要 / LLM 摘要 / PMC 全文），不含任何用户身份或检索隐私。
    而云端所有会话共用一个进程，内存索引天然就是全局的——若按会话分片，
    会话 A 译过的文章会话 B 仍要重新调接口，白白消耗 NCBI 限速配额和腾讯翻译额度，
    恰好背离了做缓存的目的。因此缓存全局共享，命中率越高、上游压力越小。
    """
    return os.environ.get("MEDLIT_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )


def cache_dir() -> str:
    return os.path.join(_data_dir(), "cache")


try:
    _MAX_SCALE = max(0.1, float(os.environ.get("MEDLIT_CACHE_MAX", "1") or 1))
except ValueError:
    _MAX_SCALE = 1.0

_ENABLED = os.environ.get("MEDLIT_CACHE", "1") != "0"

# 类别 → (TTL 秒, 最大条数, 是否一物一文件)
SPECS: dict[str, tuple[int, int, bool]] = {
    "search":   (3 * 86400,   150, False),   # 检索结果：文献库更新慢，3 天足够新鲜
    "trans":    (90 * 86400,  800, False),   # 译文：确定性高，几乎不过期
    "llm":      (30 * 86400,  200, False),   # LLM 摘要：同模型同输入结果稳定
    "abs":      (14 * 86400,  300, False),   # 抽取式摘要
    "fulltext": (7 * 86400,   120, True),    # PMC 全文 sections（单文件较大）
    "mesh":     (365 * 86400, 400, False),   # MeSH 词表：NLM 一年才更新一次
}

_lock = threading.RLock()
_mem: dict[str, dict] = {}          # 类别 → {key: {"v":…, "t":时间戳}}
_loaded: set[str] = set()
_stats = {"hits": 0, "misses": 0, "puts": 0, "evicted": 0, "errors": 0}


# ------------------------------------------------------------------ 工具
def digest(*parts) -> str:
    """把任意内容压成稳定的短键（用于译文 / 摘要这类长文本做索引）。"""
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x1f")
    return h.hexdigest()


def _file(kind: str, key: str) -> str:
    """小条目集中在 <kind>.json；大条目一物一文件。"""
    d = os.path.join(cache_dir(), kind)
    if SPECS.get(kind, (0, 0, False))[2]:
        return os.path.join(d, f"{key}.json")
    return os.path.join(d, f"{kind}.json")


def _ttl(kind: str) -> int:
    return int(SPECS.get(kind, (7 * 86400, 100, False))[0])


def _limit(kind: str) -> int:
    return max(1, int(SPECS.get(kind, (0, 100, False))[1] * _MAX_SCALE))


def _load_mem(kind: str) -> dict:
    """把整类索引读进内存（只对集中式小条目有意义）。"""
    if kind in _loaded:
        return _mem.setdefault(kind, {})
    with _lock:
        if kind in _loaded:
            return _mem.setdefault(kind, {})
        data: dict = {}
        path = _file(kind, "")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
            except Exception:
                _stats["errors"] += 1
        _mem[kind] = data
        _loaded.add(kind)
        return data


def _save_mem(kind: str) -> None:
    """把内存索引落盘。写失败只记账不抛。"""
    path = _file(kind, "")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_mem.get(kind, {}), f, ensure_ascii=False)
        os.replace(tmp, path)   # 原子替换，避免半截文件
    except Exception:
        _stats["errors"] += 1


def _evict(kind: str) -> None:
    """超出条数上限时按最久未用淘汰。"""
    data = _mem.get(kind) or {}
    limit = _limit(kind)
    if len(data) <= limit:
        return
    ordered = sorted(data.items(), key=lambda kv: kv[1].get("t", 0))
    for k, _ in ordered[: len(data) - limit]:
        data.pop(k, None)
        _stats["evicted"] += 1


# ------------------------------------------------------------------ 读写
def get(kind: str, key: str):
    """读缓存。未命中 / 过期 / 出错一律返回 None（调用方按"没缓存"处理）。"""
    if not _ENABLED or not key:
        return None
    try:
        if SPECS.get(kind, (0, 0, True))[2]:
            path = _file(kind, key)
            if not os.path.exists(path):
                _stats["misses"] += 1
                return None
            if time.time() - os.path.getmtime(path) > _ttl(kind):
                _drop_file(kind, key)
                _stats["misses"] += 1
                return None
            with open(path, "r", encoding="utf-8") as f:
                blob = json.load(f)
            _stats["hits"] += 1
            return blob.get("v") if isinstance(blob, dict) else None

        with _lock:
            entry = _load_mem(kind).get(key)
        if not entry:
            _stats["misses"] += 1
            return None
        if time.time() - entry.get("t", 0) > _ttl(kind):
            with _lock:
                _load_mem(kind).pop(key, None)
                _save_mem(kind)
            _stats["misses"] += 1
            return None
        _stats["hits"] += 1
        return entry.get("v")
    except Exception:
        _stats["errors"] += 1
        return None


def put(kind: str, key: str, value) -> bool:
    """写缓存。任何异常都不影响主流程，返回是否写成功。"""
    if not _ENABLED or not key:
        return False
    try:
        now = time.time()
        if SPECS.get(kind, (0, 0, True))[2]:
            path = _file(kind, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"v": value, "t": now}, f, ensure_ascii=False)
            os.replace(tmp, path)
        else:
            with _lock:
                data = _load_mem(kind)
                data[key] = {"v": value, "t": now}
                _evict(kind)
                _save_mem(kind)
        _stats["puts"] += 1
        return True
    except Exception:
        _stats["errors"] += 1
        logger.warning(f"缓存写入失败 {kind}:{key[:12]}")
        return False


def _drop_file(kind: str, key: str) -> None:
    try:
        os.remove(_file(kind, key))
    except OSError:
        pass


# ------------------------------------------------------------------ 统计 / 维护
def stats() -> dict:
    """命中率等统计，供侧边栏「运行诊断」展示。"""
    total = _stats["hits"] + _stats["misses"]
    out = {
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "puts": _stats["puts"],
        "evicted": _stats["evicted"],
        "errors": _stats["errors"],
        "enabled": _ENABLED,
        "hit_rate": round(_stats["hits"] / total * 100, 1) if total else None,
    }
    sizes = {}
    for kind in SPECS:
        try:
            if SPECS[kind][2]:
                d = os.path.join(cache_dir(), kind)
                sizes[kind] = len([n for n in os.listdir(d) if n.endswith(".json")]) \
                    if os.path.isdir(d) else 0
            else:
                path = _file(kind, "")
                sizes[kind] = len(json.load(open(path, "r", encoding="utf-8"))) \
                    if os.path.exists(path) else 0
        except Exception:
            sizes[kind] = -1
    out["sizes"] = sizes
    out["total"] = sum(v for v in sizes.values() if v > 0)
    return out


def format_summary() -> str:
    s = stats()
    if not s["enabled"]:
        return "缓存已关闭（MEDLIT_CACHE=0）"
    rate = f"{s['hit_rate']}%" if s["hit_rate"] is not None else "暂无数据"
    return (f"命中率 {rate} · 命中 {s['hits']} / 未命中 {s['misses']} · "
            f"写入 {s['puts']} · 淘汰 {s['evicted']} · 共 {s['total']} 条")


def clear(kind: str | None = None) -> int:
    """清空缓存，返回删除的条数。"""
    kinds = [kind] if kind else list(SPECS)
    n = 0
    for k in kinds:
        with _lock:
            if SPECS.get(k, (0, 0, False))[2]:
                d = os.path.join(cache_dir(), k)
                if os.path.isdir(d):
                    for name in os.listdir(d):
                        _drop_file(k, name[:-5] if name.endswith(".json") else name)
                        n += 1
            else:
                n += len(_mem.get(k) or {})
                _mem.pop(k, None)
                _loaded.discard(k)
                _drop_file(k, "")
    return n