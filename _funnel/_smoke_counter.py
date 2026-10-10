#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
冒烟测试 counter_server.py：能计数、能出周报、且**不往磁盘落任何身份信息**。

    python _funnel/_smoke_counter.py

会临时起一个本机服务（端口 8619）、发几组请求、校验结果与落盘内容，然后自动关闭清理。
改动 counter_server.py 后跑一遍，尤其要确认「落盘仅含日期/渠道/计数」这条红线没破。
"""
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "counter_server.py")
DATA = os.path.join(HERE, "_smoke_counter_data.json")
PORT = 8619
BASE = "http://127.0.0.1:%d" % PORT

for p in (DATA, DATA + ".tmp"):
    if os.path.exists(p):
        os.remove(p)

env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
proc = subprocess.Popen([sys.executable, SRV, "--port", str(PORT), "--data", DATA],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")


def get(path, ua="smoke/1.0"):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


ok = True
try:
    for _ in range(40):
        try:
            get("/")
            break
        except Exception:
            time.sleep(0.25)
    else:
        raise RuntimeError("服务未启动")

    today = dt.date.today()
    week = "%d-W%02d" % (today.isocalendar()[0], today.isocalendar()[1])

    # 同一 UA 连点 5 次 -> 当日去重后只记 1
    for _ in range(5):
        get("/hit?f=dxy", ua="Mozilla/5.0 (Windows NT 10.0) SmokeA")
    get("/hit?f=dxy", ua="Mozilla/5.0 (iPhone) SmokeB")            # 另一个 UA -> +1
    get("/hit?f=zhihu", ua="Mozilla/5.0 (Macintosh) SmokeC")
    get("/hit?f=zhihu", ua="Mozilla/5.0 (Macintosh) SmokeC")       # 重复 -> 去重
    get("/hit?f=evil-channel", ua="SmokeD")                        # 未知码 -> 直接访问
    get("/hit", ua="SmokeE")                                       # 无参数 -> 直接访问

    time.sleep(0.6)
    _, body = get("/stats?week=" + week)
    stats = json.loads(body.decode("utf-8"))
    # SmokeA(1) + SmokeB(1) = 丁香园 2；SmokeC 去重 = 知乎 1；SmokeD + SmokeE = 直接访问 2
    expect = {"丁香园": 2, "知乎": 1, "直接访问": 2}
    print("stats:", stats)
    print("期望 :", expect)
    if stats != expect:
        print("[FAIL] 计数或当日去重不符")
        ok = False
    else:
        print("[OK] 渠道码解析 + 当日去重正确")

    raw = open(DATA, "r", encoding="utf-8").read()
    print("\n落盘内容：\n" + raw)
    d = json.loads(raw)
    flat = json.dumps(d, ensure_ascii=False)
    bad = [k for k in ("SmokeA", "SmokeB", "SmokeC", "SmokeD", "SmokeE",
                       "127.0.0.1", "Mozilla", "User-Agent", "evil-channel")
           if k in flat]
    keys_ok = all(isinstance(v, dict) and all(isinstance(x, int) for x in v.values())
                  for v in d.values())
    print("含身份信息字段:", bad or "无")
    print("结构合法(日期->渠道->整数):", keys_ok)
    if bad or not keys_ok:
        print("[FAIL] 落盘内容触碰隐私红线")
        ok = False
    else:
        print("[OK] 落盘仅含「日期/渠道/计数」，无 IP、UA、cookie")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    for p in (DATA, DATA + ".tmp"):
        if os.path.exists(p):
            os.remove(p)

print("\n=== 冒烟测试：%s ===" % ("全部通过" if ok else "存在失败"))
sys.exit(0 if ok else 1)
