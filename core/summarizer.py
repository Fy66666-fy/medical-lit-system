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


def extractive_summary(text: str, ratio: float = 0.3, max_sentences: int = 6) -> dict:
    """基于词频-位置加权的抽取式摘要（TextRank 的轻量替代，离线可用）"""
    sentences = split_sentences(text)
    if not sentences:
        return {"summary": "", "key_terms": [], "scores": []}

    # 停用词（少量高频英文功能词 + 中文常见虚词）
    stops = set(
        "the a an of in on and or to for with by from at as is are was were be been this that these those "
        "we our their its it than then thus however results methods conclusion background objective purpose "
        "study patients patient group groups treatment were was significance p value values "
        "的 了 和 与 在 是 为 对 及 而 或 等 中 将 可 被 之 其 该".split()
    )
    tokens_per_sent = [_tokenize(s) for s in sentences]
    df = Counter()
    for toks in tokens_per_sent:
        for t in set(toks):
            if t not in stops and len(t) > 1:
                df[t] += 1

    n = len(sentences)
    scores = []
    for i, toks in enumerate(tokens_per_sent):
        if not toks:
            scores.append(0.0)
            continue
        content = [t for t in toks if t not in stops and len(t) > 1]
        tf_score = sum(1 + math.log(df[t]) for t in content) / (len(content) or 1)
        pos_score = 1.0
        if i == 0:
            pos_score = 1.5  # 首句权重
        elif i < n * 0.25:
            pos_score = 1.2
        length_penalty = min(len(toks) / 15.0, 1.0)  # 过短句子降权
        scores.append(tf_score * pos_score * length_penalty)

    keep = max(1, min(max_sentences, int(round(n * ratio))))
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)[:keep]
    chosen = sorted(ranked)

    # 关键词（按文档频率）
    key_terms = [t for t, _ in df.most_common(10)]

    return {
        "summary": " ".join(sentences[i] for i in chosen),
        "key_terms": key_terms,
        "scores": [(sentences[i], round(scores[i], 3)) for i in ranked],
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
