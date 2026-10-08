"""一键重拍落地页用的文献库截图（v3.1.0）。

三步串起来，省掉手工「起服务 / 等端口 / 拍照 / 关服务」：
    1. 播种演示数据（_seed_demo.py）→ _demo_data/
    2. 带 MEDLIT_DATA_DIR + MEDLIT_SCOPE=local 起 streamlit，轮询端口就绪
    3. 跑 _shot.py <out_dir> <port> --lib，拍 12_library.png / 12b_library_cards.png

**两个必须注意的点**（都实测踩过）：
- 只给 `MEDLIT_DATA_DIR` 不够：app.py 在没设 `MEDLIT_SCOPE` 时会按浏览器**会话 id** 分片
  （`storage.set_scope(_init_scope())`），数据落到 `data/users/s<sid>/`，页面照样是空的。
- 关服务必须**杀进程树**：launch.py 派生的 streamlit 若只 kill 父进程会留下孤儿占着端口，
  下次启动就被自动改到别的端口，截图脚本还在拍老端口。

用法：
    python _shoot_demo.py                 # 输出到 _preview/，端口 8512
    python _shoot_demo.py docs/shots 8513
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
DEMO_DIR = os.path.join(HERE, "_demo_data")


def port_ready(port: int, timeout: float = 90.0) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return time.time() - t0
        except OSError:
            time.sleep(0.3)
    return -1.0


def kill_tree(proc: subprocess.Popen) -> None:
    """杀整棵进程树。只 kill 父进程会留下孤儿 streamlit 继续占端口。"""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_dir = args[0] if args else "_preview"
    port = int(args[1]) if len(args) > 1 else 8512

    print("[1/3] 播种演示数据…")
    if subprocess.run([PY, "_seed_demo.py"], cwd=HERE).returncode != 0:
        print("  播种失败")
        return 1

    env = dict(os.environ)
    env["MEDLIT_DATA_DIR"] = DEMO_DIR
    env["MEDLIT_SCOPE"] = "local"          # 不设就会被按会话 id 分片，页面全空
    env["PYTHONIOENCODING"] = "utf-8"

    print(f"[2/3] 启动服务（端口 {port}，数据目录 {DEMO_DIR}）…")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    app = subprocess.Popen(
        [PY, "-u", "launch.py", "--port", str(port), "--no-browser"],
        cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=flags,
        start_new_session=(os.name != "nt"),
    )
    try:
        secs = port_ready(port)
        if secs < 0:
            print("  服务未在 90s 内就绪；launch.py 输出：")
            kill_tree(app)
            try:
                print((app.communicate(timeout=5)[0] or "")[-800:])
            except Exception:
                pass
            return 1
        print(f"  就绪，用时 {secs:.1f}s")

        print("[3/3] CDP 截图…")
        rc = subprocess.run([PY, "-u", "_shot.py", out_dir, str(port), "--lib"],
                            cwd=HERE, timeout=600).returncode
        print("  截图", "完成" if rc == 0 else f"失败（rc={rc}）")
        return rc
    finally:
        kill_tree(app)


if __name__ == "__main__":
    sys.exit(main())
