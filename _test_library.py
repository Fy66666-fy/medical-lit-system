"""P3-C1 自测：文献库管理化（分组 / 标签 / 笔记）。

全部落在临时数据目录，不碰真实 data/。
"""
import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_lib_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import library, storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def reset(scope: str = "local") -> None:
    storage.set_scope(scope)
    library.invalidate()


def main() -> int:
    reset()

    # ---------------- 1. 空库与容错 ----------------
    print("\n[1] 空库与容错")
    check("空库 load 不抛异常", library.load() == {"version": 1, "folders": [], "meta": {}})
    check("空库 stats 全 0", all(v == 0 for v in library.stats().values()), str(library.stats()))
    check("空库 all_tags 为空", library.all_tags() == [])
    check("空库 get_meta 返回 {}", library.get_meta("999") == {})
    check("空库 folder_counts 含未分组", library.folder_counts() == {"": 0})

    path = os.path.join(_TMP, "library.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ 这不是合法 JSON")
    library.invalidate()
    check("损坏文件退化为空库而非崩溃", library.load()["meta"] == {})
    os.remove(path)
    library.invalidate()

    # ---------------- 2. 分组 ----------------
    print("\n[2] 分组增 / 改 / 删")
    ok, msg, f1 = library.add_folder("  综述选题A  ")
    check("新建分组成功且名字被 trim", ok and f1 and f1["name"] == "综述选题A", msg)
    ok, msg, _ = library.add_folder("综述选题A")
    check("同名分组被拒绝", not ok and "已存在" in msg, msg)
    ok, msg, _ = library.add_folder("   ")
    check("空名被拒绝", not ok and "不能为空" in msg, msg)

    ok, msg, _ = library.add_folder("RCT Studies")
    check("英文分组新建成功", ok, msg)
    ok, msg, _ = library.add_folder("rct studies")
    check("同名判定忽略大小写", not ok and "已存在" in msg, msg)
    ok, msg, _ = library.add_folder("RCT   Studies")
    check("同名判定忽略连续空白差异", not ok, msg)
    _, _, f_space = library.add_folder("队列   研究")
    check("内部连续空白被压缩为单个空格", f_space["name"] == "队列 研究", f_space["name"])
    _, _, f2 = library.add_folder("机制研究")

    names = [f["name"] for f in library.list_folders()]
    check("分组列表完整且保序",
          names == ["综述选题A", "RCT Studies", "队列 研究", "机制研究"], str(names))

    ok, msg = library.rename_folder(f1["id"], "综述选题B")
    check("重命名成功", ok and library.folder_name(f1["id"]) == "综述选题B", msg)
    ok, msg = library.rename_folder(f1["id"], "机制研究")
    check("改名撞已有分组被拒绝", not ok and "已存在" in msg, msg)
    ok, msg = library.rename_folder("f_not_exist", "随便")
    check("改名不存在的分组被拒绝", not ok, msg)
    ok, msg = library.rename_folder(f1["id"], "  ")
    check("改名成空被拒绝", not ok, msg)

    # ---------------- 3. 分组归属与删除语义 ----------------
    print("\n[3] 分组归属")
    check("归入分组成功", library.set_folder("1001", f1["id"]))
    check("归入不存在的分组被拒绝", library.set_folder("1001", "f_ghost") is False)
    check("未分组用空串表示", library.set_folder("1002", ""))
    library.add_tags(["1002"], ["观察性", "队列"])
    check("get_meta 读回分组", library.get_meta("1001")["folder"] == f1["id"])
    check("folder_counts 统计正确",
          library.folder_counts()[f1["id"]] == 1 and library.folder_counts()[""] == 1,
          str(library.folder_counts()))

    check("批量归组返回变更数", library.set_folder_bulk(["1003", "1004", "1005"], f2["id"]) == 3)
    check("批量归组重复执行返回 0", library.set_folder_bulk(["1003", "1004", "1005"], f2["id"]) == 0)
    check("批量归组到未分组可清空", library.set_folder_bulk(["1003"], "") == 1)
    check("批量归组到非法分组返回 0", library.set_folder_bulk(["1004"], "f_ghost") == 0)

    check("删除分组返回受影响文献数", library.delete_folder(f2["id"]) == 2)
    check("删除后组内文献退回未分组", library.get_meta("1004").get("folder", "") == "")
    check("删除分组不丢已有标签", library.get_meta("1002").get("tags") == ["观察性", "队列"])
    check("分组已被移除", f2["id"] not in library.folder_index())
    check("删除不存在的分组返回 0", library.delete_folder("f_ghost") == 0)

    # ---------------- 4. 标签工具函数 ----------------
    print("\n[4] 标签解析与规范化")
    check("normalize_tag 去空白", library.normalize_tag("  RCT  ") == "RCT")
    check("normalize_tag 压缩内部空白", library.normalize_tag("系统   评价") == "系统 评价")
    check("normalize_tag 剥前后缀", library.normalize_tag("#心血管、") == "心血管")
    check("normalize_tag 截断超长", len(library.normalize_tag("x" * 100)) == library.MAX_TAG_LEN)
    got = library.parse_tags("RCT, 心血管、 队列研究;Meta 分析|rct\n\nRCT")
    check("parse_tags 支持多种分隔符且忽略大小写去重",
          got == ["RCT", "心血管", "队列研究", "Meta 分析"], str(got))
    check("parse_tags 空输入返回空列表", library.parse_tags("   ,,, ; ") == [])
    check("parse_tags 超量截断",
          len(library.parse_tags(",".join(f"t{i}" for i in range(50)))) == library.MAX_TAGS_PER_ITEM)

    # ---------------- 5. 标签读写 ----------------
    print("\n[5] 标签读写")
    check("批量打标签（大小写去重）", library.add_tags(["2001", "2002"], ["RCT", "rct", " 双盲 "]) == 2)
    check("标签按首次录入形式保留", library.get_meta("2001")["tags"] == ["RCT", "双盲"])
    check("重复打同一标签不计数", library.add_tags(["2001"], ["RCT"]) == 0)
    library.add_tags(["2001"], ["Meta分析"])
    library.add_tags(["2003"], ["RCT"])
    check("all_tags 统计篇数", dict(library.all_tags()).get("RCT") == 3, str(library.all_tags()))
    check("all_tags 按篇数降序", library.all_tags()[0][0] == "RCT", str(library.all_tags()))
    check("空文献列表不计数", library.add_tags([], []) == 0)
    check("空标签输入不计数", library.add_tags(["2001"], ["  ", ""]) == 0)

    check("移除标签返回变更篇数", library.remove_tags(["2001", "2002"], ["双盲"]) == 2)
    check("移除后标签消失", "双盲" not in library.get_meta("2001").get("tags", []))
    check("移除不存在的标签返回 0", library.remove_tags(["2001"], ["根本没有"]) == 0)

    check("重命名标签成功", library.rename_tag("RCT", "随机对照试验")[2] == 3)
    check("旧标签已无残留", dict(library.all_tags()).get("RCT") is None, str(library.all_tags()))

    library.add_tags(["2005"], ["RCT", "随机对照试验"])
    ok, msg, n = library.rename_tag("RCT", "随机对照试验")
    check("重命名撞名时合并而非重复", ok and n == 1, f"{msg} {n}")
    check("合并后仅留一条标签", library.get_meta("2005")["tags"] == ["随机对照试验"],
          str(library.get_meta("2005")))

    ok, msg, n = library.rename_tag("Meta分析", "meta分析")
    check("允许只改大小写的改名", ok and n == 1, f"{msg} {n}")
    check("改名后大小写已纠正",
          library.get_meta("2001")["tags"] == ["随机对照试验", "meta分析"], str(library.get_meta("2001")))
    ok, msg, _ = library.rename_tag("meta分析", "meta分析")
    check("完全相同的改名被拒绝", not ok, msg)
    ok, msg, _ = library.rename_tag("", "x")
    check("空原标签被拒绝", not ok, msg)
    ok, msg, _ = library.rename_tag("meta分析", "  ")
    check("空新标签被拒绝", not ok, msg)
    check("delete_tag 生效",
          library.delete_tag("meta分析") >= 1 and dict(library.all_tags()).get("meta分析") is None)

    check("set_tags 整体替换并去重",
          library.set_tags("2006", ["A", "a", " B "]) and library.get_meta("2006")["tags"] == ["A", "B"],
          str(library.get_meta("2006")))
    library.add_tags(["2006"], ["C"])
    check("set_tags 会移除未列出的标签",
          library.set_tags("2006", ["C"]) and library.get_meta("2006")["tags"] == ["C"])
    check("set_tags 传空列表即清空",
          library.set_tags("2006", []) and "tags" not in library.get_meta("2006"))
    check("set_tags 空 pmid 返回 False", library.set_tags("", ["x"]) is False)

    # ---------------- 6. 笔记 ----------------
    print("\n[6] 笔记")
    check("写入笔记成功", library.set_note("3001", "  样本量偏小，结论需谨慎  "))
    m = library.get_meta("3001")
    check("笔记被 trim 保存", m["note"] == "样本量偏小，结论需谨慎", str(m))
    check("笔记时间戳已记录", bool(m.get("note_updated")))
    check("超长笔记被截断",
          library.set_note("3001", "啊" * 30000)
          and len(library.get_meta("3001")["note"]) == library.MAX_NOTE_LEN)
    check("清空笔记后字段消失", library.set_note("3001", "   ") and "note" not in library.get_meta("3001"))
    check("空 pmid 写入返回 False", library.set_note("", "x") is False)

    # ---------------- 7. 空条目与孤儿清理 ----------------
    print("\n[7] 空条目与孤儿清理")
    library.set_note("4001", "临时")
    check("有笔记时元数据存在", "4001" in library.load()["meta"])
    library.set_note("4001", "")
    check("清空后空条目被自动删除", "4001" not in library.load()["meta"])
    library.set_folder("4002", "")
    check("只设未分组不产生空条目", "4002" not in library.load()["meta"])

    library.set_note("6999", "孤儿条目")
    before = len(library.load()["meta"])
    removed = library.prune(["1001", "1002", "2001", "2002", "2003", "2004", "2005", "2006"])
    check("prune 清掉不在收藏中的元数据",
          removed == 1 and len(library.load()["meta"]) == before - 1,
          f"{before} -> {len(library.load()['meta'])}")
    check("prune 保留仍存在的元数据", "1001" in library.load()["meta"])
    left = len(library.load()["meta"])
    check("空收藏列表会清空全部元数据",
          library.prune([]) == left and library.load()["meta"] == {}, str(left))
    check("prune 不影响分组", len(library.list_folders()) > 0)

    # ---------------- 8. clear_meta / stats ----------------
    print("\n[8] clear_meta 与 stats")
    reset("s_lib_stats")     # 独立作用域：local 里已积累前面几节的分组，不能复用
    fa = library.add_folder("统计测试")[2]
    library.set_folder("5001", fa["id"])
    library.add_tags(["5001", "5002"], ["标签A"])
    library.set_note("5002", "笔记")
    library.set_note("5003", "待清除")
    s = library.stats()
    check("stats 分组数正确", s["folders"] == 1, str(s))
    check("stats 已归组数正确", s["grouped"] == 1, str(s))
    check("stats 带标签数正确", s["tagged"] == 2, str(s))
    check("stats 带笔记数正确", s["noted"] == 2, str(s))
    check("stats 标签种类数正确", s["tags"] == 1, str(s))
    check("clear_meta 删除成功", library.clear_meta(["5003"]) == 1)
    check("clear_meta 后元数据消失", library.get_meta("5003") == {})
    check("clear_meta 不存在返回 0", library.clear_meta(["5003"]) == 0)

    # ---------------- 9. 备份 / 恢复 ----------------
    print("\n[9] 备份与恢复")
    payload = library.export_payload()
    check("导出含类型与时间", payload.get("kind") == "library" and bool(payload.get("exported_at")))
    check("导出含分组与元数据", len(payload["folders"]) == 1 and "5002" in payload["meta"])
    check("导出内容是独立副本", payload["meta"]["5002"]["note"] == library.get_meta("5002")["note"])

    reset("s_lib_merge")
    pre = library.add_folder("统计测试")[2]
    ok, msg, _ = library.import_payload(payload, mode="merge")
    check("合并导入成功", ok, msg)
    check("同名分组按名字合并而非新建", len(library.list_folders()) == 1, str(library.list_folders()))
    check("合并沿用既有分组 id", library.get_meta("5001")["folder"] == pre["id"],
          str(library.get_meta("5001")))
    check("导入后笔记还原", library.get_meta("5002")["note"] == "笔记")
    library.import_payload(payload, mode="merge")
    check("重复合并不会产生重复分组", len(library.list_folders()) == 1)
    check("重复合并不会产生重复标签", library.get_meta("5001")["tags"] == ["标签A"])

    reset("s_lib_new")
    library.import_payload(payload, mode="merge")
    check("导入到空库会新建分组", [f["name"] for f in library.list_folders()] == ["统计测试"])
    check("导入到空库分组归属正确",
          library.get_meta("5001")["folder"] == library.list_folders()[0]["id"])

    ok, msg, _ = library.import_payload({"folders": [], "meta": {}}, mode="merge")
    check("空备份被拒绝", not ok, msg)
    ok, msg, _ = library.import_payload("不是字典", mode="merge")
    check("非法备份被拒绝", not ok, msg)

    reset("s_lib_replace")
    library.add_folder("将被替换掉")
    ok, msg, _ = library.import_payload(payload, mode="replace")
    check("整体替换成功", ok and [f["name"] for f in library.list_folders()] == ["统计测试"], msg)
    check("替换后不含旧分组", "将被替换掉" not in [f["name"] for f in library.list_folders()])

    # ---------------- 10. 作用域隔离与缓存一致性 ----------------
    print("\n[10] 作用域隔离与缓存一致性")
    reset("s_lib_a")
    library.add_folder("A 的分组")
    check("会话 A 有 1 个分组", len(library.list_folders()) == 1)
    reset("s_lib_b")
    check("会话 B 看不到 A 的分组", library.list_folders() == [])
    library.add_folder("B 的分组")
    reset("s_lib_a")
    check("回到 A 分组仍在且未被污染",
          [f["name"] for f in library.list_folders()] == ["A 的分组"], str(library.list_folders()))
    check("分片目录按会话建立",
          os.path.isdir(os.path.join(_TMP, "users", "s_lib_a"))
          and os.path.isdir(os.path.join(_TMP, "users", "s_lib_b")))
    reset("local")
    check("local 路径仍为旧位置（平滑升级）", os.path.exists(os.path.join(_TMP, "library.json")))

    reset()
    fc = library.add_folder("缓存测试")[2]
    library.set_folder("6001", fc["id"])
    check("写入后立即读到新值（缓存已刷新）", library.get_meta("6001")["folder"] == fc["id"])
    library.set_folder("6001", "")
    check("再次写入同样立即生效", library.get_meta("6001") == {})

    with open(os.path.join(_TMP, "library.json"), "w", encoding="utf-8") as fh:
        json.dump({"folders": [{"id": "fx", "name": "外部写入"}], "meta": {}}, fh, ensure_ascii=False)
    library.invalidate()
    check("invalidate 后读到外部改动", library.folder_index() == {"fx": "外部写入"},
          str(library.folder_index()))

    snap = library.load()
    snap["folders"].append({"id": "fz", "name": "污染"})
    check("load 返回深拷贝，不污染缓存", len(library.list_folders()) == 1, str(library.list_folders()))
    check("get_meta_bulk 只含有元数据的键", "没有这个" not in library.get_meta_bulk(["6001", "没有这个"]))

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
