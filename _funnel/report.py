#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
四级漏斗 · 看板生成

    python _funnel/report.py            # 生成 _funnel/report.html（双击打开）
    python _funnel/report.py --week 2026-W41   # 只看某一周

零第三方依赖：漏斗图是手写 SVG，不引 matplotlib / plotly。
"""
import argparse
import csv
import datetime as dt
import html
import os
import sys
import webbrowser

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
F_CHANNEL = os.path.join(HERE, "funnel.csv")
F_TOTAL = os.path.join(HERE, "funnel_total.csv")
OUT = os.path.join(HERE, "report.html")
# 示例数据：仅供 --demo 演示漏斗长什么样，不是真实数据，别往里录
EX_CHANNEL = os.path.join(HERE, "example_funnel.csv")
EX_TOTAL = os.path.join(HERE, "example_funnel_total.csv")
OUT_DEMO = os.path.join(HERE, "demo_report.html")

LEVEL_COLORS = ["#2563eb", "#0891b2", "#059669", "#d97706"]
LEVEL_NAMES = ["L1 曝光", "L2 落地页访问", "L3 加入频道", "L4 次周活跃"]


def _read(path, cols):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [{k: (r.get(k) or "") for k in cols}
                for r in csv.DictReader(f)]


def _int(v):
    v = (v or "").strip()
    if v in ("", "-", "—", "?"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _pct(a, b):
    if a is None or not b:
        return None
    return a / b * 100.0


def _f(v, suffix=""):
    return "—" if v is None else "{:,}{}".format(v, suffix)


def _fp(v):
    return "—" if v is None else "%.2f%%" % v


def _e(s):
    return html.escape(str(s))


def week_stats(ch_rows, tot_rows, weeks):
    """按周汇总，返回 [(week, l1, l2, l3, l4, members)]"""
    out = []
    for w in weeks:
        cur = [r for r in ch_rows if r["week"] == w]
        tot = next((r for r in tot_rows if r["week"] == w), None) or {}
        out.append((
            w,
            sum(_int(r["impressions"]) or 0 for r in cur) or None,
            sum(_int(r["landing_uv"]) or 0 for r in cur) or None,
            _int(tot.get("joins")),
            _int(tot.get("active_next_week")),
            _int(tot.get("members_end")),
        ))
    return out


def funnel_svg(l1, l2, l3, l4):
    """手写 SVG 漏斗：四根横条，宽度按 L1 等比缩放（忠实反映真实比例）。

    两点刻意的设计：
      * 宽度**不做对数/幂次美化**——末级窄到几乎看不见，本身就是在告诉你
        「漏得有多厉害」，这正是漏斗图该传达的信息；
      * 数值文字一律放在横条**右侧固定位置**（深色），不叠在条内。
        否则条一收窄，白字溢出到白底上就看不见了。
    """
    vals = [l1, l2, l3, l4]
    W, TOP, ROW_H, GAP = 780, 16, 58, 14
    LABEL_W, BAR_MAX, MIN_W = 112, 452, 8
    X_NUM, X_RATE = 588, 668          # 数值 / 转化率：固定列，保证对齐
    base = next((v for v in vals if v), None) or 0
    h = TOP + len(vals) * (ROW_H + GAP) + 8
    parts = ['<svg viewBox="0 0 %d %d" width="100%%" '
             'style="max-width:%dpx;height:auto" role="img" '
             'aria-label="四级漏斗">' % (W, h, W)]
    for i, v in enumerate(vals):
        y = TOP + i * (ROW_H + GAP)
        ymid = y + ROW_H / 2 + 5
        c = LEVEL_COLORS[i]
        parts.append(
            '<text x="0" y="%.0f" font-size="13.5" font-weight="600" '
            'fill="#0f172a">%s</text>' % (ymid, _e(LEVEL_NAMES[i]))
        )
        if v and base:
            bw = max(MIN_W, int(BAR_MAX * v / base))
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="%d" rx="6" '
                'fill="%s" opacity="0.92"/>' % (LABEL_W, y, bw, ROW_H, c)
            )
        else:
            # 数据缺失：灰色空框，不造假形状
            parts.append(
                '<rect x="%d" y="%d" width="%d" height="%d" rx="6" '
                'fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1" '
                'stroke-dasharray="4 3"/>' % (LABEL_W, y, 56, ROW_H)
            )
        parts.append(
            '<text x="%d" y="%.0f" font-size="16" font-weight="700" '
            'fill="#0f172a">%s</text>' % (X_NUM, ymid, _e(_f(v)))
        )
        nxt = vals[i + 1] if i + 1 < len(vals) else None
        rate = _pct(nxt, v)
        if rate is not None:
            parts.append(
                '<text x="%d" y="%.0f" font-size="13" fill="#64748b">'
                '↓ %s</text>' % (X_RATE, ymid, _e(_fp(rate)))
            )
        else:
            parts.append(
                '<text x="%d" y="%.0f" font-size="11.5" fill="#cbd5e1">'
                '↓ 待补</text>' % (X_RATE, ymid)
            )
    parts.append("</svg>")
    return "\n".join(parts)


def diagnose(rows):
    """按 README 的阈值给诊断。"""
    tips = []
    if not rows:
        return ['<li class="muted">暂无数据。先跑 <code>collect.py --week &lt;ISO周&gt;</code> 录入一周。</li>']
    l1 = sum(r[1] or 0 for r in rows)
    l2 = sum(r[2] or 0 for r in rows)
    l3 = sum(r[3] or 0 for r in rows)
    l4 = sum(r[4] or 0 for r in rows)

    ctr, jr, rr = _pct(l2, l1), _pct(l3, l2), _pct(l4, l3)
    if ctr is not None and ctr < 0.5:
        tips.append('<li class="warn"><b>点击率 %.2f%%</b> 低于 0.5%%——内容钩子或渠道人群错配。'
                    "换选题，或把这条渠道的精力挪给点击率更高的那条。</li>" % ctr)
    if jr is not None and jr < 3:
        tips.append('<li class="warn"><b>入群率 %.2f%%</b> 低于 3%%——落地页没讲清“为什么要加群”。'
                    "检查 #beta 那一段：价值、门槛（有无表单）、权益是否一眼看懂。</li>" % jr)
    if rr is not None and rr < 10:
        tips.append('<li class="warn"><b>留存率 %.2f%%</b> 低于 10%%——频道缺内容，'
                    "或新人第一次用产品没跑通。优先补置顶帖与“三分钟上手”。</li>" % rr)
    if l3 < 30:
        tips.append('<li class="muted"><b>累计入群 %d 人</b>，样本不足 30，'
                    "L4/L3 波动主要是噪声，先别拿它做决策。</li>" % l3)
    if not tips:
        tips.append('<li class="ok">各项转化率都在健康区间。保持节奏，继续攒样本。</li>')
    return tips


def build(week=None, demo=False):
    fc = EX_CHANNEL if demo else F_CHANNEL
    ft = EX_TOTAL if demo else F_TOTAL
    out_path = OUT_DEMO if demo else OUT
    ch_rows = _read(fc, ["week", "channel", "impressions", "landing_uv", "note"])
    tot_rows = _read(ft, ["week", "members_end", "joins", "active_next_week", "note"])
    weeks = sorted({r["week"] for r in ch_rows} | {r["week"] for r in tot_rows})
    if not weeks:
        weeks = []
    stats = week_stats(ch_rows, tot_rows, weeks)
    if week:
        stats = [s for s in stats if s[0] == week] or stats

    latest = stats[-1] if stats else (None, None, None, None, None, None)
    lw = latest[0]

    # 渠道明细（最新周 + 全期累计）
    per_ch = {}
    for r in ch_rows:
        d = per_ch.setdefault(r["channel"], {"imp": 0, "uv": 0, "w_imp": None, "w_uv": None})
        i, u = _int(r["impressions"]), _int(r["landing_uv"])
        d["imp"] += i or 0
        d["uv"] += u or 0
        if r["week"] == lw:
            d["w_imp"], d["w_uv"] = i, u

    ch_html = []
    for name, d in sorted(per_ch.items(), key=lambda kv: -kv[1]["uv"]):
        if not (d["imp"] or d["uv"]):
            continue
        ch_html.append(
            "<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td></tr>"
            % (_e(name), _f(d["w_imp"]), _f(d["w_uv"]), _fp(_pct(d["w_uv"], d["w_imp"])),
               _f(d["imp"]), _f(d["uv"]), _fp(_pct(d["uv"], d["imp"])))
        )
    ch_table = ("<table><thead><tr><th>渠道</th><th colspan='3'>最新周 %s</th>"
                "<th colspan='3'>全期累计</th></tr>"
                "<tr><th></th><th>曝光L1</th><th>落地页L2</th><th>点击率</th>"
                "<th>曝光L1</th><th>落地页L2</th><th>点击率</th></tr></thead><tbody>%s</tbody></table>"
                % (_e(lw or "—"), "\n".join(ch_html))) if ch_html else \
        '<p class="muted">还没有渠道数据。</p>'

    # 周趋势
    tr_html = []
    for w, l1, l2, l3, l4, mem in stats:
        tr_html.append(
            "<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (_e(w), _f(l1), _f(l2), _f(l3), _f(l4), _f(mem),
               _fp(_pct(l2, l1)), _fp(_pct(l3, l2)), _fp(_pct(l4, l3)))
        )
    trend_table = ("<table><thead><tr><th>周</th><th>曝光L1</th><th>落地页L2</th>"
                   "<th>入群L3</th><th>次周活跃L4</th><th>周末成员</th>"
                   "<th>点击率</th><th>入群率</th><th>留存率</th></tr></thead>"
                   "<tbody>%s</tbody></table>" % "\n".join(tr_html)) if tr_html else \
        '<p class="muted">还没有周数据。</p>'

    svg = funnel_svg(latest[1], latest[2], latest[3], latest[4]) if lw else ""
    gen = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    doc = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>内测推广 · 四级漏斗看板</title>
<style>
:root{{--bg:#f8fafc;--card:#fff;--ink:#0f172a;--ink2:#475569;--ink3:#94a3b8;
--line:#e2e8f0;--blue:#2563eb;}}
*{{box-sizing:border-box}}
body{{margin:0;padding:28px 20px 60px;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:900px;margin:0 auto}}
h1{{font-size:23px;margin:0 0 6px}}
.sub{{color:var(--ink3);font-size:13.5px;margin-bottom:22px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:22px;margin-bottom:18px;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
h2{{font-size:16px;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:8px 9px;text-align:right;border-bottom:1px solid var(--line);
font-variant-numeric:tabular-nums}}
th{{color:var(--ink2);font-weight:600;background:#f1f5f9;font-size:12.5px}}
th:first-child,td:first-child{{text-align:left}}
tbody tr:last-child td{{border-bottom:none}}
code{{background:#f1f5f9;padding:1.5px 5px;border-radius:4px;font-size:12.5px}}
ul{{margin:0;padding-left:20px}} li{{margin-bottom:8px;font-size:14px}}
.warn{{color:#b45309}} .ok{{color:#047857}} .muted{{color:var(--ink3)}}
.banner{{background:#fffbeb;border:1px solid #fde68a;color:#92400e;
border-radius:10px;padding:11px 14px;font-size:13.5px;margin-bottom:18px}}
.note{{font-size:12.5px;color:var(--ink3);margin-top:12px;
border-top:1px dashed var(--line);padding-top:11px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;
margin-bottom:18px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.kpi .k{{font-size:12px;color:var(--ink3);margin-bottom:4px}}
.kpi .v{{font-size:21px;font-weight:700}}
</style></head><body><div class="wrap">
<h1>内测推广 · 四级漏斗</h1>
<div class="sub">曝光 → 落地页访问 → 加入频道 → 次周活跃　·　生成于 {gen}</div>
{banner}

<div class="grid">
  <div class="kpi"><div class="k">点击率 L2/L1</div><div class="v">{ctr}</div></div>
  <div class="kpi"><div class="k">入群率 L3/L2</div><div class="v">{jr}</div></div>
  <div class="kpi"><div class="k">留存率 L4/L3</div><div class="v">{rr}</div></div>
  <div class="kpi"><div class="k">总转化 L3/L1</div><div class="v">{tr}</div></div>
</div>

<div class="card"><h2>漏斗（{wlab}）</h2>
{svg}
<div class="note">横条宽度<b>按 L1 等比缩放、不做美化</b>——末级窄到几乎看不见是正常的，
这正是「漏得有多厉害」的真实形状。「↓」为该级到下一级的转化率。
显示为「—」或灰色空框表示该级数据缺失：<b>宁可空着也不要编数字</b>，缺失不参与计算。</div>
</div>

<div class="card"><h2>周趋势</h2>{trend}
<div class="note">周编号采用 ISO 周（周一为一周之始）。L3/L4 为全站总量，
无法按渠道拆分——所有人扫的是同一个频道二维码。</div></div>

<div class="card"><h2>渠道明细</h2>{chtable}
<div class="note">渠道优劣看到 L2 为止：哪条内容能把人引到落地页。
再往后的入群与留存只有总数，别硬凑一个拆不到渠道的数字。</div></div>

<div class="card"><h2>诊断</h2><ul>{tips}</ul></div>

<div class="card"><h2>怎么维护</h2>
<div class="note" style="border:none;padding-top:0">
每周固定时间跑一次，约 5 分钟：<br>
<code>python _funnel/collect.py --week 2026-W41</code> 录渠道数据<br>
<code>python _funnel/collect.py --week 2026-W41 --total joins=12 active=5 members=47</code> 录全站<br>
<code>python _funnel/report.py</code> 重新生成本页<br>
口径、阈值、隐私红线详见 <code>_funnel/README.md</code>。
</div></div>
</div></body></html>"""

    l1 = sum(r[1] or 0 for r in stats)
    l2 = sum(r[2] or 0 for r in stats)
    l3 = sum(r[3] or 0 for r in stats)
    l4 = sum(r[4] or 0 for r in stats)

    banner = ("<div class=\"banner\">这是用<b>示例数据</b>生成的演示看板，"
              "不是真实推广数据。真实数据请先用 <code>collect.py</code> 录入，"
              "再跑 <code>report.py</code> 生成 <code>report.html</code>。</div>") if demo else ""

    out = doc.format(
        gen=gen, banner=banner,
        ctr=_fp(_pct(l2, l1)), jr=_fp(_pct(l3, l2)),
        rr=_fp(_pct(l4, l3)), tr=_fp(_pct(l3, l1)),
        wlab=_e(lw or "暂无数据"), svg=svg,
        trend=trend_table, chtable=ch_table,
        tips="\n".join(diagnose(stats)),
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    return out_path, len(stats)


def main():
    ap = argparse.ArgumentParser(description="四级漏斗看板")
    ap.add_argument("--week", default=None)
    ap.add_argument("--demo", action="store_true",
                    help="用 example_*.csv 的示例数据生成演示看板 demo_report.html")
    ap.add_argument("--open", action="store_true", help="生成后自动打开")
    args = ap.parse_args()
    path, n = build(args.week, demo=args.demo)
    print("已生成：%s（%d 周数据）" % (path, n))
    if args.open:
        webbrowser.open("file:///" + path.replace("\\", "/"))


if __name__ == "__main__":
    main()
