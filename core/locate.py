"""原文定位引擎（v2.1.0）：摘要句子与关键数值在原文中的溯源
 ------------------------------------------------------
提供三项能力：
1. build_index     —— 把全文章节切句，构建带位置信息的句子索引
2. find_values     —— 扫描全文关键数值（P 值 / CI / HR·OR·RR / 百分比 / 样本量 / 均值±SD）
3. locate_sentence —— 摘要句子 → 原文出处匹配（抽取句精确命中；LLM 改写/中文输出走
                      「数字 + 拉丁术语」加权模糊匹配，跨语言依然可用）
以及 highlight_values —— 把句中关键数值渲染为高亮 HTML。
"""
from __future__ import annotations

import html
import re

from . import summarizer

# ---------------- 关键数值模式 ----------------

VALUE_TYPES: dict[str, re.Pattern] = {
    "P 值": re.compile(r"P\s*[<=>]\s*0?\.\d+", re.I),
    "置信区间": re.compile(r"9[05]\s*% CI[^.;]{0,40}", re.I),
    "风险比/比值比": re.compile(r"\b(?:a?HR|OR|RR)\b[^.;]{0,20}?\d+\.\d+", re.I),
    "百分比": re.compile(r"\d+(?:\.\d+)?%"),
    "样本量": re.compile(r"\bn\s*=\s*\d[\d,]*", re.I),
    "均值±标准差": re.compile(r"\d+\.\d+\s*[±]\s*\d+\.\d+"),
}

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z\-']{2,}")


# ---------------- 句子索引 ----------------

def build_index(sections: list[dict]) -> list[dict]:
    """
    章节全文 → 句子索引。
    每条：{"section": 章节标题, "pos": 章节内句序(0起), "text": 原句,
           "start": 章节内字符起点, "end": 终点}
    """
    out: list[dict] = []
    for sec in sections or []:
        text = sec.get("text", "") or ""
        if not text:
            continue
        base = 0
        pos = 0
        for s in summarizer.split_sentences(text):
            i = text.find(s, base)
            if i < 0:
                i = text.find(s)
            if i < 0:
                continue
            out.append({
                "section": (sec.get("title", "") or "").strip(),
                "pos": pos,
                "text": s,
                "start": i,
                "end": i + len(s),
            })
            base = i + len(s)
            pos += 1
    return out


def index_stats(index: list[dict]) -> dict:
    return {"sentences": len(index), "sections": len({it["section"] for it in index})}


# ---------------- 关键数值定位 ----------------

def _norm_value(v: str) -> str:
    return re.sub(r"\s+", "", v).lower()


def find_values(index: list[dict], per_type_limit: int = 40) -> dict[str, list[dict]]:
    """
    扫描全文关键数值。返回 {类型: [条目]}，
    条目：{"value", "section", "pos", "sentence", "start", "end"}
    按（类型, 归一化值）去重，保留首次出现；每类最多 per_type_limit 条。
    """
    seen: dict[str, set] = {}
    result: dict[str, list[dict]] = {}
    for it in index:
        sent = it["text"]
        for vtype, pat in VALUE_TYPES.items():
            bucket = result.setdefault(vtype, [])
            seen_t = seen.setdefault(vtype, set())
            if len(bucket) >= per_type_limit:
                continue
            for m in pat.finditer(sent):
                val = m.group(0).strip()
                key = (vtype, _norm_value(val))
                if key in seen_t:
                    continue
                seen_t.add(key)
                bucket.append({
                    "value": val,
                    "section": it["section"],
                    "pos": it["pos"],
                    "sentence": sent,
                    "start": it["start"] + m.start(),
                    "end": it["start"] + m.end(),
                })
    return {k: v for k, v in result.items() if v}


# ---------------- 高亮渲染 ----------------

def highlight_values(sentence: str, css_class: str = "loc-val") -> str:
    """把句中所有关键数值包上高亮 <span>（HTML 转义后拼装）"""
    spans: list[tuple[int, int]] = []
    for pat in VALUE_TYPES.values():
        for m in pat.finditer(sentence):
            spans.append((m.start(), m.end()))
    if not spans:
        return html.escape(sentence)
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    parts: list[str] = []
    cur = 0
    for a, b in merged:
        parts.append(html.escape(sentence[cur:a]))
        parts.append(f'<span class="{css_class}">' + html.escape(sentence[a:b]) + "</span>")
        cur = b
    parts.append(html.escape(sentence[cur:]))
    return "".join(parts)


# ---------------- 摘要句子 → 原文匹配 ----------------

def _norm_text(s: str) -> str:
    return re.sub(r"[\s\W_]+", "", s.lower())


def _numbers(s: str) -> set[str]:
    return {x for x in _NUM_RE.findall(s) if not (len(x) == 4 and x.isdigit() and 1900 <= int(x) <= 2100)}


def _latin_terms(s: str) -> set[str]:
    return {t.lower() for t in _LATIN_RE.findall(s)}


def locate_sentence(sentence: str, index: list[dict], limit: int = 2,
                    min_score: float = 0.30) -> list[dict]:
    """
    摘要句子 → 原文出处。返回 [{"section","pos","text","start","end","score"}]，按得分降序。

    - 精确/近似精确（归一化后相等或包含）：score = 1.0
    - 模糊：共现数字（×3，跨语言关键线索）+ 拉丁术语（×2，药名/指标名通常不被翻译）
              ÷ 原句数字与术语总数，兼顾查准
    """
    if not index or not sentence or not sentence.strip():
        return []
    q_norm = _norm_text(sentence)
    if not q_norm:
        return []

    # 1) 精确命中（抽取式摘要句即原句）
    hits = []
    for it in index:
        t_norm = _norm_text(it["text"])
        if t_norm == q_norm:
            hits.append({**it, "score": 1.0})
    if hits:
        return hits[:limit]
    # 近似精确：短句被原文句包含（清理连接词导致轻微差异）
    for it in index:
        t_norm = _norm_text(it["text"])
        if t_norm and (t_norm in q_norm or (len(q_norm) > 40 and q_norm in t_norm)):
            hits.append({**it, "score": 0.95})
    if hits:
        return hits[:limit]

    # 2) 模糊匹配：数字 + 拉丁术语
    q_nums = _numbers(sentence)
    q_terms = _latin_terms(sentence)
    if not q_nums and not q_terms:
        return []
    q_denom = max(len(q_nums) * 3 + len(q_terms) * 2, 1)

    scored: list[tuple[float, dict]] = []
    for it in index:
        t_nums = _numbers(it["text"])
        t_terms = _latin_terms(it["text"])
        shared_n = len(q_nums & t_nums)
        shared_t = len(q_terms & t_terms)
        if shared_n == 0 and shared_t == 0:
            continue
        score = (shared_n * 3 + shared_t * 2) / q_denom
        # 原句数字更多时轻微降权（命中了大段罗列多个数值的句子）
        if t_nums and shared_n < len(t_nums) * 0.5 and len(t_nums) > 3:
            score *= 0.75
        if score >= min_score:
            scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{**it, "score": round(s, 2)} for s, it in scored[:limit]]


def locate_sentences_batch(sentences: list[str], index: list[dict]) -> list[list[dict]]:
    """批量定位（同一索引复用，供 UI 逐句展示）"""
    return [locate_sentence(s, index) for s in sentences]
