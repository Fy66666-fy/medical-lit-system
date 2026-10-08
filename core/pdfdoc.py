"""PDF 全文解析（P3 · C3）——把用户上传的 PDF 变成系统内部统一的「章节列表」。

设计目标只有一个：**产物格式与 `pubmed.fetch_fulltext_any()` 完全一致**
（`[{"title": 章节标题, "text": 章节正文}, ...]`）。这样下游的
`summarizer.fulltext_summary` / `summarizer.analyze_fulltext` / `locate.build_index` /
`review.*` / `cite.*` 全部可以零改动复用——PDF 与 PMC 全文走同一条流水线。

为什么不用 PyMuPDF：它是 **AGPL-3.0**，传染性强，一旦捆绑进桌面版 exe 就意味着
整个项目要开源，与「P4 免费增值 / 订阅分层」的商业化计划冲突。
这里选的 pdfplumber 是 **MIT**，依赖链（pdfminer.six MIT / Pillow MIT-CMU /
pypdfium2 BSD-3 + Apache-2.0）全部宽松，可自由分发与商用。

合规边界（对应 ROADMAP 硬约束 6）：
- 解析全程**只吃 bytes、只在内存中**，不落盘、不写缓存、不写日志正文；
- 日志只记录页数 / 字数 / 表格数这类统计量，**绝不记录文献内容**；
- 是否拥有该 PDF 的使用权由使用者在界面上的版权责任确认处把关（见 app.py）。

版权与安全提示：本模块不做任何网络请求，PDF 内容不出本机（云端部署时不出容器）。
"""
from __future__ import annotations

import io
import os
import re
import unicodedata

# ---- 资源上限（云端与桌面共用；可用环境变量调整）----
# 上限存在的理由有两个：① 云端 Streamlit Community Cloud 单容器约 1 GB，
# 一份 200 MB 的 PDF 足以把别人的会话一起拖垮；② 解析耗时与页数近似线性，
# 不做上限会让用户对着转圈界面以为程序死了。
# 20 MB 对单篇论文足够宽松（实测 PLOS 论文 0.5 MB、25 页讲义 1.2 MB），
# 而 pdfminer 解析时的内存占用可达文件的 10 倍以上，这是取这个值的主要考量。
DEFAULT_MAX_MB = 20
DEFAULT_MAX_PAGES = 200

# 表格抽取比正文抽取慢一个量级（要推断线框与合并单元格），
# 因此单独设一个更小的页数窗口，避免一本书的 PDF 卡住整个会话。
TABLE_PAGE_WINDOW = 60
MAX_TABLES = 40


def _env_int(name: str, default: int) -> int:
    """读环境变量里的正整数；非法值一律回落到默认，不让配置错误变成崩溃。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


def limits() -> dict:
    """当前生效的上限，供界面提示与实际校验共用同一个来源。"""
    return {
        "max_mb": _env_int("MEDLIT_PDF_MAX_MB", DEFAULT_MAX_MB),
        "max_pages": _env_int("MEDLIT_PDF_MAX_PAGES", DEFAULT_MAX_PAGES),
    }


class PdfError(Exception):
    """PDF 解析失败。消息一律是可直接展示给用户的中文，不含英文栈信息。"""


# ---------------- 文本清洗 ----------------

# 连字符断行：`inflamma-\ntion` 应当还原为 `inflammation`。
# 只在小写字母 + 连字符 + 换行 + 小写字母时合并，避免把 `well-\nknown` 这类
# 真连字符词也粘起来（那种情况连字符后通常也是小写，属于已知的取舍）。
_HYPHEN_BREAK = re.compile(r"([a-z])-\s*\n\s*([a-z])")

# 单个换行（同一段内的软换行）合并为空格；连续空行保留为段落分隔。
_SOFT_WRAP = re.compile(r"(?<!\n)\n(?!\s*\n)")

_MULTISPACE = re.compile(r"[ \t\u00a0\u3000]{2,}")


def clean_text(text: str) -> str:
    """还原 PDF 抽取出的「硬换行 + 连字符断词」，并压缩多余空白。

    pdfminer 是按行输出的：一段正文会被切成很多行，行尾还有断词连字符。
    直接喂给分句器会把一句话切碎，摘要与定位都会跟着错位，因此必须先还原。
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SOFT_WRAP.sub(" ", text)
    text = _MULTISPACE.sub(" ", text)
    return text.strip()


def _clean_line(text: str) -> str:
    """单行清洗：压缩空白；不做断词还原（断词发生在段落级别）。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return _MULTISPACE.sub(" ", text).strip()


# ---------------- 章节标题识别 ----------------

# 论文里章节名高度集中，命中这些词时即便字号与正文一致也应当判为标题——
# 很多期刊的 PDF 里标题并不放大，只加粗，甚至与正文完全同字号。
_SECTION_RE = re.compile(
    r"^(?:"
    r"abstract|summary|introduction|background|objectives?|aims?|"
    r"materials?\s+and\s+methods?|patients?\s+and\s+methods?|subjects?\s+and\s+methods?|"
    r"methods?|methodology|study\s+design|statistical\s+analys[si]s|"
    r"results?|findings?|discussion|conclusions?|limitations?|"
    r"references|bibliography|acknowledge?ments?|funding|"
    r"conflicts?\s+of\s+interest|competing\s+interests|"
    r"author\s+contributions?|data\s+availability|"
    r"supplementary\s+(?:material|data|information)|appendix|"
    r"摘要|引言|前言|背景|目的|对象与方法|材料与方法|资料与方法|方法|方法学|"
    r"研究设计|统计学?分析|结果|发现|讨论|结论|局限性|参考文献|致谢|基金|"
    r"利益冲突|作者贡献|数据可用性|补充材料|附录"
    r")\.?$",
    re.IGNORECASE,
)

# 编号小标题：`2.1 Statistical analysis` / `3 Results` / `一、引言`
_NUMBERED_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+\S|[一二三四五六七八九十]+[、.]\s*\S)"
)

# 只剥离「编号前缀」本身（不含编号后面的第一个字符）。
# 不能直接用 _NUMBERED_RE 去 sub —— 它末尾的 `\S` 是「必须还有内容」的断言，
# 会额外吃掉标题的第一个字符（`2.1 Statistical` → `tatistical`）。
_NUMBER_PREFIX_RE = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+|[一二三四五六七八九十]+[、.]\s*)"
)

# 绝不出现在章节标题里的字符。用真实 PDF 压测时发现：代码清单的
# `1 #include<bits/stdc++.h>` / `6 ll pow_mod(ll a,ll b){` 会被编号规则误判成标题，
# 一篇 25 页的讲义因此"识别"出 459 个标题、切出 218 个章节。
# 花括号、分号、等号、尖括号、方括号、井号、反斜杠、竖线在标题里几乎没有可能，
# 但会大量出现在代码、公式与表格线里，适合当硬性排除条件。
_CODE_PUNCT = "{};=<>[]#\\|"

# 句子里的谓语动词：`2 patients were excluded from the analysis` 这种正文
# 在编号规则下极像标题，靠动词把它挡掉最省事也最准。
_SENTENCE_VERB_RE = re.compile(
    r"\b(?:were|was|are|is|be|been|being|has|have|had|do|does|did|will|would|"
    r"shall|should|can|could|may|might|must|showed|shows|found|finds|observed|"
    r"reported|reports|compared|compares|included|includes|received|underwent)\b",
    re.IGNORECASE,
)

# 图表题注不是章节标题——它们量大且分布在正文里，误判会把正文切得七零八落。
_CAPTION_RE = re.compile(r"^(?:table|figure|fig\.?|图|表)\s*\d+", re.IGNORECASE)


def _looks_like_numbered_heading(t: str) -> bool:
    """编号行的加分判定。

    这一路最容易误伤：参考文献条目（`1. Smith JA, et al. Lancet. 2019;393:1234-45.`）、
    代码行（`3 #define ll long long`）、正文句子（`2 patients were excluded`）
    全部以数字开头。逐条用「长度 / 标点 / 年份 / et al / 谓语动词」把它们排除掉。
    """
    if len(t) > 70:
        return False
    if _SECTION_RE.match(t):
        return True
    if len(t.split()) > 8:
        return False
    if any(ch in t for ch in _CODE_PUNCT):
        return False
    # 整行没有任何字母/汉字（如页脚残留的 `7 / 11`）不可能是章节标题
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", t):
        return False
    # 参考文献条目的典型开头：`30. Li KZH, Lindenberger U. Relations …`
    # 姓氏 + 缩写这种「大写词 + 纯大写缩写」的组合，标题里几乎不会出现
    if re.search(r"[A-Z][a-z]{1,}\s+[A-Z]{1,4}[,.]", t):
        return False
    if _SENTENCE_VERB_RE.search(t):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", t):
        return False
    if re.search(r"\bet\s+al\b", t, re.IGNORECASE):
        return False
    if t.endswith((".", "。", "，", ",", "；", ";")):
        return False
    # 去掉编号前缀后看正文部分：正文标题一般要么首字母大写、要么是中文；
    # 小写的短行（`2 groups`、`6 return`）更像被切成碎片的正文/代码，不是标题。
    # 但期刊确实有用句式小写的编号小标题（`2.1 study design and participants`），
    # 那种行实词够多，所以对小写开头只要求「≥3 个词」放行。
    core = _NUMBER_PREFIX_RE.sub("", t, count=1).strip()
    if not core:
        return False
    head = core[0]
    is_cjk = "\u4e00" <= head <= "\u9fff"
    if not (head.isupper() or is_cjk) and len(core.split()) < 3:
        return False
    return True


def _units(line: dict) -> list[dict]:
    """取一行里的基本排版单元：优先用我们自己重建行时挂的 `words`，
    兼容 pdfplumber 原生行对象的 `chars`。"""
    return line.get("words") or line.get("chars") or []


def _max_font_size(line: dict) -> float:
    sizes = [u.get("size") or 0 for u in _units(line)]
    return max(sizes) if sizes else 0.0


def _is_bold(line: dict) -> bool:
    """字体名里带 Bold/Black/Heavy 视为加粗。PDF 没有语义上的「粗体」标志，
    只能看嵌入字体的名字——这是所有 PDF 解析器都在用的经验做法。"""
    for u in _units(line):
        name = (u.get("fontname") or "").lower()
        if any(k in name for k in ("bold", "black", "heavy", "semibold")):
            return True
    return False


def _body_size(lines: list[dict]) -> float:
    """正文基准字号：按「字符数」加权取众数，而不是按行数。

    按行数会被大量短行（标题、题注、参考文献编号）带偏；
    按字符数加权能真实反映「页面上绝大部分文字是多大号」。
    """
    weight: dict[float, int] = {}
    for ln in lines:
        for u in _units(ln):
            size = round(u.get("size") or 0, 1)
            if size <= 0:
                continue
            # 词级单元没有「字符数」，用词长近似；字符级单元直接用长度
            n = len(u.get("text") or "")
            weight[size] = weight.get(size, 0) + max(1, n)
    if not weight:
        return 0.0
    return max(weight.items(), key=lambda kv: kv[1])[0]


def _is_heading(text: str, size: float, bold: bool, body: float) -> bool:
    """判定一行是否为章节标题。宁可漏判（退化为按页分节）也不要误判——
    误判会把正文切碎，摘要与原文定位都会跟着错位。"""
    t = text.strip()
    if not t or len(t) > 100:
        return False
    if any(ch in t for ch in _CODE_PUNCT):
        return False
    if _CAPTION_RE.match(t):
        return False
    # 标题几乎不以句号 / 逗号 / 分号结尾（缩写式的 `et al.` 除外，其长度也会超限）
    if t.endswith(("。", "，", "；", ",", ";")):
        return False
    words = t.split()
    if len(words) > 14:
        return False

    if _SECTION_RE.match(t):
        return True
    if _NUMBERED_RE.match(t):
        return _looks_like_numbered_heading(t)
    # 字号明显大于正文，或加粗且足够短
    if body and size >= body * 1.12 and len(words) <= 12 and not t.endswith("."):
        return True
    if bold and body and size >= body * 0.98 and len(words) <= 10 and not t.endswith("."):
        return True
    return False


# ---------------- 元数据抽取 ----------------

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_PMID_RE = re.compile(r"PMID[:\s]*(\d{6,9})", re.IGNORECASE)


def _guess_title(first_lines: list[dict], meta: dict) -> str:
    """标题优先取 PDF 内嵌元数据；没有则取首页字号最大的若干行。

    首页字号最大的文本块几乎总是标题——这是排版惯例，不是猜测。
    但要把「期刊名 / 页眉 / 版权行」这类同样不小的高频干扰排除掉。
    """
    embedded = (meta.get("Title") or "").strip()
    if embedded and len(embedded) >= 8 and not _looks_like_junk_title(embedded):
        return _clean_line(embedded)

    if not first_lines:
        return ""
    best = max((_max_font_size(l) for l in first_lines), default=0.0)
    if best <= 0:
        return ""
    picked: list[str] = []
    for ln in first_lines[:25]:
        if _max_font_size(ln) >= best * 0.95:
            t = _clean_line(ln.get("text") or "")
            if t and not _looks_like_junk_title(t):
                picked.append(t)
        if picked and len(" ".join(picked)) > 200:
            break
    return " ".join(picked)[:300]


def _looks_like_junk_title(t: str) -> bool:
    low = t.lower()
    if low.startswith(("http", "www.", "doi:", "https://doi.org")):
        return True
    if re.match(r"^(downloaded from|published by|©|copyright|all rights reserved)", low):
        return True
    if re.search(r"\b(vol\.?|volume)\s*\d+", low) and len(low) < 40:
        return True
    if len(t) < 8:
        return True
    # 内嵌元数据里的 Title 常常是生成工具塞进去的一整行版式文本
    # （实测 PyCharm 参考卡写入了 100+ 字符的排版说明）。真标题极少超过 200 字符。
    if len(t) > 200:
        return True
    return False


def _guess_authors(first_lines: list[dict], meta: dict) -> list[str]:
    """作者：优先用版面启发式（论文标题下方那行才是完整的作者列表），
    只有当它拿不到 ≥2 个人名时才退回内嵌元数据。

    为什么不是「元数据优先」：实测 PLOS 的 /Author 只登记了通讯作者
    （`Author = Daisuke Sudo`），而正文里写的是 `Daisuke Sudo, Daisuke Toyoda`。
    元数据看起来更权威，实际信息更少。
    """
    heuristic: list[str] = []
    for ln in first_lines[:14]:
        t = _clean_line(ln.get("text") or "")
        if not (8 <= len(t) <= 200):
            continue
        if "@" in t or _DOI_RE.search(t):
            continue
        # 作者行特征：含逗号或 and/&，且不是句子
        if t.count(",") >= 1 and re.search(r"\b(and|&)\b|,", t) and not t.endswith("."):
            cand = _split_authors(t)
            if len(cand) >= 2 and all(_looks_like_name(c) for c in cand[:4]):
                heuristic = cand
                break

    if len(heuristic) >= 2:
        return heuristic

    raw = (meta.get("Author") or "").strip()
    if raw:
        embedded = _split_authors(raw)
        if embedded:
            return embedded
    return heuristic


# 作者名后面的单位角标：`Daisuke Sudo 1*, Daisuke Toyoda2` 里的 `1*` 与 `2`。
# 不剔掉的话整行作者都会因为「含数字」被判为不是人名，实测 PLOS 论文因此只识别出 1 位作者。
_MARK_RE = re.compile(r"[\d\*\u2020\u2021\u00a7\u00b6#]+")


def _strip_marks(s: str) -> str:
    s = _MARK_RE.sub(" ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ,.")


def _split_authors(raw: str) -> list[str]:
    parts = re.split(r"\s*(?:;|\band\b|&|\u2022)\s*", raw)
    out: list[str] = []
    for p in parts:
        p = _strip_marks(_clean_line(p))
        if not p:
            continue
        # `Smith J, Jones AB` 这类同行并列再拆一次
        for sub in re.split(r",\s*(?=[A-Z][a-z])", p):
            sub = _strip_marks(sub)
            if sub and len(sub) <= 60:
                out.append(sub)
    # 去掉明显的机构名（含 University / Hospital / Department 等词）
    bad = ("university", "hospital", "department", "institute", "college",
           "school", "center", "centre", "clinic", "faculty")
    return [a for a in out if not any(b in a.lower() for b in bad)][:30]


_NAME_TOKEN_RE = re.compile(r"^[A-Z][A-Za-z'\-.·]{0,24}$")


def _looks_like_name(s: str) -> bool:
    """人名判定：1~6 个「首字母大写」的 token，且至少一个 token 长度 ≥ 2。

    早先只允许「首字母 + 最多 3 个字符」的后续 token，那是照着 `Smith J` 这种
    「姓 + 缩写」的写法定的，结果把 `John A Smith`（名 + 中间名缩写 + 姓）整类
    判成非人名——中文期刊与很多英文期刊都用这种全名写法。
    现在放宽为任意长度的词，只要求每个词首字母大写；全缩写（如 `JA S`）仍被拒，
    因为那种行更可能是页眉里的期刊缩写而不是作者。
    """
    s = (s or "").strip()
    if not s or len(s) > 60:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    toks = s.split()
    if not (1 <= len(toks) <= 6):
        return False
    if not all(_NAME_TOKEN_RE.match(t) for t in toks):
        return False
    return any(len(t.strip(".")) >= 2 for t in toks)


# 机构名特征。抽期刊名时必须跳过这些行——否则
# `1 National Institute of Advanced Industrial Science and Technology (AIST)`
# 会因为含有 "Science" 而被当成期刊名（实测踩到）。
_AFFIL_RE = re.compile(
    r"\b(universit[a-zé]*|institute|institution|department|dept\.?|college|hospital|"
    r"school|faculty|academy|laborator[a-z]*|clinic|medical\s+cent(?:er|re)|"
    r"aist|research\s+cent(?:er|re))\b",
    re.IGNORECASE,
)

# 期刊名提示。不是简单「包含期刊关键词就整行拿来用」——那样会把
# `Citation: Sudo D, Toyoda D (2026) … PLoS One` 整行当成期刊名。
# 这里只截取关键词周围的那个名词短语（`Journal of Clinical Medicine` / `PLoS One`）。
_JOURNAL_HINT_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z&.\-]*\s+){0,3}"
    r"(?:Journal|Annals|Archives|Review|Medicine|Lancet|Nature|Science|PLoS|PLOS|BMJ|JAMA|"
    r"Frontiers|Clinical|Circulation|Diabetes|Neurology|Oncology|Pediatrics|Radiology|"
    r"Cardiovascular|Respiratory|Nursing|Surgery|BMC|Cureus)\b"
    r"(?:\s+(?:of|for|and|in|on|the)\b)?(?:\s+[A-Z][A-Za-z&.\-]*){0,3})"
)


def _guess_journal(line_groups: list[tuple[list[dict], int]], meta: dict) -> str:
    """从「正文首页 + 页边信息」里抽取期刊名。"""
    for lines, limit in line_groups:
        for ln in (lines or [])[:limit]:
            t = _clean_line(ln.get("text") or "")
            if not (4 <= len(t) <= 220):
                continue
            if "@" in t or _AFFIL_RE.search(t):
                continue
            m = _JOURNAL_HINT_RE.search(t)
            if m:
                cand = m.group(1).strip(" .,;:")
                if 4 <= len(cand) <= 80 and not _AFFIL_RE.search(cand):
                    return cand

    # 内嵌元数据里的 Subject 有时直接写着期刊与卷期（PLOS 就会），
    # 形如 `DOI: 10.1371/journal.pone.0356206PLOS One, Volume. 21, Issue. 8`
    subj = str((meta or {}).get("Subject") or "").strip()
    if subj:
        head = re.split(r",\s*(?:volume|vol\.?|issue)\b", subj, maxsplit=1, flags=re.IGNORECASE)[0]
        head = re.sub(r"^.*?doi:?\s*\S+\s*", "", head, flags=re.IGNORECASE).strip(" .,;:")
        if 4 <= len(head) <= 80:
            return head
    return ""

# 收稿 / 接收 / 出版日期所在行里的年份，比「首页出现过的最大年份」可靠得多——
# 后者常被参考文献或正文引用的年份带偏（实测把 2026 年的论文判成了 2015 年）。
_PUB_YEAR_RE = re.compile(
    r"(?:received|revised|accepted|published|first\s+published|"
    r"©|\(c\)|copyright|licen[cs]e\s+date)"
    r"[^\n]{0,60}?\b(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)


def _guess_year(line_groups: list[tuple[list[dict], int]], meta: dict,
                all_text: str) -> str:
    """抽取出版年份：先看收稿/接收/版权行，再看内嵌元数据的创建日期，
    最后才退回「首页头部里最大的合理年份」。"""
    for lines, limit in line_groups:
        for ln in (lines or [])[:limit]:
            m = _PUB_YEAR_RE.search(ln.get("text") or "")
            if m:
                return m.group(1)
    for key in ("CreationDate", "ModDate"):
        m = re.search(r"(19\d{2}|20\d{2})", str((meta or {}).get(key) or ""))
        if m:
            return m.group(1)

    import datetime
    ceiling = datetime.date.today().year + 1
    years = [int(y) for y in _YEAR_RE.findall(all_text[:4000])]
    years = [y for y in years if 1950 <= y <= ceiling]
    return str(max(years)) if years else ""


def _build_meta(pdf, body_lines: list[dict], margin_lines: list[dict],
                all_text: str) -> dict:
    """组装元数据。

    「正文行」与「页边行」分开传入：标题与作者只可能出现在正文版心里，
    而期刊名、收稿日期、DOI 常常**只**出现在出版社的元数据边栏里。
    早先把两者混在一起按顺序扫，结果边栏排在正文后面、根本没被扫到。
    """
    meta = pdf.metadata or {}
    title = _guess_title(body_lines, meta)
    authors = _guess_authors(body_lines, meta) or _guess_authors(margin_lines, meta)
    journal = _guess_journal(
        [(body_lines, 14), (margin_lines, 40)], meta
    )
    year = _guess_year(
        [(margin_lines, 40), (body_lines, 14)], meta, all_text
    )

    doi = ""
    m = _DOI_RE.search(all_text[:30000])
    if m:
        doi = m.group(0).rstrip(".,;)")
    pmid = ""
    mp = _PMID_RE.search(all_text[:30000])
    if mp:
        pmid = mp.group(1)

    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "pmid": pmid,
        "embedded": {k: v for k, v in (meta or {}).items() if v},
    }


# ---------------- 版面重建（分栏感知） ----------------
#
# 为什么不能直接用 pdfplumber 的 extract_text_lines()：
# 它是「先分词、再按纵坐标把同一高度的词并成一行」，**完全不看横向间隔**。
# 实测一篇 PLOS 论文首页，左侧的出版社元数据栏（Citation / Editor / Received /
# Copyright）与右侧正文处在同一高度，于是被并成同一行：
#     `Citation: Sudo D, Toyoda D (2026) Effect of ... older adults: A pilot randomized trial. PLoS One`
# 后果是正文句子被腰斩——摘要里出现了
#     `Over 8 weeks, six visual-function components were assessed using the V-training Citation: Sudo D, Toyoda D (2026) ...`
# 这类句子。所以这里改为：**先按纵向留白切出真正的栏，再在栏内重建行**。
# 词级数据本身是干净的（实测 0 个跨栏词），问题只出在行分组这一步。

# 页边信息块的标签。只有在一栏里同时命中 ≥2 个标签时才判定为「出版社元数据栏」并剔除，
# 避免误伤三栏排版（三栏里每栏宽度相近，本规则不会触发）。
_MARGIN_LABELS = re.compile(
    r"^\s*(citation|editor|reviewed\s+by|handling\s+editor|received|revised|accepted|"
    r"published|copyright|licen[cs]e|data\s+availability|funding|competing\s+interests?|"
    r"conflicts?\s+of\s+interest|orcid|open\s+access|supporting\s+information|"
    r"abbreviations?|author\s+contributions?|peer\s+review|this\s+is\s+an\s+open\s+access)\b",
    re.IGNORECASE,
)


def _page_words(page) -> list[dict]:
    """取词级单元（带字号与字体名）。失败返回空表，绝不让单页毁掉整篇。"""
    try:
        return page.extract_words(extra_attrs=["size", "fontname"]) or []
    except Exception:  # noqa: BLE001
        return []


def _column_bands(words: list[dict], page_width: float, page_height: float,
                  min_width: float = 20.0, cover_ratio: float = 0.18,
                  gap_tol: float = 10.0) -> list[tuple[float, float]]:
    """按纵向留白切出栏。

    做法：对每个横向位置累加「覆盖它的词的竖向高度」，得到一条覆盖度曲线。
    两栏之间的装订线几乎不被任何词覆盖，于是曲线在那里塌到接近 0 —— 那就是栏边界。
    用「覆盖率」而不是「有没有词」是为了抗干扰：整页宽的标题会在一瞬间跨过装订线，
    但它只贡献一行的高度，占比极低，不会把两栏粘起来。

    `gap_tol` 是必须的一步「横向闭合」：词与词之间的空格在曲线上也是 0，
    不做闭合的话一栏会被每个词间距切成碎片（实测 22 行的整栏被切成了 7 段）。
    取 10pt —— 正文的词间距通常 3~8pt，而分栏装订线一般 ≥ 12pt，两者不重叠。
    """
    if not words:
        return [(0.0, page_width)]
    n = int(page_width) + 2
    cover = [0.0] * n
    for w in words:
        x0 = max(0, int(w.get("x0") or 0))
        x1 = min(n - 1, int(w.get("x1") or 0))
        if x1 <= x0:
            continue
        h = (w.get("bottom") or 0) - (w.get("top") or 0)
        if h <= 0:
            continue
        for x in range(x0, x1 + 1):
            cover[x] += h

    threshold = page_height * cover_ratio
    solid = [cover[i] >= threshold for i in range(n)]

    # 横向闭合：填掉长度 ≤ gap_tol 的空洞（词间距），保留更宽的（装订线）
    i = 0
    while i < n:
        if not solid[i]:
            j = i
            while j < n and not solid[j]:
                j += 1
            if 0 < i and j < n and (j - i) <= gap_tol:
                for k in range(i, j):
                    solid[k] = True
            i = j
        else:
            i += 1

    bands: list[tuple[float, float]] = []
    i = 0
    while i < n:
        if solid[i]:
            j = i
            while j + 1 < n and solid[j + 1]:
                j += 1
            if (j - i) >= min_width:
                bands.append((float(i), float(j)))
            i = j + 1
        else:
            i += 1
    if not bands:
        return [(0.0, page_width)]

    merged = [bands[0]]
    for b in bands[1:]:
        if b[0] - merged[-1][1] <= 8.0:      # 紧邻的碎块并回同一栏
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)
    return merged


def _make_line(ws: list[dict]) -> dict:
    ws = sorted(ws, key=lambda w: (w.get("x0") or 0))
    text = " ".join((w.get("text") or "") for w in ws).strip()
    return {
        "text": text,
        "words": ws,
        "top": min((w.get("top") or 0) for w in ws),
        "bottom": max((w.get("bottom") or 0) for w in ws),
        "x0": min((w.get("x0") or 0) for w in ws),
        "x1": max((w.get("x1") or 0) for w in ws),
    }


def _words_to_lines(words: list[dict], y_tol: float = 3.0) -> list[dict]:
    """把同一栏内的词按纵向位置聚成行。"""
    if not words:
        return []
    ws = sorted(words, key=lambda w: ((w.get("top") or 0), (w.get("x0") or 0)))
    lines: list[dict] = []
    cur: list[dict] = []
    cur_center = None
    for w in ws:
        top, bottom = w.get("top") or 0, w.get("bottom") or 0
        c = (top + bottom) / 2
        if cur and cur_center is not None and abs(c - cur_center) > y_tol:
            lines.append(_make_line(cur))
            cur = []
        cur.append(w)
        cur_center = sum(((x.get("top") or 0) + (x.get("bottom") or 0)) / 2 for x in cur) / len(cur)
    if cur:
        lines.append(_make_line(cur))
    return lines


def _looks_like_marginalia(lines: list[dict]) -> bool:
    """一栏文本是否像出版社的元数据边栏（而不是正文栏）。"""
    hits = sum(1 for l in lines if _MARGIN_LABELS.match(l.get("text") or ""))
    return hits >= 2


def _page_layout(page) -> tuple[list[dict], list[dict]]:
    """重建一页的阅读顺序，返回 (正文行, 页边信息行)。

    栏按从左到右的顺序整体读出，栏内再自上而下——这正是人读双栏论文的顺序。
    页边的元数据栏只在「同时存在一个主栏 + 一个窄栏，且窄栏里命中多个元数据标签」
    时才剔除，其余情况一律当正文保留，避免误伤三栏排版。
    """
    words = _page_words(page)
    if not words:
        return [], []
    try:
        pw = float(page.width)
        ph = float(page.height)
    except Exception:  # noqa: BLE001
        return _words_to_lines(words), []

    bands = _column_bands(words, pw, ph)
    if len(bands) < 2:
        # 单栏页：直接用全部词重建行，同时跳过整页宽的重复水印（如 PLOS 的 OPEN ACCESS 竖排标）
        return _words_to_lines(words), []

    band_words: list[list[dict]] = [[] for _ in bands]
    for w in words:
        cx = ((w.get("x0") or 0) + (w.get("x1") or 0)) / 2
        for idx, (bx0, bx1) in enumerate(bands):
            if bx0 <= cx <= bx1:
                band_words[idx].append(w)
                break
        else:
            # 落在栏外（比如跨栏的宽元素）：归入最近的栏
            idx = min(range(len(bands)),
                      key=lambda k: min(abs(cx - bands[k][0]), abs(cx - bands[k][1])))
            band_words[idx].append(w)

    lines_per_band = [_words_to_lines(bw) for bw in band_words]
    wide = [i for i, b in enumerate(bands) if (b[1] - b[0]) >= pw * 0.45]
    narrow = [i for i, b in enumerate(bands) if (b[1] - b[0]) < pw * 0.30]

    if wide and narrow:
        margin_lines = [ln for i in narrow for ln in lines_per_band[i]]
        if _looks_like_marginalia(margin_lines):
            body = [ln for i in range(len(bands)) if i not in set(narrow)
                    for ln in lines_per_band[i]]
            return body, margin_lines

    return [ln for lines in lines_per_band for ln in lines], []


# ---------------- 主入口 ----------------

def parse_pdf(data: bytes, filename: str = "") -> dict:
    """解析 PDF，返回与 `pubmed.fetch_fulltext_any()` 同构的章节列表及元数据。

    返回结构：
        {
          "sections": [{"title": str, "text": str}, ...],
          "meta":     {"title","authors","journal","year","doi","pmid","embedded"},
          "tables":   [{"page": int, "index": int, "rows": [[str|None, ...], ...]}],
          "quality":  {"has_text_layer","n_pages","n_chars","n_words",
                       "n_headings","n_tables","pages_with_images","warnings"},
        }

    失败一律抛 `PdfError`，消息是可直接展示的中文。
    """
    lim = limits()
    if not data:
        raise PdfError("文件为空，请重新选择。")
    size_mb = len(data) / 1048576
    if size_mb > lim["max_mb"]:
        raise PdfError(
            f"文件过大（{size_mb:.1f} MB），当前上限为 {lim['max_mb']} MB。"
            f"请先在本地裁剪或压缩后再上传。"
        )

    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover —— 仅在依赖缺失时触发
        raise PdfError(
            "缺少 PDF 解析依赖 pdfplumber。请执行 pip install pdfplumber 后重试。"
        ) from e

    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 —— 统一转成可读消息
        name = type(e).__name__
        if "Password" in name or "Encrypt" in name:
            raise PdfError(
                "该 PDF 已加密（有打开密码），本系统无法解析。请先用阅读器另存为未加密的副本。"
            ) from None
        raise PdfError(
            "无法解析该 PDF：文件可能已损坏、被截断，或不是标准的 PDF 格式。"
        ) from None

    try:
        n_pages = len(pdf.pages)
        if n_pages == 0:
            raise PdfError("该 PDF 没有任何页面。")
        if n_pages > lim["max_pages"]:
            raise PdfError(
                f"页数过多（{n_pages} 页），当前上限为 {lim['max_pages']} 页。"
                f"本功能面向单篇论文，不是整本书。"
            )

        warnings: list[str] = []
        per_page: list[list[dict]] = []
        margins: list[list[dict]] = []
        pages_with_images: list[int] = []

        for i, page in enumerate(pdf.pages):
            try:
                lines, margin = _page_layout(page)
            except Exception:  # noqa: BLE001 —— 单页失败不该毁掉整篇
                lines, margin = [], []
            per_page.append(lines)
            margins.append(margin)
            try:
                if page.images:
                    pages_with_images.append(i + 1)
            except Exception:  # noqa: BLE001
                pass

        n_marginalia = sum(1 for m in margins if m)
        if n_marginalia:
            warnings.append(
                f"已识别并剔除 {n_marginalia} 页的出版社元数据边栏"
                f"（Citation / Editor / 版权行等），避免其文字混入正文摘要。"
            )

        all_lines = [ln for pg in per_page for ln in pg]
        body = _body_size(all_lines)

        total_chars = sum(
            len(_clean_line(ln.get("text") or "")) for ln in all_lines
        )

        # 无文本层判定：整篇字符数过少 ⇒ 基本可以断定是扫描件（纯图片）。
        # 阈值取 200 而不是 0：有些扫描件带一层极薄的 OCR 水印或页码，字数非零但无正文。
        if total_chars < 200:
            raise PdfError(
                "未在该 PDF 中检测到文本层——这通常是**扫描件或纯图片型 PDF**。"
                "请改用带文本层的版本（在 Word / LaTeX 中导出的 PDF），"
                "或先用 OCR 工具处理后再上传。"
            )

        sections, n_headings = _build_sections(per_page, body)
        if n_headings == 0:
            warnings.append("未识别到章节标题，已按页分节。摘要质量会略低于结构化全文。")

        # 元数据：正文版心与页边信息分开传——标题只在版心，期刊名/收稿日期常在边栏
        meta = _build_meta(
            pdf,
            per_page[0] if per_page else [],
            margins[0] if margins else [],
            "\n".join(ln.get("text") or ""
                     for ln in (all_lines + [x for m in margins for x in m])),
        )

        tables = _extract_tables(pdf, n_pages, warnings)
    finally:
        try:
            pdf.close()
        except Exception:  # noqa: BLE001
            pass

    text_all = "\n".join(_clean_line(ln.get("text") or "") for ln in all_lines)
    return {
        "sections": sections,
        "meta": meta,
        "tables": tables,
        "quality": {
            "has_text_layer": True,
            "n_pages": n_pages,
            "n_chars": sum(len(s["text"]) for s in sections),
            "n_words": len(text_all.split()),
            "n_headings": n_headings,
            "n_tables": len(tables),
            "n_marginalia": n_marginalia,
            "pages_with_images": pages_with_images,
            "warnings": warnings,
        },
    }


def _build_sections(per_page: list[list[dict]], body: float) -> tuple[list[dict], int]:
    """把逐页的行合并成章节列表。识别到标题就按标题分节，否则退化为按页分节。

    首页另有一条特例：标题本身常常换行成两三行，而它与「最大字号」同尺寸。
    若不排除，标题的第二行会被当成一个独立章节（实测 PLOS 论文首页出现
    `older adults: A pilot randomized trial` 这样一个"章节"）。
    """
    # 首页最大字号 = 标题字号；与它同尺寸的续行不算章节标题。
    # 但只在「确实存在标题块」时才启用：字号要明显大于正文，且同尺寸的行只有两三行。
    # 否则（例如全篇没有标题、最大字号就是章节标题的文档）会把所有章节标题一并吃掉。
    title_size = 0.0
    title_block = False
    if per_page:
        title_size = max((_max_font_size(l) for l in per_page[0]), default=0.0)
        if title_size > 0 and body > 0 and title_size >= body * 1.25:
            big = sum(1 for l in per_page[0] if _max_font_size(l) >= title_size * 0.95)
            title_block = big <= 4

    entries: list[tuple[str, list[str]]] = []  # (标题, 原始行文本)
    cur_title = ""
    cur_lines: list[str] = []
    n_headings = 0

    for pi, lines in enumerate(per_page):
        for ln in lines:
            raw = ln.get("text") or ""
            text = _clean_line(raw)
            if not text:
                continue
            size = _max_font_size(ln)
            if pi == 0 and title_block and size >= title_size * 0.95:
                cur_lines.append(text)
                continue
            if _is_heading(text, size, _is_bold(ln), body):
                if cur_lines:
                    entries.append((cur_title, cur_lines))
                cur_title = text
                cur_lines = []
                n_headings += 1
            else:
                cur_lines.append(text)
        # 页与页之间强制断开：跨页的两个段落不该被粘成一句
        if cur_lines:
            cur_lines.append("")
    if cur_lines:
        entries.append((cur_title, cur_lines))

    if n_headings == 0:
        # 没有标题：按页分节，至少保证定位能按页回溯
        out = []
        for pi, lines in enumerate(per_page):
            txt = " ".join(_clean_line(l.get("text") or "") for l in lines)
            txt = clean_text(txt)
            if txt:
                out.append({"title": f"第 {pi + 1} 页", "text": txt})
        return out, 0

    out: list[dict] = []
    for idx, (title, lines) in enumerate(entries):
        txt = clean_text("\n".join(lines))
        if len(txt) < 2:
            continue
        label = title or ("题录与摘要" if idx == 0 else f"正文 {idx}")
        out.append({"title": label, "text": txt})
    return out, n_headings


def _extract_tables(pdf, n_pages: int, warnings: list[str]) -> list[dict]:
    """抽取表格。表格推断比正文慢得多，因此只扫前 TABLE_PAGE_WINDOW 页。"""
    if n_pages > TABLE_PAGE_WINDOW:
        warnings.append(
            f"页数超过 {TABLE_PAGE_WINDOW}，仅对前 {TABLE_PAGE_WINDOW} 页做表格抽取。"
        )
    out: list[dict] = []
    for i in range(min(n_pages, TABLE_PAGE_WINDOW)):
        if len(out) >= MAX_TABLES:
            warnings.append(f"表格数量已达上限 {MAX_TABLES}，其余未抽取。")
            break
        try:
            raw = pdf.pages[i].extract_tables() or []
        except Exception:  # noqa: BLE001 —— 表格是加分项，失败不影响正文
            continue
        for j, rows in enumerate(raw):
            cleaned = [
                [_clean_line(c or "") if c else "" for c in row]
                for row in (rows or [])
            ]
            cleaned = [r for r in cleaned if any(c for c in r)]
            # 只有一行或只有一列的多半是版式误判，不是真表格
            if len(cleaned) < 2 or max(len(r) for r in cleaned) < 2:
                continue
            out.append({"page": i + 1, "index": j + 1, "rows": cleaned})
            if len(out) >= MAX_TABLES:
                break
    return out


# ---------------- 供图表解析用的页面渲染 ----------------

def render_page_png(data: bytes, page_no: int, resolution: int = 150) -> bytes:
    """把第 `page_no` 页（1 起）渲染成 PNG 字节。

    用于图表解析：PDF 里的一张图往往由多个矢量元素拼成，直接抠图几乎不可行，
    整页渲染再交给视觉模型是最稳的路径（与现有「网页截图兜底」思路一致）。
    """
    lim = limits()
    if len(data) / 1048576 > lim["max_mb"]:
        raise PdfError("文件过大，无法渲染。")
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover
        raise PdfError("缺少 PDF 解析依赖 pdfplumber。") from e

    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n = len(pdf.pages)
            if not (1 <= page_no <= n):
                raise PdfError(f"页码超出范围（共 {n} 页）。")
            im = pdf.pages[page_no - 1].to_image(resolution=resolution)
            buf = io.BytesIO()
            im.original.convert("RGB").save(buf, format="PNG", optimize=True)
            return buf.getvalue()
    except PdfError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PdfError(f"页面渲染失败：{type(e).__name__}") from None


# ---------------- 与下游模块对接 ----------------

def to_article(parsed: dict, filename: str = "") -> dict:
    """把解析结果包装成与 PubMed 一致的 article dict。

    这样 PDF 文献可以直接进入综述工作台的文献池，参与横向对比、冲突识别、
    PRISMA 与证据化评估，也能直接走 `core/cite.py` 的六种引用导出——
    下游模块完全感知不到这篇文献来自 PDF 而不是 PubMed。

    注意 pmid/pmcid 留空：PDF 里即便印了 PMID 也不是权威来源，
    而这两个字段在下游被当作「唯一标识」用于去重与缓存，填错比留空危险得多。
    """
    meta = parsed.get("meta") or {}
    sections = parsed.get("sections") or []

    # 摘要字段：优先取真正标注为 Abstract / 摘要 的章节；
    # 没有就退回前两节——它至少包含题录与开头，比留空对下游更有用。
    abstract = ""
    for s in sections:
        if _SECTION_RE.match((s.get("title") or "").strip()) and \
                (s.get("title") or "").strip().lower().startswith(("abstract", "summary", "摘要")):
            abstract = s.get("text") or ""
            break
    if not abstract:
        abstract = " ".join(s.get("text") or "" for s in sections[:2])
    abstract = clean_text(abstract)[:4000]

    return {
        "pmid": "",
        "pmcid": "",
        "doi": meta.get("doi") or "",
        "title": meta.get("title") or (filename or "未命名 PDF"),
        "authors": list(meta.get("authors") or []),
        "journal": meta.get("journal") or "",
        "year": meta.get("year") or "",
        "abstract": abstract,
        "pubtypes": [],
        "language": "eng",
        "source": "PDF 上传",
        "is_pdf": True,
        "pdf_file": filename,
    }


def summary_markdown(parsed: dict, filename: str = "") -> str:
    """把解析结果导出为一份可读的 Markdown（章节 + 统计），供用户下载留档。"""
    meta = parsed.get("meta") or {}
    q = parsed.get("quality") or {}
    lines = [f"# {meta.get('title') or filename or 'PDF 全文解析'}", ""]
    bits = []
    if meta.get("authors"):
        bits.append("、".join(meta["authors"][:8]))
    if meta.get("journal"):
        bits.append(meta["journal"])
    if meta.get("year"):
        bits.append(str(meta["year"]))
    if bits:
        lines += [" ".join(bits), ""]
    if meta.get("doi"):
        lines += [f"DOI: {meta['doi']}", ""]
    lines += [
        f"> 来源：{filename or '本地 PDF'} ｜ {q.get('n_pages', 0)} 页 ｜ "
        f"{q.get('n_chars', 0):,} 字符 ｜ {q.get('n_headings', 0)} 个章节标题 ｜ "
        f"{q.get('n_tables', 0)} 个表格",
        "",
    ]
    for s in parsed.get("sections") or []:
        lines += [f"## {s['title']}", "", s["text"], ""]
    return "\n".join(lines)
