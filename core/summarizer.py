"""摘要引擎：内置抽取式摘要（离线）+ 可选 LLM 摘要（OpenAI 兼容接口）"""
import math
import re
import time
from collections import Counter

import requests

# 医学文本中常见的"非句号"缩写，避免切句误判（v1.2.3 修复：保护须覆盖缩写后的句点，
# 否则 "(Fig. 3)" 会被从 "Fig." 处切断，留下 "…(Fig" 这类悬空碎片）
_ABBR = ("e.g", "i.e", "et al", "vs", "Dr", "Dr.", "Prof", "Fig", "Figs", "Eq",
         "Ref", "Sec", "cf", "approx", "ca", "al")


def split_sentences(text: str) -> list[str]:
    """中英文混合切句"""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    # 保护缩写：把 "Fig." / "et al." 这类缩写句点替换为 §，切句后再还原
    protected = text
    for ab in _ABBR:
        protected = protected.replace(ab + ".", ab + "§")
    parts = re.split(r"(?<=[.!?。！？])\s+", protected)
    return [p.replace("§", ".").strip() for p in parts if len(p.strip()) > 10]


# ================= 分词与关键词基础设施 =================
# 停用词分三类：通用功能词 / 学术套话与论文结构词 / 中文虚词
_EN_STOPWORDS = frozenset("""
a about above across after again against all almost already also am an and another any are aren't as at
be because been before being below between both but by
better best good great higher highest lower lowest near plus well
can cannot could couldn't
did didn't do does doesn't doing don't down during
each either else even ever every
few first for four from further
get got
had hadn't has hasn't have haven't having he her here hers herself him himself his how however
i if in into is isn't it its itself
just
last less like little
made make many may me might mightn't mine more moreover most much must mustn't my myself
needn't neither never new no nobody none nor not nothing now
of off on once one only or other our ours ourselves out over own
per
same second she should shouldn't since so some such
than that that's the their theirs them themselves then there these they this those though three through thus to too two
under until up upon us
very via
was wasn't we were weren't what when where whether which while who whom why will with within without won't would wouldn't
yet you your yours yourself yourselves
""".split())

# 学术写作套话 + 论文结构词 + 医学文献通用词（高频但无主题区分度）
_ACADEMIC_STOPWORDS = frozenset("""
abstract achieve achieved achieves achieving addition additionally aim aims although among amongst analysis analyses
appendix approach approaches arm arms article articles assess assessed available based
background baseline basis case cases cause caused causes causing characteristic characteristics clinical cohort cohorts
type types use used uses
compared comparison conducted consider considered consisted contains
conclusion conclusions consequently corresponding data demonstrated demonstrates
describe described describes design designed despite detail details
determine determined different discussed discussion
effect effects either employ employed estimates evaluated evaluation examined example examples
excluded experiment experimental explanation
figure figures fig findings following found furthermore
given graph graphs group groups hence identified illustrated
include included includes including increase increased increases increasing indicate indicates indicating information
improve improved improves improving investigated investigation investigations
day days decrease decreased decreases decreasing hour hours lead leading leads led
month months receive received receives receiving reduce reduced reduces reducing week weeks year years
remain remained remains undergo underwent
level levels likelihood limited mainly material materials maximum measure measured measures
method methods minimum model models moderate moreover
notably noted number numbers objective objectives obtained observed occur occurred
outcome outcomes paper participant participants particular particularly patient patients performed
demonstrate demonstrated demonstrates demonstrating show showed showing shown shows
permitted possible potential potentially present presented presenting previous previously
probability provide provided provides providing
regard regarding related relatively remaining reported report reports represent represents respectively
result results review reviewed sample samples scale section sections significantly similar similarly
significant simple slightly status study studies subject subjects subsequently substantial suggest
suggested suggests summary supplementary support supported
table tables taken test tests therefore thus total treatment treatments therapy therapies
trial trials typically unlike useful usually various version versus widely work works
""".split())

# 中文虚词（单字，用于过滤含虚词的中文候选串）
_ZH_STOPWORDS = frozenset("的了和与在是为对及而或等中将被之其该均约例名有也不就都很到说要去你我他她它们这那些个上下前后里外时用于并且但如若则因由从以把让使得能会应需一般还又只更最太")

# 中文词级停用（学术套话，需整体相等才过滤，避免误杀「亚组分析」这类术语）
_ZH_WORD_STOP = frozenset(
    "研究 分析 显示 表明 提示 显著 具有 进行 方法 目的 结论 背景 结果 数据 水平 统计学 意义 "
    "明显 可以 可能 比较 进一步 分别 患者 情况 相关 影响 因素 作用 变化 特点".split()
)

# 长度不足 3 但确有医学/统计含义的缩写，避免被长度规则误杀
_SHORT_KEEP = frozenset({"ci", "hr", "rr", "os", "pfs", "dfs", "ct", "mr", "pd", "il", "cd", "ki"})

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*|[\u4e00-\u9fff]+")
_CLAUSE_RE = re.compile(r"[^.!?;:\n]+")


def _stem(word: str) -> str:
    """
    轻量英文词形归一：只合并常见的名词复数（mutations→mutation）。
    刻意不做 -ed/-ing 剥离，避免产出 improved→improv、associated→associat 这类非词形式。
    """
    w = word
    if len(w) <= 4 or "-" in w or any(ch.isdigit() for ch in w):
        return w
    if w.endswith("ies") and len(w) > 5:
        cand = w[:-3] + "y"
    elif w.endswith("sses") and len(w) > 5:
        cand = w[:-2]
    elif w.endswith("es") and len(w) > 5:
        cand = w[:-2] if w[-3] in "sxz" or w[-3:-1] in ("ch", "sh") else w[:-1]
    elif w.endswith("s") and not w.endswith("ss") and not w.endswith("is"):
        cand = w[:-1]
    else:
        return w
    return cand if len(cand) >= 3 else w


def _tokens_normalized(text: str) -> list[str]:
    """归一化分词：英文小写 + 去所有格 + 词形归一；中文按双字 bigram"""
    out = []
    for raw in _TOKEN_RE.findall(text):
        if raw[0].isascii():
            w = raw.lower().strip("'-")
            w = re.sub(r"'(s|re|ve|ll|d|m|t)$", "", w).strip("'-")
            if w:
                out.append(_stem(w))
        elif len(raw) == 1:
            out.append(raw)
        else:
            out.extend(raw[i:i + 2] for i in range(len(raw) - 1))
    return out


def _tokenize(text: str) -> list[str]:
    """简易分词：英文按词（含轻量词形归一）+ 中文按双字 bigram"""
    return _tokens_normalized(text)


def _is_candidate(tok: str) -> bool:
    """能否作为关键词候选（过滤停用词、纯数字、过短词、单字中文）"""
    if not tok:
        return False
    if tok[0].isascii():
        if tok in _EN_STOPWORDS or tok in _ACADEMIC_STOPWORDS:
            return False
        if tok in _SHORT_KEEP:
            return True
        if len(tok) < 3 or tok.isdigit() or len(set(tok)) == 1:
            return False
        return True
    # 中文走独立 n-gram 通道（见 _zh_candidates），不参与英文统计
    return False


def _zh_candidates(unit_texts) -> tuple:
    """
    中文候选词：取"极大频繁 n-gram"（2-4 字）。
    直接切 bigram 会产生「存期」「总生」这类半截词，这里先把 2-4 字的连续汉字串
    全部计数，再让被同频或更高频长串包含的短串退场，最终留下完整术语（如「总生存期」）。
    """
    ngrams = {n: Counter() for n in (2, 3, 4)}
    df = Counter()
    for unit in unit_texts:
        seen_here = set()
        for run in re.findall(r"[\u4e00-\u9fff]+", unit):
            for n in (2, 3, 4):
                for i in range(len(run) - n + 1):
                    g = run[i:i + n]
                    if g in _ZH_WORD_STOP or any(ch in _ZH_STOPWORDS for ch in g):
                        continue
                    ngrams[n][g] += 1
                    if g not in seen_here:
                        df[g] += 1
                        seen_here.add(g)

    covered = set()
    for n in (2, 3):
        for long_g, cnt in ngrams[n + 1].items():
            if cnt < 2:
                continue
            for i in range(len(long_g) - n + 1):
                short = long_g[i:i + n]
                if ngrams[n].get(short, 0) and cnt >= ngrams[n][short]:
                    covered.add(short)

    tf = Counter()
    for n in (2, 3):
        for g, c in ngrams[n].items():
            if c >= 2 and g not in covered:
                tf[g] += c
    for g, c in ngrams[4].items():  # 4 字串已是最长，直接保留
        if c >= 2:
            tf[g] += c
    return tf, df


def extract_keywords(text: str = "", top_n: int = 15, units=None, with_counts: bool = False):
    """
    高质量关键词提取（摘要页与全文分析共用）：

    1. 过滤：英文功能词（the/her/new...）/ 学术套话（study/figure/shown...）/ 论文结构词 /
       代词 / 纯数字 / 过短词；中文按虚词与词级套话过滤
    2. 归一：名词复数合并（mutations→mutation），避免同一概念被拆散重复占位；
       刻意不做 -ed/-ing 剥离，以免产出 improv、associat 这类非词形式
    3. 加权：TF-IDF 式评分——高频但遍布全文的词（如 patients）权重被压低，
       分布集中、出现频繁的词（如 pembrolizumab、r175h）得分更高
    4. 短语优先：自动识别 "overall survival"、"pd-l1 expression" 这类医学短语，
       短语入选后其组成单词让出名额
    5. 中文通道：走 _zh_candidates 的极大频繁 n-gram，输出「总生存期」而非「存期」

    units: 可传入按句/按章节切分好的文本列表，用于计算分布权重；缺省按子句自动切分。
    """
    unit_texts = units if units else _CLAUSE_RE.findall(text)
    token_units = [t for t in (_tokens_normalized(u) for u in unit_texts) if t]
    n_units = max(1, len(token_units))
    tf, df = Counter(), Counter()
    for toks in token_units:
        seen = set()
        for t in toks:
            if _is_candidate(t):
                tf[t] += 1
                if t not in seen:
                    df[t] += 1
                    seen.add(t)

    # 短语（相邻候选词组合），需求出现≥2次才算稳定术语
    # 短语仅由英文词构成（中文无空格，bigram 组合会产生跨界噪音）
    ph_tf, ph_df = Counter(), Counter()
    for toks in token_units:
        seen = set()
        for i in range(len(toks) - 1):
            a, b = toks[i], toks[i + 1]
            if a[0].isascii() and b[0].isascii() and _is_candidate(a) and _is_candidate(b):
                p = f"{a} {b}"
                ph_tf[p] += 1
                if p not in seen:
                    ph_df[p] += 1
                    seen.add(p)

    def weight(freq: int, docfreq: int) -> float:
        """TF-IDF 式权重：稀有→高分；遍布全文→低分"""
        return freq * (0.35 + math.log(1 + n_units / (1 + docfreq)))

    zh_tf, zh_df = _zh_candidates(unit_texts)
    scored = [(t, weight(tf[t], df[t])) for t in tf]
    scored += [(p, weight(ph_tf[p], ph_df[p]) * 1.45) for p in ph_tf if ph_tf[p] >= 2]
    scored += [(g, weight(zh_tf[g], zh_df[g])) for g in zh_tf]
    scored.sort(key=lambda kv: (-kv[1], kv[0]))

    picked, covered = [], {}
    for term, _ in scored:
        if len(picked) >= top_n:
            break
        parts = term.split(" ")
        if len(parts) > 1:
            if any(p in covered for p in parts):  # 与已选短语高度重叠，跳过
                continue
            # 短语优先：其组成词若几乎只以该短语形式出现，则让出名额
            picked = [t for t in picked if not (t in parts and tf.get(t, 0) <= ph_tf[term] * 1.2)]
            picked.append(term)
            for p in parts:
                covered[p] = max(covered.get(p, 0), ph_tf[term])
        else:
            # 组成词几乎只出现在已选短语中时不再单列（如 overall survival 已含 survival）
            if term in covered and tf[term] <= covered[term] * 1.2:
                continue
            # 中文 bigram 相互高度重叠（生存 / 存期 / 总生），与已选中文词共享汉字则跳过
            if not term[0].isascii() and any(
                (not p[0].isascii()) and set(p) & set(term) for p in picked
            ):
                continue
            picked.append(term)

    if with_counts:
        counts = {}
        for t in picked:
            if " " in t:
                counts[t] = ph_tf[t]
            elif t[0].isascii():
                counts[t] = tf[t]
            else:
                counts[t] = zh_tf[t]
        return picked, counts
    return picked


def extractive_summary(text: str, ratio: float = 0.3, max_sentences: int = 6, title: str = "") -> dict:
    """
    结构感知的抽取式摘要（离线可用），评分维度：
    1. TF-IDF 词重要性
    2. 结构区块权重（Results/Conclusion 高于 Background/Methods）
    3. 位置权重（首句/开头段落）
    4. 标题相关性（与文献标题的词重叠）
    5. 信息量（含数字/统计指标的句子加权）
    6. MMR 冗余去除（避免选出语义重复的句子）
    """
    sentences = split_sentences(text)
    if not sentences:
        return {"summary": "", "key_terms": [], "scores": []}

    # 停用词：与关键词提取共用同一套（英文功能词 + 学术套话 + 中文虚词）
    stops = _EN_STOPWORDS | _ACADEMIC_STOPWORDS | _ZH_STOPWORDS

    # 结构区块识别：摘要各句常带 "Background:/Methods:/Results:/Conclusion:" 等标签
    section_weights = {
        "background": 0.8, "introduction": 0.9, "purpose": 1.1, "objective": 1.1,
        "objectives": 1.1, "aim": 1.1, "methods": 0.95, "method": 0.95,
        "patients": 1.0, "materials": 0.95, "setting": 0.9, "design": 1.0,
        "results": 1.45, "result": 1.45, "findings": 1.3,
        "conclusions": 1.5, "conclusion": 1.5, "interpretation": 1.2,
        "背景": 0.8, "目的": 1.1, "方法": 0.95, "结果": 1.45, "结论": 1.5,
    }
    title_tokens = set(t for t in _tokenize(title) if t not in stops) if title else set()

    tokens_per_sent = [_tokenize(s) for s in sentences]
    n = len(sentences)

    # 文档频率（用于 TF-IDF 式权重：出现在多数句子中的词信息量低）
    df = Counter()
    for toks in tokens_per_sent:
        for t in set(toks):
            if t not in stops and len(t) > 1:
                df[t] += 1

    # 关键词：统一走 extract_keywords（停用词过滤 + 词形归一 + 医学短语识别）
    total_tf = Counter()
    for toks in tokens_per_sent:
        total_tf.update(t for t in toks if t not in stops and len(t) > 1)
    key_terms = extract_keywords(units=sentences, top_n=10)

    has_num = re.compile(r"\d")

    def sentence_bonus(s: str, i: int) -> float:
        bonus = 1.0
        # 结构区块权重
        m = re.match(r"^\s*([A-Za-z\u4e00-\u9fff]{2,20}?)\s*[:：]", s)
        if m and m.group(1).lower() in section_weights:
            bonus *= section_weights[m.group(1).lower()]
        # 位置权重
        if i == 0:
            bonus *= 1.25
        elif i < n * 0.25:
            bonus *= 1.1
        # 含数字/统计结果的句子信息量更高（排除纯年份）
        nums = re.findall(r"\d+(?:\.\d+)?%?", s)
        strong = [x for x in nums if not (len(x.rstrip("%")) == 4 and 1900 <= int(float(x.rstrip("%"))) <= 2100)]
        if strong:
            bonus *= 1.15
        # 标题相关性
        if title_tokens:
            toks = set(tokens_per_sent[i])
            overlap = len(toks & title_tokens)
            bonus *= 1.0 + min(overlap / max(len(title_tokens), 1), 0.5)
        return bonus

    scores = []
    for i, toks in enumerate(tokens_per_sent):
        if not toks:
            scores.append(0.0)
            continue
        content = [t for t in toks if t not in stops and len(t) > 1]
        if not content:
            scores.append(0.0)
            continue
        # TF-IDF：词频 ÷ 文档频率（在多数句子都出现的词区分度低）
        tfidf = sum(total_tf[t] / (1 + math.log(df[t])) for t in content) / len(content)
        length_factor = min(len(toks) / 15.0, 1.15)  # 过短句子降权，长句轻微加分
        scores.append(tfidf * sentence_bonus(sentences[i], i) * length_factor)

    keep = max(1, min(max_sentences, int(round(n * ratio))))

    # MMR 式冗余去除：按得分从高到低选句，与已选句子过于相似的跳过
    def similarity(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        return inter / (len(a) + len(b) - inter)

    token_sets = [set(toks) for toks in tokens_per_sent]
    ranked = []
    for i in sorted(range(n), key=lambda k: scores[k], reverse=True):
        if len(ranked) >= keep:
            break
        if scores[i] <= 0:
            break
        if any(similarity(token_sets[i], token_sets[j]) > 0.55 for j in ranked):
            continue
        ranked.append(i)
    if not ranked:  # 兜底：全部被过滤时取最高分句
        ranked = [max(range(n), key=lambda k: scores[k])]
    ranked.sort()

    return {
        "summary": " ".join(sentences[i] for i in ranked),
        "key_terms": key_terms,
        "scores": [(sentences[i], round(scores[i], 3)) for i in
                   sorted(range(n), key=lambda k: scores[k], reverse=True)],
    }


# ---------------- 全文摘要与数据分析（v1.2.0） ----------------

# 全文中无需纳入摘要的程式化章节
_BOILERPLATE = (
    "author contribution", "funding", "conflict of interest",
    "competing interest", "financial disclosure", "ethics", "informed consent",
    "data availab", "data sharing", "acknowledg", "abbreviation",
    "supporting information", "supplementary", "animal stud", "registry",
    "declaration", "consent", "credit statement", "利益冲突", "致谢", "伦理",
)

# 章节对全文摘要的重要性权重
_SECTION_WEIGHTS = {
    "background": 0.9, "introduction": 0.9, "methods": 0.9, "materials": 0.9,
    "results": 1.45, "findings": 1.3, "discussion": 1.15,
    "conclusion": 1.5, "conclusions": 1.5, "limitations": 1.05,
    "背景": 0.9, "引言": 0.9, "方法": 0.9, "材料": 0.9,
    "结果": 1.45, "讨论": 1.15, "结论": 1.5, "局限": 1.05,
}

# 数据分析中值得提取的统计指标
_PATTERNS = {
    "P 值": re.compile(r"P\s*[<=>]\s*0?\.\d+", re.I),
    "百分比": re.compile(r"\d+(?:\.\d+)?%"),
    "风险比/比值比": re.compile(r"\b(?:HR|OR|RR)\b[^.;]{0,20}?\d+\.\d+", re.I),
    "置信区间": re.compile(r"9[05]\s*% CI[^.;]{0,40}", re.I),
    "样本量": re.compile(r"\bn\s*=\s*\d[\d,]*", re.I),
}


def _is_boilerplate(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in _BOILERPLATE)


# 英文章节标题 → 中文标题（全文摘要小标题输出用，v1.2.2 修复小标题语言错误）
_ZH_SECTION_NAMES = {
    "background": "背景", "introduction": "引言",
    "methods": "方法", "materials and methods": "材料与方法", "materials": "材料",
    "results": "结果", "findings": "结果",
    "discussion": "讨论", "conclusion": "结论", "conclusions": "结论",
    "limitations": "研究局限", "purpose": "研究目的",
    "objective": "研究目的", "objectives": "研究目的", "aims": "研究目的",
}

# 标题前的编号/装饰前缀，如 "1. Background"、"2 METHODS"、"Section 3: Results"
_SEC_PREFIX_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s*[.、)]?\s*|[ivxlcdm]+\s*[.、)]\s*|section\s+\d+\s*[:.、)]?\s*)+",
    re.I,
)


def _zh_section_title(title: str) -> str:
    """将 PMC 英文章节标题翻译为固定中文小标题；无映射时保留原标题"""
    t = re.sub(r"\s+", " ", (title or "").strip()).rstrip(".:")
    key = _SEC_PREFIX_RE.sub("", t).strip().lower()
    if key in _ZH_SECTION_NAMES:
        return _ZH_SECTION_NAMES[key]
    return title


def fulltext_summary(sections: list[dict], title: str = "", max_sentences: int = 8) -> dict:
    """
    章节化全文摘要：按章节重要性与篇幅分配摘要名额，逐章抽取核心句。
    返回 {"summary": 全文摘要文本, "sections": [{"title","sentences":[...]}], "used_sections": n}
    """
    valid = [s for s in sections if not _is_boilerplate(s["title"]) and len(s["text"]) > 200]
    if not valid:
        return {"summary": "", "sections": [], "used_sections": 0}

    scores = []
    for s in valid:
        w = _SECTION_WEIGHTS.get(s["title"].lower().strip(), 1.0)
        scores.append(w * (len(s["text"]) + 300))
    total = sum(scores)

    picked = []
    remaining = max_sentences
    order = sorted(range(len(valid)), key=lambda i: scores[i], reverse=True)
    quota = {}
    for idx in order:
        if remaining <= 0:
            break
        k = max(1, round(max_sentences * scores[idx] / total))
        k = min(k, remaining)
        quota[idx] = k
        remaining -= k
    # 剩余名额按权重补给出最多句子的大章节
    while remaining > 0:
        idx = order[0]
        quota[idx] = quota.get(idx, 0) + 1
        remaining -= 1

    for idx in order:
        if idx not in quota:
            continue
        res = extractive_summary(valid[idx]["text"], ratio=1.0, max_sentences=quota[idx], title=title)
        sents = [s for s, _ in res["scores"][:quota[idx]]]
        if sents:
            picked.append({"title": _zh_section_title(valid[idx]["title"]), "sentences": sents})

    summary = "\n\n".join(
        f"【{p['title']}】 " + " ".join(p["sentences"]) for p in picked
    )
    return {"summary": summary, "sections": picked, "used_sections": len(picked)}


def analyze_fulltext(sections: list[dict]) -> dict:
    """全文数据分析：篇幅分布、关键词、统计指标提取"""
    valid = [s for s in sections if not _is_boilerplate(s["title"])]
    words = re.compile(r"[A-Za-z][A-Za-z\-']+|[\u4e00-\u9fff]")

    section_stats = [
        {"title": s["title"], "words": len(words.findall(s["text"])), "chars": len(s["text"])}
        for s in sections
    ]
    total_words = sum(st["words"] for st in section_stats)

    full = " ".join(s["text"] for s in valid)
    # 关键词：以子句为单位统计分布（TF-IDF 权重），并识别医学短语
    units = [c for s in valid for c in _CLAUSE_RE.findall(s["text"])]
    keywords, keyword_counts = extract_keywords(units=units, top_n=15, with_counts=True)

    metrics = {}
    for name, pat in _PATTERNS.items():
        found = pat.findall(full)
        if found:
            metrics[name] = {"count": len(found), "samples": list(dict.fromkeys(found))[:6]}

    return {
        "total_words": total_words,
        "total_chars": sum(st["chars"] for st in section_stats),
        "section_stats": section_stats,
        "keywords": keywords,
        "keyword_counts": keyword_counts,
        "metrics": metrics,
    }


def is_mostly_english(text: str) -> bool:
    """判断文本是否以英文为主（拉丁字母占比显著高于 CJK）"""
    latin = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return latin > cjk * 2 and latin > 20


# 关键词译文缓存（跨调用复用，避免重复请求翻译接口）
_KW_TRANS_CACHE: dict[str, str] = {}

# 高频医学术语对照表（免费翻译接口对单词给的是词典义，如 cell→單元格、
# breast→胸部，医学语境下需覆盖；未命中的词仍走接口）
_KW_GLOSSARY = {
    "cell": "细胞", "cells": "细胞", "cancer": "癌症", "tumor": "肿瘤", "tumour": "肿瘤",
    "breast": "乳腺", "lung": "肺", "blockade": "阻断", "immunotherapy": "免疫治疗",
    "survival": "生存", "expression": "表达", "mutation": "突变", "gene": "基因",
    "genes": "基因", "therapy": "治疗", "treatment": "治疗", "patients": "患者",
    "patient": "患者", "risk": "风险", "apoptosis": "细胞凋亡", "inflammation": "炎症",
    "biopsy": "活检", "prognosis": "预后", "metastasis": "转移", "carcinoma": "癌",
    "chemotherapy": "化疗", "radiotherapy": "放疗", "antibody": "抗体", "antibodies": "抗体",
    "protein": "蛋白质", "proteins": "蛋白质", "receptor": "受体", "receptors": "受体",
    "inhibitor": "抑制剂", "inhibitors": "抑制剂", "pathway": "信号通路", "pathways": "信号通路",
    "biomarker": "生物标志物", "biomarkers": "生物标志物", "vaccine": "疫苗",
    "obesity": "肥胖", "diabetes": "糖尿病", "hypertension": "高血压", "mortality": "死亡率",
    "incidence": "发病率", "prevalence": "患病率", "screening": "筛查", "virus": "病毒",
    "infection": "感染", "immune": "免疫", "antigen": "抗原", "leukemia": "白血病",
}


def translate_keywords(terms: list[str]) -> list[str]:
    """
    将英文关键词逐个翻译为中文（MyMemory 免费接口，带缓存与限速保护）。
    单个关键词翻译失败或译文仍是英文时，回退显示原文，不影响其余关键词。
    注意：不能用 is_mostly_english 判断——单词级关键词长度不足 20，会被误判为无需翻译
    （v1.2.3 修复此处），改为"不含中文字符即尝试翻译"。
    """
    out = []
    for t in terms:
        if re.search(r"[\u4e00-\u9fff]", t):  # 已含中文，直接保留
            out.append(t)
            continue
        key = t.lower()
        # 术语表优先（免费接口的单词译文常不合医学语境），未命中再走接口
        if key in _KW_GLOSSARY:
            _KW_TRANS_CACHE[key] = _KW_GLOSSARY[key]
            out.append(_KW_GLOSSARY[key])
            continue
        if key in _KW_TRANS_CACHE:
            out.append(_KW_TRANS_CACHE[key])
            continue
        translated = t
        try:
            r = requests.get(
                "https://api.mymemory.translated.net/get",
                params={"q": t, "langpair": "en|zh-CN"},
                timeout=15,
            )
            data = r.json()
            tr = ((data.get("responseData") or {}).get("translatedText") or "").strip().lower()
            # 译文有效：非空、非纯拉丁字母（说明真的翻成了中文）
            if data.get("responseStatus") == 200 and tr and not re.fullmatch(r"[a-z0-9\s\-\+\.\(\)]+", tr):
                translated = tr
        except Exception:
            pass  # 失败回退原文
        _KW_TRANS_CACHE[key] = translated
        out.append(translated)
        time.sleep(0.25)  # 接口限速保护
    return out


def translate_text(text: str, langpair: str = "en|zh-CN") -> str:
    """
    使用 MyMemory 免费翻译接口将文本翻译为目标语言（无需 API Key）。
    按句子分块以避开单次请求长度限制；返回拼接后的译文。
    """
    sentences = split_sentences(text)
    if not sentences:
        return text
    segments = []
    cur = ""
    for s in sentences:
        if len(cur) + len(s) + 1 <= 450:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                segments.append(cur)
            # 单句超长时优先在标点处断开，避免从词中间硬切产生无意义碎片
            while len(s) > 450:
                cut = max(s.rfind(c, 200, 450) for c in "。；;，,）)．.")
                if cut < 200:
                    cut = 450
                else:
                    cut += 1  # 标点归前一段
                segments.append(s[:cut])
                s = s[cut:]
            cur = s
    if cur:
        segments.append(cur)

    translated = []
    for seg in segments:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": seg, "langpair": langpair},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        out = (data.get("responseData") or {}).get("translatedText") or ""
        if not out or data.get("responseStatus") != 200:
            raise RuntimeError("翻译服务返回异常")
        translated.append(out)
        time.sleep(0.3)  # 接口限速保护
    return " ".join(translated)


def llm_summary(
    text: str,
    api_base: str,
    api_key: str,
    model: str,
    language: str = "中文",
    length_hint: str = "",
) -> str:
    """调用 OpenAI 兼容接口生成摘要"""
    base = api_base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = f"{base}/chat/completions"
    system = (
        f"你是一名医学文献分析助手。请用{language}对下面这篇医学文献摘要进行结构化总结，"
        "依次输出：**研究目的**、**方法**、**主要结果**（含关键数据，若有）、**结论**，"
        "最后用一行列出 3-5 个关键词。语言精炼、忠实原文，不要编造数据。"
    )
    if length_hint:
        system += f"总结长度要求：{length_hint}。"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text[:12000]},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def llm_figure_summary(
    figures: list[dict],
    api_base: str,
    api_key: str,
    model: str,
    language: str = "中文",
) -> str:
    """调用 OpenAI 兼容接口，对文献图表说明文字进行概括"""
    base = api_base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    url = f"{base}/chat/completions"
    lines = [
        f"图{i + 1} {f.get('label', '')}: {f.get('caption', '')}"
        for i, f in enumerate(figures)
    ]
    text = "\n".join(lines)[:12000]
    system = (
        f"你是一名医学文献分析助手。下面是一篇医学文献中所有图表的编号与说明文字，"
        f"请用{language}完成两项任务："
        "1. 逐图概括：每张图用一句话说明它展示了什么、想传达什么信息；"
        "2. 总体概括：用 2-3 句话总结这些图表共同讲述的研究故事（如实验设计流程、核心结果趋势）。"
        "忠实原文，不要编造未提及的数据或结论。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()
