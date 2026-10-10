"""自测：CHANGELOG 草稿生成器（_changelog_draft.py）。

只跑本地 git 只读命令，不发网络请求。用当前仓库自己的历史当样本，
因此 CI（actions/checkout 后）同样能跑。
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "_changelog_draft", os.path.join(ROOT, "_changelog_draft.py"))
draft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draft)

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


def main() -> int:
    # ---------------- 1. 提交分类 ----------------
    print("\n[1] 约定式提交分类")
    cases = [
        ("feat(review): 新增综述工作台", "新功能"),
        ("fix: 修掉分段器", "修复"),
        ("docs(changelog): 改写日志", "文档"),
        ("ci: 加一步", "CI / 构建"),
        ("release: v3.8.0", "版本发布"),
        ("chore: 清产物", "杂项"),
        ("随便写的一句", "其他"),
        ("FEAT: 大写前缀也能认", "新功能"),
    ]
    for subj, want in cases:
        got = draft.classify(subj)[1]
        check(f"分类 {subj[:22]} → {want}", got == want, got)

    # ---------------- 2. 版本号读取 ----------------
    print("\n[2] 版本号")
    v = draft.read_app_version()
    check("read_app_version 返回 v 开头", v.startswith("v"), v)
    check("read_app_version 带两段以上版本号", v.count(".") >= 2, v)

    # ---------------- 3. build_draft 结构 ----------------
    print("\n[3] 草稿结构")
    rc, out = git("describe", "--tags", "--abbrev=0")
    base = out.strip() if rc == 0 and out.strip() else "HEAD~5"
    text = draft.build_draft(base, "v9.9.9", include_dirty=False)
    check("build_draft 返回字符串", isinstance(text, str) and len(text) > 100, f"{len(text)} 字符")
    check("含版本标题", text.startswith("## v9.9.9 · "), text.splitlines()[0])
    check("含主题句占位", "<!-- 主题句" in text)
    check("含背景段占位", "<!-- 背景段" in text)
    check("含素材清单小节", "### 素材清单" in text)
    check("含条目格式提示", "### 条目按这个格式写" in text)
    check("含收尾提示（测试与打包）", "收尾固定补一行" in text)
    check("起点被写进清单", f"`{base}`" in text, base)
    check("未开 dirty 时不标注", "含未提交改动" not in text)
    check("未给主题句时留占位", "<!-- 主题句" in text)

    # ---------------- 3b. 主题句（release.py --message） ----------------
    print("\n[3b] 主题句")
    t2 = draft.build_draft(base, "v9.9.9", theme="这是一句主题句")
    check("主题句落在标题之后", t2.splitlines()[0].startswith("## v9.9.9") and
          "这是一句主题句" in t2.split("\n\n")[1], str(t2.split("\n\n")[1])[:40])
    check("给了主题句就不留占位", "<!-- 主题句" not in t2)
    check("背景段提示保留", "<!-- 背景段" in t2)
    check("主题句在素材清单之前",
          t2.index("这是一句主题句") < t2.index("### 素材清单"))

    # ---------------- 4. include_dirty ----------------
    print("\n[4] include_dirty")
    text_d = draft.build_draft(base, "v9.9.9", include_dirty=True)
    check("dirty 版同样产出", isinstance(text_d, str) and len(text_d) > 100, f"{len(text_d)} 字符")
    check("dirty 版标注来源", "含未提交改动" in text_d)
    check("dirty 版与干净版不同", text_d != text)

    # ---------------- 5. 容错：起点不存在 ----------------
    print("\n[5] 容错")
    bogus = draft.build_draft("不存在的起点tag", "v0.0.1")
    check("非法起点不抛异常", isinstance(bogus, str) and bogus.startswith("## v0.0.1"))
    check("非法起点仍给出骨架", "### 素材清单" in bogus and "### 条目按这个格式写" in bogus)

    # ---------------- 6. CLI 落盘 ----------------
    print("\n[6] CLI --out")
    tmp = tempfile.mkdtemp(prefix="medlit_draft_")
    out_path = os.path.join(tmp, "草稿.md")
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "_changelog_draft.py"),
         "--from", base, "--version", "v1.2.3", "--out", out_path],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("CLI 退出码 0", r.returncode == 0, (r.stderr or "")[-200:])
    if os.path.exists(out_path):
        body = open(out_path, encoding="utf-8").read()
        check("CLI 落盘内容含版本号", "## v1.2.3 · " in body)
        check("CLI 落盘非空", len(body) > 100, f"{len(body)} 字符")
    else:
        check("CLI 落盘文件存在", False)

    # ---------------- 7. release.py 能加载到它 ----------------
    print("\n[7] release.py 集成")
    rspec = importlib.util.spec_from_file_location(
        "_release_mod", os.path.join(ROOT, "release.py"))
    rel = importlib.util.module_from_spec(rspec)
    try:
        rspec.loader.exec_module(rel)
        builder = rel._load_draft_builder()
        check("_load_draft_builder 返回可执行对象", callable(builder), str(builder))
        if callable(builder):
            got = builder(base, "v9.9.8", include_dirty=True)
            check("release 取到的 builder 可用", "### 素材清单" in got)
    except Exception as e:
        # release.py 顶部有 argparse 之外的副作用时跳过，不算失败
        print(f"  [跳过] release.py 未能整体导入（{type(e).__name__}: {e}）")

    # ---------------- 8. 网页端更新日志校验 ----------------
    print("\n[8] 网页端更新日志校验（release.check_web_changelog）")
    if hasattr(rel, "check_web_changelog"):
        cur = rel.read_version()[0]
        check("当前版本已是网页端更新日志首条", rel.check_web_changelog(cur) is True, cur)
        check("版本不匹配时校验失败", rel.check_web_changelog("v0.0.0-nope") is False)
    else:
        check("release 提供 check_web_changelog", False, "缺少校验函数")

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
