"""医学文献智能摘要与检索系统 — Streamlit 应用"""
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from core import pubmed, summarizer, storage

st.set_page_config(
    page_title="医学文献智能摘要与检索系统",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- 全局样式 ----------------
st.markdown(
    """
    <style>
    .main-header {
        background: linear-gradient(135deg, #1a6fb5 0%, #2e9e8f 100%);
        padding: 1.6rem 2rem; border-radius: 14px; margin-bottom: 1.2rem;
    }
    .main-header h1 { color: #ffffff; margin: 0; font-size: 1.7rem; }
    .main-header p { color: #e3f2fd; margin: 0.4rem 0 0 0; font-size: 0.95rem; }
    div[data-testid="stExpander"] { border-radius: 10px; }
    .kw-chip {
        display:inline-block; background:#e8f4fd; color:#1565c0; border-radius:12px;
        padding:2px 10px; margin:2px 4px 2px 0; font-size:0.82rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def header():
    st.markdown(
        """
        <div class="main-header">
            <h1>🩺 医学文献智能摘要与检索系统</h1>
            <p>PubMed 检索 · 摘要长度可选 · 图表解析 · PDF 全文链接 · 收藏管理</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------- 侧边栏 ----------------
with st.sidebar:
    st.markdown("### 🧭 功能导航")
    page = st.radio(
        "页面",
        ["🏠 系统首页", "🔍 文献检索", "📝 智能摘要", "⭐ 我的收藏", "🕘 检索历史", "📋 更新日志"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("### 🤖 大模型设置（可选）")
    st.caption("配置 OpenAI 兼容接口后，智能摘要页可使用 LLM 生成深度总结；不配置也能使用内置抽取式摘要。")
    llm_base = st.text_input("API Base URL", value=st.session_state.get("llm_base", ""), placeholder="https://api.openai.com")
    llm_key = st.text_input("API Key", value=st.session_state.get("llm_key", ""), type="password")
    llm_model = st.text_input("模型名称", value=st.session_state.get("llm_model", ""), placeholder="gpt-4o-mini")
    st.session_state["llm_base"] = llm_base
    st.session_state["llm_key"] = llm_key
    st.session_state["llm_model"] = llm_model
    llm_ready = bool(llm_base and llm_key and llm_model)
    st.caption("✅ LLM 已就绪" if llm_ready else "⚪ 未配置，仅使用抽取式摘要")

    st.divider()
    st.caption("数据源：PubMed E-utilities（NCBI 官方公开 API）\n\n检索结果仅用于研究学习，不构成医疗建议。")


# ---------------- 工具函数 ----------------
APP_VERSION = "v1.2.1"

CHANGELOG = [
    {
        "version": "v1.2.1",
        "date": "2026-09-23",
        "tag": "最新版本",
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
        with st.container(border=True):
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                    <span style="font-size:1.25rem; font-weight:700;">{rel['version']}</span>
                    <span style="background:{badge_color}; color:#fff; border-radius:12px;
                                  padding:2px 12px; font-size:0.8rem;">{rel['tag']}</span>
                    <span style="color:#888; font-size:0.85rem;">{rel['date']}</span>
                </div>
                """,
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


# ---------------- 页面：首页 ----------------
if page == "🏠 系统首页":
    header()
    st.markdown(
        f"""
        <div style="margin:-0.8rem 0 1rem 0;">
            <span style="background:#2e9e8f; color:#fff; border-radius:12px;
                         padding:3px 14px; font-size:0.85rem;">当前版本 {APP_VERSION}</span>
            <span style="color:#888; font-size:0.85rem; margin-left:8px;">
                📋 新功能详见左侧「更新日志」</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 🔍 智能检索")
        st.write("接入 PubMed 官方 API，支持关键词、作者、发表日期过滤，自动拼写纠错建议，一键跳转原文。")
    with c2:
        st.markdown("### 📝 智能摘要")
        st.write("内置抽取式摘要引擎（词频-位置加权），离线即可快速提炼核心句与关键词；配置 LLM 后可生成结构化深度总结。")
    with c3:
        st.markdown("### ⭐ 收藏管理")
        st.write("收藏感兴趣的文献，支持导出，检索历史自动留存，方便回溯。")
    st.divider()
    favs = storage.list_favorites()
    hist = storage.list_history(5)
    m1, m2 = st.columns(2)
    with m1:
        st.metric("已收藏文献", len(favs))
    with m2:
        st.metric("累计检索次数", len(storage.list_history(200)))
    if hist:
        st.markdown("**最近检索**")
        for h in hist[:3]:
            st.caption(f"· {h['time']} — {h['query']}（{h['n_results']} 条结果）")


# ---------------- 页面：文献检索 ----------------
elif page == "🔍 文献检索":
    header()
    col_q, col_n = st.columns([4, 1])
    with col_q:
        keyword = st.text_input("检索关键词", placeholder="例如：immunotherapy lung cancer", key="kw")
    with col_n:
        retmax = st.select_slider("返回条数", options=[5, 10, 20, 30, 50], value=10)

    with st.expander("⚙️ 高级检索条件"):
        c1, c2, c3 = st.columns(3)
        with c1:
            author = st.text_input("作者（可选）", placeholder="例如：Smith J")
        with c2:
            start_date = st.text_input("起始日期 YYYY/MM/DD", placeholder="2022/01/01")
        with c3:
            end_date = st.text_input("结束日期 YYYY/MM/DD", placeholder="2026/09/21")
        sort_opt = st.radio(
            "排序方式",
            ["按相关性", "按发表时间（最新优先）"],
            horizontal=True,
        )

    if st.button("🔍 开始检索", type="primary", use_container_width=True):
        if not keyword.strip():
            st.warning("请输入检索关键词")
        else:
            query = pubmed.build_query(keyword, author, start_date, end_date)
            with st.spinner("正在检索 PubMed ..."):
                try:
                    results = pubmed.search_and_fetch(
                        query,
                        retmax=retmax,
                        sort="relevance" if sort_opt.startswith("按相关性") else "pub_date",
                    )
                except Exception as e:
                    st.error(f"检索失败：{e}")
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
        st.caption(f"检索式：`{st.session_state['last_query']}` — 共 {len(results)} 条结果")
    for a in results:
        article_card(a)
    if not results and st.session_state.get("last_query"):
        st.info("没有检索到文献，试试更宽泛的关键词。")


# ---------------- 页面：智能摘要 ----------------
elif page == "📝 智能摘要":
    header()
    st.markdown("#### 1️⃣ 选择摘要来源")
    source = st.radio(
        "来源",
        ["从最近检索结果中选择", "直接粘贴文本 / 摘要"],
        horizontal=True,
    )
    text = ""
    chosen_title = ""
    chosen_article = None
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
        lang = st.radio("摘要输出语言", ["中文", "英文"], horizontal=True, index=0)
        length_label = st.radio(
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
            st.markdown(f"#### 📄 摘要结果 — {chosen_title}（{length_label}{lang_tag}）")
            st.markdown(summary_out)
            if res["key_terms"]:
                st.markdown("**🔑 关键词**")
                st.markdown("".join(f'<span class="kw-chip">{k}</span>' for k in res["key_terms"][:8]), unsafe_allow_html=True)
            with st.expander("📊 句子重要性得分（Top 语句）"):
                for s, sc in res["scores"][:max_sents]:
                    st.markdown(f"`{sc}` {s[:120]}...")
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
                st.markdown(f"#### 🤖 LLM 深度总结 — {chosen_title}（{length_label}）")
                st.markdown(out)
                st.download_button("⬇️ 导出总结 (Markdown)", out, file_name="llm_summary.md")
            except Exception as e:
                st.error(f"LLM 调用失败：{e}（请检查 API 地址 / Key / 模型名，以及网络连通性）")
    else:
        if source == "直接粘贴文本 / 摘要":
            st.info("👆 粘贴文本后即可生成摘要")

    # ---------------- 全文摘要与数据分析（v1.2.0） ----------------
    if chosen_article and chosen_article.get("pmcid"):
        st.divider()
        st.markdown("#### 2️⃣ 全文摘要与数据分析（基于 PMC 开放全文）")
        st.caption(f"检测到 PMC 全文（{chosen_article['pmcid']}），可对论文正文（引言/方法/结果/讨论）做章节化摘要与统计分析。")
        ft_max = st.select_slider("全文摘要句子数", options=[6, 8, 10, 12, 15], value=8)
        if st.button("📚 抓取全文并生成全文摘要", type="primary"):
            try:
                with st.spinner("正在抓取全文……"):
                    secs = pubmed.fetch_pmc_fulltext(chosen_article["pmcid"])
                if not secs:
                    st.error("未能解析出全文内容。")
                else:
                    with st.spinner("正在生成章节化全文摘要与数据分析……"):
                        st.session_state["fulltext"] = secs
                        st.session_state["ft_summary"] = summarizer.fulltext_summary(
                            secs, title=chosen_title, max_sentences=ft_max
                        )
                        st.session_state["ft_analytics"] = summarizer.analyze_fulltext(secs)
            except Exception as e:
                st.error(f"全文抓取失败：{e}")

        if st.session_state.get("ft_summary"):
            ft = st.session_state["ft_summary"]
            an = st.session_state["ft_analytics"]
            summary_text = ft["summary"]

            # 中文输出
            ft_out = summary_text
            if lang == "中文" and summarizer.is_mostly_english(summary_text):
                with st.spinner("正在将全文摘要翻译为中文……"):
                    try:
                        ft_out = summarizer.translate_text(summary_text, "en|zh-CN")
                    except Exception as e:
                        st.warning(f"翻译失败（{e}），显示英文原句")
            st.markdown("#### 📚 全文摘要")
            st.markdown(ft_out)

            # ---- 数据分析面板 ----
            st.markdown("#### 📊 全文数据分析")
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
            st.markdown(
                "".join(
                    f'<span class="kw-chip">{k} <b>{kc[k]}</b></span>' if k in kc else f'<span class="kw-chip">{k}</span>'
                    for k in an["keywords"]
                ),
                unsafe_allow_html=True,
            )

            st.markdown("**🔬 关键统计指标提取**")
            if an["metrics"]:
                for name, m in an["metrics"].items():
                    with st.expander(f"{name} — 全文 {m['count']} 处"):
                        st.markdown("".join(f'<span class="kw-chip">{v}</span>' for v in m["samples"]), unsafe_allow_html=True)
            else:
                st.caption("未在全文中提取到常见统计指标。")

            st.download_button("⬇️ 导出全文摘要 (Markdown)", ft_out, file_name="fulltext_summary.md")

    # ---------------- 文献图表解析（需要 PMC 开放全文） ----------------
    if chosen_article and chosen_article.get("pmcid"):
        st.divider()
        st.markdown("#### 3️⃣ 文献图表解析（图片视图 + 说明概括）")
        st.caption(f"检测到该文献有 PMC 开放全文（{chosen_article['pmcid']}），可抓取文中图表进行查看与概括。")
        if st.button("🖼 加载并解析文献图表", type="secondary"):
            try:
                with st.spinner("正在从 PMC 抓取图表……"):
                    figures = pubmed.fetch_pmc_figures(chosen_article["pmcid"])
                    if figures:
                        with st.spinner("正在下载图片包……"):
                            pubmed.fetch_figure_images(chosen_article["pmcid"], figures)
                    figures = [f for f in figures if f.get("data")]
                st.session_state["figures"] = figures
            except Exception as e:
                st.error(f"图表抓取失败：{e}")
                st.session_state["figures"] = []
        figures = st.session_state.get("figures", [])
        if figures:
            st.success(f"共解析出 {len(figures)} 张图表")
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
                st.markdown("#### 🧩 图表信息概括（内置引擎）")
                st.markdown(fig_res["summary"])
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
                        st.markdown("#### 🤖 图表信息概括（LLM）")
                        st.markdown(fig_llm)
                    except Exception as e:
                        st.error(f"LLM 调用失败：{e}")
        elif st.session_state.get("figures") == []:
            st.info("该文献在 PMC 全文中未解析出图表，或抓取失败。")
    elif chosen_article:
        st.caption("💡 该文献暂无 PMC 开放全文，无法解析图表；可尝试选择带「📄 PDF 全文 (PMC)」链接的文献。")


# ---------------- 页面：我的收藏 ----------------
elif page == "⭐ 我的收藏":
    header()
    favs = storage.list_favorites()
    if not favs:
        st.info("暂无收藏。去「文献检索」页点击 ⭐ 收藏文献吧。")
    else:
        st.caption(f"共 {len(favs)} 篇收藏")
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
        q = st.text_input("🔎 在收藏中筛选", placeholder="输入标题/作者关键词")
        for f in favs:
            if q and q.lower() not in (f["title"] + " " + " ".join(f.get("authors", []))).lower():
                continue
            article_card(f)


# ---------------- 页面：更新日志 ----------------
elif page == "📋 更新日志":
    header()
    st.markdown(f"#### 📋 更新日志（当前版本 {APP_VERSION}）")
    st.caption("本系统的功能随版本迭代持续增加，最新改动在页面顶部。完整说明可查阅项目中的「使用说明.md」文件。")
    st.write("")
    render_changelog()


# ---------------- 页面：检索历史 ----------------
elif page == "🕘 检索历史":
    header()
    hist = storage.list_history()
    if not hist:
        st.info("暂无检索历史。")
    else:
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
