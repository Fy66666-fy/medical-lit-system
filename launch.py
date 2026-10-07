"""本地启动器（v2.5.0）：起 streamlit 服务 → 等端口就绪 → 再开浏览器。

为什么需要它：此前「一键启动.bat」用 `timeout /t 4` 固定等 4 秒就打开浏览器，
而 Streamlit 冷启动通常要 5~15 秒（首次要解压前端资源，且本项目 app.py 较大）。
浏览器打开时服务还没监听，表现为一直转圈 / "连接很慢"，让人误以为网络有问题。
本脚本改为轮询端口真实就绪后再打开浏览器，并打印实际耗时，便于判断慢在哪一步。

用法：
    python launch.py            # 默认 8501 端口，就绪后自动打开浏览器
    python launch.py --port 8600 --no-browser
    python launch.py --timeout 120
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


def wait_port(port: int, timeout: float, proc: subprocess.Popen) -> float:
    """轮询直到端口可连接或子进程提前退出。返回耗时秒数；失败返回 -1。"""
    deadline = time.time() + timeout
    t0 = time.time()
    dots = 0
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"\n[错误] Streamlit 进程已退出（退出码 {proc.returncode}），请查看上方输出。")
            return -1
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return time.time() - t0
        except OSError:
            dots += 1
            if dots % 10 == 0:
                print(f"  等待服务启动… {time.time() - t0:.0f}s", flush=True)
            time.sleep(0.3)
    return -1


def main() -> int:
    ap = argparse.ArgumentParser(description="启动医学文献智能摘要系统（本地）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEDLIT_PORT", "8501")))
    ap.add_argument("--timeout", type=float, default=90.0, help="等待端口就绪的最长秒数")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    if not os.path.exists(APP):
        print(f"[错误] 未找到 {APP}")
        return 2

    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(args.port),
        "--server.address", "localhost",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    print("=" * 56)
    print("  医学文献智能摘要系统 · 本地启动")
    print(f"  地址 http://localhost:{args.port}   按 Ctrl+C 停止")
    print("=" * 56, flush=True)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=HERE, env=env)
    try:
        secs = wait_port(args.port, args.timeout, proc)
        if secs < 0:
            return 1
        print(f"\n[就绪] 服务已启动，用时 {secs:.1f}s → http://localhost:{args.port}", flush=True)
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{args.port}")
        print("[运行中] 关闭本窗口或按 Ctrl+C 即可停止服务。\n", flush=True)
        return proc.wait()
    except KeyboardInterrupt:
        print("\n[停止] 正在关闭服务…", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
