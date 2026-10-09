"""MeSH 词表联动（P3-C5）。

**要解决的问题**：现在是裸关键词检索，漏同义词就丢结果。PubMed 本身有「自动词表映射」
（ATM），但它只在关键词与 MeSH 标题或入口词**精确匹配**时才生效；一旦用户加了字段限定
（``aspirin[tiab]``）ATM 就被完全绕过 —— 这正是「明明有同义词却搜不到」的根因。

**本模块做什么**：把 MeSH 词表显式查出来，让用户看到「PubMed 会怎么理解这个词」，
并可选地把描述符标题 + 入口词 OR 进检索式（例如把 ``lung cancer`` 展开成
``("Lung Neoplasms"[MeSH Terms] OR "Lung Cancer"[tiab] OR "Cancer of the Lung"[tiab] …)``）。

**两个必须守住的纪律**：

1. **不猜**。``db=mesh`` 的 esearch 是**模糊**检索——搜 ``aspirin`` 首条返回的是
   「Asthma, Aspirin-Induced」而不是 Aspirin 描述符。所以必须取回候选逐个校验，
   只有「标题精确匹配」或「出现在入口词表里」才算命中；没有把握就返回 ``None``，
   绝不把「最像的那条」当成用户的意思。
2. **不越界**。关键词里已经带了布尔运算符或字段限定（``[tiab]`` ``[Mesh]`` ``AND`` …）时
   不做任何改写，直接跳过并说明原因——那是用户手写的检索式，机器不该动。

数据源：NCBI E-utilities 的 ``db=mesh``（esearch + esummary），统一走 ``core/http.py``
（超时 / 退避重试 / 域名限流 / 埋点），不进新的第三方依赖。
缓存：MeSH 词表一年才更新一次，TTL 设 365 天。
"""
from __future__ import annotations

import re

from core import cache, http, logger

MESH_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
MESH_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
HEADERS = {"User-Agent": http.USER_AGENT}

# 每次 lookup 取回的候选条数。取多了浪费配额，取少了漏掉正确描述符；
# 实测 8 条足以覆盖 "aspirin"（73 条命中里 Aspirin 排第 2）这类常见歧义词。
_CANDIDATES = 8

# 单次 analyze 最多发起多少次 db=mesh 查询（每次 2 个 HTTP 请求）。
# 多词关键词按 n-gram 切分时呈平方增长，必须封顶，否则一个长句子会打几十个请求。
_MAX_LOOKUPS = 8

# 扩展检索式里每个概念最多带几个入口词。PubMed 的 GET 检索式有长度上限
# （过长会被服务器截断或返回 414），而且同义词堆太多会显著伤精确度。
_MAX_ENTRY_TERMS = 6

# 展开后的检索式总长上限，超出就不再追加同义词。
_MAX_EXPR_LEN = 1400

# 这些词单独拿出来查 MeSH 没有意义，直接跳过（省配额、也避免误命中）
_STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "with", "and", "or", "not",
    "by", "from", "at", "as", "is", "are", "be", "between", "among", "after",
    "before", "during", "vs", "versus", "study", "trial", "review", "patients",
    "patient", "effect", "effects", "role", "impact", "outcomes", "outcome",
}

# 出现这些记号说明用户写的是「手写检索式」而不是「几个关键词」，不做改写
_FIELD_QUALIFIER_RE = re.compile(r"\[[a-z0-9 /_-]{2,30}\]", re.I)
_BOOL_OP_RE = re.compile(r"(?:^|\s)(?:AND|OR|NOT)(?:\s|$)", re.I)
_JUNK_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.U)


# --------------------------------------------------------------------- 工具
def _key(s: str) -> str:
    """把词压成比较用的键：小写并去掉所有非字母数字。

    这样 ``PD-1`` 与 ``pd1``、``Lung Neoplasms`` 与 ``lung neoplasms`` 都能对上，
    同时不改变原词（MeSH 入口词里的连字符有实际含义，不能拿归一化后的串去检索）。
    """
    return _JUNK_RE.sub("", (s or "").lower())


def is_plain_keyword(keyword: str) -> bool:
    """关键词是否为「普通关键词串」（可以直接做 MeSH 分析）。

    带字段限定 ``[tiab]`` 或布尔运算符的算手写检索式，不改写。
    """
    k = (keyword or "").strip()
    if not k:
        return False
    if _FIELD_QUALIFIER_RE.search(k) or _BOOL_OP_RE.search(k):
        return False
    # 引号短语也交给用户自己控制（引号会关掉 PubMed 的自动词表映射）
    if '"' in k or "“" in k or "”" in k:
        return False
    return True


def tokenize(keyword: str) -> list[str]:
    """按空白切词，丢掉纯标点与停用词。"""
    out = []
    for t in re.split(r"\s+", (keyword or "").strip()):
        t = t.strip(" ,;:()（）[]\"'“”‘’")
        if not t or not _JUNK_RE.sub("", t):
            continue
        if t.lower() in _STOPWORDS:
            continue
        out.append(t)
    return out


# ----------------------------------------------------------------- 词表查询
def _fetch_candidates(term: str) -> list[dict]:
    """查 db=mesh，取回候选记录（不判断对错，只负责取数）。"""
    ck = cache.digest("mesh-cand", term.lower(), _CANDIDATES)
    hit = cache.get("mesh", ck)
    if hit is not None:
        return hit

    records: list[dict] = []
    try:
        r = http.get(
            MESH_ESEARCH,
            params={"db": "mesh", "term": term, "retmode": "json", "retmax": str(_CANDIDATES)},
            headers=HEADERS, timeout=25, retries=2,
        )
        ids = (r.json().get("esearchresult", {}) or {}).get("idlist") or []
        if ids:
            r2 = http.get(
                MESH_ESUMMARY,
                params={"db": "mesh", "id": ",".join(ids), "retmode": "json"},
                headers=HEADERS, timeout=25, retries=2,
            )
            result = r2.json().get("result") or {}
            for uid in ids:
                rec = result.get(uid) or {}
                terms = [str(t).strip() for t in (rec.get("ds_meshterms") or []) if str(t).strip()]
                if not terms:
                    continue
                tree = []
                for link in rec.get("ds_idxlinks") or []:
                    tn = (link or {}).get("treenum")
                    # 补充概念记录（SCR，如药物）给的是 @ 开头的占位树号，不是真树号
                    if tn and not tn.startswith("@"):
                        tree.append(tn)
                records.append({
                    "ui": uid,
                    "heading": re.sub(r"\s+", " ", terms[0]).strip(),
                    "entry_terms": terms,
                    "type": (rec.get("ds_recordtype") or "descriptor").strip() or "descriptor",
                    "mapped_to": (rec.get("ds_headingmappedto") or "").strip(),
                    "scope_note": (rec.get("ds_scopenote") or "").strip(),
                    "tree_numbers": tree,
                })
    except Exception as e:                     # 网络失败只记日志，不影响检索主流程
        logger.warning(f"MeSH 词表查询失败（{term[:30]}）：{type(e).__name__} {e}")

    cache.put("mesh", ck, records)
    return records


def lookup(term: str) -> dict | None:
    """查一个词对应的 MeSH 描述符；没有把握命中时返回 ``None``。

    判定顺序：
    1. **标题精确匹配**（``matched_by="heading"``）——最可靠；
    2. **出现在入口词表里**（``matched_by="entry_term"``）——例如 ``heart attack``
       命中 Myocardial Infarction；
    3. 都不满足 → ``None``。像 ``diabetes`` 这种 MeSH 里并没有同名描述符
       （只有 Diabetes Mellitus）的词，就属于第 3 种，返回 ``None`` 而不是猜。

    **限定词（qualifier）一律不算命中**。``therapy`` / ``diagnosis`` / ``prevention``
    在 db=mesh 里的首条命中都是副主题词（tree Y11 / Y04），它们只能挂在描述符后面
    组合使用（``Aspirin/therapy``），单独拿出来当检索概念是错的。
    补充概念记录（supplemental-record）则保留——药物与化学物质都在这里。
    """
    term = (term or "").strip()
    if not term or len(term) < 2:
        return None
    want = _key(term)
    if not want:
        return None

    candidates = [c for c in _fetch_candidates(term) if c.get("type") != "qualifier"]
    if not candidates:
        return None

    for rec in candidates:
        if _key(rec["heading"]) == want:
            return {**rec, "matched_by": "heading", "query": term}
    for rec in candidates:
        if any(_key(t) == want for t in rec["entry_terms"][1:]):
            return {**rec, "matched_by": "entry_term", "query": term}
    return None


# ------------------------------------------------------- 多词关键词的概念切分
def split_concepts(keyword: str) -> list[dict]:
    """把关键词切成若干概念，并对每个概念查 MeSH（最长匹配优先）。

    例：``immunotherapy lung cancer`` → 先试 3 词整串（无命中），再试 2 词窗口，
    ``lung cancer`` 命中 Lung Neoplasms，剩下的 ``immunotherapy`` 单独命中 Immunotherapy。

    返回 ``[{"text":…, "mesh":…|None}, …]``，顺序与原文一致。
    """
    tokens = tokenize(keyword)
    if not tokens:
        return []

    matched: dict[int, dict] = {}     # 起始下标 → 概念
    used: set[int] = set()
    lookups = 0

    for span in range(len(tokens), 0, -1):          # 词数从多到少
        for start in range(0, len(tokens) - span + 1):
            if any(i in used for i in range(start, start + span)):
                continue
            if lookups >= _MAX_LOOKUPS:
                break
            text = " ".join(tokens[start:start + span])
            lookups += 1
            rec = lookup(text)
            if rec:
                matched[start] = {"text": text, "mesh": rec}
                used.update(range(start, start + span))
        if lookups >= _MAX_LOOKUPS:
            break

    # 未被任何 MeSH 概念覆盖的词，各自作为一个「未匹配」概念保留在原位
    concepts: list[dict] = []
    i = 0
    while i < len(tokens):
        if i in matched:
            concepts.append(matched[i])
            i += len(matched[i]["text"].split(" "))
        else:
            concepts.append({"text": tokens[i], "mesh": None})
            i += 1
    return concepts


def analyze(keyword: str) -> dict:
    """分析关键词里的 MeSH 概念，产出供 UI 展示与检索式构建的报告。"""
    report = {
        "keyword": (keyword or "").strip(),
        "skipped": False,
        "skip_reason": "",
        "concepts": [],
        "matched": 0,
    }
    if not report["keyword"]:
        report["skipped"] = True
        report["skip_reason"] = "关键词为空"
        return report
    if not is_plain_keyword(report["keyword"]):
        report["skipped"] = True
        report["skip_reason"] = (
            "关键词里含字段限定（如 [tiab]）、布尔运算符或引号短语，"
            "属于手写检索式，不做 MeSH 改写"
        )
        return report

    concepts = split_concepts(report["keyword"])
    report["concepts"] = concepts
    report["matched"] = sum(1 for c in concepts if c["mesh"])
    logger.info(
        f"MeSH 分析：{report['keyword'][:40]} → {report['matched']}/{len(concepts)} 个概念命中"
    )
    return report


# ------------------------------------------------------------ 检索式扩展
def _entry_terms_for(rec: dict) -> list[str]:
    """挑出可用的入口词：去掉与标题同义的、太短的、与已选重复的。"""
    picked: list[str] = []
    seen = {_key(rec.get("heading", ""))}
    for t in rec.get("entry_terms") or []:
        k = _key(t)
        if not k or k in seen or len(k) < 3:
            continue
        seen.add(k)
        picked.append(t)
        if len(picked) >= _MAX_ENTRY_TERMS:
            break
    return picked


def concept_expression(concept: dict) -> str:
    """把单个概念渲染成检索式片段。"""
    rec = concept.get("mesh")
    text = (concept.get("text") or "").strip()
    if not rec:
        # 没查到 MeSH：多词加引号（当作短语），单词原样
        return f'"{text}"' if " " in text else text

    parts = [f'"{rec["heading"]}"[MeSH Terms]']
    for t in _entry_terms_for(rec):
        parts.append(f'"{t}"[tiab]')
    # 用户原话也带上：入口词表未必覆盖口语写法（如 "lung cancer" 虽在表里，
    # 但 "NSCLC" 这类缩写就不在），加上它成本极低
    if _key(text) not in {_key(rec["heading"])} | {_key(t) for t in _entry_terms_for(rec)}:
        parts.append(f'"{text}"[tiab]' if " " in text else f'{text}[tiab]')

    inner = " OR ".join(parts)
    return f"({inner})" if len(parts) > 1 else inner


def expand_expression(keyword: str, report: dict | None = None) -> str:
    """按 MeSH 概念把关键词展开成显式检索式；无可用概念时原样返回关键词。

    用 AND 连接各概念，与 PubMed 对空格分隔关键词的默认语义一致。
    """
    report = report or analyze(keyword)
    if report.get("skipped") or not report.get("concepts"):
        return keyword
    if not report.get("matched"):
        return keyword

    pieces: list[str] = []
    for c in report["concepts"]:
        expr = concept_expression(c)
        if sum(len(p) for p in pieces) + len(expr) > _MAX_EXPR_LEN:
            # 超长就不再展开剩余概念，直接用原词，避免检索式被服务器截断
            pieces.append(c["text"])
        else:
            pieces.append(expr)
    return " AND ".join(pieces)


def expand_markdown(report: dict, keyword: str = "") -> str:
    """把分析报告导出成 Markdown（供 ZIP 打包与「复制检索式」）。"""
    lines = ["# MeSH 概念分析", ""]
    kw = keyword or report.get("keyword", "")
    lines.append(f"- 关键词：`{kw}`")
    if report.get("skipped"):
        lines.append(f"- 未做分析：{report.get('skip_reason', '')}")
        return "\n".join(lines) + "\n"

    concepts = report.get("concepts") or []
    lines.append(f"- 概念数：{len(concepts)}，其中命中 MeSH：{report.get('matched', 0)}")
    lines.append("")
    for i, c in enumerate(concepts, 1):
        rec = c.get("mesh")
        if not rec:
            lines.append(f"{i}. **{c['text']}** —— 未在 MeSH 中找到对应描述符（按原词检索）")
            continue
        how = "标题精确匹配" if rec.get("matched_by") == "heading" else "命中入口词表"
        lines.append(f"{i}. **{c['text']}** → **{rec['heading']}**（{how}，MeSH UI {rec['ui']}）")
        if rec.get("scope_note"):
            lines.append(f"   - 定义：{rec['scope_note']}")
        if rec.get("tree_numbers"):
            lines.append(f"   - 树号：{', '.join(rec['tree_numbers'][:4])}")
        entries = _entry_terms_for(rec)
        if entries:
            lines.append(f"   - 入口词（{len(rec['entry_terms']) - 1} 个，展示 {len(entries)}）："
                         + "、".join(entries))
    lines.append("")
    lines.append("## 扩展后的检索式")
    lines.append("")
    lines.append("```")
    lines.append(expand_expression(kw, report))
    lines.append("```")
    lines.append("")
    lines.append("> 说明：PubMed 的自动词表映射（ATM）只在关键词与 MeSH 标题 / 入口词精确匹配时"
                 "生效，且加了字段限定（如 `[tiab]`）后完全失效。上面的检索式把 MeSH 描述符"
                 "与入口词显式 OR 进来，用于补齐这种情况下的召回。入口词来自 NLM 官方词表，"
                 "未做任何增删。")
    return "\n".join(lines) + "\n"
