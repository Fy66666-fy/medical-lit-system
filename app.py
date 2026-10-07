import sys
import os
import io
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from core import (cache, feedback, health, http, jobs, locate, logger, pubmed, quota,
                  review, summarizer, storage, translate)
from version import APP_VERSION  # 版本单一来源（v2.5.0）：发版只需改 version.py

# ---- 运行日志与异常兜底（v2.4.0）----
logger.setup(APP_VERSION)   # 按天落盘；写入失败静默忽略，绝不拖垮主流程
logger.install_excepthook()  # 未捕获异常写入日志，便于事后定位

# ---- P1：会话级数据隔离 ----
# 云端所有访客共用同一进程，若不按会话分片，A 用户的检索记录/收藏会出现在 B 用户界面上。
# 桌面版由 desktop_app.py 设置 MEDLIT_SCOPE=local（沿用旧数据路径），云端按会话 id 分片。
def _init_scope() -> str:
    forced = os.environ.get("MEDLIT_SCOPE", "").strip()
    if forced:
        return forced
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        sid = getattr(ctx, "session_id", "") if ctx else ""
        if sid:
            return "s" + str(sid).replace("-", "")[:12]
    except Exception:
        pass
    return "local"


storage.set_scope(_init_scope())

# ---- NCBI API Key（速率 3 → 10 req/s）----
# 优先级：侧边栏输入 > st.secrets > 环境变量 NCBI_API_KEY。
# 不配置也能用，只是并发检索时会更慢。
try:  # st.secrets 仅在存在 secrets 文件 / 云端配置时可用
    _ncbi_secret = (st.secrets.get("NCBI_API_KEY") or "").strip()
except Exception:
    _ncbi_secret = ""
if _ncbi_secret:
    http.configure_ncbi(_ncbi_secret)


def _diag_digest() -> str:
    """生成一段可读的诊断摘要：用户报错时附上它，能省掉大半来回追问。

    刻意**不含**检索内容、密钥与身份信息——只保留环境与运行指标。
    """
    hs = http.stats()
    cs = cache.stats()
    q = quota.limits()
    lines = [
        f"版本 {APP_VERSION} · 作用域 {storage.current_scope()}",
        f"外部请求 {hs['requests']} 次 / 重试 {hs['retries']} / 失败 {hs['failures']}"
        f" / 平均 {hs['avg_ms']}ms",
        f"NCBI 速率 {'%.0f req/s（已配 Key）' % (1 / http.ncbi_rate_limit()) if http.ncbi_api_key() else '约 3 req/s（未配 Key）'}",
        f"缓存 {cache.format_summary()}",
        f"依赖健康 {health.format_summary(7)}",
        f"翻译配额 会话 {q['trans_chars']['session']} 字符 / 每日 {q['trans_chars']['daily']} 字符",
        f"LLM 配额 会话 {q['llm_calls']['session']} 次 / 每日 {q['llm_calls']['daily']} 次",
    ]
    blk = quota.last_block()
    if blk.get("message"):
        lines.append(f"最近配额拦截（{blk.get('time')}）：{blk['message'][:120]}")
    return "\n".join(lines)


def _build_issue_text(kind: str, content: str) -> str:
    """留档时复制给用户的一段纯文本，可直接粘给作者。"""
    return "\n".join([
        f"[类型] {kind}",
        f"[描述] {content}",
        "[诊断]",
        _diag_digest(),
    ])


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
    /* ---------- 全局页脚：免责声明 / 数据来源 / 隐私（v2.4.0） ---------- */
    .app-footer {
        margin-top: 2.5rem; padding: 0.85rem 1.15rem;
        background: #ffffff; border: 1px solid var(--line); border-radius: 14px;
        font-size: 0.8rem; color: var(--ink2); line-height: 1.8;
    }
    .app-footer .ft-row + .ft-row {
        margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px dashed var(--line);
    }
    .app-footer b { color: var(--ink); }
    .app-footer .ft-warn { color: #a32d2d; }
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
    ("综述工作台", "journal-text"),
    ("批量全文", "stack"),
    ("我的收藏", "star"),
    ("检索历史", "clock-history"),
    ("隐私与数据", "shield-lock"),
    ("更新日志", "clipboard-data"),
]
NAV_LABELS = [label for label, _ in NAV_ITEMS]


def goto(target: str):
    """供首页卡片按钮跳转使用（回调方式；配合 manual_select 实现外部导航）"""
    st.session_state["pending_page"] = target


pending = st.session_state.pop("pending_page", None)
if pending is None:
    # 深链：?page=文献检索 可直接落到指定页（分享链接、落地页直达）
    try:
        _q = st.query_params.get("page")
        if isinstance(_q, list):
            _q = _q[0] if _q else None
        if _q and _q in NAV_LABELS:
            pending = _q
            # 记下深链目标：首次进入会先撞到隐私同意门，勾选后要回到这个页面而不是首页
            st.session_state["deeplink_page"] = _q
    except Exception:
        pass
pending_idx = NAV_LABELS.index(pending) if pending in NAV_LABELS else None

# ---------------- 后台任务（v1.7.0）：全文摘要 / 图表解析 / 批量全文 ----------------
def _ft_job(job, article: dict, title: str, max_sentences: int):
    """后台任务：单篇全文抓取（PMC → 浏览器兜底）+ 章节化摘要 + 数据分析"""
    jobs.update(job, 0.08, "正在抓取全文（PMC → 网页兜底）…")
    with logger.span("全文抓取", pmcid=article.get("pmcid", ""), title=title[:40]):
        secs, src = pubmed.fetch_fulltext_any(article)
    jobs.update(job, 0.55, "正在生成章节化摘要与数据分析…")
    with logger.span("章节化摘要", title=title[:40]):
        summary = summarizer.fulltext_summary(secs, title=title, max_sentences=max_sentences)
    analytics = summarizer.analyze_fulltext(secs)
    logger.info(f"全文摘要完成：{len(secs)} 章节 · 来源 {src}")
    return {"secs": secs, "summary": summary, "analytics": analytics,
            "pmcid": article.get("pmcid", ""), "title": title, "source": src}


def _fig_job(job, pmcid: str):
    """后台任务：图表抓取 + 图片下载（非 OA 走浏览器截图兜底）"""
    jobs.update(job, 0.15, "正在从 PMC 抓取图表…")
    with logger.span("图表元数据抓取", pmcid=pmcid):
        figures = pubmed.fetch_pmc_figures(pmcid)
    if figures:
        jobs.update(job, 0.5, "正在获取图表图片（非开放获取文献走浏览器截图兜底，约需 20-60 秒）…")
        with logger.span("图表图片获取", pmcid=pmcid, 图表数=len(figures)):
            pubmed.fetch_figure_images(pmcid, figures)
    got = [f for f in figures if f.get("data")]
    logger.info(f"图表解析完成：{len(got)}/{len(figures)} 张拿到图片 (pmcid={pmcid})")
    return got


def _batch_job(job, articles: list[dict], max_sentences: int, workers: int, lang: str):
    """后台任务：多篇文献并行全文抓取 + 摘要 +（可选）中文翻译"""
    from concurrent.futures import ThreadPoolExecutor

    total = len(articles)
    results: list[dict | None] = [None] * total

    def one(i: int, a: dict):
        try:
            with logger.span("批量·单篇", 序号=i, 标题=a["title"][:40]):
                secs, src = pubmed.fetch_fulltext_any(a)
                summary = summarizer.fulltext_summary(secs, title=a["title"], max_sentences=max_sentences)
                analytics = summarizer.analyze_fulltext(secs)
            results[i] = {"article": a, "ok": True, "summary": summary, "analytics": analytics, "source": src}
        except Exception as e:  # noqa: BLE001 —— 单篇失败不拖垮整批
            logger.error(f"批量·单篇失败 序号={i}", e)
            results[i] = {"article": a, "ok": False, "error": str(e)}
        done = sum(1 for r in results if r is not None)
        jobs.update(job, progress=done / total * 0.85, note=f"{done}/{total} 篇完成")

    logger.info(f"批量任务开始：{total} 篇 · {workers} 线程 · 输出 {lang}")
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
        logger.error(f"后台任务失败：{job['name']} | {job.get('error') or ''}")
        st.toast(f"❌ {job['name']} 失败：{(job['error'] or '')[:80]}", icon="❌")
        if job.get("key", "").startswith("fig:"):
            st.session_state["figures"] = []
            st.session_state["fig_error"] = job.get("error") or "未知错误"
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
               "PubMed 链接", "全文来源", "状态", "摘要章节数", "摘要全文",
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
            # 摘要完整导出（仅防 Excel 单元格 32767 字符上限做保护性截断）
            if len(preview) > 32000:
                preview = preview[:32000] + "…"
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
    st.markdown("### ⚡ NCBI 速率（可选）")
    st.caption(
        "NCBI 对每个 IP 的检索限速：无 API Key 约 3 次/秒，申请免费 Key 后约 10 次/秒，"
        "多人同时检索时响应差别很明显。免费申请："
        "https://account.ncbi.nlm.nih.gov/settings/#page=api_keys（填一个邮箱即可，秒批）"
    )
    n_key = st.text_input(
        "NCBI API Key",
        value=st.session_state.get("ncbi_key", ""),
        placeholder="留空则用 3 次/秒的公共额度",
        type="password",
    )
    if n_key != st.session_state.get("ncbi_key_applied", ""):
        http.configure_ncbi(n_key)
        st.session_state["ncbi_key"] = n_key
        st.session_state["ncbi_key_applied"] = n_key
        st.rerun()
    if http.ncbi_api_key():
        st.caption(f"✅ 已启用 API Key · 当前约 {1 / http.ncbi_rate_limit():.0f} 次/秒")
    else:
        st.caption("⚪ 未配置，约 3 次/秒（多人同时检索时会排队）")

    st.divider()
    st.caption("数据源：PubMed E-utilities（NCBI 官方公开 API）\n\n检索结果仅用于研究学习，不构成医疗建议。")

    # ---- 运行诊断（v2.4.0）：出问题时展开这里，截图即可定位 ----
    with st.expander("🩺 运行诊断", expanded=False):
        st.caption(f"版本 {APP_VERSION} · 日志目录 `{logger.LOG_DIR}`（保留 {logger._KEEP_DAYS} 天）")
        _hs = http.stats()
        st.caption(
            f"外部请求：{_hs['requests']} 次 · 重试 {_hs['retries']} 次 · 失败 {_hs['failures']} 次"
            f" · 平均 {_hs['avg_ms']}ms · 下行 {_hs['mb']}MB"
        )
        # P1：依赖成功率与配额（判断是否被限流 / 额度用尽）
        st.caption("📶 " + health.format_summary(7))
        _blk = quota.last_block()
        if _blk.get("message"):
            st.warning(f"配额拦截（{_blk['time']}）：{_blk['message']}")
        else:
            _rem_c = quota.remaining("trans_chars", storage.current_scope(),
                                     own_key=translate.has_tencent())
            if _rem_c is None:
                st.caption("💳 翻译额度：使用你自己的腾讯云密钥，不受宿主额度限制")
            else:
                st.caption(f"💳 本次可用翻译额度：{_rem_c} 字符（自带密钥则不受限）")
        st.caption(
            f"🗂 数据作用域 `{storage.current_scope()}`"
            + ("（云端按会话隔离，刷新或换设备将看不到本次收藏）"
               if storage.current_scope() != "local" else "（本地单机，数据长期保存）")
        )
        # P1 任务 4：缓存命中率。命中率低说明上游被反复打，是额度耗尽的前兆
        st.caption("⚡ 缓存：" + cache.format_summary())
        _c1, _c2 = st.columns(2)
        if _c1.button("🧹 清空缓存", key="cache_clear", use_container_width=True):
            n = cache.clear()
            st.toast(f"已清空 {n} 条缓存", icon="🧹")
            st.rerun()
        if _c2.button("🔄 刷新日志", key="diag_refresh", use_container_width=True):
            st.rerun()
        st.code(logger.tail(60), language="text")
        st.caption("提示：报错时展开此处截图发给开发者，可快速定位问题。")

    # ---- 反馈渠道（P1 任务 6）：本地留档 + 一键生成预填的 Issue ----
    with st.expander("💬 报错 / 建议", expanded=False):
        st.caption("填完点「留档并复制」即可：内容会存在本机，同时复制一段可直接粘贴的文本。")
        _fk = st.selectbox(
            "类型", list(feedback.KINDS),
            format_func=lambda k: {"bug": "🐛 报错", "feature": "💡 建议",
                                    "question": "❓ 疑问", "other": "📝 其他"}[k],
            key="fb_kind",
        )
        _fc = st.text_area("描述", placeholder="哪个功能、什么操作、期望是什么、实际发生了什么",
                           height=90, key="fb_content")
        with st.expander("附带诊断信息（推荐，省去来回追问）", expanded=False):
            st.code(_diag_digest(), language="text")
            st.caption("含版本、请求统计、依赖成功率、配额与缓存状态；不含你的检索内容。")
        _f1, _f2 = st.columns(2)
        if _f1.button("📥 留档并复制", key="fb_save", use_container_width=True):
            _clean = feedback.sanitize(_fc)
            if not _clean.strip():
                st.warning("请先填写描述")
            elif feedback.save(_fk, _clean, _diag_digest()):
                st.session_state["fb_copied"] = _build_issue_text(_fk, _clean)
                st.success(f"已留档 · {feedback.summary_line()}")
        if _f2.button("🔗 生成 Issue 链接", key="fb_issue", use_container_width=True):
            _clean = feedback.sanitize(_fc)
            if not _clean.strip():
                st.warning("请先填写描述")
            else:
                st.link_button("在 GitHub 提交（内容已预填）",
                               feedback.issue_url(_fk, _clean, _diag_digest()))
        if st.session_state.get("fb_copied"):
            st.code(st.session_state["fb_copied"], language="text")
            st.caption("↑ 已复制到剪贴板，可直接粘贴给作者。")
        st.caption(f"本地反馈留档：{feedback.summary_line()}（桌面版可把 data/feedback/ 整个目录发给作者）")


# ---------------- 工具函数 ----------------
CHANGELOG = [
    {
        "version": "v3.0.0",
        "date": "2026-10-08",
        "tag": "最新版本",
        "items": [
            ("🩺", "新增「证据与适用性」核查（P2 主线 B：证据化）", "面向临床医生：在综述工作台内新增第三个标签页「证据与适用性」。不替医生判断文献该不该用（工具读不到全文，也不认识患者），而是把摘要层面能核实的线索摆出来——样本量够不够、有没有对照、随访多长、终点是硬终点还是替代终点、结果是在谁身上得到的，并逐条附上判定理由与原文依据"),
            ("🔬", "偏倚风险提示（约 16 条规则，只提示不裁决）", "覆盖小样本、单臂/无对照、观察性设计使用因果表述、回顾性设计、横断面设计、未提及盲法、自报结局、未报告区间估计或 P 值、结论缺效应量、未见试验注册号、单中心或未说明中心数、替代终点、随访过短或未说明、系统评价未见异质性说明、基础/动物实验等。级别只用「重点核对 / 建议核对 / 信息缺失」三档——刻意不用「高/中/低风险」，那是 RoB 2 等工具的专有判定，需要逐条回答信号问题才能给出"),
            ("📐", "研究类型分层与证据等级参考", "研究设计归入干预性研究 / 观察性研究 / 描述性研究 / 二次研究 / 基础研究五大类，并给出牛津 CEBM 2011 的简化等级对应（1a 系统评价 → 5 机制研究）。等级仅按设计映射，未考虑偏倚风险、间接性与不一致性，页面与导出文件中均明确标注「不是正式分级，不能写进方法学部分」"),
            ("🧭", "临床适用性五维对照", "自动抽出人群、干预、主要终点性质、随访时长、研究场景（单中心/多中心/未说明），再把「向你的患者外推前需要逐维回答的问题」列全，避免漏项。工具不知道你的患者是谁，因此只列维度、不给「适用 / 不适用」的结论"),
            ("📄", "两份新导出物", "「偏倚风险提示清单」（含跨文献频次汇总，可写进讨论与局限性）与「临床适用性对照」（含逐维比对清单），均已纳入 ZIP 打包；横向对比表新增「证据等级」「偏倚提示」两列；综述初稿骨架新增 3.4 偏倚风险与适用性概览，并在 4.3 局限性中自动补入本次纳入研究集中出现的问题"),
            ("✋", "抽取不到就写「未提及」，不猜也不静默略过", "「摘要未提及」本身就是需要标注的信息：摘要没写研究中心数，不等于它是单中心；没写随访时长，不等于随访短。这类条目单独归入「信息缺失」档，不会与真正的风险提示混在一起，避免每篇文献都背上一条无意义提示、反而稀释真正该看的内容"),
            ("💳", "版本号升至 v3.0.0", "P2 双主线（综述化 + 证据化）完成，功能面向的两类用户（医学生/研究生、临床医生）均已覆盖，故由 2.x 升为 3.0.0 标记产品形态定型；本次同时把 v2.9.0 的综述工作台一并纳入正式发版"),
        ],
    },
    {
        "version": "v2.9.0",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("🧾", "新增「综述工作台」（P2 主线 A：综述化）", "面向医学生/研究生的综述写作流程，独立成页而不是塞进单篇摘要页——综述本质是多篇之间的工作：选好一组文献后，自动抽取研究设计、样本量、人群、主要终点、效应量与结论，生成可导出的横向对比表（CSV / Markdown），并附逐篇抽取依据，每条字段都能回原文核对"),
            ("⚖️", "结论冲突自动识别", "同一主题词下结论相反时高亮提示，分「结论极性冲突」与「效应方向冲突（HR/OR/RR 方向相反）」两类，标注可信度并给出可能原因（人群、剂量、终点定义、随访时长差异）。工具只提示需人工核对，不做对错仲裁；未检出冲突时也会明确说明这不等于结论一致"),
            ("🧾", "PRISMA 式筛选记录", "检索式与数据库命中总数从「文献检索」页自动带出（NCBI 的 count 字段），按 PMID/标题自动检测重复条数，逐级推导「命中—去重—题摘筛查—全文评估—纳入」并保证表内数字自洽，可导出成可直接写进综述方法学部分的 Markdown"),
            ("📝", "一键生成综述初稿骨架", "按「引言—资料与方法—结果—讨论—结论—参考文献」组织已读文献，事实来自自动抽取并标注来源，需要作者判断的地方一律写成【待补充：…】占位，避免把机器填的内容误当成自己写好的结论；参考文献按 Vancouver 格式生成。可打包导出 ZIP（对比表 + 冲突核查 + 筛选记录 + 初稿）"),
            ("🤖", "可选：大模型撰写叙述段", "只把工具已抽取好的结构化事实交给模型，提示词中硬性禁止编造样本量、效应量与结论，事实缺失处要求写「摘要未提供」；使用用户自带 Key，离线规则引擎部分零成本"),
            ("🔬", "配套抽取引擎（core/review.py，纯离线）", "研究设计识别按优先级匹配 9 类设计（系统评价/RCT/指南/队列/病例对照/横断面/病例报告/基础实验/叙述性综述），样本量支持 n=、共纳入 N 例等 4 种写法，结论倾向判定先排除否定式表述（no significant…）再判阳性，避免把「无显著改善」读成「有效」；证据强度用「设计基准分 + 样本量 + 是否报告区间估计」的可解释加权，明确标注不是 GRADE 分级"),
            ("🗂", "综述工作区可续写", "综述会跨多次刷新：主题、勾选文献、筛选记录数字按会话作用域落盘，刷新或来回切页不丢进度"),
            ("🐛", "修复「检索历史」页清空按钮报错", "该按钮引用了并不存在的常量 storage.HIST_FILE，点击会抛 AttributeError；现已改为调用 storage.clear_history()"),
        ],
    },
    {
        "version": "v2.8.2",
        "date": "2026-10-07",
        "tag": "最新版本",
        "items": [
            ("🔒", "隐私说明改为正式政策页，并加入首次使用确认", "此前的隐私说明塞在侧边栏设置区里，位置突兀、篇幅零散。现在改为左侧导航中的独立页面「隐私与数据」，按适用范围、不收集的信息、本地与会话数据、结果缓存、第三方服务、API 凭据、运行日志、医疗免责、数据来源、你的权利、政策更新共十一条组织，并标注版本与生效日期"),
            ("✅", "首次使用需确认数据处理方式", "首次进入时页面顶部会出现一条确认条，说明本工具不收集个人身份信息、以及第三方传输的例外情况，勾选后方可使用。不做强制弹窗打断，确认状态仅存在本次会话，不写盘、不上传——与「不收集个人信息」的口径保持一致"),
            ("🔗", "支持页面深链", "URL 追加 ?page=文献检索 可直接落到指定页面，便于分享链接与落地页直达"),
        ],
    },
    {
        "version": "v2.8.1",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("🚀", "修复「一键启动」在端口被占用时直接失败", "此前只要目标端口已被占用（本机常是自己上次没关的服务），Streamlit 会立刻退出，双击窗口一闪而过。现在启动器会先判断占用者是谁：是自己就直接复用并打开浏览器；是别的程序就自动往后找空闲端口并在窗口里明示；都没有则给出明确处理办法，不再让人对着窗口猜"),
            ("🌐", "修复「一键发布」在网络不佳时推送失败", "本机到 GitHub 的链路会随机回 502 / 被 reset / TLS 中断，之前每次发版都得手动加 --resolve 参数。现在发布会依次尝试「轮换直连 IP → 清空代理直连 → 系统默认」，自动找到可用链路；标签与分支分别推送，全部失败时给出补救命令"),
            ("🧭", "启动脚本的解释器查找更可靠", "此前找不到 WorkBuddy 环境就退化成裸 python，而本机 PATH 里没有 python，双击后同样是一闪而过。现在依次尝试 WorkBuddy 环境、D:\\python、PATH 上的 python.exe，全都没有才报错并给出安装指引"),
            ("🛑", "新增「一键停止」", "启动器会复用已有实例，因此需要明确的关闭入口才能重启。新增 stop.py / 一键停止.bat：按端口定位本项目的进程并结束，认进程命令行避免误杀无关程序"),
        ],
    },
    {
        "version": "v2.8.0",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("🔒", "隐私说明页", "侧边栏新增可查阅的完整隐私说明：哪些数据存在哪、谁能看到、明确声明不收集姓名/手机号/邮箱等身份信息、不做用户画像与行为追踪、不用于训练模型，并特别提示「翻译与大模型请求会经过第三方服务，请勿粘贴患者身份信息」"),
            ("💬", "反馈渠道闭环", "侧边栏「报错 / 建议」：填完一键留档到本机并复制可粘贴文本，或直接生成已预填标题与诊断信息的 GitHub Issue 链接。诊断信息含版本、请求统计、依赖成功率、配额与缓存状态——用户报错时不用再反复描述环境。反馈内容会自动隐去邮箱与手机号"),
            ("🌐", "产品落地页", "新增单文件 `index.html` 落地页：一句话定位、真实界面截图、八项能力清单、三步上手、FAQ 与合规声明，图片以 base64 内嵌，可直接用浏览器打开或作为 GitHub Pages 发布。截图由 `_shot.py` 通过 CDP 实拍，重拍后跑 `_build_landing.py` 即可同步更新"),
            ("⚡", "NCBI API Key 已启用", "已申请并配置免费 Key，检索限速从约 3 次/秒提升到约 10 次/秒。实测 8 路并发冷检索从 7.67 秒降到 3.9–6.1 秒"),
        ],
    },
    {
        "version": "v2.7.0",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("⚡", "持久化缓存：同一篇文献不再反复消耗上游配额", "此前同一篇文章被反复检索、反复翻译、反复抓取全文，每次都要重新调用 PubMed 与翻译接口——而 PubMed 是按 IP 限速的公共配额，重复消耗等于把所有人的额度一起花掉。现在检索结果、PMC 全文、抽取摘要、中文译文、大模型摘要全部走本地缓存：同一检索式的 8 路并发从 7.7 秒降到几乎瞬时，摘要重算从 50 毫秒降到 0 毫秒，命中即不消耗翻译额度与 NCBI 限速配额。带 TTL 与条数上限自动淘汰，不会把磁盘撑爆"),
            ("🧹", "缓存可控可观测", "侧边栏「🩺 运行诊断」显示命中率、命中/未命中、写入与淘汰条数，并提供一键清空。命中率偏低说明上游在被反复打，是额度耗尽的前兆信号"),
        ],
    },
    {
        "version": "v2.6.1",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("⚡", "支持 NCBI API Key，检索速率提升 3.3 倍", "NCBI 对每个 IP 的检索限速：无 Key 约 3 次/秒，申请免费 Key 后约 10 次/秒。这是多人同时使用时唯一的硬天花板——侧边栏「⚡ NCBI 速率」填入 Key 即刻生效，所有检索请求自动附带，不需要改任何代码。免费申请地址已放在设置旁，填一个邮箱即可"),
        ],
    },
    {
        "version": "v2.6.0",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("🔒", "会话级数据隔离（多人同时使用不再串号）", "此前所有访问者共用同一份历史与收藏，A 用户的检索记录会出现在 B 用户的界面上。现在按会话分片存储：在线版每人一份独立数据，互不可见；桌面版仍存本机，路径不变、旧数据平滑迁移"),
            ("📊", "用量配额与成本封顶", "新增配额层：单次会话的翻译字符数与大模型调用次数均有上限，超出时给出明确提示与解决建议（自带密钥或稍后再试）。宿主额度仅作体验池，可用环境变量一键关闭（MEDLIT_HOST_QUOTA=0），保证传播时不会被刷穿"),
            ("🔑", "自带密钥即不受限", "在侧边栏填入自己的翻译或大模型密钥后，用量不再受共享额度限制；未填密钥时走体验池并受配额保护。这样既降低传播门槛，又不会让一个链接烧穿你的账单"),
            ("💓", "外部依赖健康监控", "按天统计 PubMed、Europe PMC、图表、翻译、大模型、Unpaywall 六大外部依赖的成功率与错误次数，请求层自动埋点。侧边栏「🩺 运行诊断」可查看近 7 天成功率——出现大范围失败时能立刻判断是自家代码问题还是上游接口波动"),
        ],
    },
    {
        "version": "v2.5.0",
        "date": "2026-10-07",
        "tag": "",
        "items": [
            ("🌐", "统一外部请求层（稳定性）", "此前所有对外请求（PubMed 检索、PMC 全文、图表包、翻译接口、大模型接口）各写各的超时与重试，部分通道完全没有重试，偶发网络抖动或限流就直接失败。现在统一由一层接管：连接/读取超时分离（任何请求都有硬上限，不再把界面卡死）、5xx 与 429 自动指数退避重试并尊重服务端的 Retry-After、按域名控制请求速率（遵守 NCBI 与 Europe PMC 的公开接口配额）、统一埋点。侧边栏「🩺 运行诊断」新增请求统计（次数 / 重试 / 失败 / 平均耗时），一眼看出是网络问题还是接口问题"),
            ("🚀", "修复本地启动后浏览器打不开 / 一直转圈", "旧启动脚本固定等 4 秒就打开浏览器，而服务冷启动常需更久，浏览器实际打在尚未监听的端口上，表现就是「连接很慢」。改为轮询端口真实就绪后再打开浏览器，并显示本次启动耗时"),
            ("🏷", "版本号单一来源与发布流程", "版本号此前散落在多处、手工同步，容易出现页面显示与实际代码不一致。现在统一由 version.py 提供；新增 release.py 一键发布（跑测试 → 改版本 → 同步部署目录 → 提交打标签 → 推送）与 GitHub Actions 持续集成，每次推送自动跑冒烟测试"),
        ],
    },
    {
        "version": "v2.4.0",
        "date": "2026-10-07",
        "tag": "最新版本",
        "items": [
            ("📋", "运行日志系统（产品化 P0）", "新增按天落盘的运行日志：记录检索、全文抓取、摘要生成、图表解析、批量任务与 LLM 调用的关键步骤与耗时，异常自动记录堆栈。以前线上或桌面端出问题只能靠猜，现在有据可查。侧边栏新增「🩺 运行诊断」可直接在页面内查看最近日志，报错时截图即可定位。日志默认保留 14 天，写入失败绝不影响正常使用"),
            ("🛡", "异常兜底与友好报错", "安装全局异常钩子，未捕获异常自动写入日志；抽取式摘要等核心操作失败时给出可读提示与「技术详情」折叠区，不再把程序栈直接抛给用户；后台任务失败、批量单篇失败均记录日志"),
            ("⚕️", "医疗免责声明与数据来源署名（合规）", "每页底部常驻页脚：明确声明摘要由算法或大模型自动生成、**不能作为临床诊断与用药依据**，诊疗决策须核对原文并由专业医师判断；同时署名数据来源 PubMed / PMC（NCBI 下属 NLM）并遵循其使用条款；附隐私说明——不收集个人身份信息，历史与收藏仅存本机或当前会话"),
        ],
    },
    {
        "version": "v2.3.1",
        "date": "2026-09-30",
        "tag": "",
        "items": [
            ("🖼", "修复桌面版图表解析必然失败", "桌面版打包配置漏掉了浏览器兜底通道依赖的 websocket 组件，导致非开放获取（non-OA）文献的图表解析在 exe 中必定失败（OA 文献不受影响）。已补全打包依赖并让缺失时优雅降级"),
            ("🩺", "失败原因不再被吞掉", "图表解析失败时，页面会直接显示真实原因与解决建议（原先只弹一条 80 字提示，随即变成含糊的「未解析出图表」）"),
        ],
    },
    {
        "version": "v2.3.0",
        "date": "2026-09-28",
        "tag": "",
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


def render_footer():
    """全局页脚（v2.4.0）：医疗免责声明 + 数据来源署名 + 隐私说明。

    医疗类产品的底线件套——常驻显示在每页底部，避免任何「可直接用于诊疗」的误读。
    """
    st.markdown(
        """
        <div class="app-footer">
            <div class="ft-row">
                <b>⚕️ 医疗免责声明</b>　
                本工具生成的摘要、翻译与数据分析均由算法或大模型自动生成，可能存在遗漏、偏差或曲解。
                <span class="ft-warn"><b>不能作为临床诊断、用药或治疗方案的依据</b></span>；
                诊疗决策请务必核对文献原文，并以专业医师的判断为准。
            </div>
            <div class="ft-row">
                <b>📚 数据来源</b>　
                文献检索与全文来自 <b>PubMed / PMC</b>（美国国立卫生研究院 NCBI 下属国家医学图书馆 NLM），
                遵循 NCBI 使用条款，仅供学习与研究使用。
            </div>
            <div class="ft-row">
                <b>🔒 隐私说明</b>　
                本工具不收集任何个人身份信息；检索历史与收藏仅保存在本机（云端版为当前会话），不会上传至任何服务器。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        "icon": "🧾",
        "bg": "#eef7f1",
        "title": "综述工作台",
        "desc": "写综述：多篇横向对比、结论冲突提示、PRISMA 筛选记录、初稿骨架。看证据：研究类型分层、证据等级参考、偏倚提示、临床适用性。",
        "btn": "去综述",
        "target": "综述工作台",
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
    # 每行 4 张（卡片可继续增加，超出的自动换行；此前用 zip 截断会静默少渲染）
    for start in range(0, len(FEATURES), 4):
        cols = st.columns(4, gap="medium")
        for col, feat in zip(cols, FEATURES[start:start + 4]):
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


# ---------------- 页面：综述工作台（v3.0.0，P2 主线 A 综述化 + B 证据化） ----------------
# 为什么单独做一页而不是塞进「智能摘要」：综述是**多篇之间**的工作，
# 单篇摘要页的信息结构（一次选一篇）根本装不下横向对比与筛选记录。
RV_DEFAULTS = {
    "rv_topic": "",
    "rv_query": "",
    "rv_date_range": "",
    "rv_total": 0,
    "rv_retrieved": 0,
    "rv_dup": 0,
    "rv_ex_screen": 0,
    "rv_ex_full": 0,
    "rv_reasons": "",
    "rv_notes": "",
    "rv_picked": [],
}


def _rv_seed():
    """把磁盘上的工作区状态灌进本次会话（只灌尚未存在的键，避免覆盖用户当前输入）。"""
    saved = storage.load_review_state()
    for k, _v in RV_DEFAULTS.items():
        if k in saved and k not in st.session_state:
            st.session_state[k] = saved[k]
    # 刚在「文献检索」跑过检索时，顺手把检索式与命中数带进来，省一次手抄
    if not st.session_state.get("rv_query") and st.session_state.get("last_query"):
        st.session_state["rv_query"] = st.session_state["last_query"]
    if not st.session_state.get("rv_total") and st.session_state.get("last_total"):
        st.session_state["rv_total"] = int(st.session_state["last_total"] or 0)
    if not st.session_state.get("rv_topic") and st.session_state.get("last_query"):
        # 检索式里的字段标签（[Title/Abstract] 等）对"主题"没有意义，去掉更接近人话
        st.session_state["rv_topic"] = re.sub(r"\[[^\]]+\]", " ", st.session_state["last_query"]).strip()


def _rv_persist():
    storage.save_review_state({k: st.session_state.get(k) for k in RV_DEFAULTS})


def _rv_pool(results: list[dict], favs: list[dict]) -> list[dict]:
    """合并检索结果与收藏，按 PMID（缺失时用标题前缀）去重，保持原顺序。"""
    seen, out = set(), []
    for a in list(results) + list(favs):
        key = (a.get("pmid") or "").strip() or re.sub(
            r"[^a-z0-9\u4e00-\u9fff]", "", (a.get("title") or "").lower())[:60]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _rv_zip(rows: list[dict], conflicts: list[dict], prisma_rec: dict | None,
            draft: str, topic: str) -> bytes:
    """把综述工作台的产出打包成一个 zip：对比表 + 冲突核查 + 筛选记录 + 初稿骨架。"""
    import zipfile

    buf = io.BytesIO()
    stamp = datetime.now().strftime("%Y%m%d")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"表1_文献对比表_{stamp}.csv", review.comparison_csv(rows))
        z.writestr(f"表1_文献对比表_{stamp}.md", review.comparison_markdown(rows, topic))
        if conflicts:
            z.writestr(f"结论冲突核查_{stamp}.md", review.conflicts_markdown(conflicts, topic))
        z.writestr(f"表2_偏倚风险提示清单_{stamp}.md", review.bias_markdown(rows, topic))
        z.writestr(f"表3_临床适用性对照_{stamp}.md", review.applicability_markdown(rows, topic))
        if prisma_rec:
            z.writestr(f"文献筛选记录_PRISMA_{stamp}.md", review.prisma_markdown(prisma_rec, rows))
        if draft:
            z.writestr(f"综述初稿骨架_{stamp}.md", draft)
        z.writestr("参考文献_Vancouver.md", review.references_markdown(rows))
        z.writestr("说明.txt", (
            "由「医学文献智能摘要与检索系统」自动生成。\n"
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"综述主题：{topic or '（未填写）'}\n"
            f"纳入文献：{len(rows)} 篇\n\n"
            "内容由规则引擎从 PubMed 摘要自动抽取，可能存在遗漏或偏差，请核对原文后使用。\n"
            "「证据等级」为按研究设计粗略映射的牛津 CEBM 简化参考，「证据强度」为可解释加权提示，"
            "「偏倚提示」只反映摘要层面可见的线索——三者都不是正式分级或规范偏倚评估"
            "（RoB 2 / NOS / GRADE），不能直接写入方法学部分。\n"
        ))
    return buf.getvalue()


def render_review_page():
    import pandas as pd

    header("🧾 综述工作台",
           "多篇文献横向对比 · 结论冲突识别 · 证据与适用性核查 · PRISMA 筛选记录 · 综述初稿骨架")
    st.caption(
        "一份数据源，两种用法：**写综述**（横向对比 / 结论冲突 / 筛选记录 / 初稿骨架）"
        "与**看证据**（研究类型分层 / 证据等级参考 / 偏倚提示 / 临床适用性）。"
        "同一主题下结论打架会自动提示；所有产出都能导出成 Word 可用的 Markdown。"
        "本页全部为**离线规则引擎**，不调用大模型也不消耗任何额度（用 LLM 撰写叙述段需手动触发）。"
    )
    st.caption(
        "⚠️ 证据等级 / 证据强度 / 偏倚提示都是**筛查加速器**，不是正式分级或偏倚评估"
        "（不是 CEBM 分级、不是 GRADE、不是 RoB 2），只能用来决定先看哪几篇，"
        "最终判断请用规范工具评价全文后作出。"
    )
    _rv_seed()

    pool = _rv_pool(ensure_results(), storage.list_favorites())
    if not pool:
        st.info(
            "还没有可用文献。请先到「文献检索」页检索，或在文献卡片上点「⭐ 收藏」后再回来——"
            "综述工作台的数据来源就是检索结果与收藏。"
        )
        return

    # ---------- 第 1 步：主题与文献选择 ----------
    sec_title("1️⃣ 确定主题并勾选纳入文献", f"可选文献 {len(pool)} 篇（检索结果 + 收藏，已去重）")
    st.text_input(
        "综述主题 / 研究问题（会写进初稿标题与参考文献说明）",
        key="rv_topic",
        placeholder="例如：PD-1 抑制剂联合化疗在晚期非小细胞肺癌中的疗效与安全性",
    )

    prefill = st.session_state.pop("rv_prefill", None)
    if prefill is not None:
        # data_editor 会把用户编辑保存在自己的会话状态里，换了默认勾选值必须把这个状态丢掉，
        # 否则「全选 / 清空」点了没反应（表格仍显示上一次的勾选）。
        st.session_state.pop("rv_editor", None)
    picked = set(prefill if prefill is not None else (st.session_state.get("rv_picked") or []))
    sel_df = pd.DataFrame({
        "选择": [(a.get("pmid") or a.get("title", "")[:60]) in picked for a in pool],
        "标题": [a.get("title", "")[:90] for a in pool],
        "年份": [str(a.get("year") or "") for a in pool],
        "期刊": [a.get("journal") or "" for a in pool],
        "研究设计": [review.judge_design(a)[0] for a in pool],
        "摘要": ["有" if (a.get("abstract") or "").strip() else "无" for a in pool],
    })
    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button("✅ 全选", key="rv_all", use_container_width=True):
        st.session_state["rv_prefill"] = [a.get("pmid") or a.get("title", "")[:60] for a in pool]
        st.rerun()
    if b2.button("🧹 清空选择", key="rv_none", use_container_width=True):
        st.session_state["rv_prefill"] = []
        st.rerun()
    with b3:
        st.caption("勾选要纳入综述的文献（建议 5–30 篇：太少看不出差异，太多对比表会失去可读性）。")
    edited = st.data_editor(
        sel_df, hide_index=True, use_container_width=True, key="rv_editor",
        column_config={
            "选择": st.column_config.CheckboxColumn("纳入", help="勾选后进入对比与冲突分析", default=False),
            "标题": st.column_config.TextColumn("标题", width="large", disabled=True),
            "年份": st.column_config.TextColumn("年份", width="small", disabled=True),
            "期刊": st.column_config.TextColumn("期刊", disabled=True),
            "研究设计": st.column_config.TextColumn("研究设计（自动识别）", disabled=True),
            "摘要": st.column_config.TextColumn("摘要", width="small", disabled=True),
        },
    )
    try:
        sel_idx = [i for i, v in enumerate(edited["选择"].tolist()) if bool(v)]
    except Exception:
        sel_idx = []
    selected = [pool[i] for i in sel_idx]
    st.session_state["rv_picked"] = [a.get("pmid") or a.get("title", "")[:60] for a in selected]

    if not selected:
        st.warning("请至少勾选 1 篇文献，下方对比、冲突与初稿才会生成。")
        _rv_persist()
        return
    n_no_abs = len([a for a in selected if not (a.get("abstract") or "").strip()])
    if n_no_abs:
        st.caption(f"⚠️ 其中 {n_no_abs} 篇没有摘要，相关字段只能留空——抽取不到就留空，不做推测。")

    # 抽取结果是纯本地计算，但没必要每次控件交互都重算（几十篇全量正则约数百毫秒），
    # 用"所选 PMID 签名"做记忆，勾选变化时才重算。
    sig = tuple(a.get("pmid") or a.get("title", "")[:40] for a in selected)
    if st.session_state.get("rv_sig") != sig:
        with st.spinner("正在抽取研究设计、样本量、效应量与结论……"):
            _rows = review.build_comparison(selected)
            st.session_state["rv_rows"] = _rows
            st.session_state["rv_conflicts"] = review.detect_conflicts(_rows)
            st.session_state["rv_draft"] = ""
            st.session_state["rv_llm"] = ""
        st.session_state["rv_sig"] = sig
    rows = st.session_state.get("rv_rows", [])
    conflicts = st.session_state.get("rv_conflicts", {"terms": [], "conflicts": []})
    topic = st.session_state.get("rv_topic", "")

    t1, t2, t3, t4, t5 = st.tabs([
        "📊 横向对比表", "⚖️ 结论冲突核查", "🩺 证据与适用性",
        "🧾 筛选记录（PRISMA）", "📝 综述初稿骨架",
    ])

    # ---------- 表 1：横向对比 ----------
    with t1:
        stats = review.summary_stats(rows)
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            stat_card("纳入文献", stats["total"], "篇 · 可导出 CSV / Markdown")
        with c2:
            stat_card("最新发表年份", stats["year_to"] or "—",
                      f"区间 {stats['year_from'] or '—'}–{stats['year_to'] or '—'}")
        with c3:
            stat_card("样本量合计", f"{stats['n_total']:,}" if stats["n_total"] else "—",
                      f"例 · {stats['n_missing']} 篇未抽取到")
        with c4:
            top_design = next(iter(stats["designs"]), "—")
            stat_card("最常见设计", top_design, f"{stats['designs'].get(top_design, 0)} 篇")

        st.write("")
        sec_title("表 1　纳入文献基本特征对比",
                  "所有字段均从 PubMed 摘要自动抽取；「证据强度」为可解释加权提示，不是正式证据分级")
        show_cols = list(review.COMPARISON_COLUMNS)
        tbl = pd.DataFrame([{c: r.get(c, "") for c in show_cols} for r in rows])
        st.dataframe(
            tbl, hide_index=True, use_container_width=True,
            height=min(640, 90 + 36 * len(rows)),
            column_config={
                "标题": st.column_config.TextColumn("标题", width="large"),
                "结论": st.column_config.TextColumn("结论（摘要原文）", width="large"),
                "关键效应量": st.column_config.TextColumn("关键效应量", width="medium"),
                "主要终点": st.column_config.TextColumn("主要终点", width="medium"),
                "研究设计": st.column_config.TextColumn("研究设计", width="small"),
                "证据等级": st.column_config.TextColumn(
                    "等级（参考）", width="small",
                    help="按研究设计粗略对应牛津 CEBM 分级，未考虑偏倚等降级因素，不是正式分级"),
                "结论倾向": st.column_config.TextColumn("结论倾向", width="small"),
                "证据强度": st.column_config.TextColumn("证据强度", width="small"),
                "偏倚提示": st.column_config.TextColumn(
                    "偏倚提示", width="medium",
                    help="摘要层面可见的线索，不是 Rob 2 / NOS 评估结论；明细见「🩺 证据与适用性」"),
            },
        )
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ 导出对比表 (CSV，Excel 可直接打开)", review.comparison_csv(rows),
                           file_name="纳入文献对比表.csv", use_container_width=True)
        d2.download_button("⬇️ 导出对比表 (Markdown，可直接粘进 Word)",
                           review.comparison_markdown(rows, topic),
                           file_name="纳入文献对比表.md", use_container_width=True)

        with st.expander("🔍 逐篇查看抽取依据（每条字段都能回原文核对）", expanded=False):
            for r in rows:
                p = r["_profile"]
                st.markdown(
                    f"**{r['序号']}. {p['title']}**　"
                    f"<span class='kw-chip'>{p['design']}</span>"
                    f"<span class='kw-chip'>{p['design_layer']}</span>"
                    f"<span class='kw-chip'>等级参考 {p['cebm'][0]}</span>"
                    f"<span class='kw-chip'>样本量 {p['n'] or '未抽取'}</span>"
                    f"<span class='kw-chip'>证据强度 {p['evidence']['label']}</span>"
                    f"<span class='kw-chip'>{p['bias']['label']}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"设计依据：{p['design_evidence']}")
                if p["n_evidence"]:
                    st.caption(f"样本量原文：{p['n_evidence']}")
                if p["population"]:
                    st.caption(f"人群：{p['population']}")
                if p["primary_outcome"]:
                    st.caption(f"主要终点：{p['primary_outcome']}")
                if p["effects"]:
                    st.caption("效应量原文：" + (p["effects"].get("snippet") or review.effect_text(p["effects"])))
                st.caption(f"结论（{p['conclusion_source']}）：{p['conclusion'] or '摘要未写明结论'}")
                st.caption(f"结论倾向判定：{p['polarity']}"
                           + (f"（命中线索「{p['polarity_cue']}」）" if p["polarity_cue"] else "（未命中线索词）"))
                st.caption(f"证据强度算法：{p['evidence']['basis']}")
                if p["bias"]["flags"]:
                    st.caption("偏倚提示：" + "；".join(
                        f"{f['label']}（{f['level']}）" for f in p["bias"]["flags"]))
                st.caption(f"临床适用性：{p['applicability']['note']}")
                st.divider()

    # ---------- 结论冲突核查 ----------
    with t2:
        sec_title("结论冲突核查", "同一主题词下结论相反时高亮提示，供人工核对，工具不做对错判断")
        terms = conflicts.get("terms") or []
        if terms:
            st.caption("本次文献共同关注的主题词：" + "　".join(
                f"`{t}`（{n} 篇）" for t, n in terms))
        dist = stats["polarity"] if rows else {}
        if dist:
            st.caption("结论倾向分布：" + "　".join(f"**{k}** {v} 篇" for k, v in dist.items()))
        if not conflicts.get("conflicts"):
            st.success("✅ 未发现同一主题下的明显结论冲突。")
            st.caption(
                "需要说明的是：未检出冲突 ≠ 结论一致。可能是摘要没写明结论、或主题词覆盖不足，"
                "仍建议人工通读各篇结论段——下方列出了结论倾向分布供快速扫读。"
            )
            for r in rows:
                p = r["_profile"]
                st.markdown(f"- **{r['年份'] or '年份不详'}｜{r['研究设计']}**：{p['conclusion'] or '摘要未写明结论'}")
        else:
            st.warning(
                f"发现 {len(conflicts['conflicts'])} 处可能的结论不一致。"
                "结论打架往往不是「有人做错了」，而是人群、剂量、终点定义或随访时长不同——请回原文核对后再判断。"
            )
            for i, cf in enumerate(conflicts["conflicts"], 1):
                with st.container(border=True):
                    st.markdown(
                        f"**{i}. [{cf['type']}] 主题词「{cf['term']}」**　"
                        f"<span class='kw-chip'>可信度 {cf['confidence']}</span>"
                        f"<span class='kw-chip'>涉及 {cf['count']} 篇</span>",
                        unsafe_allow_html=True,
                    )
                    cols = st.columns(len(cf["sides"]))
                    for col, side in zip(cols, cf["sides"]):
                        with col:
                            st.markdown(f"**{side['label']}**（{len(side['studies'])} 篇）")
                            for s in side["studies"]:
                                st.markdown(
                                    f"- {s['cite']}｜{s['design']}｜样本量 {s['n'] or '未抽取'}"
                                    + (f"｜[PMID {s['pmid']}](https://pubmed.ncbi.nlm.nih.gov/{s['pmid']}/)" if s["pmid"] else "")
                                )
                                st.caption(s["snippet"] or "（摘要未写明结论）")
                    st.caption("提示：" + cf["note"])
            st.download_button("⬇️ 导出结论冲突核查 (Markdown)",
                               review.conflicts_markdown(conflicts["conflicts"], topic),
                               file_name="结论冲突核查.md")

    # ---------- 证据与适用性（P2 主线 B：面向临床医生） ----------
    with t3:
        sec_title(
            "证据与适用性核查",
            "研究类型分层 · 证据等级参考 · 偏倚提示 · 临床适用性——只标出「需要核对什么」，不做「能不能用」的裁决",
        )
        st.caption(
            "本页面向临床场景：不替你判断这篇文献该不该用（工具读不到全文，也不认识你的患者），"
            "而是把**摘要层面能核实的线索**摆出来——样本量够不够、有没有对照、随访多长、"
            "终点是硬终点还是替代终点、以及结果是在谁身上得到的。每条提示都附摘要依据，"
            "**摘要没写的会明确标成「摘要未提及」，不会静默略过**。"
        )
        bov = review.bias_overview(rows)
        top_flag = next(iter(bov["flags"]), "—")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            stat_card("纳入文献", bov["total"], "篇")
        with c2:
            stat_card("需重点核对", bov["focus_docs"], "篇 · 存在需要优先核对的提示项")
        with c3:
            stat_card("提示项合计", sum(bov["flags"].values()), f"条 · 覆盖 {len(bov['flags'])} 类")
        with c4:
            stat_card("最常见提示", top_flag if top_flag != "—" else "—",
                      f"{bov['flags'].get(top_flag, 0)} 篇" if top_flag != "—" else "本次未触发")

        with st.container(border=True):
            st.markdown(
                "**先说清楚这三样东西是什么，避免误用：**\n\n"
                "- **证据等级**：按研究设计粗略对应牛津 CEBM 2011 分级（1a 系统评价 → 5 机制研究），"
                "**未考虑**偏倚风险、间接性、不一致性等降级因素，不是正式分级；\n"
                "- **证据强度**（对比表）：设计 + 样本量 + 是否报告区间估计的可解释加权，**不是 GRADE**；\n"
                "- **偏倚提示**：只列摘要里看得见的线索，**不是** RoB 2 / NOS 的评估结论。\n\n"
                "三者都只能当作**筛查加速器**，最终判断请用规范工具评价全文后作出。"
            )

        st.write("")
        sec_title("表 2　证据特征与偏倚提示总览", "逐篇明细在下方展开区，每条都附原文依据")
        bio = pd.DataFrame([{
            "#": r["序号"],
            "标题": (r["_profile"]["title"] or "")[:70],
            "研究设计": r["_profile"]["design"],
            "类型层级": r["_profile"]["design_layer"],
            "证据等级": r["_profile"]["cebm"][0],
            "偏倚提示": r["_profile"]["bias"]["label"],
            "提示项": r["_profile"]["bias"]["brief"],
            "主要终点类型": r["_profile"]["applicability"]["outcome_class"],
            "随访": r["_profile"]["applicability"]["followup"],
            "研究场景": r["_profile"]["applicability"]["setting"],
        } for r in rows])
        st.dataframe(
            bio, hide_index=True, use_container_width=True,
            height=min(640, 90 + 36 * len(rows)),
            column_config={
                "标题": st.column_config.TextColumn("标题", width="medium"),
                "类型层级": st.column_config.TextColumn("类型层级", width="small"),
                "证据等级": st.column_config.TextColumn("等级（参考）", width="small"),
                "偏倚提示": st.column_config.TextColumn("偏倚提示", width="small"),
                "提示项": st.column_config.TextColumn("触发的主要提示", width="medium"),
                "主要终点类型": st.column_config.TextColumn("主要终点类型", width="medium"),
                "研究场景": st.column_config.TextColumn("研究场景", width="small"),
            },
        )
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ 导出偏倚风险提示清单 (Markdown)",
                           review.bias_markdown(rows, topic),
                           file_name="偏倚风险提示清单.md", use_container_width=True)
        d2.download_button("⬇️ 导出临床适用性对照 (Markdown)",
                           review.applicability_markdown(rows, topic),
                           file_name="临床适用性对照.md", use_container_width=True)

        with st.expander("🔬 逐篇证据明细（提示级别 + 判定理由 + 原文依据）", expanded=False):
            for r in rows:
                p = r["_profile"]
                st.markdown(
                    f"**{r['序号']}. {p['title']}**　"
                    f"<span class='kw-chip'>{p['design']}</span>"
                    f"<span class='kw-chip'>{p['design_layer']}</span>"
                    f"<span class='kw-chip'>等级参考 {p['cebm'][0]}</span>"
                    f"<span class='kw-chip'>{p['bias']['label']}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(f"等级对应说明：{p['cebm'][1]}")
                b = p["bias"]
                if not b["flags"]:
                    st.caption("未自动发现需要提示的项——**不等于没有偏倚**，只是摘要层面看不出线索。")
                for fl in b["flags"]:
                    st.markdown(f"- **[{fl['level']}] {fl['label']}**：{fl['reason']}")
                    if fl["evidence"]:
                        st.caption(f"　原文依据：「{fl['evidence']}」")
                    else:
                        st.caption("　原文依据：摘要未提及（该条提示正是基于「未提及」本身）")
                a = p["applicability"]
                st.markdown(
                    f"**适用性速览**：人群 `{a['population']}`　干预 `{a['intervention']}`　"
                    f"终点 `{a['outcome_class']}`　随访 `{a['followup']}`　场景 `{a['setting']}`"
                )
                st.caption(f"可及性提示：{a['availability']}")
                st.caption(a["note"])
                st.divider()

        st.markdown("#### 🧭 向你的患者外推前，请逐维回答")
        st.caption("工具不知道你的患者是谁，所以不给「适用 / 不适用」的结论——只把该比对的维度列全，避免漏项。")
        for dim, q in review.APPLICABILITY_DIMENSIONS:
            st.markdown(f"- **{dim}**：{q}")

    # ---------- 筛选记录（PRISMA） ----------
    with t4:
        sec_title("筛选记录（PRISMA 式）", "自动带出检索与纳入数字，排除理由需人工确认后填写")
        auto_dup = review.auto_duplicates(selected)
        if auto_dup and not st.session_state.get("rv_dup"):
            st.session_state["rv_dup"] = auto_dup
        if not st.session_state.get("rv_retrieved"):
            st.session_state["rv_retrieved"] = len(selected)
        st.caption(
            f"来源说明：检索式与「数据库命中」已从「文献检索」页自动带出；"
            f"「实际纳入题录」默认取当前勾选的 {len(selected)} 篇；"
            f"按 PMID/标题自动检测到的重复为 {auto_dup} 条（已预填，可修改）。"
        )
        f1, f2 = st.columns(2)
        with f1:
            st.text_input("检索数据库", value="PubMed（NCBI E-utilities）", disabled=True, key="rv_db_show")
            st.text_input("检索式", key="rv_query", placeholder="在「文献检索」页检索后会自动带出")
            st.text_input("检索时限（如 2015/01/01–2026/10/01）", key="rv_date_range")
            st.number_input("数据库命中总数", min_value=0, step=1, key="rv_total")
        with f2:
            st.number_input("实际下载题录数", min_value=0, step=1, key="rv_retrieved")
            st.number_input("去重后剔除条数", min_value=0, step=1, key="rv_dup")
            st.number_input("阅读题名/摘要后排除", min_value=0, step=1, key="rv_ex_screen")
            st.number_input("全文评估后排除", min_value=0, step=1, key="rv_ex_full")
        st.text_area(
            "排除原因及篇数（每行一条，例如：非随机对照研究 12 篇）",
            key="rv_reasons", height=90,
            placeholder="重复发表 3 篇\n非目标人群 8 篇\n无法获取全文 2 篇",
        )
        st.text_area("补充说明（可写限定语种、手检补充等）", key="rv_notes", height=70)

        prisma_rec = {
            "topic": topic,
            "query": st.session_state.get("rv_query", ""),
            "database": "PubMed（NCBI E-utilities）",
            "date_range": st.session_state.get("rv_date_range", ""),
            "search_date": datetime.now().strftime("%Y-%m-%d"),
            "total_hits": st.session_state.get("rv_total", 0),
            "retrieved": st.session_state.get("rv_retrieved", 0),
            "duplicates": st.session_state.get("rv_dup", 0),
            "excluded_screening": st.session_state.get("rv_ex_screen", 0),
            "excluded_fulltext": st.session_state.get("rv_ex_full", 0),
            "excluded_reasons": [x.strip() for x in (st.session_state.get("rv_reasons") or "").splitlines() if x.strip()],
            "notes": st.session_state.get("rv_notes", ""),
        }
        cnt = review.prisma_counts(prisma_rec)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            stat_card("数据库命中", cnt["identified"], "条")
        with m2:
            stat_card("进入筛查", cnt["screened"], f"条 · 去重 {cnt['duplicates']}")
        with m3:
            stat_card("进入全文评估", cnt["assessed"], f"条 · 题摘排除 {cnt['excluded_screening']}")
        with m4:
            stat_card("最终纳入", cnt["included"], f"条 · 全文排除 {cnt['excluded_fulltext']}")
        md = review.prisma_markdown(prisma_rec, rows)
        st.markdown(md)
        st.download_button("⬇️ 导出筛选记录 (Markdown)", md,
                           file_name="文献筛选记录_PRISMA.md", use_container_width=True)
        st.caption("说明：排除理由与篇数由使用者负责填写核对，工具只保证各级数字在表内自洽。")

    # ---------- 综述初稿骨架 ----------
    with t5:
        sec_title("综述初稿骨架", "按「背景—方法—结果—讨论—结论」组织已读文献，事实来自抽取，空缺写成待补充")
        c1, c2 = st.columns([1, 2])
        with c1:
            if st.button("🧩 生成综述初稿骨架", type="primary", use_container_width=True):
                st.session_state["rv_draft"] = review.build_review_draft(
                    topic, rows, conflicts.get("conflicts", []), prisma_rec,
                    extra={"terms": conflicts.get("terms") or []},
                )
                st.toast("初稿骨架已生成（离线，未调用大模型）", icon="🧩")
        with c2:
            st.caption(
                "骨架里所有需要作者判断的地方都写成 `【待补充：…】`，由工具抽取到的事实则直接填入并标注来源。"
                "这样你不会误把机器填的内容当成自己写好的结论。"
            )
        draft = st.session_state.get("rv_draft", "")
        if draft:
            st.markdown(draft)
            df1, df2 = st.columns(2)
            df1.download_button("⬇️ 导出初稿骨架 (Markdown)", draft,
                                file_name="综述初稿骨架.md", use_container_width=True)
            df2.download_button(
                "📦 打包导出全部产出 (ZIP)",
                _rv_zip(rows, conflicts.get("conflicts", []), prisma_rec, draft, topic),
                file_name=f"综述产出_{datetime.now().strftime('%Y%m%d')}.zip",
                use_container_width=True,
            )

        st.divider()
        st.markdown("#### 🤖 可选：让大模型撰写「结果概述」与「讨论」叙述段")
        st.caption(
            "只把工具已经抽取好的结构化事实（设计/样本量/效应量/结论/冲突点）交给模型，"
            "并在提示词里硬性禁止编造数据——事实缺失处要求写「摘要未提供」。使用你自己的 Key，按次计费。"
        )
        if not llm_ready:
            st.caption("⚪ 侧边栏未配置大模型，跳过此步也可直接使用上面的骨架。")
        else:
            if st.button("🤖 撰写叙述段", use_container_width=False):
                try:
                    with st.spinner("大模型正在撰写（约 10–40 秒）……"):
                        with logger.span("综述叙述生成", 主题=topic[:30], 篇数=len(rows)):
                            st.session_state["rv_llm"] = review.draft_with_llm(
                                st.session_state["llm_base"], st.session_state["llm_key"],
                                st.session_state["llm_model"], topic, rows,
                                conflicts.get("conflicts", []),
                            )
                except Exception as e:
                    logger.error("综述叙述生成失败", e)
                    st.error(f"生成失败：{e}")
            llm_txt = st.session_state.get("rv_llm", "")
            if llm_txt:
                with st.container(key="panel_llm"):
                    st.markdown(llm_txt)
                merged = (draft or "") + "\n\n---\n\n## 附：大模型撰写的叙述段（须逐句核对事实）\n\n" + llm_txt
                st.download_button("⬇️ 导出「骨架 + 叙述段」(Markdown)", merged,
                                   file_name="综述初稿_含叙述段.md", use_container_width=True)

    _rv_persist()


# ---------------- 首次进入：隐私条款确认（对应注册页的同意勾选） ----------------
# 设计取舍：不做强制弹窗打断，但第一次进入必须明确勾选才能操作，
# 勾选状态只存在本次会话（session_state），不写盘、不上传——与"不收集个人信息"一致。
if not st.session_state.get("privacy_ack"):
    with st.container(border=True):
        st.markdown("#### 使用前请先确认数据处理方式")
        st.caption(
            "本工具不收集姓名、手机号、邮箱等任何个人身份信息；检索历史与收藏仅保存在"
            "本机（云端为你本次会话专属目录）。唯一的例外是：翻译与大模型摘要请求会"
            "把文本发送至第三方服务，请勿在检索框粘贴患者身份信息。"
            "完整条款见左侧「🔒 隐私与数据」。"
        )
        c1, c2 = st.columns([3, 1])
        ack = c1.checkbox("我已阅读并同意上述数据处理方式", key="privacy_ack_box")
        if c2.button("查看完整政策", key="privacy_open"):
            st.session_state["pending_page"] = "隐私与数据"
            st.rerun()
        if ack:
            st.session_state["privacy_ack"] = True
            # 若本次是通过 ?page= 深链进来的，同意后要回到目标页，而不是被丢回首页
            _target = st.session_state.pop("deeplink_page", None)
            if _target and _target != "系统首页":
                st.session_state["pending_page"] = _target
            st.rerun()
        st.stop()


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
                    with logger.span("PubMed 检索", 检索式=query[:60], 条数上限=retmax):
                        results = pubmed.search_and_fetch(
                            query,
                            retmax=retmax,
                            sort="relevance" if sort_opt.startswith("按相关性") else "pub_date",
                        )
                    logger.info(f"检索完成：{len(results)} 条")
                except Exception as e:
                    logger.error("PubMed 检索失败", e)
                    st.error(f"检索失败：{pubmed.friendly_error(e)}")
                    with st.expander("技术详情"):
                        st.code(str(e)[:500])
                    results = []
            st.session_state["results"] = results
            st.session_state["last_query"] = query
            # 记录本次检索在数据库中的命中总数（综述工作台的 PRISMA 记录要用）
            st.session_state["last_total"] = pubmed.last_total()
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
        try:
            with st.spinner("正在分析文本……"):
                with logger.span("抽取式摘要", 标题=chosen_title[:40], 档位=max_sents):
                    res = summarizer.extractive_summary(text, ratio=1.0, max_sentences=max_sents, title=chosen_title)
        except Exception as e:
            logger.error("抽取式摘要生成失败", e)
            st.error("摘要生成失败，问题已记录到日志。可稍后重试或换一篇文献。")
            with st.expander("技术详情"):
                st.code(str(e)[:500])
            st.stop()
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
            with logger.span("LLM 深度总结", 模型=st.session_state.get("llm_model", ""), 标题=chosen_title[:40]):
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
            logger.error("LLM 调用失败", e)
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
                st.session_state["fig_error"] = ""
                jobs.start("图表解析", _fig_job, key=f"fig:{_pmcid_f}", pmcid=_pmcid_f)
                st.toast("图表抓取已在后台开始，页面可继续操作", icon="⏳")
        figures = st.session_state.get("figures", [])
        fig_err = st.session_state.pop("fig_error", "")
        if fig_err:
            st.error(f"❌ 图表解析失败：{fig_err}")
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
        elif st.session_state.get("figures") == [] and not fig_err:
            st.info("该文献在 PMC 全文中未解析出图表，或抓取失败。")
    elif chosen_article:
        st.caption("💡 该文献暂无 PMC 开放全文，无法解析图表；可尝试选择带「📄 PDF 全文 (PMC)」链接的文献。")


# ---------------- 页面：综述工作台（v3.0.0） ----------------
elif page == "综述工作台":
    render_review_page()


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


# ---------------- 页面：隐私与数据 ----------------
elif page == "隐私与数据":
    header("🔒 隐私与数据", "本工具的数据处理方式")
    sec_title("隐私政策与数据处理说明",
              f"版本 {APP_VERSION} · 生效日期 2026-10-07 · 本页内容与仓库 README 的「隐私」章节一致")

    st.markdown(
        """
本工具是一款开源的医学文献检索与摘要辅助工具，以本地/会话内存储为主，
不设用户账号体系。以下逐条说明数据如何被处理。

---

#### 一、适用范围

本政策适用于本工具的全部形态：Streamlit Cloud 在线版、Windows 桌面版，
以及用户自行部署的实例。桌面版不与本项目作者共享任何数据；
在线版的运行日志仅用于故障排查，不会用于识别使用者身份。

#### 二、我们不收集的信息

本工具**不收集、不存储、不传输**下列信息：

- 姓名、身份证号、手机号、邮箱地址等直接身份信息
- 用户画像、行为标签、广告标识
- 任何用于跨会话追踪的技术标识

项目代码中不存在第三方统计 SDK、广告脚本或用户行为追踪逻辑。

#### 三、本地与会话数据

| 数据类型 | 存放位置 | 可见范围 | 保留期限 |
|---|---|---|---|
| 检索历史 | 桌面版：本机 `data/history.json`；在线版：`data/users/<会话>/` | 仅本人 | 至用户主动清除 |
| 文献收藏 | 桌面版：本机 `data/favorites.json`；在线版：同上 | 仅本人 | 至用户主动删除 |
| 反馈留档 | 本机 `data/feedback/` | 仅本人 | 至用户主动删除 |

在线版的会话标识由服务端随机生成，仅用于区分不同访问者的数据目录，
不可反向推导身份，且随会话结束失效。

#### 四、结果缓存

为避免对 PubMed 公共接口与翻译额度造成重复消耗，本工具在服务器本地保留一份
**结果缓存**，涵盖检索结果、PMC 全文、抽取摘要、机器译文与大模型摘要。

- 缓存内容**全部来源于 PubMed 公开文献**，不含任何用户身份信息；
- 缓存为**全体用户共享**，以提高命中率并降低上游接口压力；
- 每类缓存设有保留期与条数上限，超出后按最久未用自动淘汰；
- 用户可在侧边栏「🩺 运行诊断」中一键清空缓存。

#### 五、第三方服务

以下操作会**由用户主动触发**并将相应文本发送至第三方服务提供方：

| 功能 | 第三方 | 发送的内容 |
|---|---|---|
| 文献检索 / 全文获取 | NCBI（PubMed / PMC） | 检索式、PMCID、DOI |
| 机器翻译 | 腾讯云机器翻译（或 MyMemory 兜底） | 待翻译的英文摘要文本 |
| 智能摘要 | 用户自填的大模型服务 | 待总结的正文或摘要文本 |

**用户应自行避免在上述输入框中粘贴患者姓名、住院号、身份证号等身份信息。**
本工具不对用户输入内容做身份信息识别与脱敏，该责任由使用者承担。

#### 六、API 凭据

用户填写的腾讯云密钥、NCBI API Key、大模型 API Key 等凭据，
**仅保存在运行进程的内存中**，不写入磁盘文件、不写入运行日志、
不随会话持久化保存。进程重启后需重新填写。

#### 七、运行日志

为便于故障定位，应用会在服务器本地记录运行日志与外部依赖健康统计，
按天滚动，保留 14 天。日志包含功能名称、耗时、请求次数与异常堆栈，
**不包含**用户检索内容与凭据。

#### 八、医疗免责声明

本工具生成的摘要、翻译与数据分析均由算法或大模型自动生成，
可能存在遗漏、偏差或曲解，**不得作为临床诊断、用药或治疗方案的依据**。
使用者应核对文献原文，并以专业医师的判断为准。

#### 九、数据来源与使用限制

文献元数据来自 PubMed / PMC（美国国立卫生研究院 NCBI 下属国家医学图书馆 NLM），
遵循 NCBI 使用条款，仅供学习与研究使用，不得用于批量抓取或商业用途。

#### 十、你的权利

由于本工具不设账号体系、不收集身份信息，**不存在需要向我们申请查询、更正或删除的个人数据**。
你随时可以在侧边栏「🩺 运行诊断」清空缓存、在「我的收藏」「检索历史」中删除记录、
在 `data/` 目录下直接删除全部本地数据。

#### 十一、政策更新

本政策如有变更，会在应用「📋 更新日志」中记录，并在本页顶部更新版本号与生效日期。
本政策随项目源码一同公开，可随时查阅历史版本。
"""
    )

    st.divider()
    st.caption("本页内容与仓库 README 的「隐私」章节保持一致；如发现不一致，以本页为准。")

    st.divider()
    st.markdown("#### 需要反馈？")
    st.caption("如对隐私处理有疑问或发现不一致，请在左侧「💬 报错 / 建议」中提交。")
    if st.button("💬 去反馈", key="privacy_feedback"):
        st.session_state["pending_page"] = "系统首页"
        st.rerun()


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
            storage.clear_history()
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


# ---------------- 全局页脚（v2.4.0）：每页底部常驻 ----------------
render_footer()
