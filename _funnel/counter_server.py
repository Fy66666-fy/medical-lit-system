#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四级漏斗 · 落地页匿名计数服务（README 方案 B）

设计上刻意做到「够用就好、绝不越界」：

  * 只维护一个聚合整数表：日期 -> 渠道 -> 计数；
  * **不存 IP、不存 UA、不设 cookie、不做设备指纹**；
  * 当日去重用的哈希只在**内存**里活 24 小时，进程重启即清空，**从不落盘**；
  * 落盘的 data.json 里只有「日期 / 渠道 / 数字」三个字段，没有任何可复原到人的信息。

这与 README 的隐私承诺（不收集身份信息、不做行为追踪、不接统计 SDK）一致。
若改用 Umami 等统计 SDK，必须先修改 README 与应用内「隐私与数据」页条款。

端点：
    GET /hit?f=丁香园      计数 +1，返回 1x1 GIF（前端埋在 <img> 里，不阻塞页面）
    GET /stats?week=2026-W41   返回该周各渠道 UV（近似值）
    GET /                 运行状态与总量

启动：
    python _funnel/counter_server.py --port 8611 --data _funnel/counter_data.json
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

LOCK = threading.Lock()
DATA_PATH = "counter_data.json"
# 当日去重集合：只存哈希，不落盘，重启即失（宁可略高估，也不碰身份信息）
_seen = {}          # date_str -> set(hash)
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
       b"\x21\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
       b"\x00\x00\x02\x02D\x01\x00;")
CHANNELS = ["丁香园", "知乎", "小木虫", "小红书", "B站", "GitHub", "直接访问"]
# 渠道码 -> 渠道名。落地页发来的是英文码（URL 里中文易断链），
# 这里统一成中文名，与 collect.py 的 CHANNELS、links.md 保持一致。
CODE_MAP = {"dxy": "丁香园", "zhihu": "知乎", "xmc": "小木虫", "xhs": "小红书",
            "bili": "B站", "bilibili": "B站", "github": "GitHub",
            "direct": "直接访问"}


def resolve_channel(raw):
    """把 URL 上的渠道码解析成渠道名，无法识别的一律回落「直接访问」。"""
    k = (raw or "").strip().lower()
    return CODE_MAP.get(k) or (k if k in CHANNELS else "直接访问")


def load():
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(d):
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, DATA_PATH)


def bump(channel, day):
    d = load()
    d.setdefault(day, {}).setdefault(channel, 0)
    d[day][channel] += 1
    # 只保留最近 120 天，文件不会无限膨胀
    for k in sorted(d)[:-120]:
        d.pop(k, None)
    save(d)


def week_day_keys(week):
    """'2026-W41' -> 该周 7 天的日期键列表"""
    try:
        y, w = week.upper().split("-W")
        y, w = int(y), int(w)
    except Exception:
        return []
    mon = dt.date.fromisocalendar(y, w, 1)
    return [(mon + dt.timedelta(days=i)).isoformat() for i in range(7)]


class H(BaseHTTPRequestHandler):
    server_version = "anon-counter/1.0"

    def log_message(self, fmt, *a):        # 不写访问日志（日志里会有 IP）
        pass

    def _send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/hit":
            ch = resolve_channel((q.get("f") or ["direct"])[0])
            day = dt.date.today().isoformat()
            # 近似 UV：IP+UA+日 哈希后只在内存比对，用完即弃，不写盘
            raw = "%s|%s|%s" % (self.client_address[0] if self.client_address else "",
                                self.headers.get("User-Agent", ""), day)
            h = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
            with LOCK:
                s = _seen.setdefault(day, set())
                if h not in s:
                    s.add(h)
                    for k in list(_seen):
                        if k != day:
                            _seen.pop(k, None)   # 跨日即弃
                    bump(ch, day)
            self._send(200, GIF, "image/gif")
        elif u.path == "/stats":
            week = (q.get("week") or [""])[0]
            keys = week_day_keys(week) or [dt.date.today().isoformat()]
            d = load()
            out = {}
            for k in keys:
                for ch, v in (d.get(k) or {}).items():
                    out[ch] = out.get(ch, 0) + v
            self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif u.path == "/":
            d = load()
            tot = sum(sum(v.values()) for v in d.values())
            body = ("匿名计数服务运行中\n累计计数：%d\n覆盖日期：%d 天\n"
                    "不存储 IP / UA / cookie，仅保存聚合整数\n"
                    % (tot, len(d))).encode("utf-8")
            self._send(200, body, "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")


def main():
    global DATA_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "counter_data.json"))
    # 默认只监听本机；确实要对外提供服务时再显式传 --host 0.0.0.0
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    DATA_PATH = args.data
    print("匿名计数服务启动：http://%s:%d" % (args.host, args.port))
    print("数据文件：%s" % DATA_PATH)
    print("落盘内容仅含「日期 / 渠道 / 计数」，不存 IP、UA、cookie")
    ThreadingHTTPServer((args.host, args.port), H).serve_forever()


if __name__ == "__main__":
    main()
