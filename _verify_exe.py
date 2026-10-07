"""验证桌面版 exe：以 server 模式启动 → 等健康检查 → 请求首页 → 关闭。

用法：python _verify_exe.py [dist目录名] [端口]
"""
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
dist = sys.argv[1] if len(sys.argv) > 1 else "dist_v9"
port = sys.argv[2] if len(sys.argv) > 2 else "8599"

exe = os.path.join(ROOT, dist, "医学文献智能摘要", "医学文献智能摘要.exe")
print("exe:", exe, "exists:", os.path.exists(exe))
if not os.path.exists(exe):
    sys.exit(1)

# 关键：v2.5.0 起 app.py 依赖 version.py，漏打会直接起不来
internal = os.path.join(ROOT, dist, "医学文献智能摘要", "_internal")
for f in ("app.py", "version.py", os.path.join("core", "http.py")):
    p = os.path.join(internal, f)
    print(f"  打包内含 {f}: {os.path.exists(p)}")

proc = subprocess.Popen([exe, "server", port],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")
ready = False
t0 = time.time()
try:
    while time.time() - t0 < 150:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(1)
    print(f"健康检查: {'OK' if ready else '失败'}（{time.time() - t0:.1f}s）")
    if ready:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            body = r.read()
        print("首页 HTTP", r.status, "bytes", len(body))
        appdata = os.path.join(os.environ.get("APPDATA", ""), "MedLitSummary")
        print("用户数据目录存在:", os.path.isdir(appdata))
        logs = os.path.join(appdata, "logs")
        if os.path.isdir(logs):
            print("日志文件:", os.listdir(logs))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
print("退出码判定:", 0 if ready else 1)
sys.exit(0 if ready else 1)
