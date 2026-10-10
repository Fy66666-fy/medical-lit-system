#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CHANGELOG 草稿生成器（只读 git，不改任何文件）

解决的问题：release.py 的 update_changelog() 只会产出「版本号 + 裸提交列表」的骨架，
真正能读的更新日志必须人来写；而写的时候最耗时的不是措辞，是**回忆这次到底改了什么**。
本脚本把「改了什么」整理成素材清单，人只负责组织语言。

用法：
  python _changelog_draft.py                       # 自上一个 tag 起
  python _changelog_draft.py --from v3.7.1         # 指定起点
  python _changelog_draft.py --version v3.9.0 --out 草稿.md
  python _changelog_draft.py --from v3.8.0 --include-dirty   # 连未提交的改动一起统计

产出结构：
  ## vX.Y.Z · 日期
  （主题句占位）
  （背景段占位）
  ### 素材清单（写完正文后删掉这一节）
    提交分类计数 / 改动文件 +- 行 / 新增文件 / 新增或改动的公开函数 / 测试文件变化
  ### 条目按这个格式写
    - **小标题**（`模块.函数`）：做了什么 + 为什么 + 边界纪律

release.py 在「更新 CHANGELOG.md」这一步会 import 本文件的 build_draft()，
把素材清单直接写进 CHANGELOG.md，省掉「机器先写一遍裸提交、人再整个覆盖」这道工序。
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(ROOT, ".git")):
    ROOT = r"D:\项目开发\medical-lit-system"  # 本脚本放在工作区时的兜底

# 约定式提交前缀 → 中文分组
_PREFIX = [
    ("feat", "新功能"),
    ("fix", "修复"),
    ("docs", "文档"),
    ("chore", "杂项"),
    ("ci", "CI / 构建"),
    ("release", "版本发布"),
    ("refactor", "重构"),
    ("test", "测试"),
    ("perf", "性能"),
]

_DEF_RE = re.compile(r"^\+\s*(?:def|class)\s+(\w+)")
_TEST_RE = re.compile(r"^_test_|^_smoke")


def git(*args):
    r = subprocess.run(
        ["git"] + list(args), cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "")


def last_tag():
    rc, out = git("describe", "--tags", "--abbrev=0")
    return out.strip() if rc == 0 and out.strip() else None


def classify(subject: str) -> tuple[str, str]:
    s = subject.strip()
    low = s.lower()
    for p, zh in _PREFIX:
        if low.startswith(p + "(") or low.startswith(p + ":") or low.startswith(p + " "):
            return p, zh
    if low.startswith("release:"):
        return "release", "版本发布"
    return "other", "其他"


def changed_defs(rng: str, files: list[str]) -> dict[str, list[str]]:
    """取出各文件里新增/改动的顶层 def / class 名。"""
    out: dict[str, list[str]] = {}
    for f in files:
        if not f.endswith(".py"):
            continue
        rc, diff = git("diff", "-U0", rng, "--", f)
        if rc != 0:
            continue
        names: list[str] = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                m = _DEF_RE.match(line)
                if m and m.group(1) not in names:
                    names.append(m.group(1))
        if names:
            out[f] = names
    return out


def read_app_version() -> str:
    try:
        src = open(os.path.join(ROOT, "version.py"), encoding="utf-8").read()
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)', src)
        return m.group(1) if m else "vX.Y.Z"
    except Exception:
        return "vX.Y.Z"


def build_draft(base: str, version: str, include_dirty: bool = False,
                theme: str = "") -> str:
    """生成 CHANGELOG 草稿（纯字符串，不落盘）。

    base           起点 tag / commit
    version        新版本号
    include_dirty  True 时统计「工作区 vs base」，把尚未提交的改动也算进来。
                   release.py 在提交之前写 CHANGELOG，必须开这个，否则本次改动全丢。
    theme          主题句（`release.py --message` 传来的）；给了就直接顶掉占位注释。
    """
    rng_log = f"{base}..HEAD"
    rng_diff = base if include_dirty else f"{base}..HEAD"

    rc, log = git("log", "--pretty=%h|%s", rng_log)
    commits = [l for l in log.splitlines() if "|" in l]
    rc2, stat = git("diff", "--numstat", rng_diff)
    rc3, namestat = git("diff", "--name-status", rng_diff)

    groups: dict[str, list[tuple[str, str]]] = {}
    for line in commits:
        h, subj = line.split("|", 1)
        kind, zh = classify(subj)
        groups.setdefault(zh, []).append((h, subj))

    files_added, files_mod = [], []
    for line in namestat.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        st, path = parts[0], parts[-1]
        if st.startswith("A"):
            files_added.append(path)
        elif st.startswith("M") or st.startswith("R"):
            files_mod.append(path)
    stats = {}
    for line in stat.splitlines():
        # numstat 格式：<新增行> <删除行> <路径>（二进制文件为 "-")
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        add, dele, path = int(parts[0]), int(parts[1]), parts[-1]
        stats[path] = (add + dele, add, dele)

    defs = changed_defs(rng_diff, files_mod + files_added)
    tests = [f for f in files_mod + files_added if _TEST_RE.search(os.path.basename(f))]

    today = dt.date.today().isoformat()
    L: list[str] = []
    L.append(f"## {version} · {today}\n")
    if theme:
        L.append(f"{theme}\n")
        L.append("<!-- 背景段：用户反馈原话 / 为什么做 / 解决了什么歧义（没有就删掉本行） -->\n")
    else:
        L.append("<!-- 主题句：一句话说清这次是什么（写完后删掉本行） -->\n")
        L.append("<!-- 背景段：用户反馈原话 / 为什么做 / 解决了什么歧义（写完后删掉本行） -->\n")
    L.append("\n### 素材清单（正文写完后删掉这一节）\n")
    scope = f"起点 `{base}`" + ("（含未提交改动）" if include_dirty else "")
    L.append(f"\n- {scope}，共 **{len(commits)}** 项已提交：" +
             "、".join(f"{zh} {len(v)}" for zh, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))))
    if stats:
        L.append("\n\n**改动量**（按行数排序，前 10）：\n")
        for f, (n, p, m_) in sorted(stats.items(), key=lambda kv: -kv[1][0])[:10]:
            L.append(f"- `{f}`  {n} 行（+{p} / −{m_}）")
    if files_added:
        L.append("\n\n**新增文件**：" + "、".join(f"`{f}`" for f in files_added))
    if tests:
        L.append("\n\n**测试文件变化**：" + "、".join(f"`{f}`" for f in tests) +
                 "（记得补上断言条数与新增用例说明）")
    if defs:
        L.append("\n\n**新增 / 改动的顶层函数与类**（写条目时优先提这些）：\n")
        for f, names in defs.items():
            L.append(f"- `{f}`：" + "、".join(f"`{n}()`" if not n[0].isupper() else f"`{n}`" for n in names[:14]))
    if commits:
        L.append("\n\n**提交明细**：\n")
        for zh, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            for h, subj in items:
                L.append(f"- `{h}` {subj}")
    L.append("\n\n### 条目按这个格式写（写完删掉本提示行）\n")
    L.append("\n- **小标题**（`模块.函数`）：做了什么 → 为什么这么做 → 边界 / 纪律 / 不做什么。\n")
    L.append("- **另一条**：同上。每条都要能被用户感知，不要写「优化了内部逻辑」这种空话。\n")
    L.append("\n- 收尾固定补一行：测试与打包情况（几套件 / 多少条断言 / 桌面版 dist_vN 三段式验证）。\n")

    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="CHANGELOG 草稿生成器")
    ap.add_argument("--from", dest="frm", help="起点（tag 或 commit），默认上一个 tag")
    ap.add_argument("--version", help="新版本号，默认读 version.py")
    ap.add_argument("--include-dirty", action="store_true",
                    help="把工作区里尚未提交的改动也统计进来")
    ap.add_argument("--out")
    args = ap.parse_args()

    base = args.frm or last_tag()
    if not base:
        print("找不到起点：没有 tag，请用 --from 指定")
        return 2
    version = args.version or read_app_version()

    text = build_draft(base, version, include_dirty=args.include_dirty)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        print("已写入", args.out, len(text), "字符")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
