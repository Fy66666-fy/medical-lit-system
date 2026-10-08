"""停止本地服务：按端口找到本系统的 Streamlit 进程并结束它。

为什么需要：启动器会复用已有实例（端口被自己占用时不再重复启动），
所以想重启服务时需要一个明确的关闭入口，否则用户只能去任务管理器手动杀。

跨平台（v3.1.0 起同时支持 Windows 与 Linux / macOS / WSL）：
- Windows：`netstat -ano` 定位 PID → PowerShell CIM / wmic 取命令行 → `taskkill` 结束
- Linux / macOS：`lsof -t -i:PORT`（退 `ss -ltnp`）定位 PID → 读 `/proc/<pid>/cmdline`
  （macOS 退 `ps -p`）取命令行 → SIGTERM → 宽限 → SIGKILL

判定"是不是本项目"的规则宁可放过也不误杀：
- Linux 上额外比对 `/proc/<pid>/cwd` 是否就是本目录（`streamlit run app.py` 的 argv 里
  并不含项目名，只看命令行会漏判）
- 拿不到命令行时，退一步要求该端口上至少是个真的 Streamlit 服务

用法：
    python stop.py                # 停默认 8501
    python stop.py --port 8600
    python stop.py --all          # 停掉 8501~8520 上本项目所有实例
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_MARK = os.path.basename(HERE).lower()   # medical-lit-system
IS_WIN = os.name == "nt"


# ---------------------------------------------------------------- 定位 PID --
def _pids_win(port: int) -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    pids = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                pids.add(int(m.group(1)))
    return sorted(pids)


def _pids_unix(port: int) -> list[int]:
    """Linux / macOS：优先 lsof，退到 ss -ltnp。"""
    pids: set[int] = set()
    try:
        cp = subprocess.run(["lsof", "-t", "-i", f":{port}", "-sTCP:LISTEN"],
                            capture_output=True, text=True, timeout=15)
        for line in (cp.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    except Exception:
        pass
    if pids:
        return sorted(pids)

    # ss 输出形如：LISTEN 0 128 127.0.0.1:8501 0.0.0.0:* users:(("python3",pid=1234,fd=7))
    try:
        cp = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, timeout=15)
        for line in (cp.stdout or "").splitlines():
            if re.search(rf":{port}\b", line):
                for m in re.finditer(r"pid=(\d+)", line):
                    pids.add(int(m.group(1)))
    except Exception:
        pass
    return sorted(pids)


def pids_on_port(port: int) -> list[int]:
    return _pids_win(port) if IS_WIN else _pids_unix(port)


# ------------------------------------------------------------ 取命令行 --
def _cmdline_win(pid: int) -> str:
    """wmic 在新版 Windows 已移除，故优先用 PowerShell CIM。"""
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if cp.returncode == 0 and (cp.stdout or "").strip():
            return cp.stdout
    except Exception:
        pass
    try:
        cp = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if cp.returncode == 0:
            return cp.stdout or ""
    except Exception:
        pass
    return ""


def _cmdline_unix(pid: int) -> str:
    """/proc/<pid>/cmdline 用 NUL 分隔；macOS 无 /proc，退到 ps。"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
        if raw:
            return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except Exception:
        pass
    try:
        cp = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                            capture_output=True, text=True, timeout=15)
        return cp.stdout or ""
    except Exception:
        return ""


def _cmdline_of(pid: int) -> str:
    return _cmdline_win(pid) if IS_WIN else _cmdline_unix(pid)


def _is_streamlit(port: int) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200 and b"ok" in r.read()[:64].lower()
    except Exception:
        return False


def is_our_project(pid: int, port: int) -> bool:
    """判断该端口上的进程是否属于本项目，宁可放过也不误杀。"""
    if not IS_WIN:
        # Linux：cwd 就是本目录 → 几乎可以确定是它（argv 里不含项目名）
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
            if os.path.realpath(cwd) == os.path.realpath(HERE):
                return True
        except Exception:
            pass
    cmd = _cmdline_of(pid).lower()
    if cmd:
        return PROJECT_MARK in cmd or ("streamlit" in cmd and "app.py" in cmd)
    # 拿不到命令行时退一步：该端口至少得是个真的 Streamlit 服务
    return _is_streamlit(port)


# ---------------------------------------------------------------- 结束进程 --
def _kill_win(pid: int) -> bool:
    for args in (["taskkill", "/PID", str(pid), "/T", "/F"],
                 ["taskkill", "/PID", str(pid), "/F"]):
        try:
            cp = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
            if cp.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _alive(pid: int) -> bool:
    if IS_WIN:
        # 重要：Windows 上 os.kill(pid, 0) 不是「探测存活」而是真的 TerminateProcess。
        # 这里硬拦一道，避免任何人在 Windows 分支误调而静默杀进程。
        raise RuntimeError("_alive() 仅用于 POSIX；Windows 请走 taskkill 分支")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # 存在但不属于当前用户
    except Exception:
        return False


def _kill_unix(pid: int, grace: float = 5.0) -> bool:
    """先 SIGTERM 让 Streamlit 收尾，宽限期过后再 SIGKILL。"""
    if IS_WIN:
        raise RuntimeError("_kill_unix() 仅用于 POSIX；Windows 请走 _kill_win()")
    if not _alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return False
    deadline = time.time() + grace
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.2)
    # signal.SIGKILL 在部分平台（如 Windows）不存在，取不到就退回 SIGTERM
    sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    try:
        os.kill(pid, sigkill)
    except Exception:
        pass
    time.sleep(0.3)
    return not _alive(pid)


def kill(pid: int) -> bool:
    return _kill_win(pid) if IS_WIN else _kill_unix(pid)


def stop_port(port: int) -> int:
    n = 0
    for pid in pids_on_port(port):
        if not is_our_project(pid, port):
            print(f"  跳过 {port} 端口上的进程 {pid}（不是本项目，可能误杀）")
            continue
        if kill(pid):
            print(f"  已结束进程 {pid}（{port} 端口）")
            n += 1
        else:
            hint = f"taskkill /F /PID {pid}" if IS_WIN else f"kill -9 {pid}"
            print(f"  结束进程 {pid} 失败，可手动执行：{hint}")
    if not n:
        print(f"  {port} 端口上没有本项目的进程")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="停止医学文献智能摘要系统的本地服务")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MEDLIT_PORT", "8501")))
    ap.add_argument("--all", action="store_true", help="扫描 8501-8520，停止全部实例")
    args = ap.parse_args()

    print("=" * 56)
    print("  医学文献智能摘要系统 · 停止服务")
    print("=" * 56)
    total = 0
    if args.all:
        for p in range(args.port, args.port + 20):
            total += stop_port(p)
    else:
        total = stop_port(args.port)
    print(f"\n共结束 {total} 个进程。")
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
