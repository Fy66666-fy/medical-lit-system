"""本地启动器（v2.5.0）：起 streamlit 服务 → 等端口就绪 → 再开浏览器。

为什么需要它：此前「一键启动.bat」用 `timeout /t 4` 固定等 4 秒就打开浏览器，
而 Streamlit 冷启动通常要 5~15 秒（首次要解压前端资源，且本项目 app.py 较大）。
浏览器打开时服务还没监听，表现为一直转圈 / "连接很慢"，让人误以为网络有问题。
本脚本改为轮询端口真实就绪后再打开浏览器，并打印实际耗时，便于判断慢在哪一步。

v2.8.1 修复「一键启动失败」：端口被占用时不再直接失败，而是先判断占用者是谁——
- 是本系统（健康检查返回 Streamlit 页面）→ 直接复用，只开浏览器；
- 是别的程序 → 自动往后找空闲端口，并在标题里明示用的是哪个；
- 两者都不是 → 明确报错并给出处理建议，不再让用户对着窗口猜。

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
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def is_our_app(port: int) -> bool:
    """端口上跑的是不是本系统（认 Streamlit 的健康检查端点）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            if r.status != 200:
                return False
            return b"ok" in r.read()[:64].lower()
    except Exception:
        return False


def pick_port(start: int, span: int = 20) -> int | None:
    """从 start 开始找一个没人用的端口。"""
    for p in range(start, start + span):
        if not port_open(p):
            return p
    return None


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


def resolve_port(want: int) -> tuple[int, str]:
    """决定最终用哪个端口。返回 (端口, 说明)。"""
    if not port_open(want):
        return want, ""
    if is_our_app(want):
        return want, f"检测到 {want} 端口上已有本系统在运行，将直接复用。"
    free = pick_port(want + 1)
    if free is None:
        raise RuntimeError(
            f"{want}~{want + 20} 端口都被占用。\n"
            f"  处理办法：关掉占用程序，或用  python launch.py --port 8600  指定其它端口。"
        )
    return free, (f"{want} 端口被其它程序占用（不是本系统），已自动改用 {free}。")


def main() -> int:
    ap = argparse.ArgumentParser(description="启动医学文献智能摘要系统（本地）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEDLIT_PORT", "8501")))
    ap.add_argument("--timeout", type=float, default=90.0, help="等待端口就绪的最长秒数")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    if not os.path.exists(APP):
        print(f"[错误] 未找到 {APP}")
        return 2

    print("=" * 56)
    print("  医学文献智能摘要系统 · 本地启动")
    print("=" * 56, flush=True)

    # ---- 端口决策：占用时复用或换端口，绝不直接失败 ----
    try:
        port, note = resolve_port(args.port)
    except RuntimeError as e:
        print(f"\n[错误] {e}")
        return 3
    if note:
        print(f"[提示] {note}")
    if port != args.port:
        print(f"[提示] 本次使用端口：{port}")
    print(f"  地址 http://localhost:{port}   按 Ctrl+C 停止\n", flush=True)

    # 已有实例在跑 → 不再重复启动，直接开浏览器
    if is_our_app(port):
        print(f"[就绪] 服务已在运行 → http://localhost:{port}")
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{port}")
        print("[提示] 若要重启服务，请先关掉原来的启动窗口（或运行 stop.py）。\n", flush=True)
        return 0

    cmd = [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.port", str(port),
        "--server.address", "localhost",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(cmd, cwd=HERE, env=env)
    try:
        secs = wait_port(port, args.timeout, proc)
        if secs < 0:
            return 1
        print(f"\n[就绪] 服务已启动，用时 {secs:.1f}s → http://localhost:{port}", flush=True)
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{port}")
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
