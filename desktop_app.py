"""桌面版启动器：双击运行 → 起本地 Streamlit 服务 → 打开独立应用窗口。

同一 exe 三种模式（PyInstaller 打包后 sys.executable 指向自身）：
  - 无参数：窗口模式——拉起 server 子进程，等待就绪后用 pywebview 开窗口
  - "server <port>"：服务模式——在该端口运行 Streamlit 应用（阻塞）
  - "selftest <pdf路径>"：自检模式——在冻结环境内真解析一份 PDF 并渲染首页

第三种模式存在的理由：pdfminer 依赖 `cmap/` 数据文件、pypdfium2 依赖
`pdfium.dll` 原生库，这类资源「文件在磁盘上」和「运行时真能加载」是两回事
（PyInstaller 打包最常见的坑就是把纯 Python 模块打进去了、数据文件却没带上）。
`_verify_exe.py` 靠本模式给出确定性结论，而不是只看目录里有没有文件。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

# ---------------- 路径 ----------------
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS  # PyInstaller 解包目录（app.py / core/ 都在里面）
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_SCRIPT = os.path.join(BASE_DIR, "app.py")

# 用户数据（收藏 / 历史 / 图表缓存）写到 %APPDATA%，程序目录保持只读
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MedLitSummary")
os.environ["MEDLIT_DATA_DIR"] = DATA_DIR
# 桌面版是单机使用：数据不分片，沿用旧的 favorites.json / history.json 路径
os.environ.setdefault("MEDLIT_SCOPE", "local")
os.makedirs(DATA_DIR, exist_ok=True)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ready(port: int, timeout: float = 60.0) -> bool:
    url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def run_server(port: str) -> None:
    """服务模式：在当前进程跑 Streamlit（阻塞）。"""
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    # 冻结 exe 里 streamlit.__file__ 不含 site-packages，会被误判为开发模式（拒绝配置端口）
    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", APP_SCRIPT,
        "--server.port", port,
        "--server.address", "127.0.0.1",
        "--server.headless", "true",
    ]
    sys.exit(stcli.main())


def run_window() -> None:
    """窗口模式：起 server 子进程 + pywebview 窗口。"""
    port = _free_port()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "server", str(port)],
        cwd=BASE_DIR,
        env=os.environ.copy(),
        creationflags=flags,
    )
    try:
        if not _wait_ready(port):
            raise RuntimeError("本地服务启动超时")

        import webview

        webview.create_window(
            "医学文献智能摘要系统",
            f"http://127.0.0.1:{port}",
            width=1360,
            height=900,
            min_size=(980, 640),
        )
        webview.start()  # 阻塞直到窗口关闭
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def run_selftest(pdf_path: str, out_path: str | None = None) -> None:
    """自检模式：在冻结环境内真跑一次「PDF 解析 + 首页渲染」。

    输出以 `[selftest]` 前缀逐行打印，便于调用方（_verify_exe.py）解析；
    全流程无异常且文本层可用、PNG 魔数正确时退出码 0。

    `out_path` 不是可有可无的：本 exe 用 PyInstaller 的无控制台引导器
    （runw.exe）构建，`sys.stdout` 可能是 None，`print` 会静默丢弃。
    所以结果**必须同时落盘**，验证脚本读文件才拿得到确定性结论。
    """
    import traceback

    lines: list[str] = []

    def emit(msg: str) -> None:
        lines.append(msg)
        print(msg)  # 有控制台时同步可见；无控制台时 print 自身会安全跳过

    code = 1
    try:
        import core.pdfdoc as pdfdoc
        import version as version_mod

        emit(f"[selftest] 程序版本 {version_mod.APP_VERSION}")
        with open(pdf_path, "rb") as fh:
            data = fh.read()
        emit(f"[selftest] 输入 {os.path.basename(pdf_path)} {len(data):,} bytes")
        emit(f"[selftest] BASE_DIR={BASE_DIR}")
        emit(f"[selftest] DATA_DIR={DATA_DIR}")

        parsed = pdfdoc.parse_pdf(data, os.path.basename(pdf_path))
        meta = parsed.get("meta") or {}
        q = parsed.get("quality") or {}
        emit(f"[selftest] meta.title={meta.get('title', '')!r}")
        emit(f"[selftest] meta.journal={meta.get('journal', '')!r} year={meta.get('year', '')!r}")
        emit(f"[selftest] pages={q.get('n_pages')} chars={q.get('n_chars')} "
             f"words={q.get('n_words')} headings={q.get('n_headings')} "
             f"tables={q.get('n_tables')} marginalia={q.get('n_marginalia')}")
        emit(f"[selftest] has_text_layer={q.get('has_text_layer')} "
             f"sections={len(parsed.get('sections') or [])}")

        # 渲染首页：这条链路才会真正加载 pypdfium2 的 pdfium.dll。
        # 光看目录里有这个 dll 不算数——它可能因架构/依赖缺失而加载失败。
        png = pdfdoc.render_page_png(data, 1, resolution=110)
        magic_ok = png[:4] == b"\x89PNG"
        emit(f"[selftest] 首页渲染 {len(png):,} bytes magic={'OK' if magic_ok else 'NG'}")

        art = pdfdoc.to_article(parsed, os.path.basename(pdf_path))
        emit(f"[selftest] to_article source={art.get('source')!r} "
             f"has_abstract={bool((art.get('abstract') or '').strip())}")

        ok = (bool(q.get("has_text_layer")) and (q.get("n_pages") or 0) >= 1
              and magic_ok and len(png) > 1000)
        emit("[selftest] 结论: " + ("PASS" if ok else "FAIL"))
        code = 0 if ok else 1
    except Exception:  # noqa: BLE001
        emit("[selftest] 未捕获异常：")
        for ln in traceback.format_exc().splitlines():
            emit("[selftest]   " + ln)
        emit("[selftest] 结论: FAIL")
        code = 1
    finally:
        target = out_path or os.path.join(DATA_DIR, "selftest.txt")
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        run_server(sys.argv[2] if len(sys.argv) > 2 else "8501")
    elif len(sys.argv) > 1 and sys.argv[1] == "selftest":
        if len(sys.argv) < 3:
            print("用法: 医学文献智能摘要.exe selftest <pdf路径> [结果输出路径]")
            sys.exit(2)
        run_selftest(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        run_window()
