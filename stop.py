"""停止本地服务（v2.8.1）：按端口找到本系统的 Streamlit 进程并结束它。

为什么需要：`一键启动.bat` 复用已有实例（端口被自己占用时不再重复启动），
所以想重启服务时需要一个明确的关闭入口，否则用户只能去任务管理器手动杀。

用法：
    python stop.py                # 停默认 8501
    python stop.py --port 8600
    python stop.py --all          # 停掉本项目所有实例
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_MARK = os.path.basename(HERE).lower()   # medical-lit-system


def pids_on_port(port: int) -> list[int]:
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    pids = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                pids.add(int(m.group(1)))
    return sorted(pids)


def _cmdline_of(pid: int) -> str:
    """取进程命令行。wmic 在新版 Windows 已移除，故优先用 PowerShell CIM。"""
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


def _is_streamlit(port: int) -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200 and b"ok" in r.read()[:64].lower()
    except Exception:
        return False


def is_our_project(pid: int, port: int) -> bool:
    """判断该端口上的进程是否属于本项目，宁可放过也不误杀。"""
    cmd = _cmdline_of(pid).lower()
    if cmd:
        return PROJECT_MARK in cmd or ("streamlit" in cmd and "app.py" in cmd)
    # 拿不到命令行时退一步：该端口至少得是个真的 Streamlit 服务
    return _is_streamlit(port)


def kill(pid: int) -> bool:
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
            print(f"  结束进程 {pid} 失败，可手动执行：taskkill /F /PID {pid}")
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