"""P3-C3 自测：PDF 全文解析（core/pdfdoc.py）。

测试用 PDF 由本文件自带的极简生成器现场拼出来（手写对象 + 精确 xref 偏移），
不引入 reportlab / fpdf 之类的写库——测试依赖越少，跨平台越不容易坏。
标准 14 号字体只支持 ASCII，因此 PDF 级用例全部用英文；
中文标题识别等纯函数用例直接调函数，不走 PDF。

不碰真实 data/，全部在内存里完成。
"""
import io
import os
import sys
import zlib  # noqa: F401  （保留：用于将来验证压缩流用例）

os.environ.pop("MEDLIT_SCOPE", None)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import cite, pdfdoc, review, summarizer  # noqa: E402
from core import locate  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# ---------------------------------------------------------------- 极简 PDF 生成器

F1 = "/F1"   # Helvetica
F2 = "/F2"   # Helvetica-Bold


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content(lines, extra_ops: str = "") -> bytes:
    """lines: [(text, size, bold, x, y)]，y 为基线坐标；extra_ops 追加原始 PDF 操作符。"""
    out = ["BT"]
    cur = None
    for text, size, bold, x, y in lines:
        font = F2 if bold else F1
        if font != cur:
            out.append(f"{font} {size} Tf")
            cur = font
        elif cur is not None:
            out.append(f"{size} Tf")
        out.append(f"1 0 0 1 {x} {y} Tm")
        out.append(f"({_esc(text)}) Tj")
    out.append("ET")
    if extra_ops:
        out.append(extra_ops)
    return "\n".join(out).encode("latin-1", "replace")


def make_pdf(pages, info: dict | None = None) -> bytes:
    """pages: [[(text, size, bold, x, y), ...], ...]；info: 写入 /Info 的元数据。"""
    fonts = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    n_pages = len(pages)
    page_nums = [5 + 2 * i for i in range(n_pages)]

    bodies: list[bytes] = []
    # 1 catalog / 2 pages / 3 F1 / 4 F2
    bodies.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{n} 0 R" for n in page_nums)
    bodies.append(
        f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode("latin-1")
    )
    bodies += fonts

    for i, lines in enumerate(pages):
        content_num = page_nums[i] + 1
        stream = (lines if isinstance(lines, bytes) else _content(lines))
        bodies.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
             f"/Contents {content_num} 0 R >>").encode("latin-1")
        )
        bodies.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    info_num = 0
    if info:
        info_num = len(bodies) + 1
        items = " ".join(f"/{k} ({_esc(str(v))})" for k, v in info.items())
        bodies.append(f"<< {items} >>".encode("latin-1"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num, body in enumerate(bodies, start=1):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(bodies) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for num in range(1, len(bodies) + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {len(bodies) + 1} /Root 1 0 R"
    if info_num:
        trailer += f" /Info {info_num} 0 R"
    trailer += f" >>\nstartxref\n{xref_pos}\n%%EOF\n"
    out += trailer.encode("latin-1")
    return bytes(out)


def _para(prefix: str, n: int = 6) -> str:
    """拼一段足够长的正文（章节正文需 > 200 字符才会被 fulltext_summary 采纳）。"""
    base = (f"{prefix} the participants were assessed at baseline and followed for "
            f"twelve months. Primary outcomes included mortality and readmission. "
            f"Secondary outcomes included quality of life and adverse events. ")
    return (base * n).strip()


def _lines_for(spec, y0=780.0):
    """spec: [(text, size, bold)]，按行高自动排布。"""
    out = []
    y = y0
    for text, size, bold in spec:
        out.append((text, size, bold, 50.0, y))
        y -= size * 1.7
    return out


def sample_pages():
    """三页结构化学术 PDF：含标题 / 作者 / 摘要 / 引言 / 方法 / 结果 / 讨论 / 参考文献。"""
    p1 = _lines_for([
        ("Randomized Trial of Drug X in Chronic Heart Failure", 16, True),
        ("John A Smith, Jane B Doe, Robert C Brown", 10, False),
        ("Journal of Clinical Medicine", 10, False),
        ("doi:10.1000/jcm.2021.0042   Published 2021", 9, False),
        ("Abstract", 12, True),
        (_para("In this randomized trial,", 3), 10, False),
        ("Introduction", 12, True),
        (_para("Heart failure remains a major cause of", 5), 10, False),
    ])
    p2 = _lines_for([
        ("Methods", 12, True),
        (_para("We enrolled consecutive patients and randomly assigned them,", 5), 10, False),
        ("Results", 12, True),
        (_para("A total of three hundred patients completed follow up,", 3), 10, False),
        ("The hazard ratio was 0.72 (95% CI 0.58 to 0.89, P = 0.002) for the "
         "primary composite endpoint, and 41 patients (13.7%) died in the "
         "intervention group versus 62 patients (20.7%) in the control group.", 10, False),
        (_para("Pre specified subgroup analyses were consistent,", 3), 10, False),
    ])
    p3 = _lines_for([
        ("Discussion", 12, True),
        (_para("Our findings suggest that the intervention reduced", 5), 10, False),
        ("References", 12, True),
        ("1. Smith JA, et al. Lancet. 2019;393:1234-45.", 9, False),
        ("2. Doe JB, et al. N Engl J Med. 2020;382:567-78.", 9, False),
    ])
    return [p1, p2, p3]


def table_page_content() -> bytes:
    """一页带线框表格的内容流（pdfplumber 的 lines 策略靠这些描边线识别单元格）。"""
    ops = ["0.8 w"]
    xs, ys = [50, 170, 330, 480], [700, 684, 668, 652]
    for y in ys:
        ops.append(f"{xs[0]} {y} m {xs[-1]} {y} l S")
    for x in xs:
        ops.append(f"{x} {ys[0]} m {x} {ys[-1]} l S")
    lines = [
        ("Group", 9, False, 58, 689),
        ("N", 9, False, 178, 689),
        ("Event rate", 9, False, 338, 689),
        ("Drug X", 9, False, 58, 673),
        ("150", 9, False, 178, 673),
        ("0.21", 9, False, 338, 673),
        ("Placebo", 9, False, 58, 657),
        ("150", 9, False, 178, 657),
        ("0.34", 9, False, 338, 657),
    ]
    return _content(lines, extra_ops="\n".join(ops))


# ---------------------------------------------------------------- 用例

def main() -> int:
    print("[1] PDF 生成器自检")
    pdf_bytes = make_pdf(sample_pages(), info={"Title": "Randomized Trial of Drug X",
                                              "Author": "Smith JA; Doe JB"})
    check("生成物是 PDF 魔数开头", pdf_bytes.startswith(b"%PDF-1.4"))
    check("生成物含 EOF 标记", pdf_bytes.rstrip().endswith(b"%%EOF"))
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as _p:
        check("pdfplumber 能以 3 页打开", len(_p.pages) == 3, str(len(_p.pages)))

    print("\n[2] 基础解析")
    r = pdfdoc.parse_pdf(pdf_bytes, "trial.pdf")
    sects = r["sections"]
    titles = [s["title"] for s in sects]
    check("解析出多个章节", len(sects) >= 5, str(titles))
    check("识别到 Introduction", any("Introduction" in t for t in titles), str(titles))
    check("识别到 Methods", any(t.startswith("Methods") for t in titles))
    check("识别到 Results", any(t.startswith("Results") for t in titles))
    check("识别到 Discussion", any(t.startswith("Discussion") for t in titles))
    check("Abstract 成为独立章节", any(t.startswith("Abstract") for t in titles))
    check("页数统计正确", r["quality"]["n_pages"] == 3)
    check("有文本层标记为 True", r["quality"]["has_text_layer"] is True)
    check("章节标题数 > 0", r["quality"]["n_headings"] > 0, str(r["quality"]["n_headings"]))
    check("题目与正文未粘在一起",
          not any("Introduction" in t and len(t) > 40 for t in titles), str(titles))

    print("\n[3] 元数据抽取")
    meta = r["meta"]
    check("标题取内嵌元数据", meta["title"] == "Randomized Trial of Drug X", meta["title"])
    check("作者优先取正文作者行（比内嵌元数据更全）",
          meta["authors"] == ["John A Smith", "Jane B Doe", "Robert C Brown"],
          str(meta["authors"]))
    check("DOI 正确抽取", meta["doi"].startswith("10.1000/jcm.2021.0042"), meta["doi"])
    check("年份抽取为 2021", meta["year"] == "2021", meta["year"])
    check("期刊名被识别", "Journal" in meta["journal"], meta["journal"])
    check("内嵌元数据被保留", "Title" in meta["embedded"])

    print("\n[4] 无内嵌元数据时的启发式标题")
    r2 = pdfdoc.parse_pdf(make_pdf(sample_pages()), "noinfo.pdf")
    t2 = r2["meta"]["title"]
    check("启发式标题取到首页大字", t2.lower().startswith("randomized trial"), t2)
    check("启发式标题未混入期刊名", "Journal of Clinical Medicine" not in t2, t2)
    check("启发式作者可解析出 3 位", len(r2["meta"]["authors"]) >= 3, str(r2["meta"]["authors"]))

    # 正文里没有作者行时，必须退回内嵌元数据（实测 PLOS 的内嵌 Author 只登记通讯作者，
    # 因此两条路径都要有：有正文作者行时用正文，没有时才用元数据）
    no_author = make_pdf([_lines_for([
        ("A Study Without A Visible Author Line", 16, True),
        ("Abstract", 12, True),
        (_para("This study examined whether", 5), 10, False),
    ])], info={"Author": "Smith JA; Doe JB"})
    r2b = pdfdoc.parse_pdf(no_author, "ea.pdf")
    check("无正文作者行时退回内嵌元数据",
          r2b["meta"]["authors"] == ["Smith JA", "Doe JB"], str(r2b["meta"]["authors"]))
    check("超长内嵌 Title 被弃用（防版式垃圾）",
          pdfdoc._looks_like_junk_title("x" * 300) and
          pdfdoc._looks_like_junk_title("Master your IDE " * 20) and
          not pdfdoc._looks_like_junk_title("Randomized Trial of Drug X in Heart Failure"))

    print("\n[5] 表格抽取")
    tbl_pdf = make_pdf([sample_pages()[0], table_page_content()])
    rt = pdfdoc.parse_pdf(tbl_pdf, "table.pdf")
    tabs = rt["tables"]
    check("抽到至少 1 个表格", len(tabs) >= 1, f"{len(tabs)} 个")
    if tabs:
        rows = tabs[0]["rows"]
        check("表格行列数合理", len(rows) >= 2 and max(len(r_) for r_ in rows) >= 2,
              f"{len(rows)} 行 × {max(len(r_) for r_ in rows)} 列")
        flat = " ".join(c for row in rows for c in row)
        check("表格内容含 Drug X / Placebo", "Drug X" in flat and "Placebo" in flat, flat[:80])
        check("表格记录了页码", tabs[0]["page"] == 2, str(tabs[0]["page"]))
    check("quality.n_tables 与 tables 一致", rt["quality"]["n_tables"] == len(tabs))

    print("\n[6] 无文本层（扫描件）")
    blank = make_pdf([[("", 10, False, 50, 700)]])
    try:
        pdfdoc.parse_pdf(blank, "scan.pdf")
        check("扫描件应抛 PdfError", False, "未抛异常")
    except pdfdoc.PdfError as e:
        check("扫描件抛 PdfError", True)
        check("提示里点明是扫描件 / 文本层", "扫描" in str(e) or "文本层" in str(e), str(e)[:60])

    print("\n[7] 错误与边界")
    try:
        pdfdoc.parse_pdf(b"", "empty.pdf")
        check("空文件应报错", False)
    except pdfdoc.PdfError as e:
        check("空文件给出中文提示", "空" in str(e), str(e)[:40])

    try:
        pdfdoc.parse_pdf(b"this is definitely not a pdf file at all", "bad.pdf")
        check("非 PDF 应报错", False)
    except pdfdoc.PdfError as e:
        check("非 PDF 给出中文提示", "损坏" in str(e) or "不是标准" in str(e), str(e)[:50])

    old_pages = os.environ.get("MEDLIT_PDF_MAX_PAGES")
    os.environ["MEDLIT_PDF_MAX_PAGES"] = "2"
    try:
        try:
            pdfdoc.parse_pdf(pdf_bytes, "big.pdf")
            check("超页数应报错", False)
        except pdfdoc.PdfError as e:
            check("超页数给出中文提示", "页数过多" in str(e), str(e)[:50])
        check("limits() 读到环境变量", pdfdoc.limits()["max_pages"] == 2)
    finally:
        if old_pages is None:
            os.environ.pop("MEDLIT_PDF_MAX_PAGES", None)
        else:
            os.environ["MEDLIT_PDF_MAX_PAGES"] = old_pages
    check("limits() 恢复默认", pdfdoc.limits()["max_pages"] == pdfdoc.DEFAULT_MAX_PAGES)

    old_mb = os.environ.get("MEDLIT_PDF_MAX_MB")
    os.environ["MEDLIT_PDF_MAX_MB"] = "1"
    try:
        try:
            pdfdoc.parse_pdf(b"x" * (2 * 1024 * 1024), "huge.pdf")
            check("超体积应报错", False)
        except pdfdoc.PdfError as e:
            check("超体积给出中文提示", "过大" in str(e), str(e)[:50])
    finally:
        if old_mb is None:
            os.environ.pop("MEDLIT_PDF_MAX_MB", None)
        else:
            os.environ["MEDLIT_PDF_MAX_MB"] = old_mb

    os.environ["MEDLIT_PDF_MAX_MB"] = "not-a-number"
    try:
        check("非法环境变量回落到默认", pdfdoc.limits()["max_mb"] == pdfdoc.DEFAULT_MAX_MB)
    finally:
        os.environ.pop("MEDLIT_PDF_MAX_MB", None)

    print("\n[8] 文本清洗与标题判定（纯函数，含中文）")
    check("参考文献条目不被判为标题",
          not pdfdoc._looks_like_numbered_heading("30. Li KZH, Lindenberger U. Relations between aging"),
          "参考文献误判是真实 PDF 上踩到的 bug")
    check("页脚页码不被判为标题", not pdfdoc._looks_like_numbered_heading("7 / 11"))
    check("含代码符号的行不被判为标题",
          not pdfdoc._is_heading("1 #include<bits/stdc++.h>", 10, False, 10))
    check("代码块花括号行不被判为标题",
          not pdfdoc._is_heading("6 ll pow_mod(ll a,ll b){", 10, False, 10))
    check("正文句子不被判为编号标题",
          not pdfdoc._looks_like_numbered_heading("2 patients were excluded from the analysis"))
    check("带编号的真实小标题仍被识别",
          pdfdoc._looks_like_numbered_heading("2.1 Statistical analysis"))
    check("中文编号小标题仍被识别",
          pdfdoc._looks_like_numbered_heading("一、研究对象"))
    check("连字符断词被还原",
          pdfdoc.clean_text("inflamma-\ntion of the heart") == "inflammation of the heart",
          pdfdoc.clean_text("inflamma-\ntion of the heart"))
    check("软换行合并为空格",
          pdfdoc.clean_text("hello\nworld") == "hello world")
    check("段落空行保留",
          pdfdoc.clean_text("para one\n\npara two") == "para one\n\npara two",
          repr(pdfdoc.clean_text("para one\n\npara two")))
    check("多余空白被压缩", pdfdoc.clean_text("a    b") == "a b")
    check("中文摘要被判为标题", pdfdoc._is_heading("摘要", 10, False, 10))
    check("中文引言被判为标题", pdfdoc._is_heading("引言", 10, False, 10))
    check("中文参考文献被判为标题", pdfdoc._is_heading("参考文献", 10, False, 10))
    check("编号小标题被判为标题", pdfdoc._is_heading("2.1 Statistical analysis", 10, False, 10))
    check("中文编号标题被判为标题", pdfdoc._is_heading("一、研究对象", 10, False, 10))
    check("普通正文不被判为标题",
          not pdfdoc._is_heading("this is a normal sentence of body text.", 10, False, 10))
    check("图表题注不被判为标题",
          not pdfdoc._is_heading("Table 1. Baseline characteristics", 10, False, 10))
    check("过长文本不被判为标题",
          not pdfdoc._is_heading("word " * 30, 14, True, 10))
    check("放大字号被判为标题", pdfdoc._is_heading("Study Design", 13, False, 10))
    check("作者行拆分为 2 人以上",
          len(pdfdoc._split_authors("Smith J, Jones AB, and Brown C")) >= 2,
          str(pdfdoc._split_authors("Smith J, Jones AB, and Brown C")))
    check("机构名被剔除",
          all("University" not in a for a in pdfdoc._split_authors("Smith J, Oxford University")),
          str(pdfdoc._split_authors("Smith J, Oxford University")))
    check("正文基准字号按字符数加权",
          pdfdoc._body_size([
              {"chars": [{"text": "T", "size": 18.0}]},
              {"chars": [{"text": c, "size": 10.0} for c in "abcdefghij"]},
          ]) == 10.0)

    print("\n[9] 与下游模块对接（复用同一流水线）")
    secs = r["sections"]
    ft = summarizer.fulltext_summary(secs, title=meta["title"], max_sentences=8)
    check("fulltext_summary 产出非空摘要", bool(ft["summary"]), str(ft["used_sections"]))
    check("摘要分节带 title_zh", all("title_zh" in p for p in ft["sections"]))

    an = summarizer.analyze_fulltext(secs)
    check("analyze_fulltext 词数 > 0", an["total_words"] > 0, str(an["total_words"]))
    check("analyze_fulltext 有章节分布", len(an["section_stats"]) >= 5)

    idx = locate.build_index(secs)
    stat = locate.index_stats(idx)
    check("locate 索引有句子", stat["sentences"] > 0, str(stat))
    check("关键词检索命中",
          len(locate.search_keyword(idx, "participants")) > 0)
    check("数值定位能抽到指标", len(locate.find_values(idx)) >= 1,
          str(list(locate.find_values(idx).keys())[:5]))

    art = pdfdoc.to_article(r, "trial.pdf")
    check("to_article 标题正确", art["title"] == meta["title"], art["title"])
    check("to_article 标记来源为 PDF", art["source"] == "PDF 上传" and art["is_pdf"])
    check("to_article pmid 故意留空", art["pmid"] == "")
    check("to_article 摘要取到 Abstract 章节",
          "randomized trial" in art["abstract"].lower(), art["abstract"][:60])

    rows = review.build_comparison([art])
    check("综述引擎能消费 PDF 文献", len(rows) == 1, str(len(rows)))
    check("对比表含研究设计列", "研究设计" in rows[0], str(list(rows[0].keys())[:6]))
    check("对比表带出标题", rows[0]["标题"] == meta["title"], rows[0]["标题"])
    check("偏倚评估不崩溃", isinstance(review.assess_bias(art), dict))
    check("适用性评估不崩溃", isinstance(review.assess_applicability(art), dict))

    for fmt in cite.FORMAT_KEYS:
        out = cite.render([art], fmt)
        check(f"引用导出 {cite.label(fmt)} 非空", bool(out and out.strip()), str(out)[:50])
    bib = cite.render([art], "bibtex")
    check("BibTeX 含标题", meta["title"][:20] in bib, bib[:120])
    check("BibTeX 含 DOI", "10.1000" in bib, bib[:200])
    check("Vancouver 含作者", "Smith" in cite.render([art], "vancouver"))

    print("\n[10] 导出与渲染")
    md = pdfdoc.summary_markdown(r, "trial.pdf")
    check("Markdown 导出含标题", md.startswith("# Randomized Trial of Drug X"), md[:60])
    check("Markdown 导出含全部章节",
          all(s["title"] in md for s in secs))
    png = pdfdoc.render_page_png(pdf_bytes, 1)
    check("页面渲染产出 PNG", png[:8] == b"\x89PNG\r\n\x1a\n", str(png[:8]))
    check("渲染出的图非空", len(png) > 5000, f"{len(png)} bytes")
    try:
        pdfdoc.render_page_png(pdf_bytes, 99)
        check("越界页码应报错", False)
    except pdfdoc.PdfError as e:
        check("越界页码给出中文提示", "页码" in str(e), str(e)[:40])

    print("\n[11] 双栏与页边（本次修复的核心：实测 PLOS 论文的版面结构）")
    # 左栏 x=50..290，右栏 x=310..550，装订线 20pt；正文足够高以满足覆盖率阈值
    left = [("Introduction", 12, True, 50, 700.0)]
    right = [("Methods", 12, True, 310, 700.0)]
    for i in range(14):
        left.append((f"LEFTCOL{i} " + _para("alpha beta gamma", 1), 10, False, 50, 682.0 - i * 12))
        right.append((f"RIGHTCOL{i} " + _para("delta epsilon zeta", 1), 10, False, 310, 682.0 - i * 12))
    two_col = make_pdf([left + right])
    tc = pdfdoc.parse_pdf(two_col, "twocol.pdf")
    ordered = [s["title"] for s in tc["sections"]]
    joined = " ".join(s["text"] for s in tc["sections"])
    lpos, rpos = joined.find("LEFTCOL0"), joined.find("RIGHTCOL0")
    check("双栏被识别为两个独立章节",
          any(t.startswith("Introduction") for t in ordered) and
          any(t.startswith("Methods") for t in ordered), str(ordered))
    check("左栏内容整体先于右栏（正确阅读顺序）", 0 <= lpos < rpos, f"left={lpos} right={rpos}")
    check("未把左右栏并成同一行",
          "LEFTCOL0" in joined and "RIGHTCOL13" in joined and
          joined.find("LEFTCOL13") < joined.find("RIGHTCOL0"))
    check("双栏页不误判页边", tc["quality"]["n_marginalia"] == 0)

    # 主栏 + 出版社元数据边栏（PLOS 结构）：边栏必须被剔除，不能混进正文摘要
    # 注意边栏行要够短且在窄栏内换行——真实 PLOS 边栏宽约 136pt，写长了会和主栏粘连
    main = [("Introduction", 12, True, 198, 760.0)]
    side = []
    labels = ["Citation: Sudo D, Toyoda D",
              "Editor: Tadashi Ito, Aichi",
              "Received: March 3, 2026",
              "Copyright: 2026 Sudo, Toyoda",
              "Data Availability: Yes",
              "Funding: JSPS KAKENHI"]
    for i in range(22):
        side.append((labels[i] if i < len(labels) else f"JAPAN note {i}",
                     8, False, 36, 750.0 - i * 12))
    for i in range(22):
        main.append((f"MAINLINE{i} " + _para("heart failure patients were", 1),
                     10, False, 198, 742.0 - i * 12))
    marg_pdf = make_pdf([side + main])
    mp = pdfdoc.parse_pdf(marg_pdf, "marg.pdf")
    mtext = " ".join(s["text"] for s in mp["sections"])
    check("识别出元数据边栏", mp["quality"]["n_marginalia"] == 1,
          str(mp["quality"]["n_marginalia"]))
    check("边栏文字未混入正文", "Tadashi Ito" not in mtext and "Copyright: 2026" not in mtext)
    check("正文内容完整保留", "MAINLINE0" in mtext and "MAINLINE21" in mtext)
    check("剔除边栏有明确提示",
          any("边栏" in w for w in mp["quality"]["warnings"]), str(mp["quality"]["warnings"]))

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
