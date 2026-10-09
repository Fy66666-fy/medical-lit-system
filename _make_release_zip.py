# -*- coding: utf-8 -*-
"""把 PyInstaller onedir 产物（dist/医学文献智能摘要）压缩为发布 zip，
并生成 SHA256SUMS.txt 与 GitHub Release 说明（NOTES.md）。

CI（.github/workflows/release-desktop.yml）与本地均可使用。本地用法：
  python -m PyInstaller desktop_app.spec --noconfirm
  python _make_release_zip.py
产物输出到 release_out/（zip、SHA256SUMS.txt、NOTES.md）。

zip 内不含 data/（用户数据一律在 %APPDATA%\\MedLitSummary，本就不进 dist），
包内附「开始这里-请先读我.txt」，覆盖 SmartScreen 首启提示与数据位置说明。
"""
from __future__ import annotations

import hashlib
import io
import os
import zipfile

from version import APP_VERSION

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "dist", "医学文献智能摘要")
OUT = os.path.join(ROOT, "release_out")
ZIP = os.path.join(OUT, f"MedLitSummary-{APP_VERSION}-desktop-win64.zip")

README_TMPL = """【医学文献智能摘要 · 桌面版 {v}】

■ 运行方法
1. 解压本压缩包到任意目录（建议非系统盘，例如 D:\\MedLit\\）
2. 进入「医学文献智能摘要」文件夹，双击「医学文献智能摘要.exe」
3. 首次启动约需 10~30 秒（Windows 在做安全检查），之后启动会快很多

■ 安全提示（正常现象，不是病毒特征）
- 本程序未做代码签名，首次运行时 Windows SmartScreen 可能弹出
  「已保护你的电脑」——点「更多信息」→「仍要运行」即可
- 部分杀毒软件首次启动会对新 exe 做云端信誉检查，造成短暂卡顿

■ 数据与隐私
- 所有数据（检索历史、收藏、笔记）只保存在你自己电脑的
  %APPDATA%\\MedLitSummary\\ 目录；本工具不做用户画像、不上传任何数据
- 检索走 PubMed 官方接口（NCBI E-utilities）。可在应用侧边栏里
  免费申请自己的 API Key 提速（约 3 次/秒 → 10 次/秒，填邮箱秒批），不填也能用

■ 版本与更新
- 本包对应 {v}。最新版本、在线网页版与源码见：
  https://github.com/Fy66666-fy/medical-lit-system
- 完整性校验：压缩包的 SHA256 值见 Release 页的 SHA256SUMS.txt，
  下载后请先核对校验值再解压运行

■ 免责声明
- 摘要由算法自动生成，可能遗漏或曲解原始文献信息，仅供文献调研参考，
  不得直接作为临床诊疗依据；正式使用前请务必核对原文。
"""


def main() -> int:
    if not os.path.isdir(SRC):
        print(f"[NG] 未找到打包产物：{SRC}（先跑 python -m PyInstaller desktop_app.spec --noconfirm）")
        return 1
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(ZIP):
        os.remove(ZIP)

    readme_path = os.path.join(OUT, "开始这里-请先读我.txt")
    with io.open(readme_path, "w", encoding="utf-8") as fh:
        fh.write(README_TMPL.format(v=APP_VERSION))

    n = 0
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(SRC):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.join("医学文献智能摘要", os.path.relpath(p, SRC)))
                n += 1
        z.write(readme_path, "开始这里-请先读我.txt")
        n += 1

    h = hashlib.sha256()
    with open(ZIP, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with io.open(os.path.join(OUT, "SHA256SUMS.txt"), "w", encoding="utf-8") as fh:
        fh.write(digest + "  " + os.path.basename(ZIP) + "\n")

    with io.open(os.path.join(OUT, "NOTES.md"), "w", encoding="utf-8") as fh:
        fh.write(extract_notes())

    print("zip:", ZIP, "%.0f MB" % (os.path.getsize(ZIP) / 1048576), "files:", n)
    print("sha256:", digest)
    print("notes:", os.path.join(OUT, "NOTES.md"))
    return 0


def extract_notes() -> str:
    """从 CHANGELOG.md 截取当前版本段落作为 Release 说明；截不到则给通用说明。"""
    path = os.path.join(ROOT, "CHANGELOG.md")
    lines = io.open(path, encoding="utf-8").read().splitlines()
    out: list[str] = []
    on = False
    for ln in lines:
        if ln.startswith("## "):
            if on:
                break
            on = ln.startswith("## " + APP_VERSION)
            continue
        if on:
            out.append(ln)
    body = "\n".join(out).strip()
    if not body:
        body = f"详见仓库 CHANGELOG.md 的 {APP_VERSION} 段落。"
    header = (
        f"桌面版（Windows 64 位）。下载 `MedLitSummary-{APP_VERSION}-desktop-win64.zip`，"
        "解压后双击「医学文献智能摘要.exe」即可使用；首次启动约 10~30 秒属正常现象。\n\n"
        "## 本版更新\n\n"
    )
    return header + body + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
