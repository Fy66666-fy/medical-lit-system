#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四级漏斗 · 数据采集

四级：曝光(L1) -> 落地页访问(L2) -> 加入频道(L3) -> 次周活跃(L4)

用法：
    python _funnel/collect.py --week 2026-W41                       # 交互式录入
    python _funnel/collect.py --week 2026-W41 --set 丁香园 imp=5200 uv=210
    python _funnel/collect.py --week 2026-W41 --total joins=12 active=5 members=47
    python _funnel/collect.py --show                                # 只看不写

口径见 _funnel/README.md。同 week+channel 重复录入为覆盖（幂等）。
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

# Windows 控制台默认是 cp936/cp1252，重定向到管道时中文会炸，强制 UTF-8 输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
F_CHANNEL = os.path.join(HERE, "funnel.csv")
F_TOTAL = os.path.join(HERE, "funnel_total.csv")
F_SOURCES = os.path.join(HERE, "sources.json")

CHANNELS = ["丁香园", "知乎", "小木虫", "小红书", "B站", "GitHub", "直接访问"]
COLS_CH = ["week", "channel", "impressions", "landing_uv", "note"]
COLS_TOT = ["week", "members_end", "joins", "active_next_week", "note"]


# ---------- 基础读写 ----------
def _read(path, cols):
    """读 CSV。文件不存在返回空列表。编码兼容 UTF-8 / UTF-8-BOM。"""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.DictReader(f)
        return [{k: (r.get(k) or "") for k in cols} for r in rdr]


def _write(path, cols, rows):
    """写 CSV（UTF-8 无 BOM + LF），按 week 升序、channel 固定顺序排。"""
    order = {c: i for i, c in enumerate(CHANNELS)}
    rows = sorted(rows, key=lambda r: (r.get("week", ""), order.get(r.get("channel", ""), 99)))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def iso_week(d):
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w)


def default_week():
    """默认取上一周（本周还没过完）。"""
    return iso_week(dt.date.today() - dt.timedelta(days=7))


def _int(v):
    v = (v or "").strip()
    if v in ("", "-", "—", "?"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _pct(a, b):
    """a/b 百分比，任一为空或分母为 0 返回 None。"""
    if a is None or not b:
        return None
    return a / b * 100.0


def _fmt_pct(v):
    return "—" if v is None else "%.2f%%" % v


# ---------- 录入 ----------
def upsert_channel(week, channel, imp, uv, note):
    rows = _read(F_CHANNEL, COLS_CH)
    rec = next((r for r in rows if r["week"] == week and r["channel"] == channel), None)
    if rec is None:
        rec = {"week": week, "channel": channel, "impressions": "", "landing_uv": "", "note": ""}
        rows.append(rec)
    if imp is not None:
        rec["impressions"] = str(imp)
    if uv is not None:
        rec["landing_uv"] = str(uv)
    if note:
        rec["note"] = note
    _write(F_CHANNEL, COLS_CH, rows)
    return rec


def upsert_total(week, joins, active, members, note):
    rows = _read(F_TOTAL, COLS_TOT)
    rec = next((r for r in rows if r["week"] == week), None)
    if rec is None:
        rec = {"week": week, "members_end": "", "joins": "", "active_next_week": "", "note": ""}
        rows.append(rec)
    if members is not None:
        rec["members_end"] = str(members)
    if joins is not None:
        rec["joins"] = str(joins)
    if active is not None:
        rec["active_next_week"] = str(active)
    if note:
        rec["note"] = note
    _write(F_TOTAL, COLS_TOT, rows)
    return rec


def interactive(week):
    print("== 四级漏斗 · 录入 [%s] ==" % week)
    print("直接回车 = 保持原值/留空。宁可空着，也不要编数字。\n")
    ch_rows = _read(F_CHANNEL, COLS_CH)
    for ch in CHANNELS:
        cur = next((r for r in ch_rows if r["week"] == week and r["channel"] == ch), None)
        ci = (cur or {}).get("impressions", "")
        cu = (cur or {}).get("landing_uv", "")
        print("[%s] 当前：曝光=%s  落地页UV=%s" % (ch, ci or "空", cu or "空"))
        a = input("   曝光 L1 (渠道后台阅读/播放/浏览数)：").strip()
        b = input("   落地页 UV L2：").strip()
        n = input("   备注（这周发了什么，可留空）：").strip()
        if a or b or n:
            upsert_channel(week, ch, _int(a) if a else None, _int(b) if b else None, n)
    print()
    tot = next((r for r in _read(F_TOTAL, COLS_TOT) if r["week"] == week), None)
    print("== 全站总量（L3/L4，渠道无法拆分）==")
    print("   当前：周末成员=%s  当周新增=%s  次周活跃=%s"
          % ((tot or {}).get("members_end") or "空",
             (tot or {}).get("joins") or "空",
             (tot or {}).get("active_next_week") or "空"))
    m = input("   周末频道成员总数：").strip()
    j = input("   当周新增入群：").strip()
    ac = input("   次周活跃人数（上周入群者本周发言/用过产品）：").strip()
    tn = input("   备注（可留空）：").strip()
    if m or j or ac or tn:
        upsert_total(week, _int(m) if m else None, _int(ac) if ac else None,
                     _int(j) if j else None, tn)


def auto_pull(week):
    """从自建匿名计数端点自动拉 landing_uv（见 README 方案 B）。
    未配置 sources.json 的 counter_url 则静默跳过。"""
    if not os.path.exists(F_SOURCES):
        return 0
    try:
        cfg = json.load(open(F_SOURCES, "r", encoding="utf-8"))
    except Exception as e:
        print("sources.json 解析失败：%s" % e)
        return 0
    url = (cfg or {}).get("counter_url", "").strip()
    if not url:
        return 0
    import urllib.request
    try:
        req = urllib.request.Request(
            url.rstrip("/") + "/stats?week=" + week,
            headers={"User-Agent": "funnel-collect/1.0"},
        )
        data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    except Exception as e:
        print("自动拉取失败（已跳过，可手填）：%s" % e)
        return 0
    n = 0
    for ch, v in (data or {}).items():
        if ch in CHANNELS and isinstance(v, (int, float)):
            upsert_channel(week, ch, None, int(v), "")
            n += 1
    print("自动拉取 landing_uv：%d 个渠道" % n)
    return n


# ---------- 汇总展示 ----------
def summarize(week=None):
    ch_rows = _read(F_CHANNEL, COLS_CH)
    tot_rows = _read(F_TOTAL, COLS_TOT)
    weeks = sorted({r["week"] for r in ch_rows} | {r["week"] for r in tot_rows})
    if not weeks:
        print("暂无数据。先跑：python _funnel/collect.py --week <ISO周>")
        return
    if week and week in weeks:
        weeks = [week]

    print("\n" + "=" * 72)
    print("四级漏斗 · 汇总")
    print("=" * 72)
    for w in weeks:
        cur_ch = [r for r in ch_rows if r["week"] == w]
        tot = next((r for r in tot_rows if r["week"] == w), None) or {}
        imp = sum(_int(r["impressions"]) or 0 for r in cur_ch)
        uv = sum(_int(r["landing_uv"]) or 0 for r in cur_ch)
        joins = _int(tot.get("joins"))
        act = _int(tot.get("active_next_week"))
        mem = _int(tot.get("members_end"))
        print("\n【%s】周末成员数：%s" % (w, mem if mem is not None else "—"))
        print("  L1 曝光        %8s" % (imp or "—"))
        print("  L2 落地页UV    %8s   点击率 L2/L1 = %s"
              % (uv or "—", _fmt_pct(_pct(uv, imp))))
        print("  L3 加入频道    %8s   入群率 L3/L2 = %s"
              % (joins if joins is not None else "—", _fmt_pct(_pct(joins, uv))))
        print("  L4 次周活跃    %8s   留存率 L4/L3 = %s"
              % (act if act is not None else "—", _fmt_pct(_pct(act, joins))))
        print("  总转化 L3/L1 = %s" % _fmt_pct(_pct(joins, imp)))

        print("  ── 渠道明细（按总转化潜力排序）──")
        hdr = "     %-8s %9s %9s %9s" % ("渠道", "曝光L1", "落地页L2", "点击率")
        print(hdr)
        for r in sorted(cur_ch, key=lambda x: -(_int(x["landing_uv"]) or 0)):
            i, u = _int(r["impressions"]), _int(r["landing_uv"])
            if i is None and u is None:
                continue
            print("     %-8s %9s %9s %9s" % (r["channel"],
                                             i if i is not None else "—",
                                             u if u is not None else "—",
                                             _fmt_pct(_pct(u, i))))


def main():
    ap = argparse.ArgumentParser(description="四级漏斗采集")
    ap.add_argument("--week", default=None, help="ISO 周，如 2026-W41；默认上一周")
    # action="append" + nargs="+"：允许多次 --set（只用 nargs="+" 时后者会覆盖前者）
    ap.add_argument("--set", action="append", nargs="+", default=[],
                    help="渠道数据：渠道名 imp=5200 uv=210（imp/uv 可只给一个）")
    ap.add_argument("--total", nargs="+", default=[],
                    help="全站数据：joins=12 active=5 members=47 note=xxx")
    ap.add_argument("--auto", action="store_true", help="尝试从自建计数端点拉 landing_uv")
    ap.add_argument("--show", action="store_true", help="只显示汇总，不录入")
    args = ap.parse_args()

    week = args.week or default_week()

    if args.show:
        summarize(week if args.week else None)
        return

    if not args.set and not args.total and not sys.stdin.isatty():
        # 非交互环境且没给参数：只汇总
        summarize(week if args.week else None)
        return

    if args.auto:
        auto_pull(week)

    for item in args.set:
        # action="append" 时 item 已是 list；兼容单字符串写法
        parts = item if isinstance(item, list) else str(item).split()
        if not parts:
            continue
        ch = parts[0]
        if ch not in CHANNELS:
            print("跳过未知渠道：%s（可用：%s）" % (ch, "、".join(CHANNELS)))
            continue
        imp = uv = None
        note = ""
        for p in parts[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                if k in ("imp", "impressions", "曝光"):
                    imp = _int(v)
                elif k in ("uv", "landing_uv", "落地页"):
                    uv = _int(v)
                elif k in ("note", "备注"):
                    note = v
        upsert_channel(week, ch, imp, uv, note)
        print("已写入 %s / %s：曝光=%s 落地页UV=%s" % (week, ch, imp, uv))

    if args.total:
        kw = {}
        for p in args.total:
            if "=" in p:
                k, v = p.split("=", 1)
                kw[k.strip()] = v
        upsert_total(week, _int(kw.get("joins")), _int(kw.get("active")),
                     _int(kw.get("members")), kw.get("note", ""))
        print("已写入 %s 全站：新增=%s 次周活跃=%s 周末成员=%s"
              % (week, kw.get("joins"), kw.get("active"), kw.get("members")))

    if not args.set and not args.total:
        interactive(week)

    summarize(week)


if __name__ == "__main__":
    main()
