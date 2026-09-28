import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from core import jobs, locate, pubmed, summarizer, storage, translate


def _resolve_tencent_creds() -> tuple[str, str]:
    """腾讯云翻译凭据解析：侧边栏输入 > st.secrets > 环境变量"""
    sid = os.environ.get("TENCENT_SECRET_ID", "")
    skey = os.environ.get("TENCENT_SECRET_KEY", "")
    try:  # st.secrets 仅在存在 secrets 文件/云端配置时可用
        if st.secrets.get("TENCENT_SECRET_ID") and st.secrets.get("TENCENT_SECRET_KEY"):
            sid = st.secrets["TENCENT_SECRET_ID"]
            skey = st.secrets["TENCENT_SECRET_KEY"]
    except Exception:
        pass
    sid = st.session_state.get("tencent_sid") or sid
    skey = st.session_state.get("tencent_skey") or skey
    return (sid or "").strip(), (skey or "").strip()


_sid, _skey = _resolve_tencent_creds()
translate.configure(_sid, _skey)

# ---- 可选插件（streamlit 生态组件，缺失时自动降级为原生控件）----
try:
    from streamlit_option_menu import option_menu

    HAS_OPTION_MENU = True
except Exception:  # pragma: no cover - 插件可选
    HAS_OPTION_MENU = False

st.set_page_config(
    page_title="医学文献智能摘要与检索系统",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- 全局样式（简约清新主题） ----------------
st.markdown(
    """
    <style>
    /* ---------- 主题变量 ---------- */
    :root {
        --ink:  #14313c;
        --ink2: #5b7280;
        --ink3: #93a4ae;
        --teal: #2e9e8f;
        --teal-d: #217a6e;
        --teal-s: #eaf7f4;
        --sky:  #3d8fd1;
        --line: #e6f1ef;
    }
    .stApp { background: #f7fbfa; }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1300px; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
    [data-testid="stHeader"] { background: transparent; }

    /* ---------- 内页页头 ---------- */
    .page-head {
        background: linear-gradient(120deg, #f1fbf8 0%, #f4f9fd 100%);
        border: 1px solid #e3f1ee; border-radius: 16px;
        padding: 1rem 1.35rem; margin-bottom: 1rem;
    }
    .page-head h1 { font-size: 1.24rem; margin: 0; color: var(--ink); font-weight: 700; }
    .page-head p { margin: 0.28rem 0 0; color: var(--ink2); font-size: 0.87rem; }

    /* ---------- 首页 Hero（整体卡片，由容器 key 承载） ---------- */
    div[class*="st-key-hero"] {
        background: linear-gradient(125deg, #f0fbf8 0%, #f4f9fd 58%, #f7f5fd 100%);
        border: 1px solid #e3f1ee; border-radius: 24px;
        padding: 1.9rem 2rem 1.4rem;
        box-shadow: 0 6px 26px rgba(46, 158, 143, 0.06);
        margin-bottom: 1.15rem;
    }
    .hero-pill {
        display: inline-block; background: #ffffff; color: var(--teal);
        border: 1px solid #cdece5; border-radius: 999px;
        padding: 4px 14px; font-size: 0.78rem; font-weight: 600; letter-spacing: 0.3px;
    }
    .hero-wrap h1 {
        font-size: 1.98rem; line-height: 1.32; margin: 0.9rem 0 0.6rem;
        color: #12303a; font-weight: 800; letter-spacing: -0.3px;
    }
    .hero-sub { color: var(--ink2); font-size: 0.97rem; line-height: 1.8; margin: 0 0 1rem; max-width: 520px; }
    .hero-tags span {
        display: inline-block; background: rgba(255, 255, 255, 0.85); color: #4a6070;
        border: 1px solid #e0efec; border-radius: 999px;
        padding: 3px 11px; margin: 0 6px 6px 0; font-size: 0.775rem;
    }
    .hero-svg-box { display: flex; align-items: center; justify-content: center; }
    .hero-svg-box svg { max-width: 100%; height: auto; }

    /* ---------- 统计卡 ---------- */
    .stat-card {
        background: #ffffff; border: 1px solid var(--line); border-radius: 16px;
        padding: 0.9rem 1.1rem; height: 100%;
        box-shadow: 0 2px 10px rgba(46, 158, 143, 0.045);
    }
    .stat-card .k { color: var(--ink3); font-size: 0.78rem; letter-spacing: 0.3px; }
    .stat-card .v { color: #12303a; font-size: 1.58rem; font-weight: 700; line-height: 1.3; margin-top: 0.12rem; }
    .stat-card .u { color: var(--ink2); font-size: 0.75rem; }

    /* ---------- 功能卡 ---------- */
    div[class*="st-key-featcard"] {
        background: #ffffff; border: 1px solid var(--line); border-radius: 18px;
        padding: 1.15rem 1.15rem 0.8rem; height: 100%;
        box-shadow: 0 3px 14px rgba(46, 158, 143, 0.05);
        transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
    }
    div[class*="st-key-featcard"]:hover {
        transform: translateY(-3px);
        box-shadow: 0 12px 28px rgba(46, 158, 143, 0.12);
        border-color: #c8ebe4;
    }
    .fc-icon {
        width: 40px; height: 40px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.15rem; margin-bottom: 0.7rem;
    }
    .fc-title { font-size: 0.99rem; font-weight: 700; color: #12303a; margin-bottom: 0.3rem; }
    .fc-desc { font-size: 0.835rem; color: var(--ink2); line-height: 1.72; min-height: 4.3rem; }
    div[class*="st-key-featcard"] .stButton > button {
        width: 100%; font-size: 0.84rem; padding: 0.28rem 0; margin-top: 0.15rem;
    }

    /* ---------- 步骤条 ---------- */
    .step {
        background: #ffffff; border: 1px dashed #d9ece8; border-radius: 16px;
        padding: 0.95rem 1.1rem; height: 100%;
    }
    .step .num {
        display: inline-flex; align-items: center; justify-content: center;
        width: 26px; height: 26px; border-radius: 50%;
        background: var(--teal-s); color: var(--teal-d);
        font-size: 0.82rem; font-weight: 700; margin-bottom: 0.5rem;
    }
    .step .t { font-weight: 650; color: #12303a; font-size: 0.91rem; margin-bottom: 0.18rem; }
    .step .d { color: var(--ink2); font-size: 0.815rem; line-height: 1.7; }

    /* ---------- 区块标题 ---------- */
    .sec-title { display: flex; align-items: baseline; gap: 9px; margin: 1.15rem 0 0.8rem; }
    .sec-title .bar { width: 4px; height: 17px; border-radius: 3px; background: var(--teal); }
    .sec-title .tx { font-size: 1.05rem; font-weight: 700; color: #12303a; }
    .sec-title .hint { font-size: 0.79rem; color: var(--ink3); }

    /* ---------- 按钮 ---------- */
    .stButton > button, .stDownloadButton > button {
        border-radius: 11px; border: 1px solid #d9eae7; font-weight: 600;
        color: #33505c; transition: all 0.16s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: var(--teal); color: var(--teal-d);
        background: #f3fbf9; transform: translateY(-1px);
    }
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {
        background: var(--teal); border-color: var(--teal); color: #ffffff;
        box-shadow: 0 4px 14px rgba(46, 158, 143, 0.24);
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {
        background: var(--teal-d); border-color: var(--teal-d); color: #ffffff;
    }

    /* ---------- 表单控件协同（与主页同一套边框 / 圆角 / 主题色） ---------- */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea {
        border-radius: 10px; border: 1px solid #d9eae7;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: var(--teal); box-shadow: 0 0 0 2px rgba(46, 158, 143, 0.12);
    }
    [data-testid="stSelectbox"] > div > div,
    [data-testid="stSlider"] > div > div {
        border-radius: 10px;
    }
    div[data-testid="stExpander"] { background: #ffffff; }
    [data-testid="stAlert"] { border-radius: 12px; }

    /* 指标卡（全文数据分析面板的 st.metric）卡片化 */
    [data-testid="stMetric"] {
        background: #ffffff; border: 1px solid var(--line); border-radius: 14px;
        padding: 0.8rem 1rem;
        box-shadow: 0 2px 10px rgba(46, 158, 143, 0.045);
    }

    /* ---------- 结果面板（摘要 / 全文分析输出区） ---------- */
    div[class*="st-key-panel"] {
        background: #ffffff; border: 1px solid var(--line); border-radius: 18px;
        padding: 1.15rem 1.35rem;
        box-shadow: 0 3px 14px rgba(46, 158, 143, 0.05);
    }

    /* ---------- 输入区卡片（来源选择 / 参数设置） ---------- */
    div[class*="st-key-step-card"] {
        background: #fbfefd; border: 1px solid var(--line); border-radius: 18px;
        padding: 1.15rem 1.35rem;
    }
    /* 卡片内控件标题加粗，选项标题保持常规 */
    div[class*="st-key-step-card"] label[data-testid="stWidgetLabel"] p {
        font-weight: 600; margin-bottom: 0.15rem;
    }
    /* 参数子面板：语言 / 长度并排放进浅青底圆角块，与上方文献选择区分 */
    div[class*="st-key-step-params"] {
        background: #f2faf8; border: 1px solid #d9ece7; border-radius: 14px;
        padding: 0.85rem 1.1rem 0.35rem; margin-top: 0.9rem;
    }
    div[class*="st-key-step-params"] [data-testid="stRadio"] { margin-bottom: 0.45rem; }
    /* 卡片内控件组之间的呼吸感 */
    div[class*="st-key-step-card"] [data-testid="stVerticalBlock"] > div { margin-top: 0.55rem; }

    /* ---------- 其它 ---------- */
    div[data-testid="stExpander"] { border-radius: 12px; border-color: var(--line); }
    .kw-chip {
        display: inline-block; background: var(--teal-s); color: var(--teal-d);
        border-radius: 999px; padding: 2px 11px; margin: 2px 5px 2px 0; font-size: 0.79rem;
    }
    /* ---------- 原文定位（v2.1.0） ---------- */
    .loc-val {
        background: #fdeecd; color: #8a5a00; border-radius: 4px;
        padding: 0 4px; font-weight: 600;
    }
    .loc-sent {
        display: block; background: #f7fbfa; border: 1px solid var(--line);
        border-radius: 10px; padding: 0.55rem 0.85rem; margin: 0.35rem 0;
        line-height: 1.65; color: var(--ink); font-size: 0.86rem;
    }
    .loc-tag {
        color: var(--ink3); font-size: 0.76rem; margin-right: 0.5rem;
    }
    .loc-score {
        display: inline-block; background: #eaf7f4; color: var(--teal-d);
        border-radius: 999px; padding: 0 8px; font-size: 0.74rem; margin-left: 6px;
    }
    .loc-kw {
        background: #e3edfd; color: #1d4fb0; border-radius: 4px;
        padding: 0 4px; font-weight: 600;
    }
    hr { border-color: var(--line); }
    </style>
    """,
    unsafe_allow_html=True,
)


def header(title: str = "🩺 医学文献智能摘要与检索系统", subtitle: str = "PubMed 检索 · 摘要长度可选 · 图表解析 · PDF 全文链接 · 收藏管理"):
    st.markdown(
        f"""
        <div class="page-head">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------- 页面路由 ----------------
NAV_ITEMS = [
    ("系统首页", "house"),
    ("文献检索", "search"),
    ("智能摘要", "file-earmark-text"),
    ("批量全文", "stack"),
    ("我的收藏", "star"),
    ("检索历史", "clock-history"),
    ("更新日志", "clipboard-data"),
]
NAV_LABELS = [label for label, _ in NAV_ITEMS]


def goto(target: str):
    """供首页卡片按钮跳转使用（回调方式；配合 manual_select 实现外部导航）"""
    st.session_state["pending_page"] = target


pending = st.session_state.pop("pending_page", None)
pending_idx = NAV_LABELS.index(pending) if pending in NAV_LABELS else None

# ---------------- 后台任务（v1.7.0）：全文摘要 / 图表解析 / 批量全文 ----------------
def _ft_job(job, article: dict, title: str, max_sentences: int):
    """后台任务：单篇全文抓取（PMC → 浏览器兜底）+ 章节化摘要 + 数据分析"""
    jobs.update(job, 0.08, "正在抓取全文（PMC → 网页兜底）…")
    secs, src = pubmed.fetch_fulltext_any(article)
    jobs.update(job, 0.55, "正在生成章节化摘要与数据分析…")
    summary = summarizer.fulltext_summary(secs, title=title, max_sentences=max_sentences)
    analytics = summarizer.analyze_fulltext(secs)
    return {"secs": secs, "summary": summary, "analytics": analytics,
            "pmcid": article.get("pmcid", ""), "title": title, "source": src}


def _fig_job(job, pmcid: str):
    """后台任务：图表抓取 + 图片下载（非 OA 走浏览器截图兜底）"""
    jobs.update(job, 0.15, "正在从 PMC 抓取图表…")
    figures = pubmed.fetch_pmc_figures(pmcid)
    if figures:
        jobs.update(job, 0.5, "正在获取图表图片（非开放获取文献走浏览器截图兜底，约需 20-60 秒）…")
        pubmed.fetch_figure_images(pmcid, figures)
    return [f for f in figures if f.get("data")]


def _batch_job(job, articles: list[dict], max_sentences: int, workers: int, lang: str):
    """后台任务：多篇文献并行全文抓取 + 摘要 +（可选）中文翻译"""
    from concurrent.futures import ThreadPoolExecutor

    total = len(articles)
    results: list[dict | None] = [None] * total

    def one(i: int, a: dict):
        try:
            secs, src = pubmed.fetch_fulltext_any(a)
            summary = summarizer.fulltext_summary(secs, title=a["title"], max_sentences=max_sentences)
            analytics = summarizer.analyze_fulltext(secs)
            results[i] = {"article": a, "ok": True, "summary": summary, "analytics": analytics, "source": src}
        except Exception as e:  # noqa: BLE001 —— 单篇失败不拖垮整批
            results[i] = {"article": a, "ok": False, "error": str(e)}
        done = sum(1 for r in results if r is not None)
        jobs.update(job, progress=done / total * 0.85, note=f"{done}/{total} 篇完成")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in [ex.submit(one, i, a) for i, a in enumerate(articles)]:
            f.result()

    if lang == "中文":
        for i, r in enumerate(results):
            if not (r and r["ok"]):
                continue
            jobs.update(job, progress=0.85 + 0.15 * i / max(total, 1), note=f"翻译为中文：{i + 1}/{total}…")
            for p in r["summary"].get("sections", []):
                body = " ".join(p["sentences"])
                if summarizer.is_mostly_english(body):
                    try:
                        body = summarizer.translate_text(body, "en|zh-CN")
                    except Exception:
                        pass
                p["body_zh"] = body
    jobs.update(job, 1.0, f"完成（{sum(1 for r in results if r and r['ok'])}/{total} 篇成功）")
    return {"items": results, "lang": lang, "max_sentences": max_sentences}


def _apply_job_result(job: dict):
    """UI 主线程：把已完成任务的结果写入 session_state 并触发整页刷新"""
    if job["status"] == "error":
        st.toast(f"❌ {job['name']} 失败：{(job['error'] or '')[:80]}", icon="❌")
        if job.get("key", "").startswith("fig:"):
            st.session_state["figures"] = []
        return
    key = job.get("key", "")
    res = job.get("result") or {}
    if key.startswith("ft:"):
        st.session_state["fulltext"] = res["secs"]
        st.session_state["ft_summary"] = res["summary"]
        st.session_state["ft_analytics"] = res["analytics"]
        st.session_state["ft_source"] = res.get("source", "")
        st.toast("✅ 全文摘要已生成", icon="✅")
    elif key.startswith("fig:"):
        st.session_state["figures"] = res
        st.toast(f"✅ 图表解析完成（{len(res)} 张）", icon="✅")
    elif key == "batch":
        st.session_state["batch_results"] = res["items"]
        st.session_state["batch_lang"] = res.get("lang", "中文")
        ok = sum(1 for r in res["items"] if r.get("ok"))
        st.toast(f"✅ 批量全文完成：{ok}/{len(res['items'])} 篇成功", icon="✅")


def _batch_export_md(items: list[dict], lang: str) -> str:
    """把批量全文结果（摘要 + 数据分析）组装成一份 Markdown"""
    from datetime import datetime

    ok_n = sum(1 for r in items if r.get("ok"))
    lines = [
        "# 医学文献批量全文摘要与数据分析",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} · 共 {len(items)} 篇（成功 {ok_n}，失败 {len(items) - ok_n}）",
        "",
    ]
    for i, r in enumerate(items, 1):
        a = r["article"]
        lines += [f"## {i}. {a['title']}", ""]
        meta = [", ".join(a.get("authors") or []) if a.get("authors") else "",
                a.get("journal") or "", a.get("year") or ""]
        meta = " · ".join(x for x in meta if x)
        if meta:
            lines += [f"{meta} · PMID: {a.get('pmid', '-')} · {a.get('pmcid', '')}", ""]
        if not r.get("ok"):
            lines += [f"> ❌ 抓取失败：{r.get('error', '')}", "", "---", ""]
            continue
        if str(r.get("source", "")).startswith("网页"):
            lines += ["> 🌐 全文来源：网页提取（浏览器兜底，非 PMC 开放存档）", ""]
        summ, an = r["summary"], r["analytics"]
        if summ.get("sections"):
            for p in summ["sections"]:
                if lang == "中文":
                    body = p.get("body_zh") or " ".join(p["sentences"])
                    lines += [f"**【{p.get('title_zh') or p['title']}】** {body}", ""]
                else:
                    lines += [f"**【{p['title']}】** " + " ".join(p["sentences"]), ""]
        elif summ.get("summary"):
            lines += [summ["summary"], ""]
        lines += ["### 📊 数据分析", ""]
        lines.append(
            f"- 全文词数：{an['total_words']:,}；字符数：{an['total_chars']:,}；"
            f"章节数：{len(an['section_stats'])}"
        )
        kc = an.get("keyword_counts", {})
        kws = an.get("keywords", [])[:10]
        if kws:
            lines.append("- 高频关键词：" + "、".join(f"{k}（{kc[k]}）" if k in kc else k for k in kws))
        for name, m in (an.get("metrics") or {}).items():
            lines.append(f"- {name}（{m['count']} 处）：" + "；".join(m["samples"][:5]))
        lines += ["", "---", ""]
    return "\n".join(lines)


def _batch_export_xlsx(items: list[dict], lang: str = "中文") -> bytes:
    """批量结果统计表：Excel 三工作表（文献汇总 / 章节明细 / 统计指标），带表头样式与筛选"""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1F6E54")
    head_font = Font(bold=True, color="FFFFFF")
    wrap = Alignment(vertical="top", wrap_text=True)

    def _style(ws, widths: dict, freeze: str = "A2"):
        for c, wdt in widths.items():
            ws.column_dimensions[c].width = wdt
        for cell in ws[1]:
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.freeze_panes = freeze
        ws.auto_filter.ref = ws.dimensions

    # ---------- Sheet1 文献汇总 ----------
    ws = wb.active
    ws.title = "文献汇总"
    ws.append(["序号", "标题", "作者", "期刊", "年份", "DOI", "PMID", "PMCID",
               "PubMed 链接", "全文来源", "状态", "摘要章节数", "摘要预览",
               "全文总词数", "全文字符数", "正文章节数", "高频关键词 Top10",
               "统计指标汇总", "失败原因"])
    for i, r in enumerate(items, 1):
        a = r["article"]
        authors = ", ".join(a.get("authors") or [])
        pmid = a.get("pmid") or ""
        if r.get("ok"):
            an, summ = r["analytics"], r["summary"]
            kc = an.get("keyword_counts", {})
            kws = "、".join(f"{k}({kc[k]})" if k in kc else k for k in an.get("keywords", [])[:10])
            msum = "；".join(f"{name}×{m['count']}" for name, m in (an.get("metrics") or {}).items()) or "未检出"
            if summ.get("sections"):
                parts = []
                for p in summ["sections"]:
                    t = (p.get("title_zh") or p["title"]) if lang == "中文" else p["title"]
                    body = (p.get("body_zh") or " ".join(p["sentences"])) if lang == "中文" else " ".join(p["sentences"])
                    parts.append(f"【{t}】{body}")
                preview = " ".join(parts)
                n_secs = len(summ["sections"])
            else:
                preview, n_secs = summ.get("summary", ""), 0
            if len(preview) > 220:
                preview = preview[:220] + "…"
            ws.append([i, a.get("title", ""), authors, a.get("journal", ""), a.get("year", ""),
                       a.get("doi", ""), pmid, a.get("pmcid", ""),
                       f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                       r.get("source", ""), "成功", n_secs, preview,
                       an.get("total_words", ""), an.get("total_chars", ""),
                       len(an.get("section_stats") or []), kws, msum, ""])
            ws.cell(ws.max_row, 11).font = Font(color="1F6E54", bold=True)
        else:
            ws.append([i, a.get("title", ""), authors, a.get("journal", ""), a.get("year", ""),
                       a.get("doi", ""), pmid, a.get("pmcid", ""), "", "", "失败",
                       "", "", "", "", "", "", "", r.get("error", "")])
            ws.cell(ws.max_row, 11).font = Font(color="C0392B", bold=True)
    _style(ws, {"A": 6, "B": 45, "C": 28, "D": 20, "E": 8, "F": 22, "G": 13, "H": 13,
                "I": 34, "J": 12, "K": 8, "L": 11, "M": 60, "N": 11, "O": 11, "P": 11,
                "Q": 40, "R": 30, "S": 30})
    for row in ws.iter_rows(min_row=2):
        for cell in (row[1], row[12], row[16]):  # 标题/预览/关键词列换行
            cell.alignment = wrap

    # ---------- Sheet2 章节明细 ----------
    ws2 = wb.create_sheet("章节明细")
    ws2.append(["文献序号", "文献标题", "章节", "章节词数", "章节字符数"])
    for i, r in enumerate(items, 1):
        if not r.get("ok"):
            continue
        t = r["article"].get("title", "")
        for st in r["analytics"].get("section_stats", []):
            ws2.append([i, t, st.get("title", ""), st.get("words", ""), st.get("chars", "")])
    _style(ws2, {"A": 9, "B": 45, "C": 22, "D": 11, "E": 12})

    # ---------- Sheet3 统计指标 ----------
    ws3 = wb.create_sheet("统计指标")
    ws3.append(["文献序号", "文献标题", "指标", "出现次数", "示例值"])
    for i, r in enumerate(items, 1):
        if not r.get("ok"):
            continue
        t = r["article"].get("title", "")
        for name, m in (r["analytics"].get("metrics") or {}).items():
            ws3.append([i, t, name, m.get("count", ""), "；".join(m.get("samples", [])[:6])])
    _style(ws3, {"A": 9, "B": 45, "C": 18, "D": 10, "E": 70})
    for row in ws3.iter_rows(min_row=2):
        row[4].alignment = wrap

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@st.fragment(run_every=1.5)
def job_monitor():
    """侧边栏任务进度监视：轮询后台任务，完成后消费结果并整页刷新"""
    snaps = jobs.snapshot()
    running = [j for j in snaps if j["status"] == "running"]
    if not running and not any(not j["consumed"] for j in snaps):
        return
    changed = False
    for j in snaps:
        if not j["consumed"] and j["status"] in ("done", "error"):
            full = jobs.consume(j["id"])
            if full:
                _apply_job_result(full)
                changed = True
    if running:
        st.markdown("⏳ **后台任务**")
        for j in running:
            st.caption(f"{j['name']} · {j['note']}")
            st.progress(max(j["progress"], 0.03))
    if changed:
        st.rerun(scope="app")


# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.markdown("### 🧭 功能导航")
    if HAS_OPTION_MENU:
        page = option_menu(
            None,
            NAV_LABELS,
            icons=[icon for _, icon in NAV_ITEMS],
            default_index=0,
            manual_select=pending_idx,
            key="nav",
            styles={
                "container": {"padding": "0", "background-color": "transparent"},
                "icon": {"color": "#2e9e8f", "font-size": "0.95rem"},
                "nav-link": {
                    "font-size": "0.93rem",
                    "border-radius": "10px",
                    "padding": "8px 12px",
                    "margin": "2px 0",
                    "color": "#4a6070",
                    "--hover-color": "#eaf7f4",
                },
                "nav-link-selected": {
                    "background-color": "#2e9e8f",
                    "color": "#ffffff",
                    "font-weight": "600",
                },
            },
        )
        if page not in NAV_LABELS:  # 兜底，防止状态异常
            page = NAV_LABELS[0]
    else:
        if pending is not None:
            st.session_state["nav"] = pending
        page = st.radio("页面", NAV_LABELS, label_visibility="collapsed", key="nav")
    st.divider()
    job_monitor()  # 后台任务进度（全文摘要 / 图表解析 / 批量全文）
    st.divider()
    st.markdown("### 🤖 大模型设置（可选）")
    st.caption("配置 OpenAI 兼容接口后，智能摘要页可使用 LLM 生成深度总结；不配置也能使用内置抽取式摘要。")

    llm_base = st.text_input(
        "API Base URL",
        value=st.session_state.get("llm_base", ""),
        placeholder="https://api.openai.com",
    )
    llm_key = st.text_input(
        "API Key",
        value=st.session_state.get("llm_key", ""),
        type="password",
    )
    llm_model = st.text_input(
        "模型名称",
        value=st.session_state.get("llm_model", ""),
        placeholder="gpt-4o-mini",
    )
    st.session_state["llm_base"] = llm_base
    st.session_state["llm_key"] = llm_key
    st.session_state["llm_model"] = llm_model
    llm_ready = bool(llm_base and llm_key and llm_model)
    if llm_ready:
        st.caption("✅ LLM 已就绪")
    else:
        st.caption("⚪ 未配置，仅使用抽取式摘要")

    st.divider()
    st.markdown("### 🌐 翻译设置（可选）")
    st.caption(
        "配置腾讯云机器翻译（每月 500 万字符免费额度）后，中文翻译走腾讯接口，"
        "质量与额度大幅优于默认的 MyMemory 免费接口；未配置或调用失败时自动回退 MyMemory。"
    )
    t_sid = st.text_input(
        "腾讯云 SecretId",
        value=st.session_state.get("tencent_sid", ""),
        placeholder="AKID********",
    )
    t_skey = st.text_input(
        "腾讯云 SecretKey",
        value=st.session_state.get("tencent_skey", ""),
        type="password",
    )
    st.session_state["tencent_sid"] = t_sid
    st.session_state["tencent_skey"] = t_skey
    if t_sid and t_skey:
        st.caption("✅ 腾讯云翻译已就绪")
    elif os.environ.get("TENCENT_SECRET_ID"):
        st.caption("✅ 检测到环境变量凭据")
    else:
        st.caption("⚪ 未配置，使用 MyMemory 免费接口")

    st.divider()
    st.caption("数据源：PubMed E-utilities（NCBI 官方公开 API）\n\n检索结果仅用于研究学习，不构成医疗建议。")


# ---------------- 工具函数 ----------------
APP_VERSION = "v2.3.0"

CHANGELOG = [
    {
        "version": "v2.3.0",
        "date": "2026-09-28",
        "tag": "最新版本",
        "items": [
            ("🌐", "翻译引擎可插拔（腾讯云 TMT）", "侧边栏新增翻译设置：配置腾讯云机器翻译的 SecretId/SecretKey 后，中文翻译走腾讯接口（每月 500 万字符免费额度，质量更高），彻底解决 MyMemory 免费额度不够对外发行的问题；未配置或调用失败时自动回退 MyMemory，行为与旧版一致。云端可在 Streamlit Secrets 中配置 TENCENT_SECRET_ID / TENCENT_SECRET_KEY"),
        ],
    },
    {
        "version": "v2.2.0",
        "date": "2026-09-27",
        "tag": "",
        "items": [
            ("🔎", "全文关键词搜索定位", "在原文定位区输入关键词（中英文均可，多个词空格分隔=同时包含），实时列出所有命中原句：所在章节、章节内句序、命中次数，关键词蓝色高亮"),
            ("🩹", "统计指标提取修复", "置信区间不再混入引文标记或截断（兼容 Lancet 中点小数 0·64）；百分比排除「95% CI」误抓；计数标签明确「全文 N 处 · 去重 M 种」"),
        ],
    },
    {
        "version": "v2.1.0",
        "date": "2026-09-27",
        "tag": "",
        "items": [
            ("📍", "摘要句子原文定位", "全文摘要的每一句都可回溯到原文出处：所在章节、章节内句序、带高亮的英文原句；中文翻译与英文原文对照展示，摘要不再「来路不明」"),
            ("🔢", "关键数值原文定位", "自动扫描全文的 P 值 / 95%CI / HR·OR·RR / 百分比 / 样本量 n / 均值±SD，逐类列出数值及其所在原句并高亮数值本身"),
            ("🤖", "LLM 总结也可溯源", "LLM 深度总结逐句匹配原文出处——中文总结靠数字与药名/指标名等术语跨语言对齐原文，匹配度不足时如实标注「未找到可靠对应」"),
        ],
    },
    {
        "version": "v2.0.0",
        "date": "2026-09-26",
        "tag": "",
        "items": [
            ("🎉", "v2.0.0 正式发行", "本版本为第一个对外发布的大版本，功能集齐：智能检索 → 全文抓取 → 章节摘要 → 数据分析 → 批量导出全链路"),
            ("📊", "批量统计表（Excel 三工作表）", "文献汇总 / 章节明细 / 统计指标，DOI、PubMed 直链、摘要预览、指标逐条示例值，打开即用"),
            ("🌐", "全文三通道抓取", "PMC 开放全文 → Unpaywall 开放副本 → 无头浏览器网页提取（带反拦截），免费能看的文献基本都能抓到"),
            ("⚙️", "后台任务与并行架构", "全文摘要与图表解析可同时进行；批量全文多线程并行抓取；NCBI 全局限流防封禁"),
            ("🔍", "搜索引擎升级", "主副关键词 AND/OR/NOT 组合、期刊筛选（全名自动转缩写）、作者国籍筛选、检索式实时预览"),
        ],
    },
    {
        "version": "v1.7.2",
        "date": "2026-09-26",
        "tag": "",
        "items": [
            ("📊", "批量统计表升级为 Excel 三工作表", "文献汇总 / 章节明细 / 统计指标，表头配色、冻结首行、自动筛选，打开即用"),
            ("🧾", "汇总表信息量大幅扩充", "新增 DOI、PubMed 直达链接、摘要章节数、摘要预览、全文字符数、统计指标汇总（如 P值×5；95%CI×3）、状态红绿标注"),
            ("📐", "章节明细与指标逐条成表", "每篇文献各章节的词数/字符数分布一张表，P 值、置信区间等统计指标连同示例值逐条列出"),
        ],
    },
    {
        "version": "v1.7.1",
        "date": "2026-09-26",
        "tag": "",
        "items": [
            ("🌐", "全文抓取第三通道：网页提取兜底", "PMC 双通道失败时自动改用无头浏览器打开 Unpaywall 开放副本 / DOI 出版社页，直接提取渲染正文（非截图识别，零损失）。内置反拦截（正常 UA + 隐藏自动化特征）与正文清理（掐导航、去参考文献）"),
            ("🧹", "失败原因更透明", "付费墙文献会明确提示：免费渠道（含网页截图）均无法获取其全文，如 MMR 那篇 Elsevier 文章经 Unpaywall 确认无任何合法开放副本"),
            ("✅", "修复批量任务 TypeError", "批量结果返回结构与页面消费端不一致导致的崩溃（list 按 dict 解析），已端到端实测修复"),
        ],
    },
    {
        "version": "v1.7.0",
        "date": "2026-09-26",
        "tag": "",
        "items": [
            ("🚀", "批量全文摘要（新页面）", "从检索结果或收藏中勾选多篇文献，多线程并行抓取 PMC 开放全文并逐篇生成章节化摘要与数据分析；单篇失败不影响整批。内置 NCBI 限流保护（约 3 请求/秒），并行再快也不会触发封禁"),
            ("⬇️", "一键导出摘要与分析", "批量结果一键导出：完整 Markdown（每篇含章节化摘要、词数统计、高频关键词、统计指标）+ CSV 统计表（Excel 直接打开，UTF-8 BOM 不乱码）"),
            ("⚡", "全文摘要与图表解析可同时进行", "智能摘要页的全文抓取与图表抓取改为后台任务执行：点击后页面立即可操作，进度实时显示在左侧「后台任务」，完成自动刷新展示——两项功能可同时跑，互不阻塞"),
            ("🧵", "并行架构升级", "新增轻量后台任务管理器（工作线程 + UI 轮询），所有耗时操作不再冻结页面"),
        ],
    },
    {
        "version": "v1.6.0",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🔎", "搜索引擎升级：主副关键词组合", "主关键词 + 副关键词自由组合，支持 AND（同时包含）/ OR（任一包含）/ NOT（排除）三种逻辑，检索式实时预览"),
            ("📰", "来源期刊筛选", "按期刊过滤检索结果，支持全名（Nature Medicine）或缩写（Nat Med）：全名经本地主流期刊词典 + NLM Catalog 自动转为 MEDLINE 缩写，解决全名检索为 0 条的问题"),
            ("🌍", "作者国籍 / 地区筛选", "新增 20 个常用国家/地区下拉（按作者单位 Affiliation 匹配），可结合日期范围精准定位某国团队的研究"),
            ("🛠", "检索式优先级修复", "OR 逻辑与期刊/国籍/日期过滤组合时自动整体加括号，避免 PubMed 运算符优先级（AND 高于 OR）把过滤条件吞进 OR 分支导致结果错误"),
        ],
    },
    {
        "version": "v1.5.1",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🌐", "英文摘要不再混入中文小标题", "全文摘要结果同时保留原始章节标题与中文标题：中文模式用中文小标题，英文模式用原文标题（Background / Methods / Results 等），切换语言无需重新生成"),
            ("🎨", "智能摘要页输入区分区强化", "摘要语言与长度并排放入浅青色参数子面板，控件标题加粗、组间距加大，来源选择 / 参数设置 / 生成按钮三段更分明"),
        ],
    },
    {
        "version": "v1.5.0",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🖥️", "新增 Windows 桌面版", "PyInstaller + pywebview 打包为独立应用：双击 exe 起本地服务并弹出独立窗口，无需安装 Python；数据（收藏 / 历史 / 图表缓存）写入 %APPDATA%\\MedLitSummary，程序目录只读"),
            ("🔧", "数据目录支持环境变量覆盖", "storage 与图表缓存路径支持 MEDLIT_DATA_DIR 环境变量重定向，为打包发行做准备；网页版行为不变"),
        ],
    },
    {
        "version": "v1.4.1",
        "date": "2026-09-25",
        "items": [
            ("🔗", "修复：有时无法解析出 PDF 全文", "全文抓取升级为双通道：NCBI efetch 无正文（非 OA 文献返回 200 + 错误 XML）时自动改走 Europe PMC 全文 XML，两源互补；正文开头未分章节的段落不再丢失；全部失败时给出具体原因与建议（该文献可能不属于 PMC 开放获取子集，可走 PDF / DOI 链接），不再静默返回空。已批量实测 13 篇文献全部解析成功"),
            ("🎨", "各功能页界面与主页风格协同", "检索结果、摘要来源、全文分析、图表解析、收藏列表、检索记录、更新日志等区块标题统一为主页的竖条标题样式；摘要 / LLM 总结 / 图表概括结果卡片化呈现；输入框、下拉、滑杆、指标卡、提示框统一主题色与圆角；收藏页新增统计卡（收藏数 / 可用摘要数）"),
        ],
    },
    {
        "version": "v1.4.0",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🏠", "主页焕新（homepage-design 分支合并）", "简约清新视觉主题：Hero 区配内联 SVG 插画、核心能力卡片点击直达、快速开始三步引导、数据概览与最近动态；侧边栏升级为图标导航（streamlit-option-menu），全站按钮 / 卡片 / 步骤条统一新样式"),
        ],
    },
    {
        "version": "v1.3.6",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🤫", "修复：LLM 结果导出了 deepseek 的思考过程", "推理模型把输出额度全部用于思考、正文为空时，旧版会把思考过程（reasoning_content）当结果展示。现改为：自动加大输出额度重试一次，仍失败则给出可操作提示；思考过程绝不作为结果输出。已实测 deepseek-flash 多图视觉分析输出干净"),
        ],
    },
    {
        "version": "v1.3.5",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("📑", "修复：全文摘要章节输出乱序", "章节原按得分高低输出（讨论→结果→引言→方法）。现名额分配仍按章节权重，但展示顺序改为遵循论文逻辑（引言→方法→结果→讨论→结论）；同时清理抽取句开头的承接连接词（此外，/然而，/因此，…），避免脱离上下文后语义悬空"),
            ("🧹", "关键词去泛词 + 译文校验", "percentage change、difficult、use 等无主题区分度的泛词不再入选；关键词译文增加合理性校验，拒绝翻译记忆库返回的整句垃圾（如打出这样的球很不容易）与词典释义串"),
        ],
    },
    {
        "version": "v1.3.4",
        "date": "2026-09-25",
        "tag": "",
        "items": [
            ("🌐", "网络报错中文化 + 重试加固", "NCBI 请求重试升级为指数退避（2/4/6/8 秒），可度过瞬时 DNS 污染窗口；检索失败等网络异常改为可操作的中文提示（SSL 证书校验失败 / 连接失败 / 超时分别说明原因与处理建议），技术详情折叠展示"),
        ],
    },
    {
        "version": "v1.3.3",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🖼", "修复：非开放获取文献图表抓取失败", "Europe PMC 图片包对非 OA / 作者手稿文献不可用（实测 PMC5727893 即此场景）。新增三级兜底：逐图接口 → 无头浏览器抓取原图 → 图表页整页截图（带失败重试与本地缓存），实测 4/4 全部成功"),
            ("🌐", "关键句支持中文翻译", "「句子重要性得分」中的关键句在输出语言为中文时自动翻译（带缓存），(Fig. 2) 等引用一并正确转换"),
        ],
    },
    {
        "version": "v1.3.2",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🔬", "修复：视觉分析对推理模型输出为空", "deepseek-flash 等推理模型的思考过程（reasoning）也计入 max_tokens，复杂看图请求会耗尽额度导致正文为空——现提高 token 上限至 8000，且正文为空时自动回退显示推理内容；已实测 deepseek-flash 看图分析正常"),
            ("💡", "提示更新", "视觉分析按钮与错误提示标注 deepseek-flash 为可用模型（已实测支持图片输入）"),
        ],
    },
    {
        "version": "v1.3.1",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🐛", "修复：摘要结果 KeyError('source_count') 崩溃", "长时间运行的服务热重载界面但缓存旧版引擎模块导致键缺失——改为兜底读取，并重启本地服务"),
        ],
    },
    {
        "version": "v1.3.0",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🔬", "新功能：LLM 视觉分析图表图片", "新增「用 LLM 视觉分析图表图片」——把 PMC 图表图片缩放编码后连同说明文字一起送多模态模型（如 gpt-4o / qwen-vl），模型直接看图解读数据趋势与结论，不再只依赖说明文字；需配置支持图片输入的模型"),
            ("🧮", "修复：摘要句子数与所选档位不符", "冗余句过滤可能少给句子——现改为三轮回填（严格去冗余 → 放宽阈值 → 按分数补齐），原文句子数足够时输出句数必然与所选档位一致；原文本身不足档位句数时，结果旁会明示「实际输出 N 句（原文共 M 句，已全部纳入）」"),
            ("🈶", "修复：部分关键词未翻译为中文", "免费翻译接口对部分词会原样返回英文、或返回繁体（如 stem cells → 幹細胞）——现在会扫描接口的候选译文兜底，并将繁体自动转为简体（幹細胞→干细胞）"),
        ],
    },
    {
        "version": "v1.2.3",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🧩", "修复：摘要出现「（图」等无意义碎片", "切句时缩写保护失效——句中引用如「(Fig. 3)」会在 Fig. 处被误切断，留下悬空的「（图」，后半截被丢弃；现已正确保护 Fig. / et al. / e.g. 等缩写，超长句翻译分段也改为优先在标点处断开"),
            ("🈶", "修复：关键词未翻译为中文", "输出语言选「中文」时，摘要页与全文分析的关键词现自动翻译为中文（内置 60+ 高频医学术语对照表优先命中，避免免费接口的词典误译如 cell→單元格；未命中走翻译接口，失败回退英文）"),
            ("🔧", "配套增强", "关键词译文带缓存，同一词不重复请求；翻译接口限速保护避免触发限制"),
        ],
    },
    {
        "version": "v1.2.2",
        "date": "2026-09-24",
        "tag": "",
        "items": [
            ("🈶", "修复：全文摘要小标题语言错误", "「【Background】【Methods】」等英文章节小标题现统一显示为「背景 / 方法 / 结果 / 讨论 / 结论」等规范中文标题（支持带编号章节如 1. Introduction），且翻译时只翻译正文、不再把小标题混入翻译接口，输出语言不再错乱"),
            ("🖼", "修复：无法抓取图表", "Europe PMC 对部分文献返回「200 + XML 错误体」而非图片包，旧版把错误体当图片包缓存导致永远报错——现在校验有效图片包后才落盘、坏缓存自动删除重下，并对非开放获取文献给出明确中文提示"),
            ("🔧", "配套增强", "图片文件名匹配升级为大小写不敏感 + 归一化模糊匹配（fig1 ↔ F1.jpg 也能对上）；NCBI 接口请求增加自动重试，网络抖动不再直接失败；图表信息概括在选「中文」输出时同样自动翻译"),
        ],
    },
    {
        "version": "v1.2.1",
        "date": "2026-09-23",
        "tag": "",
        "items": [
            ("🔑", "优化：关键词提取质量", "新增完整英文停用词表（功能词 / 代词 / 学术套话，如 the、her、new、study、figure 等一律不再入选）、名词复数归并（mutations 与 mutation 不再重复占位）、自动识别 overall survival、pd-l1 expression 这类医学短语；关键词后标注出现次数"),
            ("🈶", "中文关键词升级", "改用极大频繁 n-gram 提取，输出「总生存期」这样的完整术语，不再出现「存期」「总生」半截词"),
            ("📉", "配套优化", "摘要页关键词与全文关键词统一走同一套过滤与加权逻辑，全文分析与摘要结果口径一致"),
        ],
    },
    {
        "version": "v1.2.0",
        "date": "2026-09-21",
        "tag": "",
        "items": [
            ("📚", "全文摘要（重大更新）", "对有 PMC 开放全文的文献，抓取论文正文（引言/方法/结果/讨论，数万字符）做章节化摘要，不再局限于摘要本身"),
            ("📊", "全文数据分析面板", "全文词数统计、各章节篇幅分布图表、高频关键词提取、P 值 / 百分比 / 风险比 / 置信区间 / 样本量等统计指标自动提取"),
            ("🈶", "全文摘要中文输出", "英文全文摘要自动翻译为中文（延续 v1.1.0 的翻译能力）"),
        ],
    },
    {
        "version": "v1.1.1",
        "date": "2026-09-21",
        "tag": "",
        "items": [
            ("🧮", "修复：文本长度统计不准", "字符统计不再把空格和换行计入，英文文献同时显示词数，两种口径一目了然"),
            ("🧠", "优化：摘要算法全面升级", "新增结构区块权重（Results/Conclusion 优先）、TF-IDF 词权重、标题相关性、数字结果句加分、冗余句去除，提取的核心信息更关键"),
        ],
    },
    {
        "version": "v1.1.0",
        "date": "2026-09-21",
        "tag": "",
        "items": [
            ("🐛", "修复：内置摘要不支持中文", "英文文献的抽取式摘要现会自动翻译为中文输出（选择「中文」输出语言时自动生效），翻译失败时回退英文原句并提示"),
        ],
    },
    {
        "version": "v1.0.1",
        "date": "2026-09-21",
        "tag": "",
        "items": [
            ("📏", "摘要长度可选", "短（约3句）/ 中（约6句）/ 长（约10句）三档自由切换，抽取式摘要与 LLM 总结均支持"),
            ("📎", "原文文档链接", "检索结果与摘要页附加 PDF 全文（PMC）、DOI 原文、PubMed 页面直达链接"),
            ("🖼", "文献图表解析", "抓取 PMC 开放全文中的图表图片与说明文字：图片视图逐图展示、内置引擎自动概括、LLM 逐图解读，图片本地缓存加速"),
        ],
    },
    {
        "version": "v1.0.0",
        "date": "2026-09-21",
        "tag": "首个正式版",
        "items": [
            ("🔍", "PubMed 智能检索", "关键词 / 作者 / 日期过滤，相关性或最新排序，拼写纠错建议"),
            ("⚡", "抽取式智能摘要", "词频-位置加权引擎，离线可用，关键词提取与句子得分展示"),
            ("🤖", "LLM 深度总结", "可选配置 OpenAI 兼容接口，输出结构化中文总结"),
            ("⭐", "收藏与历史", "收藏管理、Markdown 导出、检索历史自动留存"),
        ],
    },
]


def render_changelog():
    for i, rel in enumerate(CHANGELOG):
        badge_color = "#2e9e8f" if i == 0 else "#8a97a5"
        tag_html = ""
        if rel.get("tag"):
            tag_html = (
                f'<span style="background:{badge_color}; color:#fff; border-radius:12px;'
                f'padding:2px 12px; font-size:0.8rem;">{rel["tag"]}</span>'
            )
        with st.container(border=True):
            badge_html = (
                f'<span style="background:{badge_color}; color:#fff; border-radius:12px;'
                f'padding:2px 12px; font-size:0.8rem; margin:0 4px;">{rel["tag"]}</span>'
                if rel.get("tag")
                else ""
            )
            st.markdown(
                '<div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">'
                f"<span style=\"font-size:1.25rem; font-weight:700;\">{rel['version']}</span>"
                f"{badge_html}"
                f"<span style=\"color:#888; font-size:0.85rem;\">{rel['date']}</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            for icon, title, desc in rel["items"]:
                st.markdown(f"- {icon} **{title}**：{desc}")


def article_card(a: dict, show_actions: bool = True):
    with st.container(border=True):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"**{a['title']}**")
            meta = []
            if a.get("authors"):
                meta.append(", ".join(a["authors"][:4]) + (" 等" if len(a["authors"]) > 4 else ""))
            if a.get("journal"):
                meta.append(f"*{a['journal']}*")
            if a.get("year"):
                meta.append(a["year"])
            if meta:
                st.caption(" · ".join(meta))
            if a.get("pmid"):
                links = pubmed.get_pdf_links(a)
                link_md = "  |  ".join(f"[{name}]({u})" for name, u in links)
                st.caption(f"PMID: {a['pmid']}  |  {link_md}")
        with col2:
            if show_actions and a.get("pmid"):
                if storage.is_favorited(a["pmid"]):
                    if st.button("取消收藏", key=f"unfav_{a['pmid']}"):
                        storage.remove_favorite(a["pmid"])
                        st.rerun()
                    st.caption("⭐ 已收藏")
                elif st.button("⭐ 收藏", key=f"fav_{a['pmid']}"):
                    storage.add_favorite(a)
                    st.toast("已加入收藏", icon="⭐")
                    st.rerun()
        if a.get("abstract"):
            with st.expander("📖 摘要全文", expanded=False):
                st.write(a["abstract"])


def ensure_results():
    return st.session_state.get("results", [])


# ---------------- 首页组件 ----------------
def sec_title(text: str, hint: str = ""):
    st.markdown(
        f'<div class="sec-title"><div class="bar"></div><div class="tx">{text}</div>'
        f'<div class="hint">{hint}</div></div>',
        unsafe_allow_html=True,
    )


# ---------------- 原文定位渲染（v2.1.0） ----------------
def _render_located_sentences(index: list[dict], sentences: list[str], show_heading_tags: bool = True):
    """逐句展示摘要句的原文出处：章节 · 句序 · 高亮原句（数值高亮）"""
    import html as _h

    for sent in sentences:
        s = sent.strip()
        if len(s) < 12:  # 过短的多为标题/列表行，不做定位
            continue
        if s.startswith(("#", "|", "- [ ]")):
            continue
        matches = locate.locate_sentence(s, index)
        if matches:
            m = matches[0]
            sc = float(m.get("score", 0.0))
            sc_tag = (
                f'<span class="loc-score">{"精确" if sc >= 0.99 else f"匹配 {sc:.2f}"}</span>'
                if show_heading_tags else ""
            )
            st.markdown(
                f'<div class="loc-sent"><span class="loc-tag">📍 {_h.escape(m["section"]) or "正文"} · 第 {m["pos"] + 1} 句</span>{sc_tag}'
                f'<br>{locate.highlight_values(m["text"])}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="loc-sent"><span class="loc-tag">⚠️ 未找到可靠原文对应（可能为模型改写 / 概括）</span>'
                f'<br>{_h.escape(s)}</div>',
                unsafe_allow_html=True,
            )


def _render_value_locator(index: list[dict]):
    """关键数值 → 原文出处：按类型分组，数值在原句中高亮"""
    vals = locate.find_values(index)
    if not vals:
        st.caption("未在全文中扫描到常见统计数值（P 值 / CI / 百分比等）。")
        return
    total = sum(len(v) for v in vals.values())
    st.caption(f"共定位 {total} 处关键数值，每类最多展示 40 处；数值在原句中以橙色高亮。")
    for vtype, items in vals.items():
        with st.expander(f"{vtype} — 全文 {len(items)} 处", expanded=False):
            for it in items:
                st.markdown(
                    f'<div class="loc-sent"><span class="loc-tag">📍 {it["section"] or "正文"} · 第 {it["pos"] + 1} 句</span>'
                    f'{locate.highlight_values(it["sentence"])}</div>',
                    unsafe_allow_html=True,
                )


def _render_keyword_search(index: list[dict]):
    import html as _h

    kw_q = st.text_input(
        "输入关键词定位原文（中英文均可；多个词用空格分隔 = 需同时包含）",
        key="kw_locate_q",
        placeholder="例如：metformin HbA1c / 低血糖 / 95% CI",
    )
    q = (kw_q or "").strip()
    if not q:
        st.caption("输入后在全文原句中实时定位：显示所在章节、章节内句序与命中次数，关键词蓝色高亮。")
        return
    terms = locate.parse_terms(q)
    hits = locate.search_keyword(index, q, limit=80)
    if not hits:
        st.info(f"全文原句中未找到同时包含「{'」和「'.join(terms) if len(terms) > 1 else terms[0]}」的内容。"
                "可尝试换用英文原词（正文多为英文）。")
        return
    total_occ = sum(h["count"] for h in hits)
    shown = hits[:50]
    st.caption(
        f"共 {len(hits)} 句命中、出现 {total_occ} 次"
        + (f"，已展示前 {len(shown)} 句" if len(hits) > len(shown) else "")
        + "；按原文出现顺序排列。"
    )
    for h in shown:
        st.markdown(
            f'<div class="loc-sent"><span class="loc-tag">📍 {_h.escape(h["section"]) or "正文"} · 第 {h["pos"] + 1} 句 · 命中 {h["count"]} 次</span>'
            f'<br>{locate.highlight_query(h["text"], terms)}</div>',
            unsafe_allow_html=True,
        )


def stat_card(label: str, value, unit: str = ""):
    st.markdown(
        f'<div class="stat-card"><div class="k">{label}</div>'
        f'<div class="v">{value}</div><div class="u">{unit}</div></div>',
        unsafe_allow_html=True,
    )


def hero_illustration() -> str:
    """首页插画：纯内联 SVG 线描，随主题配色，无外部资源依赖"""
    return """
<svg viewBox="0 0 340 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="文献检索与智能摘要示意图">
<defs>
<linearGradient id="hBlob" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="#d6f1ea"/><stop offset="100%" stop-color="#dbe9fa"/>
</linearGradient>
<linearGradient id="hDoc" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#f5fbfa"/>
</linearGradient>
<linearGradient id="hBar" x1="0" y1="1" x2="0" y2="0">
<stop offset="0%" stop-color="#2e9e8f"/><stop offset="100%" stop-color="#72cbbd"/>
</linearGradient>
</defs>
<circle cx="166" cy="126" r="104" fill="url(#hBlob)" opacity="0.5"/>
<circle cx="304" cy="46" r="15" fill="#dcecfb" opacity="0.8"/>
<circle cx="32" cy="200" r="10" fill="#d9f2ec" opacity="0.9"/>
<g transform="translate(52,42)">
<rect x="0" y="0" width="138" height="170" rx="16" fill="url(#hDoc)" stroke="#cfe7e3" stroke-width="1.6"/>
<rect x="22" y="30" width="56" height="10" rx="5" fill="#8ed3c6"/>
<rect x="22" y="52" width="94" height="6" rx="3" fill="#e2eef2"/>
<rect x="22" y="66" width="82" height="6" rx="3" fill="#e2eef2"/>
<rect x="22" y="80" width="94" height="6" rx="3" fill="#e2eef2"/>
<rect x="22" y="94" width="62" height="6" rx="3" fill="#e2eef2"/>
<rect x="22" y="118" width="94" height="6" rx="3" fill="#e2eef2"/>
<rect x="22" y="132" width="74" height="6" rx="3" fill="#e2eef2"/>
<g transform="translate(22,152)">
<rect x="0" y="-16" width="9" height="16" rx="3" fill="url(#hBar)"/>
<rect x="15" y="-26" width="9" height="26" rx="3" fill="url(#hBar)" opacity="0.82"/>
<rect x="30" y="-11" width="9" height="11" rx="3" fill="url(#hBar)" opacity="0.6"/>
<rect x="45" y="-21" width="9" height="21" rx="3" fill="url(#hBar)" opacity="0.72"/>
</g>
</g>
<g transform="translate(178,132)">
<circle cx="0" cy="0" r="42" fill="#ffffff" stroke="#2e9e8f" stroke-width="4.5"/>
<line x1="30" y1="30" x2="58" y2="58" stroke="#2e9e8f" stroke-width="9" stroke-linecap="round"/>
<path d="M-22 12 L-8 -6 L4 6 L18 -18" fill="none" stroke="#3d8fd1" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="-8" cy="-6" r="3.2" fill="#3d8fd1"/>
<circle cx="18" cy="-18" r="3.2" fill="#3d8fd1"/>
</g>
<g transform="translate(200,38)">
<rect x="0" y="0" width="92" height="30" rx="15" fill="#ffffff" stroke="#dcecea" stroke-width="1.4"/>
<text x="46" y="20" text-anchor="middle" font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="12.5" font-weight="600" fill="#2e8f83">P &lt; 0.001</text>
</g>
<g transform="translate(248,190)">
<rect x="0" y="0" width="78" height="30" rx="15" fill="#ffffff" stroke="#dcecea" stroke-width="1.4"/>
<text x="39" y="20" text-anchor="middle" font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="12.5" font-weight="600" fill="#3d8fd1">HR 0.59</text>
</g>
</svg>
"""


FEATURES = [
    {
        "icon": "🔍",
        "bg": "#eaf7f4",
        "title": "文献检索",
        "desc": "接入 PubMed 官方接口，支持关键词、作者、发表日期过滤与拼写纠错，结果可直达原文页面。",
        "btn": "去检索",
        "target": "文献检索",
    },
    {
        "icon": "📝",
        "bg": "#eef6fd",
        "title": "智能摘要",
        "desc": "内置抽取式引擎离线可用，按章节权重提取关键句；配置 LLM 后可生成结构化深度总结。",
        "btn": "去摘要",
        "target": "智能摘要",
    },
    {
        "icon": "📊",
        "bg": "#f3f0fd",
        "title": "全文数据分析",
        "desc": "抓取论文正文，输出章节篇幅分布与高频关键词，自动提取 P 值、样本量、风险比等指标。",
        "btn": "去分析",
        "target": "智能摘要",
    },
    {
        "icon": "🖼",
        "bg": "#fdf4ea",
        "title": "图表解读",
        "desc": "解析全文中的图表图片与说明文字，逐图视图展示并自动概括，快速把握研究图示信息。",
        "btn": "去解读",
        "target": "智能摘要",
    },
]


def render_home():
    favs = storage.list_favorites()
    hist_all = storage.list_history(200)
    results = ensure_results()
    pmc_count = len([a for a in results if a.get("pmcid")])

    # ---------- Hero ----------
    with st.container(key="hero"):
        left, right = st.columns([1.32, 1], gap="large")
        with left:
            st.markdown(
                """
                <div class="hero-wrap">
                    <span class="hero-pill">🩺 医学文献工作台 · 免费公开数据源</span>
                    <h1>从 PubMed 检索<br>到论文全文智能摘要</h1>
                    <p class="hero-sub">输入一个关键词，检索、正文抓取、结构化摘要、图表解读与数据分析一次完成，不必在多个网站之间来回切换。</p>
                    <div class="hero-tags">
                        <span>PubMed 官方数据源</span>
                        <span>离线抽取式摘要</span>
                        <span>论文全文解析</span>
                        <span>统计指标提取</span>
                        <span>LLM 深度总结（可选）</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(f'<div class="hero-svg-box">{hero_illustration()}</div>', unsafe_allow_html=True)
        b1, b2, b3, _sp = st.columns([1, 1, 1, 1.7])
        with b1:
            st.button("🔍 开始检索", type="primary", width="stretch",
                      on_click=goto, args=("文献检索",))
        with b2:
            st.button("📝 生成摘要", width="stretch",
                      on_click=goto, args=("智能摘要",))
        with b3:
            st.button("📋 更新日志", width="stretch",
                      on_click=goto, args=("更新日志",))

    # ---------- 数据概览 ----------
    s1, s2, s3, s4 = st.columns(4, gap="medium")
    with s1:
        stat_card("已收藏文献", len(favs), "篇 · 支持 Markdown 导出")
    with s2:
        stat_card("累计检索次数", len(hist_all), "次 · 历史自动留存")
    with s3:
        stat_card("当前结果集", len(results), f"篇 · 其中 {pmc_count} 篇有开放全文")
    with s4:
        stat_card("当前版本", APP_VERSION, "新功能见「更新日志」")

    st.write("")

    # ---------- 核心能力 ----------
    sec_title("核心能力", "点击卡片按钮直接进入对应功能")
    cols = st.columns(4, gap="medium")
    for col, feat in zip(cols, FEATURES):
        with col:
            with st.container(key=f"featcard_{feat['target']}_{feat['title']}"):
                st.markdown(
                    f'<div class="fc-icon" style="background:{feat["bg"]}">{feat["icon"]}</div>'
                    f'<div class="fc-title">{feat["title"]}</div>'
                    f'<div class="fc-desc">{feat["desc"]}</div>',
                    unsafe_allow_html=True,
                )
                st.button(
                    feat["btn"], key=f"featbtn_{feat['title']}", width="stretch",
                    on_click=goto, args=(feat["target"],),
                )

    st.write("")

    # ---------- 快速开始 ----------
    sec_title("快速开始", "三步完成一次文献分析")
    STEPS = [
        ("1", "检索文献", "在「文献检索」输入英文关键词（如 immunotherapy lung cancer），按需筛选年份与排序方式。"),
        ("2", "生成摘要", "在「智能摘要」选择文献与长度档位，点「生成抽取式摘要」，英文结果会自动译成中文。"),
        ("3", "深入解读", "若文献带有 PMC 开放全文，可继续做全文摘要、数据分析与图表解读，挖掘统计指标。"),
    ]
    scols = st.columns(3, gap="medium")
    for col, (num, title, desc) in zip(scols, STEPS):
        with col:
            st.markdown(
                f'<div class="step"><div class="num">{num}</div>'
                f'<div class="t">{title}</div><div class="d">{desc}</div></div>',
                unsafe_allow_html=True,
            )

    st.write("")

    # ---------- 最近动态 ----------
    sec_title("最近动态", "")
    r1, r2 = st.columns(2, gap="medium")
    with r1:
        with st.container(border=True):
            st.markdown("**🕘 最近检索**")
            if hist_all:
                for h in hist_all[:4]:
                    st.caption(f"{h['time']} — {h['query']}（{h['n_results']} 条结果）")
            else:
                st.caption("暂无检索记录，点上面「开始检索」试试。")
    with r2:
        with st.container(border=True):
            st.markdown("**⭐ 最近收藏**")
            if favs:
                for f in favs[:4]:
                    st.caption(f"{f.get('saved_at', '')} — {f.get('title', '')[:52]}")
            else:
                st.caption("暂无收藏，检索结果点「⭐ 收藏」即可保存。")


# ---------------- 页面：首页 ----------------
if page == "系统首页":
    render_home()

# ---------------- 页面：文献检索 ----------------
elif page == "文献检索":
    # 作者国籍/地区（PubMed 按作者单位 Affiliation 匹配英文国名）
    COUNTRIES = [
        ("不限", ""), ("中国", "China"), ("美国", "United States"), ("英国", "United Kingdom"),
        ("日本", "Japan"), ("韩国", "South Korea"), ("德国", "Germany"), ("法国", "France"),
        ("意大利", "Italy"), ("西班牙", "Spain"), ("加拿大", "Canada"), ("澳大利亚", "Australia"),
        ("印度", "India"), ("巴西", "Brazil"), ("荷兰", "Netherlands"), ("瑞士", "Switzerland"),
        ("瑞典", "Sweden"), ("土耳其", "Turkey"), ("伊朗", "Iran"), ("新加坡", "Singapore"),
    ]
    country_map = dict(COUNTRIES)

    header("🔍 文献检索", "主副关键词组合 · 来源期刊 / 作者 / 国籍筛选 · 日期范围与排序")
    col_q, col_n = st.columns([4, 1])
    with col_q:
        keyword = st.text_input("主关键词（必填）", placeholder="例如：immunotherapy lung cancer", key="kw")
    with col_n:
        retmax = st.select_slider("返回条数", options=[5, 10, 20, 30, 50], value=10)

    with st.expander("⚙️ 高级检索条件"):
        s1, s2 = st.columns([3, 2])
        with s1:
            secondary = st.text_input(
                "副关键词（可选）",
                placeholder="例如：PD-1 biomarker；与主关键词按下方逻辑组合",
            )
        with s2:
            logic = st.radio(
                "组合逻辑",
                ["AND（同时包含）", "OR（任一包含）", "NOT（排除）"],
                horizontal=True,
                index=0,
            )
        st.caption(
            "组合逻辑说明：**AND** 结果须同时含主副关键词 · "
            "**OR** 含其一即可 · **NOT** 排除含副关键词的文献"
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            author = st.text_input("作者（可选）", placeholder="例如：Smith J")
        with c2:
            journal = st.text_input(
                "来源期刊（可选）",
                placeholder="例如：Nature Medicine 或 N Engl J Med",
                help="支持全名或缩写，全名会在检索时自动转换为 MEDLINE 缩写",
            )
        with c3:
            country_zh = st.selectbox(
                "作者国籍 / 地区（可选，按作者单位匹配）",
                [zh for zh, _ in COUNTRIES],
                index=0,
            )
        d1, d2, d3 = st.columns(3)
        with d1:
            start_date = st.text_input("起始日期 YYYY/MM/DD", placeholder="2022/01/01")
        with d2:
            end_date = st.text_input("结束日期 YYYY/MM/DD", placeholder="2026/09/21")
        with d3:
            sort_opt = st.radio(
                "排序方式",
                ["按相关性", "按发表时间（最新优先）"],
                horizontal=True,
            )

    # 检索式实时预览
    logic_key = "AND" if logic.startswith("AND") else ("OR" if logic.startswith("OR") else "NOT")
    if keyword.strip():
        st.caption(
            "检索式预览：`"
            + pubmed.build_query(
                keyword, secondary, logic_key, author, journal, country_map[country_zh], start_date, end_date
            )
            + "`"
        )

    if st.button("🔍 开始检索", type="primary", use_container_width=True):
        if not keyword.strip():
            st.warning("请输入主关键词")
        else:
            journal_input = journal.strip()
            if journal_input:
                # PubMed [Journal] 字段只匹配 MEDLINE 缩写，全名需先经 NLM Catalog 解析
                with st.spinner("正在解析期刊名称……"):
                    journal_ta = pubmed.resolve_journal_ta(journal_input)
                if journal_ta != journal_input:
                    st.caption(f"期刊「{journal_input}」→ 检索用缩写「{journal_ta}」")
            else:
                journal_ta = ""
            query = pubmed.build_query(
                keyword, secondary, logic_key, author, journal_ta, country_map[country_zh], start_date, end_date
            )
            with st.spinner("正在检索 PubMed ..."):
                try:
                    results = pubmed.search_and_fetch(
                        query,
                        retmax=retmax,
                        sort="relevance" if sort_opt.startswith("按相关性") else "pub_date",
                    )
                except Exception as e:
                    st.error(f"检索失败：{pubmed.friendly_error(e)}")
                    with st.expander("技术详情"):
                        st.code(str(e)[:500])
                    results = []
            st.session_state["results"] = results
            st.session_state["last_query"] = query
            if results:
                storage.add_history(query, len(results))

    # 拼写建议
    if keyword.strip() and not ensure_results():
        for s in pubmed.mesh_suggest(keyword):
            st.info(f"💡 未找到匹配结果，是否想检索：**{s}**？")

    results = ensure_results()
    if st.session_state.get("last_query"):
        sec_title("检索结果", f"共 {len(results)} 篇")
        st.caption(f"检索式：`{st.session_state['last_query']}`")
    for a in results:
        article_card(a)
    if not results and st.session_state.get("last_query"):
        st.info("没有检索到文献，试试更宽泛的关键词。")


# ---------------- 页面：智能摘要 ----------------
elif page == "智能摘要":
    header("📝 智能摘要", "抽取式摘要 · 全文摘要与数据分析 · 图表解读 · 可选 LLM 深度总结")
    sec_title("1️⃣ 选择摘要来源", "从最近检索结果中选择，或直接粘贴文本")
    with st.container(key="step-card"):
        source = st.radio(
            "来源",
            ["从最近检索结果中选择", "直接粘贴文本 / 摘要"],
            horizontal=True,
        )
        text = ""
        chosen_title = ""
        chosen_article = None
        run_ext = run_llm = False  # 无文本时保持未触发，供卡片外的结果渲染判断
        if source == "从最近检索结果中选择":
            results = [a for a in ensure_results() if a.get("abstract")]
            fav_results = [a for a in storage.list_favorites() if a.get("abstract")]
            options = [f"{a['title'][:60]}..." for a in results] + [f"⭐ {a['title'][:55]}..." for a in fav_results]
            pool = results + fav_results
            if not pool:
                st.info("暂无可用文献，请先在「文献检索」页检索，或粘贴文本。")
            else:
                idx = st.selectbox("选择文献", range(len(pool)), format_func=lambda i: options[i])
                text = pool[idx]["abstract"]
                chosen_title = pool[idx]["title"]
                chosen_article = pool[idx]
        else:
            pasted = st.text_area("粘贴文献摘要或全文片段", height=200, placeholder="在此粘贴英文或中文医学文献摘要……")
            text = pasted
            chosen_title = "（自定义文本）"

        # 文献全文文档链接
        if chosen_article:
            doc_links = pubmed.get_pdf_links(chosen_article)
            if doc_links:
                st.markdown("📎 **原文文档**：" + "  ·  ".join(f"[{n}]({u})" for n, u in doc_links))

        if text.strip():
            # 统计口径修正：字符数不含空白，英文按词计数
            clean = re.sub(r"\s+", "", text)
            words = len(re.findall(r"[A-Za-z][A-Za-z\-']*|[\u4e00-\u9fff]", text))
            st.caption(f"文本长度：{len(clean):,} 字符（不含空格换行） · 约 {words:,} 词")
            with st.container(key="step-params"):
                pc1, pc2 = st.columns(2)
                lang = pc1.radio("摘要输出语言", ["中文", "英文"], horizontal=True, index=0)
                length_label = pc2.radio(
                    "摘要长度",
                    ["短（约 3 句）", "中（约 6 句）", "长（约 10 句）"],
                    horizontal=True,
                    index=1,
                )
            length_map = {"短（约 3 句）": 3, "中（约 6 句）": 6, "长（约 10 句）": 10}
            llm_length_map = {
                "短（约 3 句）": "简短，正文约 150 字以内",
                "中（约 6 句）": "中等，正文约 300 字",
                "长（约 10 句）": "详细，正文 500 字以上",
            }
            max_sents = length_map[length_label]

            c1, c2 = st.columns(2)
            run_ext = c1.button("⚡ 生成抽取式摘要（内置引擎，离线）", use_container_width=True)
            run_llm = c2.button(
                "🤖 生成 LLM 深度总结" + ("" if llm_ready else "（需先在侧边栏配置）"),
                use_container_width=True,
                disabled=not llm_ready,
            )
        else:
            if source == "直接粘贴文本 / 摘要":
                st.info("👆 粘贴文本后即可生成摘要")

    if run_ext:
        with st.spinner("正在分析文本……"):
            res = summarizer.extractive_summary(text, ratio=1.0, max_sentences=max_sents, title=chosen_title)
        summary_out = res["summary"]
        translated = False
        if lang == "中文" and summarizer.is_mostly_english(summary_out):
            with st.spinner("检测到英文摘要，正在自动翻译为中文……"):
                try:
                    summary_out = summarizer.translate_text(summary_out, "en|zh-CN")
                    translated = True
                except Exception as e:
                    st.warning(f"自动翻译失败（{e}），已显示英文原句。也可配置 LLM 获得中文深度总结。")
        lang_tag = " · 中文翻译" if translated else (" · 原文" if lang == "中文" else "")
        with st.container(key="panel_ext"):
            st.markdown(f"#### 📄 摘要结果 — {chosen_title}（{length_label}{lang_tag}）")
            # 明示实际句数：摘要原文不足所选档位时只能全部纳入，避免"句子数与选择不符"的困惑
            # 用 .get 兜底：正在运行的服务若仍缓存旧版引擎模块，也不会 KeyError 崩溃
            src_n = res.get("source_count", 0)
            picked_n = res.get("picked_count", 0)
            lack = src_n < max_sents
            st.caption(
                f"实际输出 {picked_n} 句（原文共 {src_n} 句"
                + ("，原文句子数少于所选档位，已全部纳入）" if lack else "）")
            )
            st.markdown(summary_out)
            key_terms = res["key_terms"]
            if lang == "中文" and key_terms:
                with st.spinner("正在翻译关键词为中文……"):
                    key_terms = summarizer.translate_keywords(key_terms[:8])
            if key_terms:
                st.markdown("**🔑 关键词**")
                st.markdown("".join(f'<span class="kw-chip">{k}</span>' for k in key_terms[:8]), unsafe_allow_html=True)
            with st.expander("📊 句子重要性得分（Top 语句）"):
                top_sents = [s for s, _ in res["scores"][:max_sents]]
                top_scores = [sc for _, sc in res["scores"][:max_sents]]
                if lang == "中文" and top_sents and summarizer.is_mostly_english(" ".join(top_sents)):
                    with st.spinner("正在翻译关键句为中文……"):
                        try:
                            top_sents = summarizer.translate_sentences(top_sents)
                        except Exception:
                            st.caption("（关键句自动翻译失败，已显示英文原文）")
                for s, sc in zip(top_sents, top_scores):
                    st.markdown(f"`{sc}` {s[:160]}")
            with st.expander("🔢 关键数值原文定位", expanded=False):
                _render_value_locator(locate.build_index([{"title": chosen_title or "原文", "text": text}]))
            st.download_button("⬇️ 导出摘要 (Markdown)", summary_out, file_name="summary.md")

    if run_llm:
        try:
            with st.spinner("LLM 正在生成深度总结……"):
                out = summarizer.llm_summary(
                    text,
                    st.session_state["llm_base"],
                    st.session_state["llm_key"],
                    st.session_state["llm_model"],
                    language=lang,
                    length_hint=llm_length_map[length_label],
                )
            with st.container(key="panel_llm"):
                st.markdown(f"#### 🤖 LLM 深度总结 — {chosen_title}（{length_label}）")
                st.markdown(out)
                with st.expander("📍 原文定位（逐句溯源）", expanded=False):
                    _render_located_sentences(
                        locate.build_index([{"title": chosen_title or "全文", "text": text}]),
                        summarizer.split_sentences(out),
                    )
                st.download_button("⬇️ 导出总结 (Markdown)", out, file_name="llm_summary.md")
        except Exception as e:
            st.error(f"LLM 调用失败：{e}（请检查 API 地址 / Key / 模型名，以及网络连通性）")

    # ---------------- 全文摘要与数据分析（v1.2.0） ----------------
    if chosen_article and chosen_article.get("pmcid"):
        st.divider()
        sec_title("2️⃣ 全文摘要与数据分析", f"基于开放全文（{chosen_article['pmcid']}；PMC 不可用时自动转网页提取兜底）——引言 / 方法 / 结果 / 讨论章节化摘要与统计分析")
        ft_max = st.select_slider("全文摘要句子数", options=[6, 8, 10, 12, 15], value=8)
        if st.button("📚 抓取全文并生成全文摘要", type="primary"):
            # v1.7.0：后台任务执行，页面不阻塞，可与图表解析同时进行
            _pmcid = chosen_article["pmcid"]
            if jobs.is_running(f"ft:{_pmcid}"):
                st.warning("该文献的全文摘要任务正在进行中，进度见左侧「后台任务」。")
            else:
                jobs.start("全文摘要", _ft_job, key=f"ft:{_pmcid}",
                           article={"pmcid": _pmcid, "doi": chosen_article.get("doi") or ""},
                           title=chosen_title, max_sentences=ft_max)
                st.toast("全文抓取已在后台开始，页面可继续操作", icon="⏳")

        if st.session_state.get("ft_summary"):
            ft = st.session_state["ft_summary"]
            an = st.session_state["ft_analytics"]
            summary_text = ft["summary"]

            # 小标题按所选语言取用：中文用 title_zh，英文用原始章节标题（v1.5.1 修复英文摘要混入中文小标题）
            if lang == "中文" and ft.get("sections"):
                parts, failed = [], False
                for p in ft["sections"]:
                    body = " ".join(p["sentences"])
                    if summarizer.is_mostly_english(body):
                        try:
                            body = summarizer.translate_text(body, "en|zh-CN")
                        except Exception:
                            failed = True
                    parts.append(f"【{p.get('title_zh') or p['title']}】 {body}")
                ft_out = "\n\n".join(parts)
                if failed:
                    st.warning("部分章节翻译失败，对应小节已保留英文原句。")
            elif ft.get("sections"):
                ft_out = "\n\n".join(
                    f"【{p['title']}】 " + " ".join(p["sentences"]) for p in ft["sections"]
                )
            else:
                ft_out = summary_text
            if str(st.session_state.get("ft_source", "")).startswith("网页"):
                st.info("🌐 本文不在 PMC 开放存档，正文经网页提取兜底获得（Unpaywall OA 副本 / 出版社页面），章节划分可能与原文略有出入。")
            sec_title("📚 全文摘要", f"共 {ft.get('used_sections', 0)} 个章节纳入摘要")
            with st.container(key="panel_ft"):
                st.markdown(ft_out)

            # ---- 原文定位（v2.1.0）：摘要句子与关键数值回溯原文 ----
            secs_loc = st.session_state.get("fulltext") or []
            if secs_loc:
                _loc_index = locate.build_index(secs_loc)
                _loc_stat = locate.index_stats(_loc_index)
                sec_title(
                    "📍 原文定位",
                    f"摘要句子与关键数值回溯原文（索引 {_loc_stat['sentences']} 句 / {_loc_stat['sections']} 章节）",
                )
                _render_keyword_search(_loc_index)
                with st.expander("📍 摘要句子 → 原文出处", expanded=False):
                    for p in ft.get("sections", []):
                        st.markdown(f"**【{p.get('title_zh') or p.get('title', '')}】**")
                        _render_located_sentences(_loc_index, p.get("sentences", []), show_heading_tags=False)
                with st.expander("🔢 关键数值 → 原文出处", expanded=False):
                    _render_value_locator(_loc_index)

            # ---- 数据分析面板 ----
            sec_title("📊 全文数据分析", "词数统计 · 章节篇幅 · 高频关键词 · 统计指标")
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("全文词数", f"{an['total_words']:,}")
            with m2:
                st.metric("全文字符", f"{an['total_chars']:,}")
            with m3:
                st.metric("章节数", len(an['section_stats']))

            st.markdown("**各章节篇幅分布**")
            chart_data = {s["title"][:30]: s["words"] for s in an["section_stats"]}
            st.bar_chart(chart_data)

            st.markdown("**🔑 全文高频关键词**（已过滤功能词与套话，括号内为出现次数）")
            kc = an.get("keyword_counts", {})
            ft_kws = an["keywords"]
            if lang == "中文" and ft_kws:
                with st.spinner("正在翻译关键词为中文……"):
                    ft_kws = summarizer.translate_keywords(ft_kws)
            st.markdown(
                "".join(
                    f'<span class="kw-chip">{k} <b>{kc[k]}</b></span>' if k in kc else f'<span class="kw-chip">{k}</span>'
                    for k in ft_kws
                ),
                unsafe_allow_html=True,
            )

            st.markdown("**🔬 关键统计指标提取**")
            if an["metrics"]:
                st.caption("「N 处」为全文出现总次数；下方展示去重后的不同取值（最多 12 种）。")
                for name, m in an["metrics"].items():
                    with st.expander(f"{name} — 全文 {m['count']} 处 · 去重 {len(m['samples'])} 种"):
                        st.markdown("".join(f'<span class="kw-chip">{v}</span>' for v in m["samples"]), unsafe_allow_html=True)
            else:
                st.caption("未在全文中提取到常见统计指标。")

            st.download_button("⬇️ 导出全文摘要 (Markdown)", ft_out, file_name="fulltext_summary.md")

    # ---------------- 文献图表解析（需要 PMC 开放全文） ----------------
    if chosen_article and chosen_article.get("pmcid"):
        st.divider()
        sec_title("3️⃣ 文献图表解析", f"图片视图 + 说明概括（{chosen_article['pmcid']}）")
        if st.button("🖼 加载并解析文献图表", type="secondary"):
            # v1.7.0：后台任务执行，可与全文摘要同时进行
            _pmcid_f = chosen_article["pmcid"]
            if jobs.is_running(f"fig:{_pmcid_f}"):
                st.warning("该文献的图表解析任务正在进行中，进度见左侧「后台任务」。")
            else:
                jobs.start("图表解析", _fig_job, key=f"fig:{_pmcid_f}", pmcid=_pmcid_f)
                st.toast("图表抓取已在后台开始，页面可继续操作", icon="⏳")
        figures = st.session_state.get("figures", [])
        if figures:
            n_shot = sum(1 for f in figures if f.get("is_screenshot"))
            st.success(f"共解析出 {len(figures)} 张图表" + (
                f"（其中 {n_shot} 张为浏览器截图——该文献非完全开放获取，原始图片包不可用，已自动用截图兜底）"
                if n_shot else ""))
            # 视图展示
            for i, f in enumerate(figures):
                with st.container(border=True):
                    st.markdown(f"**{f.get('label') or f'Figure {i + 1}'}**")
                    st.image(f["data"], use_container_width=True)
                    if f.get("caption"):
                        st.caption(f["caption"])
            # 概括：内置抽取式
            captions_text = " ".join(f.get("caption", "") for f in figures if f.get("caption"))
            if captions_text.strip():
                with st.spinner("正在概括图表信息……"):
                    fig_res = summarizer.extractive_summary(captions_text, ratio=0.5, max_sentences=5)
                with st.container(key="panel_figcap"):
                    sec_title("🧩 图表信息概括", "内置抽取式引擎，基于各图表说明文字")
                    fig_out = fig_res["summary"]
                    if lang == "中文" and summarizer.is_mostly_english(fig_out):
                        try:
                            fig_out = summarizer.translate_text(fig_out, "en|zh-CN")
                        except Exception:
                            st.caption("（图表概括自动翻译失败，已显示英文原文）")
                    st.markdown(fig_out)
            # 概括：LLM（可选）
            if llm_ready:
                if st.button("🤖 用 LLM 逐图概括图表信息"):
                    try:
                        with st.spinner("LLM 正在分析图表说明……"):
                            fig_llm = summarizer.llm_figure_summary(
                                figures,
                                st.session_state["llm_base"],
                                st.session_state["llm_key"],
                                st.session_state["llm_model"],
                                language=lang,
                            )
                        with st.container(key="panel_figllm"):
                            sec_title("🤖 图表信息概括", "LLM 逐图解读说明文字")
                            st.markdown(fig_llm)
                    except Exception as e:
                        st.error(f"LLM 调用失败：{e}")
                # v1.3.0：多模态视觉分析——直接把图表图片送 LLM"看图"解读
                if st.button("🔬 用 LLM 视觉分析图表图片（多模态模型如 deepseek-flash / gpt-4o）", use_container_width=True):
                    try:
                        with st.spinner("LLM 正在逐张查看并分析图表图片（图片较多时约需 1-2 分钟）……"):
                            fig_vision = summarizer.llm_figure_vision(
                                figures,
                                st.session_state["llm_base"],
                                st.session_state["llm_key"],
                                st.session_state["llm_model"],
                                language=lang,
                            )
                        with st.container(key="panel_vision"):
                            sec_title("🔬 图表图片视觉分析", "LLM 多模态逐张看图解读")
                            st.markdown(fig_vision)
                    except Exception as e:
                        st.error(
                            f"视觉分析失败：{e}（请确认所配置模型支持图片输入，"
                            "如 deepseek-flash / gpt-4o / qwen-vl 等；纯文本模型无法看图）"
                        )
        elif st.session_state.get("figures") == []:
            st.info("该文献在 PMC 全文中未解析出图表，或抓取失败。")
    elif chosen_article:
        st.caption("💡 该文献暂无 PMC 开放全文，无法解析图表；可尝试选择带「📄 PDF 全文 (PMC)」链接的文献。")


# ---------------- 页面：批量全文（v1.7.0） ----------------
elif page == "批量全文":
    import pandas as pd

    header("📚 批量全文摘要", "多篇文献并行抓取 PMC 开放全文，批量生成章节化摘要与数据分析，一键导出")

    results_list = st.session_state.get("results", [])
    favs = storage.list_favorites()
    src_opts = ["当前检索结果"] + (["我的收藏"] if favs else [])
    src = st.radio("文献来源", src_opts, horizontal=True)
    pool = results_list if src == "当前检索结果" else favs
    pmc_pool = [a for a in pool if a.get("pmcid")]

    if not pmc_pool:
        st.info(
            "当前来源没有带 PMC 开放全文的文献。请先到「文献检索」页检索，"
            "或收藏带「📄 PDF 全文 (PMC)」标记的文献后再来。"
        )
    else:
        sel_df = pd.DataFrame({
            "选择": [False] * len(pmc_pool),
            "标题": [a["title"][:80] for a in pmc_pool],
            "期刊": [a.get("journal") or "" for a in pmc_pool],
            "年份": [a.get("year") or "" for a in pmc_pool],
            "PMCID": [a["pmcid"] for a in pmc_pool],
        })
        edited = st.data_editor(
            sel_df, hide_index=True, use_container_width=True, key="batch_sel",
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", help="勾选要处理的文献", default=False),
                "标题": st.column_config.TextColumn("标题", width="large", disabled=True),
                "期刊": st.column_config.TextColumn("期刊", disabled=True),
                "年份": st.column_config.TextColumn("年份", disabled=True),
                "PMCID": st.column_config.TextColumn("PMCID", disabled=True),
            },
        )
        try:
            chosen_idx = [i for i, v in enumerate(edited["选择"].tolist()) if bool(v)]
        except Exception:
            chosen_idx = []
        selected = [pmc_pool[i] for i in chosen_idx]

        p1, p2, p3 = st.columns(3)
        with p1:
            ft_max = st.select_slider("每篇摘要句子数", options=[6, 8, 10, 12, 15], value=8)
        with p2:
            workers = st.slider("并行线程数", 1, 6, 3, help="NCBI 有限流（约 3 请求/秒），建议 3-4")
        with p3:
            batch_lang = st.radio("输出语言", ["中文", "英文"], horizontal=True)

        if st.button(
            f"🚀 并行抓取并生成摘要（已选 {len(selected)} 篇）",
            type="primary", disabled=not selected, use_container_width=True,
        ):
            if jobs.is_running("batch"):
                st.warning("已有批量任务在进行中，请等待完成（进度见左侧「后台任务」）。")
            else:
                articles = [
                    {k: a.get(k) for k in ("pmid", "pmcid", "title", "journal", "year", "authors", "doi")}
                    for a in selected
                ]
                jobs.start(f"批量全文（{len(articles)} 篇）", _batch_job, key="batch",
                           articles=articles, max_sentences=ft_max, workers=workers, lang=batch_lang)
                st.toast(f"批量任务已开始：{len(articles)} 篇 × {workers} 线程，页面可继续操作", icon="🚀")

    @st.fragment(run_every=1.5)
    def _batch_progress():
        running = [j for j in jobs.snapshot() if j["status"] == "running" and j.get("key") == "batch"]
        if running:
            j = running[0]
            st.info(f"⏳ {j['name']} — {j['note']}")
            st.progress(max(j["progress"], 0.03))

    _batch_progress()

    batch_results = st.session_state.get("batch_results")
    if batch_results:
        batch_lang_out = st.session_state.get("batch_lang", "中文")
        ok_n = sum(1 for r in batch_results if r.get("ok"))
        st.divider()
        sec_title("📦 批量结果", f"共 {len(batch_results)} 篇 · 成功 {ok_n} · 失败 {len(batch_results) - ok_n}")

        md_text = _batch_export_md(batch_results, batch_lang_out)
        xlsx_bytes = _batch_export_xlsx(batch_results, batch_lang_out)
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "⬇️ 一键导出全部摘要与分析 (Markdown)", md_text,
                file_name="batch_fulltext_summary.md", mime="text/markdown",
                type="primary", use_container_width=True,
            )
        with d2:
            st.download_button(
                "⬇️ 导出统计表 (Excel：汇总 / 章节明细 / 统计指标)", xlsx_bytes,
                file_name="batch_fulltext_stats.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        for i, r in enumerate(batch_results, 1):
            a = r["article"]
            src_note = f"　·　🌐 {r['source']}" if r.get("ok") and str(r.get("source", "")).startswith("网页") else ""
            with st.expander(("✅ " if r.get("ok") else "❌ ") + f"{i}. {a['title']}" + src_note):
                if not r.get("ok"):
                    st.error(f"抓取失败：{r.get('error', '')}")
                    continue
                summ, an = r["summary"], r["analytics"]
                if summ.get("sections"):
                    if batch_lang_out == "中文":
                        for p in summ["sections"]:
                            body = p.get("body_zh") or " ".join(p["sentences"])
                            st.markdown(f"**【{p.get('title_zh') or p['title']}】** {body}")
                    else:
                        for p in summ["sections"]:
                            st.markdown(f"**【{p['title']}】** " + " ".join(p["sentences"]))
                elif summ.get("summary"):
                    st.markdown(summ["summary"])
                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("全文词数", f"{an['total_words']:,}")
                with m2:
                    st.metric("章节数", len(an["section_stats"]))
                with m3:
                    st.metric("统计指标类", len(an.get("metrics") or {}))
                kc = an.get("keyword_counts", {})
                kws = an.get("keywords", [])[:8]
                if kws:
                    st.markdown(
                        "".join(
                            f'<span class="kw-chip">{k} <b>{kc[k]}</b></span>' if k in kc else f'<span class="kw-chip">{k}</span>'
                            for k in kws
                        ),
                        unsafe_allow_html=True,
                    )


# ---------------- 页面：我的收藏 ----------------
elif page == "我的收藏":
    header("⭐ 我的收藏", "已收藏的文献集中管理，支持筛选与 Markdown 导出")
    favs = storage.list_favorites()
    if not favs:
        st.info("暂无收藏。去「文献检索」页点击 ⭐ 收藏文献吧。")
    else:
        f1, f2 = st.columns(2, gap="medium")
        with f1:
            stat_card("收藏文献", len(favs), "篇 · 支持 Markdown 导出")
        with f2:
            n_abs = len([a for a in favs if a.get("abstract")])
            stat_card("其中带摘要", n_abs, "篇 · 可直接在智能摘要页使用")
        st.write("")
        if st.button("🧹 清空全部收藏"):
            for f in favs:
                storage.remove_favorite(f["pmid"])
            st.rerun()
        # 导出
        export = "\n\n---\n\n".join(
            f"**{f['title']}**\n- 作者：{', '.join(f.get('authors', []))}\n- 期刊：{f.get('journal','')} ({f.get('year','')})\n- PMID: {f.get('pmid','')}  链接: {f.get('url','')}\n- 摘要：{f.get('abstract','')}"
            for f in favs
        )
        st.download_button("⬇️ 导出全部收藏 (Markdown)", export, file_name="favorites.md")
        st.divider()
        sec_title("收藏列表", "输入关键词可按标题 / 作者筛选")
        q = st.text_input("🔎 在收藏中筛选", placeholder="输入标题/作者关键词", label_visibility="collapsed")
        for f in favs:
            if q and q.lower() not in (f["title"] + " " + " ".join(f.get("authors", []))).lower():
                continue
            article_card(f)


# ---------------- 页面：更新日志 ----------------
elif page == "更新日志":
    header("📋 更新日志", "各版本新增与修复内容一览")
    sec_title("更新日志", f"当前版本 {APP_VERSION} · 最新改动在页面顶部，完整说明见「使用说明.md」")
    st.write("")
    render_changelog()


# ---------------- 页面：检索历史 ----------------
elif page == "检索历史":
    header("🕘 检索历史", "回溯过往检索式与结果数量，可一键复用检索条件")
    hist = storage.list_history()
    if not hist:
        st.info("暂无检索历史。")
    else:
        sec_title("检索记录", f"共 {len(hist)} 次 · 点击「重新检索」可直接复用该检索式")
        if st.button("🧹 清空历史"):
            storage._save(storage.HIST_FILE, [])
            st.rerun()
        for h in hist:
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"**{h['query']}**")
                    st.caption(f"{h['time']} · {h['n_results']} 条结果")
                with c2:
                    if st.button("重新检索", key=f"re_{h['time']}_{h['query'][:10]}"):
                        st.session_state["kw"] = h["query"]
                        st.switch_page("app.py") if False else None
                        st.session_state["page_hint"] = "search"
                        st.toast("已填入关键词，请前往「文献检索」页", icon="🔍")
