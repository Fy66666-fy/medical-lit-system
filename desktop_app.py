"""桌面版启动器：双击运行 → 起本地 Streamlit 服务 → 打开独立应用窗口。

同一 exe 两种模式（PyInstaller 打包后 sys.executable 指向自身）：
  - 无参数：窗口模式——拉起 server 子进程，等待就绪后用 pywebview 开窗口
  - "server <port>"：服务模式——在该端口运行 Streamlit 应用（阻塞）
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        run_server(sys.argv[2] if len(sys.argv) > 2 else "8501")
    else:
        run_window()
