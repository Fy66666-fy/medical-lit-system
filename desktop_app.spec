# -*- mode: python ; coding: utf-8 -*-
# 医学文献智能摘要系统 - 桌面版打包配置
# 构建：python -m PyInstaller desktop_app.spec --noconfirm
import os
from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     copy_metadata)

block_cipher = None

# Streamlit 等库在运行时用 importlib.metadata 查版本，必须带上 dist-info 元数据
datas = copy_metadata("streamlit")
for pkg in ("altair", "pyarrow", "pandas", "pillow", "requests", "zhconv",
            "websocket-client", "openpyxl", "streamlit_option_menu",
            # v3.2.0：PDF 全文分析依赖（pdfminer 发行名带点，必须写 pdfminer.six）
            "pdfplumber", "pdfminer.six", "pypdfium2"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# streamlit/static（前端 SPA 资源，缺失时首页直接 404）与组件前端资源
datas += collect_data_files("streamlit")
datas += collect_data_files("streamlit_option_menu")

# v3.2.0：PDF 解析所需的**数据与原生库**，PyInstaller 静态分析收集不到：
#  - pdfminer/cmap/*.json.gz：CJK 等编码的 CMap 表，缺了中文 PDF 直接解析失败
#  - pypdfium2_raw/pdfium.dll：页面转 PNG 的渲染引擎（图表解析用）
datas += collect_data_files("pdfminer")
datas += collect_data_files("pypdfium2")
datas += collect_data_files("pypdfium2_raw")

datas += [
    ("app.py", "."),
    # v2.5.0：版本号改为 version.py 单一来源，app.py 会 import 它，漏了 exe 直接起不来
    ("version.py", "."),
    ("core", "core"),
    ("使用说明.md", "."),
]

hiddenimports = [
    "streamlit.runtime.scriptrunner.magic_funcs",
    "streamlit_option_menu",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr_loader",
    "clr_loader.netfx",
    "pythonnet",
    # ↓ app.py 与 core/ 是"运行时动态导入"的数据文件，PyInstaller 静态分析看不到
    #   它们内部的 import，必须在此显式声明（v2.3.1 修复图表解析在 exe 中失败：
    #   浏览器兜底通道缺 websocket-client 导致非 OA 文献必然失败）
    "websocket",
    "zhconv",
    "openpyxl",
    "openpyxl.styles",
    "PIL",
    "PIL.Image",
    "pandas",
    "requests",
    # ↓ v3.2.0：core/pdfdoc.py 只在解析 PDF 时才 import，同样属于动态导入
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pdfminer.layout",
    "pypdfium2",
    "pypdfium2_raw",
    "pypdfium2_raw.bindings",
]

a = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=collect_dynamic_libs("pypdfium2_raw"),
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="医学文献智能摘要",
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="医学文献智能摘要",
)
