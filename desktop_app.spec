# -*- mode: python ; coding: utf-8 -*-
# 医学文献智能摘要系统 - 桌面版打包配置
# 构建：python -m PyInstaller desktop_app.spec --noconfirm
import os
from PyInstaller.utils.hooks import copy_metadata, collect_data_files

block_cipher = None

# Streamlit 等库在运行时用 importlib.metadata 查版本，必须带上 dist-info 元数据
datas = copy_metadata("streamlit")
for pkg in ("altair", "pyarrow", "pandas", "pillow", "requests", "zhconv"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# streamlit/static（前端 SPA 资源，缺失时首页直接 404）与组件前端资源
datas += collect_data_files("streamlit")
datas += collect_data_files("streamlit_option_menu")

datas += [
    ("app.py", "."),
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
]

a = Analysis(
    ["desktop_app.py"],
    pathex=["."],
    binaries=[],
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
