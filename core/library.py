"""文献库管理化（P3-C1）：分组 / 标签 / 笔记。

收藏夹原本是一个平铺列表：文献一多就没法用，也接不上「一篇综述需要的一组文献」这个真实场景。
本模块给收藏补上三件基础设施，全部落在**收藏之外**的独立文件 `library.json`：

- **分组（folder）**：一篇文献至多属于一个分组，是「课题 / 综述选题」这一层；
  分组是显式实体（有 id 与名字），可以改名、删除，删除时组内文献退回「未分组」而不是丢文献。
- **标签（tag）**：多对多，用于「研究类型 / 干预 / 人群」这类横切维度，可跨分组筛选。
- **笔记（note）**：纯文本，用来记「为什么纳入 / 排除」「样本量存疑」这类只有自己看得懂的判断。

设计取舍：

1. **不改 `favorites.json` 的结构**。收藏本身由 `storage.py` 管，本模块只在旁边挂一份
   `{pmid: {...}}` 的元数据。好处是旧数据零迁移、取消收藏后元数据可单独保留或清理；
   代价是两者可能不同步——因此提供了 `prune()`，每次进入文献库时按现存收藏清一遍孤儿。
2. **元数据条目不留空**。分组、标签、笔记全空时整条元数据删除，避免文件越用越肿。
3. **分组名唯一（忽略大小写）**，标签去重也忽略大小写但保留首次录入的大小写形式。
4. **带 mtime 缓存**。一次页面渲染要为每张卡片读分组/标签，逐次读盘会退化成 O(n²)；
   这里按「文件路径 + mtime」缓存整份数据，写入时同步刷新，外部改动也能被 mtime 感知。
5. **不做任何在线/多端同步**。文件跟随 `storage` 作用域走：桌面版在本机，云端版按会话分片。

对外一律返回副本，调用方改返回值不会污染缓存。
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
from datetime import datetime

from core import storage

FILE = "library.json"

UNGROUPED = ""            # 未分组：folder 字段为空串（不用 sentinel，方便 JSON 往返）
MAX_FOLDER_NAME = 40
MAX_FOLDER_COUNT = 200
MAX_TAG_LEN = 24
MAX_TAGS_PER_ITEM = 30
MAX_NOTE_LEN = 20000

# {path, mtime} -> 整份数据；见模块 docstring 第 4 条
_CACHE: dict = {"key": None, "data": None}


# ---------------------------------------------------------------- 基础工具

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _blank() -> dict:
    return {"version": 1, "folders": [], "meta": {}}


def normalize_tag(tag: str) -> str:
    """标签规范化：去首尾空白（含全角空格）、压缩内部空白、剥掉常见的分隔性前后缀。"""
    s = re.sub(r"[\s\u3000]+", " ", str(tag or "")).strip()
    s = s.strip("#＃,，;；、|/-")
    return s[:MAX_TAG_LEN].strip()


def parse_tags(text: str) -> list[str]:
    """把一行输入切成标签列表：逗号 / 顿号 / 分号 / 竖线 / 换行都当分隔符，忽略大小写去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,，;；、|\n\r\t]+", str(text or "")):
        t = normalize_tag(part)
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= MAX_TAGS_PER_ITEM:
            break
    return out


def _clean_folder_name(name) -> str:
    s = re.sub(r"[\s\u3000]+", " ", str(name or "")).strip()
    return s[:MAX_FOLDER_NAME].strip()


def _new_id(taken: set[str]) -> str:
    for _ in range(64):
        fid = "f" + secrets.token_hex(4)
        if fid not in taken:
            return fid
    return "f" + secrets.token_hex(8)


def _clean_entry(raw: dict, valid_fids: set[str]) -> dict:
    """把一条元数据规范化；全空则返回 {}（调用方据此删除该条）。"""
    entry: dict = {}
    folder = str(raw.get("folder") or "").strip()
    if folder and folder in valid_fids:
        entry["folder"] = folder
    tags: list[str] = []
    seen: set[str] = set()
    for t in raw.get("tags") or []:
        nt = normalize_tag(t) if isinstance(t, str) else ""
        if nt and nt.lower() not in seen:
            seen.add(nt.lower())
            tags.append(nt)
        if len(tags) >= MAX_TAGS_PER_ITEM:
            break
    if tags:
        entry["tags"] = tags
    note = str(raw.get("note") or "").strip()
    if note:
        entry["note"] = note[:MAX_NOTE_LEN]
        entry["note_updated"] = str(raw.get("note_updated") or "")[:19]
    return entry


def _normalize(data) -> dict:
    """把任意输入（含损坏文件）收敛成合法结构；不做异常上抛。"""
    out = _blank()
    if not isinstance(data, dict):
        return out
    folders: list[dict] = []
    seen: set[str] = set()
    for f in data.get("folders") or []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        name = _clean_folder_name(f.get("name"))
        if not fid or not name or fid in seen:
            continue
        seen.add(fid)
        folders.append({"id": fid, "name": name, "created_at": str(f.get("created_at") or "")[:19]})
        if len(folders) >= MAX_FOLDER_COUNT:
            break
    out["folders"] = folders

    valid = {f["id"] for f in folders}
    meta: dict[str, dict] = {}
    raw_meta = data.get("meta")
    if isinstance(raw_meta, dict):
        for key, m in raw_meta.items():
            if not isinstance(m, dict):
                continue
            pmid = str(key).strip()
            if not pmid:
                continue
            entry = _clean_entry(m, valid)
            if entry:
                meta[pmid] = entry
    out["meta"] = meta
    return out


# ---------------------------------------------------------------- 读写与缓存

def _cache_key():
    path = storage.scoped_path(FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    return (path, mtime)


def _raw() -> dict:
    """返回缓存中的整份数据（**不要直接改**；内部函数会改并立刻落盘）。"""
    key = _cache_key()
    if _CACHE["data"] is not None and _CACHE["key"] == key:
        return _CACHE["data"]
    data = None
    if os.path.exists(key[0]):
        try:
            with open(key[0], "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None      # 损坏时退化为空库，绝不让页面崩
    data = _normalize(data)
    _CACHE["key"] = key
    _CACHE["data"] = data
    return data


def _write(data: dict) -> bool:
    path = storage.scoped_path(FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        return False
    data["version"] = 1
    _CACHE["key"] = _cache_key()
    _CACHE["data"] = data
    return True


def invalidate() -> None:
    """丢弃缓存（测试或外部直接改文件后使用）。"""
    _CACHE["key"] = None
    _CACHE["data"] = None


def _ensure(data: dict, pmid: str):
    key = str(pmid or "").strip()
    if not key:
        return None
    return data["meta"].setdefault(key, {})


def _prune_empty(data: dict) -> int:
    drop = [k for k, v in data["meta"].items() if not v]
    for k in drop:
        del data["meta"][k]
    return len(drop)


# ---------------------------------------------------------------- 分组

def load() -> dict:
    """整库快照（深拷贝），供页面一次性读取。"""
    return copy.deepcopy(_raw())


def list_folders() -> list[dict]:
    return [dict(f) for f in _raw()["folders"]]


def folder_index() -> dict[str, str]:
    return {f["id"]: f["name"] for f in _raw()["folders"]}


def folder_name(fid: str) -> str:
    return folder_index().get(fid, "")


def add_folder(name: str) -> tuple[bool, str, dict | None]:
    clean = _clean_folder_name(name)
    if not clean:
        return False, "分组名不能为空", None
    data = _raw()
    if len(data["folders"]) >= MAX_FOLDER_COUNT:
        return False, f"分组数量已达上限（{MAX_FOLDER_COUNT} 个）", None
    low = clean.lower()
    if any(f["name"].lower() == low for f in data["folders"]):
        return False, f"已存在同名分组「{clean}」", None
    folder = {"id": _new_id({f["id"] for f in data["folders"]}),
              "name": clean, "created_at": _now()}
    data["folders"].append(folder)
    _write(data)
    return True, "", dict(folder)


def rename_folder(fid: str, name: str) -> tuple[bool, str]:
    clean = _clean_folder_name(name)
    if not clean:
        return False, "分组名不能为空"
    data = _raw()
    target = next((f for f in data["folders"] if f["id"] == fid), None)
    if target is None:
        return False, "分组不存在（可能已在其它标签页删除）"
    low = clean.lower()
    if any(f["id"] != fid and f["name"].lower() == low for f in data["folders"]):
        return False, f"已存在同名分组「{clean}」"
    target["name"] = clean
    _write(data)
    return True, ""


def delete_folder(fid: str) -> int:
    """删除分组，组内文献**退回未分组**（标签与笔记保留），返回受影响的文献数。"""
    data = _raw()
    if not any(f["id"] == fid for f in data["folders"]):
        return 0
    data["folders"] = [f for f in data["folders"] if f["id"] != fid]
    n = 0
    for entry in data["meta"].values():
        if entry.get("folder") == fid:
            entry.pop("folder", None)
            n += 1
    _prune_empty(data)
    _write(data)
    return n


def folder_counts() -> dict[str, int]:
    """每个分组下的文献数（键为 folder id，含 UNGROUPED）。"""
    data = _raw()
    counts = {UNGROUPED: 0}
    for f in data["folders"]:
        counts[f["id"]] = 0
    for entry in data["meta"].values():
        fid = entry.get("folder") or UNGROUPED
        counts[fid] = counts.get(fid, 0) + 1
    return counts


# ---------------------------------------------------------------- 单篇元数据

def get_meta(pmid: str) -> dict:
    entry = _raw()["meta"].get(str(pmid or "").strip())
    return copy.deepcopy(entry) if entry else {}


def get_meta_bulk(pmids) -> dict[str, dict]:
    meta = _raw()["meta"]
    out = {}
    for p in pmids:
        entry = meta.get(str(p or "").strip())
        if entry:
            out[str(p).strip()] = copy.deepcopy(entry)
    return out


def set_folder(pmid: str, fid: str) -> bool:
    data = _raw()
    fid = str(fid or "").strip()
    if fid and fid not in {f["id"] for f in data["folders"]}:
        return False
    entry = _ensure(data, pmid)
    if entry is None:
        return False
    if fid:
        entry["folder"] = fid
    else:
        entry.pop("folder", None)
    _prune_empty(data)
    return _write(data)


def set_folder_bulk(pmids, fid: str) -> int:
    data = _raw()
    fid = str(fid or "").strip()
    if fid and fid not in {f["id"] for f in data["folders"]}:
        return 0
    n = 0
    for p in pmids:
        entry = _ensure(data, p)
        if entry is None:
            continue
        before = entry.get("folder", "")
        if before == fid:
            continue
        if fid:
            entry["folder"] = fid
        else:
            entry.pop("folder", None)
        n += 1
    _prune_empty(data)
    if n:
        _write(data)
    return n


def set_note(pmid: str, text: str) -> bool:
    data = _raw()
    entry = _ensure(data, pmid)
    if entry is None:
        return False
    note = str(text or "").strip()
    if note:
        entry["note"] = note[:MAX_NOTE_LEN]
        entry["note_updated"] = _now()
    else:
        entry.pop("note", None)
        entry.pop("note_updated", None)
    _prune_empty(data)
    return _write(data)


def clear_meta(pmids) -> int:
    """删除这些文献的全部元数据（取消收藏时调用；不碰收藏本身）。"""
    data = _raw()
    n = 0
    for p in pmids:
        if data["meta"].pop(str(p or "").strip(), None) is not None:
            n += 1
    if n:
        _write(data)
    return n


# ---------------------------------------------------------------- 标签

def all_tags() -> list[tuple[str, int]]:
    """全部标签及其使用篇数，按（篇数降序, 名称）排。"""
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for entry in _raw()["meta"].values():
        for t in entry.get("tags") or []:
            key = t.lower()
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, t)
    return sorted(((labels[k], v) for k, v in counts.items()), key=lambda x: (-x[1], x[0]))


def add_tags(pmids, tags) -> int:
    clean = [normalize_tag(t) for t in (tags or [])]
    clean = [t for t in clean if t]
    if not clean:
        return 0
    data = _raw()
    n = 0
    for p in pmids:
        entry = _ensure(data, p)
        if entry is None:
            continue
        cur = entry.setdefault("tags", [])
        lowered = {x.lower() for x in cur}
        added = False
        for t in clean:
            if t.lower() not in lowered and len(cur) < MAX_TAGS_PER_ITEM:
                cur.append(t)
                lowered.add(t.lower())
                added = True
        if not cur:
            entry.pop("tags", None)
        if added:
            n += 1
    _prune_empty(data)
    if n:
        _write(data)
    return n


def set_tags(pmid: str, tags) -> bool:
    """**整体替换**某篇的标签（编辑卡片一次保存的语义）；传空列表等价于清空。"""
    data = _raw()
    entry = _ensure(data, pmid)
    if entry is None:
        return False
    clean: list[str] = []
    seen: set[str] = set()
    for t in tags or []:
        nt = normalize_tag(t)
        if nt and nt.lower() not in seen:
            seen.add(nt.lower())
            clean.append(nt)
        if len(clean) >= MAX_TAGS_PER_ITEM:
            break
    if clean:
        entry["tags"] = clean
    else:
        entry.pop("tags", None)
    _prune_empty(data)
    return _write(data)


def remove_tags(pmids, tags) -> int:
    targets = {normalize_tag(t).lower() for t in (tags or [])}
    targets.discard("")
    if not targets:
        return 0
    data = _raw()
    n = 0
    for p in pmids:
        entry = data["meta"].get(str(p or "").strip())
        if not entry or not entry.get("tags"):
            continue
        kept = [t for t in entry["tags"] if t.lower() not in targets]
        if len(kept) != len(entry["tags"]):
            n += 1
            if kept:
                entry["tags"] = kept
            else:
                entry.pop("tags", None)
    _prune_empty(data)
    if n:
        _write(data)
    return n


def rename_tag(old: str, new: str) -> tuple[bool, str, int]:
    src = normalize_tag(old)
    dst = normalize_tag(new)
    if not src:
        return False, "原标签为空", 0
    if not dst:
        return False, "新标签不能为空", 0
    # 只差大小写时**允许**改名——这正是用户「把 meta分析 纠正成 Meta分析」的用法。
    # 标签去重本身忽略大小写，所以这类改名不会在同一篇里产生重复条目。
    if src == dst:
        return False, "新旧标签完全相同", 0
    data = _raw()
    n = 0
    for entry in data["meta"].values():
        tags = entry.get("tags")
        if not tags:
            continue
        if any(t.lower() == src.lower() for t in tags):
            out, seen = [], set()
            for t in tags:
                nt = dst if t.lower() == src.lower() else t
                if nt.lower() in seen:      # 合并时可能与既有标签撞名
                    continue
                seen.add(nt.lower())
                out.append(nt)
            entry["tags"] = out
            n += 1
    if n:
        _write(data)
    return True, "", n


def delete_tag(tag: str) -> int:
    return remove_tags(list(_raw()["meta"].keys()), [tag])


# ---------------------------------------------------------------- 维护

def prune(valid_pmids) -> int:
    """清理已不在收藏中的文献元数据，返回删除条数。"""
    valid = {str(p or "").strip() for p in valid_pmids}
    data = _raw()
    drop = [k for k in data["meta"] if k not in valid]
    for k in drop:
        del data["meta"][k]
    if drop:
        _write(data)
    return len(drop)


def stats() -> dict:
    data = _raw()
    meta = data["meta"]
    tags = {t.lower() for e in meta.values() for t in (e.get("tags") or [])}
    return {
        "folders": len(data["folders"]),
        "grouped": len([e for e in meta.values() if e.get("folder")]),
        "tagged": len([e for e in meta.values() if e.get("tags")]),
        "noted": len([e for e in meta.values() if e.get("note")]),
        "tags": len(tags),
        "meta": len(meta),
    }


# ---------------------------------------------------------------- 备份 / 恢复

def export_payload() -> dict:
    """整库备份（不含收藏正文——收藏由「导出 Markdown / 引用」负责）。"""
    data = _raw()
    return {
        "app": "medical-lit-system",
        "kind": "library",
        "version": 1,
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "folders": copy.deepcopy(data["folders"]),
        "meta": copy.deepcopy(data["meta"]),
    }


def import_payload(payload, mode: str = "merge") -> tuple[bool, str, dict]:
    """导入备份。

    ``merge``（默认）：分组按**名称**匹配既有分组（同名则复用，避免出现两个「综述选题」），
    元数据合并——标签取并集，分组与笔记在导入值非空时覆盖。
    ``replace``：整体替换当前库。
    """
    if not isinstance(payload, dict):
        return False, "文件格式不正确：应为 JSON 对象", {}
    incoming = _normalize(payload)
    if not incoming["folders"] and not incoming["meta"]:
        return False, "文件中没有可导入的分组或标注", {}

    if mode == "replace":
        ok = _write(incoming)
        return (ok, "" if ok else "写入失败", {"folders": len(incoming["folders"]), "meta": len(incoming["meta"])})

    data = _raw()
    id_map: dict[str, str] = {}
    for f in incoming["folders"]:
        low = f["name"].lower()
        existing = next((g for g in data["folders"] if g["name"].lower() == low), None)
        if existing:
            id_map[f["id"]] = existing["id"]
        elif len(data["folders"]) < MAX_FOLDER_COUNT:
            nid = _new_id({g["id"] for g in data["folders"]})
            data["folders"].append({"id": nid, "name": f["name"],
                                    "created_at": f.get("created_at") or _now()})
            id_map[f["id"]] = nid

    n_meta = 0
    for pmid, m in incoming["meta"].items():
        entry = data["meta"].setdefault(pmid, {})
        if m.get("folder"):
            mapped = id_map.get(m["folder"])
            if mapped:
                entry["folder"] = mapped
        # 标签取并集
        cur = entry.setdefault("tags", [])
        lowered = {t.lower() for t in cur}
        for t in m.get("tags") or []:
            if t.lower() not in lowered and len(cur) < MAX_TAGS_PER_ITEM:
                cur.append(t)
                lowered.add(t.lower())
        if not cur:
            entry.pop("tags", None)
        if m.get("note"):
            entry["note"] = m["note"]
            entry["note_updated"] = m.get("note_updated") or ""
        n_meta += 1
    _prune_empty(data)
    ok = _write(data)
    stats_out = {"folders": len(data["folders"]), "meta": n_meta}
    return ok, "" if ok else "写入失败", stats_out
