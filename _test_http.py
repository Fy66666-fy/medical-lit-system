"""统一外部请求层 core/http.py 自测（v2.5.0）

用本地 HTTP 服务模拟真实故障（500 / 429 / 4xx / 慢响应），验证：
超时、退避重试、Retry-After、4xx 不重试、域名限流、统计埋点、异常类型兼容。
不依赖外网，可在 CI 与发布前离线运行。
"""
import os
import sys
import threading
import time

# 必须在导入 core.http 之前设置：退避时间在模块导入时读取
os.environ["MEDLIT_HTTP_BACKOFF"] = "0.01"
os.environ["MEDLIT_HTTP_MAX_BACKOFF"] = "0.05"
os.environ["MEDLIT_HTTP_CONNECT"] = "3"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import http

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# ---------------- 本地 mock server ----------------
class Handler(BaseHTTPRequestHandler):
    hits = {}          # path -> 已访问次数
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _count(self):
        with Handler.lock:
            n = Handler.hits.get(self.path, 0) + 1
            Handler.hits[self.path] = n
        return n

    def do_GET(self):
        # 客户端超时断开时服务端写响应会抛连接类异常，属预期噪音，静默忽略
        try:
            self._handle_get()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _handle_get(self):
        n = self._count()
        if self.path.startswith("/flaky500"):
            if n < 3:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        elif self.path.startswith("/always500"):
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        elif self.path.startswith("/throttled"):
            if n < 2:
                self.send_response(429)
                self.send_header("Retry-After", "0.05")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        elif self.path.startswith("/notfound"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        elif self.path.startswith("/slow"):
            time.sleep(1.2)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    print(f"mock server @ {base}\n")
    http.reset_stats()

    # 1. 正常请求
    r = http.get(f"{base}/ok", timeout=5)
    check("正常 200 返回", r.status_code == 200 and r.json().get("ok") is True)

    # 2. 5xx 重试后成功（前两次 500）
    r = http.get(f"{base}/flaky500", timeout=5, retries=3)
    check("5xx 指数退避重试后成功", r.status_code == 200, f"命中 {Handler.hits.get('/flaky500')} 次")
    check("重试次数被计入统计", http.stats()["retries"] >= 2, str(http.stats()["retries"]))

    # 3. 持续 5xx：重试耗尽后抛 HTTPError（requests 异常子类，兼容既有 except）
    try:
        http.get(f"{base}/always500", timeout=5, retries=2)
        check("持续 5xx 最终抛异常", False)
    except requests.HTTPError as e:
        check("持续 5xx 抛 requests.HTTPError", True, f"status={e.response.status_code}")
    except Exception as e:
        check("持续 5xx 抛 requests.HTTPError", False, type(e).__name__)

    # 4. 429 + Retry-After
    t0 = time.time()
    r = http.get(f"{base}/throttled", timeout=5, retries=2)
    check("429 尊重 Retry-After 后重试成功", r.status_code == 200, f"{time.time() - t0:.2f}s")

    # 5. 4xx 不重试（只请求一次）
    before = Handler.hits.get("/notfound", 0)
    try:
        http.get(f"{base}/notfound", timeout=5, retries=3)
        check("4xx 抛 HTTPError", False)
    except requests.HTTPError:
        pass
    check("4xx 不重试（仅 1 次请求）",
          Handler.hits.get("/notfound", 0) - before == 1,
          f"实际 {Handler.hits.get('/notfound', 0) - before} 次")

    # 6. 读取超时
    t0 = time.time()
    try:
        http.get(f"{base}/slow", timeout=(3, 0.3), retries=0)
        check("慢响应触发读取超时", False)
    except requests.Timeout:
        check("慢响应触发 requests.Timeout", True, f"{time.time() - t0:.2f}s")
    except Exception as e:
        check("慢响应触发 requests.Timeout", False, type(e).__name__)

    # 7. raise_for_status=False 时返回响应而不抛
    r = http.get(f"{base}/notfound", timeout=5, retries=0, raise_for_status=False)
    check("raise_for_status=False 返回 404 响应", r.status_code == 404)

    # 8. 域名限流：同一 host 连续请求间隔不小于设定值
    http.reset_stats()
    t0 = time.time()
    for _ in range(3):
        http.get(f"{base}/ok", timeout=5, host_delay=0.15, retries=0)
    elapsed = time.time() - t0
    check("域名限流间隔生效", elapsed >= 0.29, f"3 次请求耗时 {elapsed:.2f}s（期望 ≥0.29s）")

    # 9. 统计
    st = http.stats()
    check("统计累计请求数", st["requests"] == 3, str(st["requests"]))
    check("统计累计耗时与平均", st["avg_ms"] >= 0 and st["ms"] >= 0, f"avg={st['avg_ms']}ms")
    check("失败计数被记录", st["failures"] == 0, "限流场景无失败")

    # 10. 异常不吞：连接失败抛 ConnectionError
    try:
        http.get("http://127.0.0.1:1/none", timeout=(1, 1), retries=0)
        check("连接失败抛异常", False)
    except requests.RequestException as e:
        check("连接失败抛 requests.RequestException", True, type(e).__name__)

    # 11. ping 自检不抛异常
    ok, info = http.ping(f"{base}/ok", timeout=5)
    check("ping 可达", ok and "200" in info, info)
    ok2, info2 = http.ping("http://127.0.0.1:1/x", timeout=1)
    check("ping 不可达返回 False 而不抛", ok2 is False, info2)

    srv.shutdown()
    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
