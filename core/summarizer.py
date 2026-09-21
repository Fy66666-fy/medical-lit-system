"""摘要引擎：内置抽取式摘要（离线）+ 可选 LLM 摘要（OpenAI 兼容接口）"""
import math
import re
import time
from collections import Counter

import requests

# 医学文本中常见的"非句号"缩写，避免切句误判
_ABBR = {"e.g", "i.e", "et al", "vs", "Dr", "Prof", "Fig", "approx", "p.<", "ca"}


def split_sentences(text: str) -> list[str]:
    """中英文混合切句"""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    # 保护缩写
    protected = text
    for i, ab in enumerate(_ABBR):
        protected = protected.replace(ab, ab.replace(".", "§"))
    parts = re.split(r"(?<=[.!?。！？])\s+", protected)
    return [p.replace("§", ".").strip() for p in parts if len(p.strip()) > 10]


def _tokenize(text: str) -> list[str]:
    """简易分词：英文按词 + 中文按双字 bigram"""
    words = re.findall(r"[A-Za-z][A-Za-z\-']+", text.lower())
    han = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = [han[i] + han[i + 1] for i in range(len(han) - 1)]
    return words + bigrams


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

    # 停用词（少量高频英文功能词 + 中文常见虚词）
    stops = set(
        "the a an of in on and or to for with by from at as is are was were be been this that these those "
        "we our their its it than then thus however among between during after before both each other more most "
        "study patients patient group groups treatment were was significance p value values using used based "
        "的 了 和 与 在 是 为 对 及 而 或 等 中 将 可 被 之 其 该 均 约 例 名".split()
    )

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

    # 关键词：优先跨句出现的词，按 df 与词频综合排序
    total_tf = Counter()
    for toks in tokens_per_sent:
        total_tf.update(t for t in toks if t not in stops and len(t) > 1)
    key_terms = [
        t for t, _ in sorted(
            df.items(), key=lambda kv: (kv[1] * math.log(1 + total_tf[kv[0]]), kv[0]), reverse=True
        )
        if df[t] >= 2 or total_tf[t] >= 2
    ][:10] or [t for t, _ in df.most_common(10)]

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
            picked.append({"title": valid[idx]["title"], "sentences": sents})

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
    tokens = _tokenize(full)
    stops = set(
        "the a an of in on and or to for with by from at as is are was were be been this that these those "
        "we our their its it than then thus however among between during after before both each other more most "
        "study patients patient group groups treatment were was using used based respectively significant "
        "的 了 和 与 在 是 为 对 及 而 或 等 中 将 可 被 之 其 该 均 约 例 名".split()
    )
    tf = Counter(t for t in tokens if t not in stops and len(t) > 2)
    for noise in ("figure", "figures", "table", "fig", "additional", "available", "shown", "however"):
        tf.pop(noise, None)
    keywords = [t for t, _ in tf.most_common(15)]

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
        "metrics": metrics,
    }


def is_mostly_english(text: str) -> bool:
    """判断文本是否以英文为主（拉丁字母占比显著高于 CJK）"""
    latin = len(re.findall(r"[A-Za-z]", text))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return latin > cjk * 2 and latin > 20


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
            # 单句超长时硬切
            while len(s) > 450:
                segments.append(s[:450])
                s = s[450:]
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
