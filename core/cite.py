"""引用格式导出（P3-C2）。

把系统内的文献记录（PubMed 抽取结果 / 收藏夹）转成主流参考文献管理器能直接
导入的格式，让「检索 → 精读 → 综述」走到最后一步不必再手抄参考文献：

- ``bibtex``   → Zotero / JabRef / LaTeX
- ``ris``      → Zotero / EndNote / Mendeley / NoteExpress
- ``endnote``  → EndNote / NoteExpress 的 ``.enw`` 标签格式
- ``medline``  → PubMed 原生标签格式（可与 EndNote 双向互转）
- ``vancouver``→ 医学期刊常用的顺序编码制文后参考文献
- ``gbt7714``  → GB/T 7714-2015，中文毕业论文 / 中文期刊常用格式

设计取舍（都是刻意的）：

1. **字段缺失整条省略，不猜也不编造**。PubMed 摘要页拿不到卷 / 期 / 页码时，
   宁可少一项，也不填占位符——参考文献一旦写错，比缺了更难被发现。
2. **团体作者（研究协作组）保留**。``fetch_articles`` 已把 ``CollectiveName``
   并入作者串，这里再区分「人名 / 团体名」，团体名在 BibTeX 里用 ``{}`` 包住，
   避免被解析成「姓 + 名缩写」。
3. **不擅自改写姓名**。不做音译，不改缩写形式，只按各格式的语法重排。
4. **BibTeX key 批内唯一**。重名自动追加 ``a`` / ``b`` / ``c``。
5. 本模块只处理期刊论文（PubMed 收录主体），因此 GB/T 7714 的类型标识固定为
   ``[J]``；若将来接入非期刊文献，需要按 ``pubtypes`` 再细分。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

# ---------------------------------------------------------------- 格式注册表

FORMATS: tuple[dict, ...] = (
    {
        "key": "bibtex",
        "label": "BibTeX",
        "ext": "bib",
        "mime": "application/x-bibtex",
        "hint": "Zotero / JabRef / LaTeX",
    },
    {
        "key": "ris",
        "label": "RIS",
        "ext": "ris",
        "mime": "application/x-research-info-systems",
        "hint": "Zotero / EndNote / Mendeley / NoteExpress",
    },
    {
        "key": "endnote",
        "label": "EndNote (.enw)",
        "ext": "enw",
        "mime": "text/plain",
        "hint": "EndNote / NoteExpress 双击导入",
    },
    {
        "key": "medline",
        "label": "MEDLINE",
        "ext": "txt",
        "mime": "text/plain",
        "hint": "PubMed 原生标签格式",
    },
    {
        "key": "vancouver",
        "label": "Vancouver",
        "ext": "txt",
        "mime": "text/plain",
        "hint": "医学期刊文后参考文献（顺序编码制）",
    },
    {
        "key": "gbt7714",
        "label": "GB/T 7714",
        "ext": "txt",
        "mime": "text/plain",
        "hint": "中文毕业论文 / 中文期刊",
    },
)

FORMAT_KEYS = tuple(f["key"] for f in FORMATS)

_LABELS = {f["key"]: f["label"] for f in FORMATS}
_EXTS = {f["key"]: f["ext"] for f in FORMATS}
_MIMES = {f["key"]: f["mime"] for f in FORMATS}
_HINTS = {f["key"]: f["hint"] for f in FORMATS}


def label(fmt: str) -> str:
    return _LABELS.get(fmt, fmt)


def extension(fmt: str) -> str:
    return _EXTS.get(fmt, "txt")


def mime(fmt: str) -> str:
    return _MIMES.get(fmt, "text/plain")


def hint(fmt: str) -> str:
    return _HINTS.get(fmt, "")


# ---------------------------------------------------------------- 字段工具

_INITIALS_RE = re.compile(r"^[A-Z]{1,4}$")


def _s(v) -> str:
    """安全取字符串：None / 非字符串统一成去空白的 str。"""
    if v is None:
        return ""
    return str(v).strip()


def split_name(name: str) -> tuple[str, str, bool]:
    """把 ``"Smith JA"`` 拆成 ``("Smith", "JA", False)``。

    团体作者（如 ``"The ESPRIT Study Group"``）返回 ``(原名, "", True)``——
    靠「末段是否是一串大写缩写字母」来判断，因为 PubMed 的姓名一律是
    ``LastName Initials`` 形式，而团体名末段通常是完整单词。
    """
    name = _s(name)
    if not name:
        return "", "", False
    if " " in name:
        head, tail = name.rsplit(" ", 1)
        if _INITIALS_RE.match(tail):
            return head.strip(), tail, False
    return name, "", True


def _year(article: dict) -> str:
    """``year`` 可能混着 ``"2020 Jan-Feb"`` 这类 MedlineDate，只取四位年份。"""
    y = _s(article.get("year"))
    m = re.search(r"(1[89]\d{2}|20\d{2})", y)
    return m.group(1) if m else y


def _pages(article: dict) -> str:
    """页码统一成 ``"123-130"``；``"123-30"`` 这类缩写按 PubMed 原样保留。"""
    p = _s(article.get("pages"))
    return p.replace("--", "-")


def _split_pages(pages: str) -> tuple[str, str]:
    if not pages:
        return "", ""
    if "-" in pages:
        a, _, b = pages.partition("-")
        return a.strip(), b.strip()
    return pages.strip(), ""


def _norm_lang(article: dict) -> str:
    return _s(article.get("language")).lower()


# ---------------------------------------------------------------- BibTeX

_BIB_TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _bib_escape(text: str) -> str:
    return "".join(_BIB_TEX_ESCAPES.get(ch, ch) for ch in _s(text))


def _fold_ascii(text: str) -> str:
    """去掉变音符号并只保留 ``[a-z0-9]``，用于生成 BibTeX key。"""
    norm = unicodedata.normalize("NFKD", _s(text))
    ascii_only = norm.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]", "", ascii_only)


_KEY_STOP = {
    "the", "a", "an", "of", "and", "or", "on", "in", "for", "to", "with",
    "from", "by", "at", "as", "is", "are", "effect", "effects", "study",
}


def _bib_authors(authors: list) -> str:
    parts = []
    for a in authors or []:
        family, initials, collective = split_name(_s(a))
        if not family:
            continue
        parts.append("{" + family + "}" if collective else f"{family}, {initials}".rstrip(", "))
    return " and ".join(parts)


def _bib_key(article: dict, used: set) -> str:
    authors = [_s(a) for a in (article.get("authors") or [])]
    stem = ""
    for a in authors:
        family, _in, collective = split_name(a)
        if family and not collective:
            stem = _fold_ascii(family)
            break
    if not stem:
        stem = _fold_ascii(authors[0]) if authors else _fold_ascii(article.get("journal"))
    if not stem:
        stem = "anon"
    year = _fold_ascii(_year(article))
    word = ""
    for w in re.split(r"[\s:;,.\-()\[\]/]+", _s(article.get("title"))):
        fw = _fold_ascii(w)
        if len(fw) >= 4 and fw not in _KEY_STOP:
            word = fw
            break
    base = stem + year + word
    key = base
    suffix = ord("a")
    while key in used:
        key = base + chr(suffix)
        suffix += 1
    used.add(key)
    return key


def bibtex_entry(article: dict, used: set | None = None) -> str:
    used = used if used is not None else set()
    fields: list[tuple[str, str]] = []
    authors = _bib_authors(article.get("authors"))
    if authors:
        fields.append(("author", authors))
    if _s(article.get("title")):
        fields.append(("title", "{" + _bib_escape(article["title"]) + "}"))
    if _s(article.get("journal")):
        fields.append(("journal", _bib_escape(article["journal"])))
    if _year(article):
        fields.append(("year", _bib_escape(_year(article))))
    for src, dst in (("volume", "volume"), ("issue", "number"), ("pages", "pages"),
                     ("doi", "doi"), ("issn", "issn"), ("url", "url")):
        if _s(article.get(src)):
            fields.append((dst, _bib_escape(article[src])))
    if _s(article.get("pmid")):
        fields.append(("note", f"PMID: {_bib_escape(article['pmid'])}"))
    body = ",\n".join(f"  {k:<7} = {{{v}}}" for k, v in fields)
    return f"@article{{{_bib_key(article, used)},\n{body}\n}}"


def to_bibtex(articles: list[dict]) -> str:
    used: set = set()
    return "\n\n".join(bibtex_entry(a, used) for a in articles) + "\n"


# ---------------------------------------------------------------- RIS

def _ris_authors(authors: list) -> list[str]:
    out = []
    for a in authors or []:
        family, initials, collective = split_name(_s(a))
        if not family:
            continue
        out.append(family if collective else f"{family}, {initials}".rstrip(", "))
    return out


def ris_entry(article: dict) -> str:
    lines = ["TY  - JOUR"]
    for a in _ris_authors(article.get("authors")):
        lines.append(f"AU  - {a}")
    if _s(article.get("title")):
        lines.append(f"TI  - {_s(article['title'])}")
    if _s(article.get("journal")):
        lines.append(f"JO  - {_s(article['journal'])}")
    sp, ep = _split_pages(_pages(article))
    if sp:
        lines.append(f"SP  - {sp}")
    if ep:
        lines.append(f"EP  - {ep}")
    if _s(article.get("volume")):
        lines.append(f"VL  - {_s(article['volume'])}")
    if _s(article.get("issue")):
        lines.append(f"IS  - {_s(article['issue'])}")
    if _year(article):
        lines.append(f"PY  - {_year(article)}")
    if _s(article.get("issn")):
        lines.append(f"SN  - {_s(article['issn'])}")
    if _s(article.get("doi")):
        lines.append(f"DO  - {_s(article['doi'])}")
    if _s(article.get("pmid")):
        lines.append(f"AN  - {_s(article['pmid'])}")
    if _s(article.get("url")):
        lines.append(f"UR  - {_s(article['url'])}")
    if _s(article.get("language")):
        lines.append(f"LA  - {_s(article['language'])}")
    lines.append("ER  - ")
    return "\n".join(lines)


def to_ris(articles: list[dict]) -> str:
    return "\n\n".join(ris_entry(a) for a in articles) + "\n"


# ---------------------------------------------------------------- EndNote (.enw)

def to_endnote(articles: list[dict]) -> str:
    records = []
    for article in articles:
        lines = ["%0 Journal Article"]
        for a in article.get("authors") or []:
            family, initials, collective = split_name(_s(a))
            if not family:
                continue
            lines.append(f"%A {family}" if collective else f"%A {family}, {initials}".rstrip(", "))
        if _s(article.get("title")):
            lines.append(f"%T {_s(article['title'])}")
        if _s(article.get("journal")):
            lines.append(f"%J {_s(article['journal'])}")
        if _year(article):
            lines.append(f"%D {_year(article)}")
        if _s(article.get("volume")):
            lines.append(f"%V {_s(article['volume'])}")
        if _s(article.get("issue")):
            lines.append(f"%N {_s(article['issue'])}")
        if _pages(article):
            lines.append(f"%P {_pages(article)}")
        if _s(article.get("issn")):
            lines.append(f"%@ {_s(article['issn'])}")
        if _s(article.get("doi")):
            lines.append(f"%R {_s(article['doi'])}")
        if _s(article.get("url")):
            lines.append(f"%U {_s(article['url'])}")
        if _s(article.get("pmid")):
            lines.append(f"%M {_s(article['pmid'])}")
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


# ---------------------------------------------------------------- MEDLINE

def to_medline(articles: list[dict]) -> str:
    records = []
    for article in articles:
        lines = []
        if _s(article.get("pmid")):
            lines.append(f"PMID- {_s(article['pmid'])}")
        for a in article.get("authors") or []:
            family, initials, collective = split_name(_s(a))
            if not family:
                continue
            lines.append(f"AU  - {family}" if collective else f"AU  - {family} {initials}".rstrip())
        for pt in article.get("pubtypes") or []:
            if _s(pt):
                lines.append(f"PT  - {_s(pt)}")
        if _s(article.get("title")):
            lines.append(f"TI  - {_s(article['title'])}")
        if _s(article.get("journal")):
            lines.append(f"JT  - {_s(article['journal'])}")
        if _year(article):
            lines.append(f"DP  - {_year(article)}")
        if _s(article.get("volume")):
            lines.append(f"VI  - {_s(article['volume'])}")
        if _s(article.get("issue")):
            lines.append(f"IP  - {_s(article['issue'])}")
        if _pages(article):
            lines.append(f"PG  - {_pages(article)}")
        if _s(article.get("issn")):
            lines.append(f"IS  - {_s(article['issn'])}")
        for line in (_s(article.get("abstract")) or "").splitlines():
            if line.strip():
                lines.append(f"AB  - {line.strip()}")
        if _s(article.get("doi")):
            lines.append(f"LID - {_s(article['doi'])} [doi]")
            lines.append(f"AID - {_s(article['doi'])} [doi]")
        if _s(article.get("pmcid")):
            lines.append(f"AID - {_s(article['pmcid'])} [pmc]")
        records.append("\n".join(lines))
    return "\n\n".join(records) + "\n"


# ---------------------------------------------------------------- Vancouver

_VANCOUVER_MAX_AUTHORS = 6


def _vancouver_authors(authors: list) -> str:
    names = []
    for a in authors or []:
        family, initials, collective = split_name(_s(a))
        if not family:
            continue
        names.append(family if collective else f"{family} {initials}".rstrip())
    if not names:
        return ""
    if len(names) > _VANCOUVER_MAX_AUTHORS:
        return ", ".join(names[:_VANCOUVER_MAX_AUTHORS]) + ", et al"
    return ", ".join(names)


def vancouver_entry(article: dict) -> str:
    parts = []
    authors = _vancouver_authors(article.get("authors"))
    if authors:
        parts.append(authors + ".")
    if _s(article.get("title")):
        parts.append(_s(article["title"]).rstrip(".") + ".")
    loc = _s(article.get("journal"))
    if _year(article):
        vol_issue = _s(article.get("volume"))
        if _s(article.get("issue")):
            vol_issue += f"({_s(article['issue'])})"
        seg = f"{_year(article)}"
        if vol_issue:
            seg += f";{vol_issue}"
        if _pages(article):
            seg += f":{_pages(article)}"
        loc = (loc + ". " if loc else "") + seg + "."
    elif loc:
        loc += "."
    if loc:
        parts.append(loc)
    if _s(article.get("doi")):
        parts.append(f"doi:{_s(article['doi'])}.")
    if _s(article.get("pmid")):
        parts.append(f"PMID: {_s(article['pmid'])}.")
    return " ".join(parts)


def to_vancouver(articles: list[dict]) -> str:
    return "\n".join(
        f"{i}. {vancouver_entry(a)}" for i, a in enumerate(articles, 1)
    ) + "\n"


# ---------------------------------------------------------------- GB/T 7714

def _gbt_initials(initials: str) -> str:
    """``"JA"`` → ``"J A"``；已是 ``"J A"`` 或 ``"J.A."`` 也能正常处理。"""
    letters = re.findall(r"[A-Za-z]", initials or "")
    return " ".join(ch.upper() for ch in letters)


def _gbt_authors(authors: list) -> str:
    names = []
    for a in authors or []:
        family, initials, collective = split_name(_s(a))
        if not family:
            continue
        if collective:
            names.append(family.upper())
        else:
            ini = _gbt_initials(initials)
            names.append((family.upper() + (" " + ini if ini else "")).strip())
    if not names:
        return ""
    if len(names) > 3:
        return ", ".join(names[:3]) + ", et al"
    return ", ".join(names)


def gbt7714_entry(article: dict) -> str:
    parts = []
    authors = _gbt_authors(article.get("authors"))
    if authors:
        parts.append(authors + ".")
    if _s(article.get("title")):
        parts.append(_s(article["title"]).rstrip(".") + "[J].")
    journal = _s(article.get("journal"))
    vol_issue = _s(article.get("volume"))
    if _s(article.get("issue")):
        vol_issue += f"({_s(article['issue'])})"
    tail = ", ".join(x for x in (journal, _year(article), vol_issue) if x)
    if tail:
        if _pages(article):
            tail += f": {_pages(article)}"
        parts.append(tail + ".")
    if _s(article.get("doi")):
        parts.append(f"DOI:{_s(article['doi'])}.")
    return " ".join(parts)


def to_gbt7714(articles: list[dict]) -> str:
    return "\n".join(
        f"[{i}] {gbt7714_entry(a)}" for i, a in enumerate(articles, 1)
    ) + "\n"


# ---------------------------------------------------------------- 统一入口

_RENDERERS = {
    "bibtex": to_bibtex,
    "ris": to_ris,
    "endnote": to_endnote,
    "medline": to_medline,
    "vancouver": to_vancouver,
    "gbt7714": to_gbt7714,
}


def render(articles: list[dict], fmt: str) -> str:
    """按格式渲染一批文献。``fmt`` 非法时抛 ``ValueError``。"""
    fn = _RENDERERS.get(fmt)
    if fn is None:
        raise ValueError(f"未知引用格式：{fmt}（可选：{', '.join(FORMAT_KEYS)}）")
    if not articles:
        return ""
    return fn(articles)


def filename(articles: list[dict], fmt: str, stamp: str | None = None) -> str:
    stamp = stamp or datetime.now().strftime("%Y%m%d")
    return f"参考文献_{len(articles)}篇_{stamp}.{extension(fmt)}"


def preview(article: dict, fmt: str) -> str:
    """单篇预览，用于界面上的样例展示。"""
    return render([article], fmt).rstrip("\n")


def completeness(article: dict) -> list[str]:
    """列出该条记录缺失的引用关键字段（用于提示「导出前建议补齐」）。

    只报告 PubMed 摘要页**本来就应该有**的字段：卷 / 期 / 页码缺失通常是
    电子优先发表（online ahead of print），属正常情况，不算缺陷。
    """
    missing = []
    if not (article.get("authors") or []):
        missing.append("作者")
    if not _s(article.get("title")):
        missing.append("标题")
    if not _s(article.get("journal")):
        missing.append("期刊")
    if not _year(article):
        missing.append("年份")
    return missing
