"""综述化引擎（P2 主线 A：面向医学生 / 研究生）

解决的问题：检索到 20 篇文献之后，用户真正要做的不是"逐篇读摘要"，而是把它们
摆在一起看——谁做的是随机对照、样本量多大、结论是否互相矛盾、写进综述的方法学
部分需要交代哪些筛选步骤。这一层能力目前竞品普遍缺失（或仅面向英文用户）。

本模块**全部为离线规则引擎**，不调用任何外部接口，因此云端零成本、可反复重算：

- ``extract_profile()``    单篇结构化画像（研究设计 / 样本量 / 人群 / 干预 / 主要终点 /
                           效应量 / 结论句与结论倾向）
- ``build_comparison()``   多篇横向对比表（含证据强度提示）
- ``detect_conflicts()``   同一主题下结论不一致的自动识别
- ``prisma_*()``           PRISMA 式「检索 — 筛选 — 纳入」记录
- ``build_review_draft()`` 综述初稿骨架（背景 — 方法 — 结果 — 讨论）
- 导出：``comparison_markdown`` / ``comparison_csv`` / ``references_markdown``

P2 主线 B（证据化，面向临床医生）在同一份画像上追加：

- ``design_layer()`` / ``cebm_level()``  研究类型分层与 CEBM 简化等级参考
- ``assess_bias()``      摘要层面可核实的偏倚提示（约 16 条规则，逐条可溯源，只提示不裁决）
- ``extract_followup()`` / ``classify_outcome()``  随访时长、终点性质（硬终点 / 替代终点）
- ``assess_applicability()``  人群 / 干预 / 结局 / 对照 / 场景五维对照，供医生人工比对
- 导出：``bias_markdown`` / ``applicability_markdown``

设计原则（很重要，直接决定这东西能不能信）：

1. **宁可标「未识别」，也不猜**。抽取不到就留空并说明原因，不生成看起来专业
   但实际错误的内容——医学场景下，错误信息的代价远高于"没填"。
2. 每一条结论都附带**原文片段**（snippet）作为证据，可回原文核对。
3. 冲突识别只负责"提示需要人工核对"，**不做结论仲裁**；证据强度用
   "研究设计 + 样本量 + 是否报告区间估计"的可解释加权，明确标注不是 GRADE 分级。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from core import summarizer

# ---------------------------------------------------------------------------
# 一、研究设计识别
# ---------------------------------------------------------------------------
# 顺序即优先级：一篇文献可能同时命中多条（如 "systematic review of randomized
# trials"），此时按此顺序取最"高等级"的那一类。叙述性综述放在最后，
# 避免把 "systematic review" 误判成普通综述。
_DESIGN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "系统评价 / Meta 分析",
        ("systematic review", "meta-analysis", "meta analysis", "meta-analyses",
         "pooled analysis", "network meta", "系统评价", "荟萃分析", "meta分析"),
    ),
    (
        "随机对照试验",
        ("randomized controlled", "randomised controlled", "randomly assigned",
         "double-blind", "double blind", "placebo-controlled", "randomized trial",
         "randomised trial", "randomized clinical trial", "randomly allocated",
         "crossover trial", "randomised controlled trial", "随机对照"),
    ),
    (
        "临床指南 / 专家共识",
        ("clinical practice guideline", "practice guideline", "consensus statement",
         "expert consensus", "recommendations from the", "guideline recommend",
         "指南", "专家共识"),
    ),
    (
        "队列研究",
        ("prospective cohort", "retrospective cohort", "cohort study", "cohort of",
         "longitudinal cohort", "follow-up study", "observational cohort",
         "population-based cohort", "队列研究"),
    ),
    (
        "病例对照研究",
        ("case-control", "case control study", "matched case-control", "病例对照"),
    ),
    (
        "横断面研究",
        ("cross-sectional", "cross sectional", "nationwide survey", "questionnaire survey",
         "prevalence study", "cross-sectional study", "横断面"),
    ),
    (
        "病例报告 / 病例系列",
        ("case report", "case series", "we report a case", "病例报告"),
    ),
    (
        "基础 / 动物实验",
        ("in vitro", "in vivo", "mice", "murine", "rat model", "mouse model",
         "cell line", "xenograft", "organoid", "zebrafish", "动物实验"),
    ),
    (
        "叙述性综述",
        ("narrative review", "this review", "we review", "overview of",
         "literature review", "review article", "综述"),
    ),
)

# 证据强度加权：仅用于排序提示，不是正式证据分级
_DESIGN_BASE = {
    "系统评价 / Meta 分析": 4.0,
    "随机对照试验": 3.0,
    "临床指南 / 专家共识": 3.0,
    "队列研究": 2.0,
    "病例对照研究": 2.0,
    "横断面研究": 1.0,
    "病例报告 / 病例系列": 1.0,
    "基础 / 动物实验": 1.0,
    "叙述性综述": 1.0,
    "未识别": 0.0,
}

# ---------------------------------------------------------------------------
# 二、结论倾向（极性）判定
# ---------------------------------------------------------------------------
# 判定顺序：先排除"否定式表述"（no significant / did not...），再看风险信号，
# 最后才认阳性结论。否则 "no significant improvement" 会被误判成"有效"。
_NULL_CUES = (
    "no significant", "no statistically significant", "not significantly",
    "did not significantly", "no difference", "no significant difference",
    "were comparable", "was comparable", "similar between", "no association",
    "not associated", "no benefit", "no effect", "no improvement", "unchanged",
    "no evidence of", "failed to show", "did not improve", "did not reduce",
    "neither", "无显著差异", "未见显著", "无统计学差异", "未发现差异",
)
_HARM_CUES = (
    "significantly worse", "increased risk", "higher risk", "higher mortality",
    "increased mortality", "adverse", "harmful", "inferior", "worsened",
    "increased incidence", "more likely to die", "increased the risk",
    "风险增加", "死亡率更高", "更差",
)
_POS_CUES = (
    "significantly improved", "significant improvement", "improved",
    "significantly reduced", "reduced the risk", "significantly decreased",
    "significantly lower", "associated with lower", "associated with better",
    "prolonged survival", "increased survival", "improved survival",
    "effective", "efficacy", "superior", "benefit", "beneficial", "protective",
    "better outcomes", "significant", "显著改善", "显著降低", "提示有效",
)

POLARITY_POS = "支持有效 / 正相关"
POLARITY_NULL = "无显著差异 / 无关联"
POLARITY_HARM = "提示风险增加 / 不利"
POLARITY_UNKNOWN = "未明确"

_NEGATION_RE = re.compile(
    r"(?:no|not|without|neither|nor|failed to|did not|does not|wasn't|weren't|"
    r"未|无|没有|不)\s*$",
    re.I,
)


def _match_cue(text: str, cues: tuple[str, ...]) -> str:
    """在文本中找第一个**未被否定**的线索词，返回命中的线索（找不到返回空串）。

    否定判断只看线索词前 14 个字符——足够覆盖 "there was no significant..." 这类
    常见句式，又不会把上一句话的否定误算进来。
    """
    for cue in cues:
        start = 0
        while True:
            idx = text.find(cue, start)
            if idx == -1:
                break
            head = text[max(0, idx - 14):idx]
            if not _NEGATION_RE.search(head):
                return cue
            start = idx + 1
    return ""


def judge_polarity(text: str) -> tuple[str, str]:
    """判断结论文本的倾向，返回 ``(倾向标签, 命中线索)``。"""
    if not text:
        return POLARITY_UNKNOWN, ""
    low = text.lower()
    null = _match_cue(low, _NULL_CUES)
    if null:
        # "no significant difference in mortality, but increased risk of X" 仍判无差异优先，
        # 因为否定式表述是作者对主要结论的表述方式
        return POLARITY_NULL, null
    harm = _match_cue(low, _HARM_CUES)
    if harm:
        return POLARITY_HARM, harm
    pos = _match_cue(low, _POS_CUES)
    if pos:
        return POLARITY_POS, pos
    return POLARITY_UNKNOWN, ""


# ---------------------------------------------------------------------------
# 三、结构化字段抽取
# ---------------------------------------------------------------------------
_N_PATTERNS = (
    re.compile(r"\b[Nn]\s*=\s*([\d][\d,]{1,})"),
    re.compile(
        r"\b(\d[\d,]{1,})\s+(?:patients|participants|subjects|individuals|adults|"
        r"children|neonates|infants|cases|records|people|women|men|pregnancies|"
        r"eyes|lesions|samples|pairs|centers|centres)\b"
    ),
    re.compile(r"\b(?:total of|enrolled|included|analyzed|analysed|recruited|"
               r"randomized|randomised)\s+(\d[\d,]{1,})"),
    re.compile(r"共\s*(?:纳入|收集|分析)?\s*(\d[\d,]{1,})\s*(?:例|名|位|篇)"),
)

_POP_RE = re.compile(
    r"\b(?:patients|adults|children|adolescents|women|men|participants|individuals|"
    r"neonates|infants)\s+(?:with|who)\s+([A-Za-z0-9\-/ ,]{3,70})",
    re.I,
)
_INTERV_RE = re.compile(
    r"\b(?:treated with|received|were given|assigned to|compared|underwent|"
    r"administered|intervention was)\s+([A-Za-z0-9\-/ ,%+]{3,60})",
    re.I,
)
_PRIMARY_OUTCOME_RE = re.compile(
    r"\bprimary\s+(?:outcome|end\s?point)s?\b|\bmain\s+(?:outcome|end\s?point)\b|主要(?:终点|结局)",
    re.I,
)
_CONCLUSION_LABEL_RE = re.compile(
    r"^\s*(?:conclusions?|结论)\s*[:：]\s*(.+)$", re.I | re.S,
)
# 摘要尾部常见的、不属于结论的内容
_TAIL_NOISE_RE = re.compile(
    r"^(trial registration|funding|registration|clinicaltrials\.gov|"
    r"copyright|©|conflict of interest|keywords|研究注册|注册号)",
    re.I,
)

_EFFECT_PATTERNS = (
    ("HR", re.compile(r"\b(?:aHR|HR|hazard ratio)\s*[=:]?\s*(\d+(?:\.\d+)?)", re.I)),
    ("OR", re.compile(r"\b(?:aOR|OR|odds ratio)\s*[=:]?\s*(\d+(?:\.\d+)?)", re.I)),
    ("RR", re.compile(r"\b(?:aRR|RR|risk ratio|relative risk)\s*[=:]?\s*(\d+(?:\.\d+)?)", re.I)),
    ("IRR", re.compile(r"\bIRR\s*[=:]?\s*(\d+(?:\.\d+)?)", re.I)),
)
# 注意：不能用 [^.;]。区间值本身带小数点（0.58-0.90），用句点做终止符会把
# 「95% CI 0.58-0.90」截成「95% CI 0」。
_CI_RE = re.compile(
    r"95%\s*(?:CI|confidence interval)\s*[:：]?\s*([0-9][0-9.,\-–—\s]{2,28})", re.I)
_P_RE = re.compile(r"\b[Pp]\s*(?:<|>|=|≤|≥)\s*0?\.\d+")
_MD_RE = re.compile(r"\b(?:WMD|SMD|MD)\s*[=:]?\s*[-−]?\s*\d+(?:\.\d+)?", re.I)


def _clean_snippet(text: str, limit: int = 160) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip()
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def extract_sample_size(article: dict) -> tuple[int | None, str]:
    """抽取样本量，返回 ``(数值, 原文片段)``；抽取不到返回 ``(None, "")``。

    多篇文献的摘要里会同时出现"共筛查 5000 例、最终纳入 213 例"这类表述，
    因此取各组命中值中的**最大值**——通常是研究总体规模。
    """
    text = article.get("abstract") or ""
    best: int | None = None
    best_ctx = ""
    for rx in _N_PATTERNS:
        for m in rx.finditer(text):
            raw = m.group(1).replace(",", "")
            try:
                val = int(raw)
            except ValueError:
                continue
            if not (10 <= val <= 5_000_000):
                continue
            if best is None or val > best:
                best = val
                best_ctx = _clean_snippet(text[max(0, m.start() - 40):m.end() + 20])
    return best, best_ctx


def extract_effects(article: dict) -> dict:
    """抽取效应量与区间估计：HR / OR / RR / IRR、95% CI、P 值、MD。

    返回 ``{"HR": ["0.72", ...], ..., "CI": [...], "P": [...], "snippet": 原句}``。
    ``snippet`` 取包含第一个效应量数值的完整句子，便于回原文核对。
    """
    text = article.get("abstract") or ""
    out: dict = {}
    for name, rx in _EFFECT_PATTERNS:
        vals: list[str] = []
        for m in rx.finditer(text):
            v = m.group(1)
            if v not in vals:
                vals.append(v)
        if vals:
            out[name] = vals
    ci = [c.strip(" ,;，；") for c in _CI_RE.findall(text)]
    if ci:
        out["CI"] = [f"95% CI {c}" for c in ci[:6] if c]
    pvals = _P_RE.findall(text)
    if pvals:
        out["P"] = pvals[:6]
    md = _MD_RE.findall(text)
    if md:
        out["MD"] = md[:4]

    snippet = ""
    if any(k in out for k in ("HR", "OR", "RR", "IRR")):
        for sent in summarizer.split_sentences(text):
            if any(rx.search(sent) for _, rx in _EFFECT_PATTERNS):
                snippet = _clean_snippet(sent, 220)
                break
    return out


def effect_direction(effects: dict) -> int:
    """由效应量数值判断方向：``-1`` 偏向降低、``1`` 偏向升高、``0`` 无/未知。

    HR / OR / RR < 1 表示结局事件风险降低，> 1 表示升高。取第一个可用数值判断。
    """
    for key in ("HR", "OR", "RR", "IRR"):
        for v in effects.get(key, []) or []:
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if abs(num - 1.0) < 1e-9:
                return 0
            return -1 if num < 1 else 1
    return 0


def extract_conclusion(article: dict) -> tuple[str, str]:
    """抽取结论句，返回 ``(结论文本, 来源说明)``。

    优先取结构化摘要的 ``CONCLUSION:`` 段；没有标签时退回摘要最后两句
    （并跳过试验注册号、资助声明这类尾部噪音）。
    """
    abstract = article.get("abstract") or ""
    if not abstract.strip():
        return "", "无摘要"
    # 1) 结构化摘要标签：fetch_articles 会把 Label 拼成 "CONCLUSION: xxx" 并独占一行
    for line in abstract.split("\n"):
        m = _CONCLUSION_LABEL_RE.match(line.strip())
        if m:
            return _clean_snippet(m.group(1), 900), "结构化结论段"
    # 2) 退回末两句
    sents = [
        s.strip() for s in summarizer.split_sentences(abstract)
        if len(s.strip()) >= 20 and not _TAIL_NOISE_RE.match(s.strip())
    ]
    if not sents:
        return "", "摘要过短"
    tail = sents[-2:] if len(sents) >= 2 else sents[-1:]
    return _clean_snippet(" ".join(tail), 900), "摘要末句（无结构化标签）"


def extract_population(article: dict) -> str:
    text = (article.get("title") or "") + ". " + (article.get("abstract") or "")
    m = _POP_RE.search(text)
    if not m:
        return ""
    frag = m.group(1)
    frag = re.split(r"[.;,]\s|\bwere\b|\bwas\b|\band\b\s+\d", frag)[0]
    return _clean_snippet(frag, 60)


def extract_intervention(article: dict) -> str:
    text = (article.get("title") or "") + ". " + (article.get("abstract") or "")
    m = _INTERV_RE.search(text)
    return _clean_snippet(m.group(1), 50) if m else ""


def extract_primary_outcome(article: dict) -> str:
    for sent in summarizer.split_sentences(article.get("abstract") or ""):
        if _PRIMARY_OUTCOME_RE.search(sent):
            return _clean_snippet(sent, 200)
    return ""


def judge_design(article: dict) -> tuple[str, str]:
    """识别研究设计，返回 ``(设计标签, 命中依据原文)``。"""
    title = article.get("title") or ""
    abstract = article.get("abstract") or ""
    low_title = title.lower()
    low_all = f"{title} {abstract}".lower()
    for label, cues in _DESIGN_RULES:
        for cue in cues:
            # 标题命中优先：标题里的 "randomized trial" 比摘要里偶然出现的更可靠
            if cue in low_title:
                return label, f"标题命中「{cue}」"
            if cue in low_all:
                return label, f"摘要命中「{cue}」"
    return "未识别", "标题与摘要中未见明确的研究设计表述"


def evidence_strength(design: str, n: int | None, effects: dict) -> dict:
    """可解释的证据强度提示（**不是** GRADE 分级）。

    评分 = 设计基准分 + 样本量加分 + 是否报告区间估计加分，每一项都在
    ``basis`` 里写明依据，用户可自行判断是否认可。
    """
    score = _DESIGN_BASE.get(design, 0.0)
    parts = [f"设计={design}（{score:g} 分）"]
    if n:
        if n >= 1000:
            score += 1.0
            parts.append(f"样本量 {n}（+1）")
        elif n >= 100:
            score += 0.5
            parts.append(f"样本量 {n}（+0.5）")
        else:
            parts.append(f"样本量 {n}（不足 100，不加分）")
    else:
        parts.append("样本量未抽取到（不加分）")
    if effects.get("CI") or effects.get("P"):
        score += 0.5
        parts.append("报告了 95% CI 或 P 值（+0.5）")
    else:
        parts.append("未见区间估计或 P 值（不加分）")
    label = "强" if score >= 4 else ("中" if score >= 2.5 else "弱")
    return {"score": round(score, 1), "label": label, "basis": "；".join(parts)}


# ---------------------------------------------------------------------------
# 三·五、证据化（P2 主线 B）：面向临床医生的"这条证据我能不能用"
# ---------------------------------------------------------------------------
# 与主线 A（综述化）的分工：A 解决"把这些文献摆在一起看"，B 解决"看的时候
# 该警惕什么、以及它能不能套到我眼前这个病人身上"。所有结论都遵守两条纪律：
#
#   1. **只提示，不裁决**。工具读不到全文、也不认识病人，永不说"这篇不能用"，
#      只列出"需要注意什么"以及"为什么"，最终判断权留给医生。
#   2. **每条提示都能溯源**。附摘要原文片段；摘要确实没写，就明确标成
#      "摘要未提及"——"没写"本身就是需要标注的信息，不能静默略过。
#
# 特别声明：「证据等级」是牛津 CEBM 2011 分级的**简化对应**（按治疗/预防类问题
# 的常见映射，仅依据研究设计），**不考虑**偏倚风险、间接性、不一致性、发表偏倚
# 等降级因素，因此**不等于**正式分级，也不能替代 Cochrane RoB 2 / NOS / GRADE
# 等规范工具。我们宁可把话说小，也不给用户一个看起来权威、实际会误导的等级。
CEBM_CAVEAT = (
    "「证据等级」按研究设计粗略对应牛津 CEBM 2011 分级（治疗/预防类问题），"
    "未考虑偏倚风险、间接性与不一致性等降级因素，**不是正式证据分级**，"
    "不能替代 Cochrane RoB 2 / NOS / GRADE 等评价工具。"
)

DESIGN_LAYERS: dict[str, str] = {
    "系统评价 / Meta 分析": "二次研究（证据合成）",
    "临床指南 / 专家共识": "二次研究（推荐意见）",
    "叙述性综述": "二次研究（叙述性）",
    "随机对照试验": "干预性研究（试验）",
    "队列研究": "观察性研究",
    "病例对照研究": "观察性研究",
    "横断面研究": "观察性研究",
    "病例报告 / 病例系列": "描述性研究",
    "基础 / 动物实验": "基础研究",
    "未识别": "未识别",
}

_CEBM_REF: dict[str, tuple[str, str]] = {
    "系统评价 / Meta 分析": ("1a", "同质随机对照试验的系统评价"),
    "随机对照试验": ("1b", "单项随机对照试验（置信区间较窄时）"),
    "临床指南 / 专家共识": ("—", "推荐意见文件，可信度取决于制定方法，工具不代为分级"),
    "队列研究": ("2b", "单项队列研究（或质量较差的随机对照试验）"),
    "病例对照研究": ("3b", "非连续纳入的病例对照研究"),
    "横断面研究": ("4", "描述性证据，只能反映同期分布，不能推断因果"),
    "病例报告 / 病例系列": ("4", "无对照的病例报告 / 病例系列"),
    "基础 / 动物实验": ("5", "机制研究，尚未在患者中验证"),
    "叙述性综述": ("5", "叙述性综述 / 专家意见"),
    "未识别": ("—", "研究类型未识别，不给等级"),
}

# 偏倚提示级别用词：刻意**不用**"高/中/低风险"——那是 RoB 2 等工具的专有判定，
# 需要逐条回答信号问题才能给出。这里只区分"要多看一眼"的程度。
BIAS_FOCUS = "重点核对"
BIAS_CHECK = "建议核对"
BIAS_INFO = "信息缺失"
_BIAS_LEVEL_ORDER = {BIAS_FOCUS: 0, BIAS_CHECK: 1, BIAS_INFO: 2}

_FOLLOWUP_EN_RE = re.compile(
    r"follow[- ]?up[^.;\n]{0,40}?(\d+(?:\.\d+)?)\s*"
    r"(day|week|month|year|mo|yr)s?\b", re.I,
)
_FOLLOWUP_ZH_RE = re.compile(r"随访[^。；\n]{0,25}?(\d+(?:\.\d+)?)\s*(天|周|个月|月|年)")

_CONTROL_CUES = (
    "control group", "controlled trial", "placebo", "comparator", "compared with",
    "compared to", "versus", " vs ", "usual care", "standard care", "routine care",
    "sham", "non-exposed", "unexposed", "对照", "安慰剂",
)
_MULTICENTER_CUES = (
    "multicenter", "multicentre", "multi-center", "multi-centre", "multinational",
    "across centers", "across centres", "多中心",
)
_SINGLE_CENTER_CUES = ("single-center", "single centre", "single institution",
                       "at one center", "单中心")
_BLIND_CUES = ("double-blind", "double blind", "single-blind", "single blind",
               "blinded", "masking", "masked", "allocation concealment",
               "double dummy", "盲法", "双盲", "单盲")
_SELF_REPORT_CUES = ("self-reported", "self reported", "self-administered",
                     "patient-reported", "questionnaire", "questionnaires",
                     "自评", "自报")
_SINGLE_ARM_CUES = ("single-arm", "single arm", "one-arm", "uncontrolled",
                    "open-label single", "non-comparative")
_RETROSPECTIVE_CUES = ("retrospective", "retrospectively", "回顾性")
_CAUSAL_CUES = ("caused", "causes", "led to", "leads to", "resulted in",
                "results in", "due to", "attributable to", "导致", "引起")
_SURROGATE_CUES = (
    "hba1c", "blood pressure", "ldl", "hdl", "triglyceride", "cholesterol",
    "biomarker", "biomarkers", "biochemical", "surrogate", "radiographic response",
    "tumor size", "tumour size", "response rate", "viral load", "bmi", "density",
    "inflammatory marker", "crp", "血糖", "血压", "血脂", "生物标志物",
)
_PATIENT_IMPORTANT_CUES = (
    "overall survival", "mortality", "death", "died", "myocardial infarction",
    "stroke", "hospitalization", "hospitalisation", "quality of life",
    "complication", "relapse", "recurrence", "disability", "symptom",
    "functional status", "总生存", "死亡率", "生活质量",
)
_REGISTRATION_RE = re.compile(r"\b(?:NCT\d{7,8}|ChiCTR[-\w]*|ISRCTN\d+|"
                              r"clinicaltrials\.gov|umin\.ac\.jp|注册号)\b", re.I)

_OBSERVATIONAL_DESIGNS = {"队列研究", "病例对照研究", "横断面研究", "病例报告 / 病例系列"}
_TRIAL_DESIGNS = {"随机对照试验"}
_EVIDENCE_SYNTHESIS = {"系统评价 / Meta 分析", "临床指南 / 专家共识", "叙述性综述"}


def design_layer(design: str) -> str:
    """研究类型 → 所属大类（干预性 / 观察性 / 描述性 / 二次研究 / 基础）。"""
    return DESIGN_LAYERS.get(design, "未识别")


def cebm_level(design: str) -> tuple[str, str]:
    """按研究设计给出牛津 CEBM 分级的简化对应，返回 ``(等级, 对应说明)``。

    仅作**粗略参考**，使用前请读 ``CEBM_CAVEAT``。
    """
    return _CEBM_REF.get(design, ("—", "研究类型未识别，不给等级"))


_CUE_PATTERN_CACHE: dict[tuple[str, ...], re.Pattern] = {}


def _cue_pattern(cues: tuple[str, ...]) -> re.Pattern:
    """把线索词表编成一个正则（带缓存）。

    为什么不能直接用 ``cue in text``：纯字母线索必须加词边界，否则
    ``died`` 会命中 ``studied``、``bmi`` 会命中 ``bmip`` 之类的片段，
    凭空给用户制造一条并不存在的"偏倚提示"。含空格 / 连字符的线索
    （`` vs ``、``single-arm``）保留子串语义，只对两侧字母数字做排除。
    """
    pat = _CUE_PATTERN_CACHE.get(cues)
    if pat is None:
        parts = []
        for c in cues:
            if re.fullmatch(r"[A-Za-z0-9]+", c):
                parts.append(rf"\b{re.escape(c)}\b")
            elif c.startswith(" ") or c.endswith(" "):
                # 必须**先 strip 再 escape**：反过来会把 re.escape 产出的
                # 尾部带转义空格的 `\ vs\ ` 截成 `\ vs\`，那个残留反斜杠会
                # 转义掉后面 lookahead 的括号，整条正则直接编译失败。
                parts.append(
                    rf"(?<![A-Za-z0-9]){re.escape(c.strip())}(?![A-Za-z0-9])")
            else:
                parts.append(re.escape(c))
        pat = re.compile("|".join(parts), re.I)
        _CUE_PATTERN_CACHE[cues] = pat
    return pat


def _first_hit(low_text: str, cues: tuple[str, ...]) -> str:
    m = _cue_pattern(cues).search(low_text)
    return m.group(0).strip() if m else ""


def extract_followup(article: dict) -> tuple[str, float | None]:
    """抽取随访时长，返回 ``(可读文本, 折算月数)``；抽不到返回 ``("", None)``。"""
    text = article.get("abstract") or ""
    m = _FOLLOWUP_EN_RE.search(text) or _FOLLOWUP_ZH_RE.search(text)
    if not m:
        return "", None
    try:
        val = float(m.group(1))
    except (TypeError, ValueError):
        return "", None
    # 注意中文单位要先判 "个月"：写成 startswith("月") 会漏掉「个月」（它以「个」开头），
    # 结果 36 个月被当成 36 天折算成 1.2 个月，进而误报"随访时长较短"。
    unit = m.group(2).lower()
    if unit in ("个月", "月") or unit.startswith(("month", "mo")):
        months = val
    elif unit == "年" or unit.startswith(("year", "yr")):
        months = val * 12
    elif unit == "周" or unit.startswith("week"):
        months = val / 4.345
    else:                                   # day / 天
        months = val / 30.44
    return _clean_snippet(m.group(0), 60), round(months, 1)


def classify_outcome(article: dict) -> dict:
    """判断主要终点属于"患者重要结局"还是"替代终点"。

    仅作提示：替代终点本身不是缺点（很多领域只能用替代终点），但它与患者最终
    获益之间的关系需要额外论证，因此值得在证据卡上标出来。
    """
    text = f"{article.get('title') or ''}. {article.get('abstract') or ''}"
    low = text.lower()
    hard = _first_hit(low, _PATIENT_IMPORTANT_CUES)
    if hard:
        return {"class": "患者重要结局（硬终点）", "cue": hard}
    surr = _first_hit(low, _SURROGATE_CUES)
    if surr:
        return {"class": "替代终点（实验室 / 影像指标）", "cue": surr}
    return {"class": "未明确", "cue": ""}


def assess_bias(article: dict) -> dict:
    """基于**摘要层面可看到的信息**给出偏倚风险提示。

    返回 ``{"flags": [...], "level_counts": {...}, "focus": n, "label": str, "brief": str}``。
    每条 flag 形如 ``{"key", "label", "level", "reason", "evidence"}``。
    再次强调：这不是 RoB 2 之类的正式偏倚风险评估，逐条提示都附了摘要依据或
    明确标注"摘要未提及"，请据此回原文核对。
    """
    title = article.get("title") or ""
    abstract = article.get("abstract") or ""
    low = f"{title}. {abstract}".lower()
    design, _ = judge_design(article)
    n, _ = extract_sample_size(article)
    effects = extract_effects(article)
    conclusion, _ = extract_conclusion(article)
    polarity, _ = judge_polarity(conclusion or abstract)
    follow_txt, follow_months = extract_followup(article)
    outcome = classify_outcome(article)

    flags: list[dict] = []

    def add(key: str, label: str, level: str, reason: str, evidence: str = "") -> None:
        flags.append({"key": key, "label": label, "level": level,
                      "reason": reason, "evidence": evidence})

    # 无摘要：后面所有提示都以摘要为依据，此时只能整体作罢（避免产生"看起来有依据"的空提示）
    if not abstract.strip():
        add("no_abstract", "无摘要，无法评估", BIAS_INFO,
            "数据库未提供摘要，研究设计以外的方法学信息（对照、盲法、随访、"
            "区间估计）均无法核实，本行的偏倚与适用性提示一律不适用。")
        return _bias_result(flags)

    # 1) 样本量 / 把握度
    if n is None:
        add("n_unknown", "样本量未抽取到", BIAS_INFO,
            "摘要中没有可识别的样本量表述，无法判断研究的把握度，建议回原文确认。")
    elif n < 100:
        add("small_n", "小样本", BIAS_CHECK,
            f"样本量仅 {n} 例，属于小样本：阳性结果更容易被随机波动放大，"
            "阴性结果也可能因为把握度不足而漏检真实差异。")

    # 2) 设计与结论的"错配"
    if design == "基础 / 动物实验":
        add("basic", "基础 / 动物实验", BIAS_FOCUS,
            "属于机制或动物层面研究，尚未在患者中验证；可用于解释机制，"
            "不能直接作为临床决策依据。",
            evidence=_first_hit(low, ("in vitro", "in vivo", "mice", "murine",
                                      "rat model", "mouse model", "cell line",
                                      "xenograft", "organoid", "zebrafish")))
    if design == "病例报告 / 病例系列":
        add("no_control_case", "无对照的描述性研究", BIAS_FOCUS,
            "病例报告 / 病例系列没有对照组，无法区分「干预效果」与「疾病自然"
            "病程、回归均值或伴随治疗」；主要用于提示罕见事件或提出假设。")
    if design in _OBSERVATIONAL_DESIGNS and polarity != POLARITY_UNKNOWN:
        causal = _first_hit(low, _CAUSAL_CUES)
        if causal:
            add("causal_claim", "观察性设计 + 因果性措辞", BIAS_FOCUS,
                "结论使用了因果性措辞，但研究为观察性设计：暴露并非随机分配，"
                "残余混杂与反向因果难以完全排除，宜表述为「相关」而非「导致」。",
                evidence=causal)
    if design in _TRIAL_DESIGNS and not _first_hit(low, _CONTROL_CUES):
        add("no_control_desc", "未见对照设置描述", BIAS_CHECK,
            "标注为随机对照类设计，但摘要中未出现对照组 / 比较组的描述，"
            "无法确认效应是相对什么得出的。")
    if _first_hit(low, _SINGLE_ARM_CUES):
        add("single_arm", "单臂 / 无同期对照", BIAS_FOCUS,
            "研究为单臂设计，缺少同期对照，疗效无法与自然病程或标准治疗区分。",
            evidence=_first_hit(low, _SINGLE_ARM_CUES))

    # 3) 选择 / 测量 / 报告偏倚线索
    if _first_hit(low, _RETROSPECTIVE_CUES):
        add("retrospective", "回顾性设计", BIAS_CHECK,
            "回顾性收集资料：暴露与结局在入组时均已发生，选择偏倚与回忆偏倚"
            "较难避免，因果时序证据弱于前瞻性设计。",
            evidence=_first_hit(low, _RETROSPECTIVE_CUES))
    if design == "横断面研究":
        add("cross_sectional", "横断面设计", BIAS_CHECK,
            "横断面设计只反映同一时点的分布，无法确定暴露与结局的先后顺序，"
            "不能用于判断因果或疗效。")
    if design in _TRIAL_DESIGNS and not _first_hit(low, _BLIND_CUES):
        add("no_blinding", "未提及盲法 / 分配隐藏", BIAS_CHECK,
            "摘要未提及盲法或分配隐藏：开放性试验中，主观终点（疼痛、症状评分）"
            "或知晓分组的医生容易产生测量偏倚。")
    if _first_hit(low, _SELF_REPORT_CUES):
        add("self_report", "自报结局", BIAS_CHECK,
            "结局由受试者自报或填写量表，存在报告偏倚与社会期望偏倚，"
            "建议核对是否使用了经过验证的工具。",
            evidence=_first_hit(low, _SELF_REPORT_CUES))

    # 4) 精确度 / 报告完整性
    if not effects.get("CI") and not effects.get("P"):
        add("no_precision", "未报告区间估计或 P 值", BIAS_CHECK,
            "摘要未报告 95% CI 或 P 值，无法评估效应估计的精确度，"
            "也看不出阴性结果是否只是样本量不足。")
    if not effects.get("CI") and (effects.get("HR") or effects.get("OR")
                                  or effects.get("RR") or effects.get("IRR")):
        add("no_ci_point", "仅有效应量点估计", BIAS_CHECK,
            "给出了 HR/OR/RR 的数值但未见 95% CI，需回原文核对置信区间与调整变量。")
    if polarity != POLARITY_UNKNOWN and not effect_text(effects):
        add("no_effect_size", "结论缺效应量", BIAS_CHECK,
            "结论给出了方向性判断，但摘要中没有可提取的效应量，"
            "无法核对效应大小是否具有临床意义。")
    if design in _TRIAL_DESIGNS and not _REGISTRATION_RE.search(abstract):
        add("no_registration", "未见试验注册号", BIAS_INFO,
            "摘要中未见试验注册号（NCT / ChiCTR / ISRCTN 等），无法核对结局指标"
            "是否在注册时预先设定，建议到注册库回查以排除选择性报告。")

    if design == "系统评价 / Meta 分析" and not _first_hit(
            low, ("heterogeneity", "i2", "i²", "random-effects", "fixed-effect",
                  "funnel plot", "publication bias", "sensitivity analysis",
                  "异质性", "发表偏倚")):
        add("no_heterogeneity", "未见异质性 / 发表偏倚说明", BIAS_CHECK,
            "系统评价 / Meta 分析摘要中未见异质性检验或发表偏倚评估的说明："
            "纳入研究若差异较大，合并后的点估计可能并不代表任何一个具体人群，"
            "建议核对原文的异质性指标（I²）与敏感性分析。")

    # 5) 外推与适用性前哨
    if not _first_hit(low, _MULTICENTER_CUES) and design not in _EVIDENCE_SYNTHESIS:
        if _first_hit(low, _SINGLE_CENTER_CUES):
            add("single_center", "单中心研究", BIAS_CHECK,
                "摘要明确为单中心研究：该中心的患者构成、诊疗习惯与操作者水平"
                "会影响结果，外推到其他机构时需谨慎。")
        else:
            # 级别刻意放在"信息缺失"而不是"建议核对"：摘要没写中心数≠它是单中心，
            # 把它升级成风险提示会让几乎每篇文献都背上一条，反而稀释了真正该看的项。
            add("center_unknown", "未说明是否多中心", BIAS_INFO,
                "摘要未说明研究中心数量；这不等于单中心，但外推前建议回原文确认"
                "（多中心研究涉及的人群与诊疗场景更广）。")
    if outcome["class"].startswith("替代终点"):
        add("surrogate", "主要终点为替代终点", BIAS_CHECK,
            f"主要终点判定为替代终点（命中「{outcome['cue']}」）："
            "指标改善不必然等同于患者最终获益（生存、生活质量）改善，"
            "需看是否有硬终点数据支撑。",
            evidence=outcome["cue"])
    if follow_months is None:
        add("followup_unknown", "随访时长未说明", BIAS_INFO,
            "摘要未说明随访时长，无法判断观察窗口是否覆盖临床关心的时点"
            "（例如长期生存、远期并发症）。")
    elif follow_months < 6:
        add("short_followup", "随访时长较短", BIAS_CHECK,
            f"随访约 {follow_txt}，不足以观察远期结局；对慢性病或肿瘤学问题，"
            "短随访的阳性结果需要更长随访来确认。",
            evidence=follow_txt)

    return _bias_result(flags)


def _bias_result(flags: list[dict]) -> dict:
    flags = sorted(flags, key=lambda f: _BIAS_LEVEL_ORDER.get(f["level"], 9))
    counts = {lv: sum(1 for f in flags if f["level"] == lv)
              for lv in (BIAS_FOCUS, BIAS_CHECK, BIAS_INFO)}
    focus = counts[BIAS_FOCUS]
    if focus:
        label = f"有 {focus} 项需重点核对"
    elif counts[BIAS_CHECK]:
        label = f"有 {counts[BIAS_CHECK]} 项建议核对"
    elif flags:
        # 只剩"信息缺失"：这类是"摘要没写"，不是"有问题"，用词上必须区分开，
        # 否则用户会把「摘要未说明随访时长」当成一项偏倚缺陷。
        label = "仅信息缺失项"
    else:
        label = "未自动发现"
    brief = "、".join(f["label"] for f in flags[:3])
    if len(flags) > 3:
        brief += f" 等 {len(flags)} 项"
    return {"flags": flags, "level_counts": counts, "focus": focus,
            "label": label, "brief": brief or "—"}


def bias_overview(rows: list[dict]) -> dict:
    """跨文献汇总偏倚提示，供页面顶部概览与初稿「局限性」段引用。"""
    from collections import Counter

    c: Counter = Counter()
    focus_docs = 0
    for r in rows:
        b = (r.get("_profile") or {}).get("bias") or {}
        if b.get("focus"):
            focus_docs += 1
        for f in b.get("flags") or []:
            c[f["label"]] += 1
    return {
        "total": len(rows),
        "focus_docs": focus_docs,
        "flags": dict(c.most_common()),
    }


def bias_markdown(rows: list[dict], topic: str = "") -> str:
    """偏倚风险提示清单（Markdown，供写进综述讨论 / 局限部分）。"""
    ov = bias_overview(rows)
    out = [f"### 偏倚风险提示清单（{topic}）" if topic else "### 偏倚风险提示清单", ""]
    out.append(f"- 纳入文献：{ov['total']} 篇；其中 {ov['focus_docs']} 篇存在需重点核对的提示项。")
    out.append("")
    out.append(f"> {CEBM_CAVEAT}")
    out.append("")
    out.append("> 本清单基于 PubMed **摘要**层面可看到的信息，逐条给出提示与依据，"
               "**不是** RoB 2 / NOS 等规范偏倚风险评估，也不能替代全文方法学评价。")
    out.append("")
    if ov["flags"]:
        out.append("**出现频次较高的提示项**")
        out.append("")
        for k, v in ov["flags"].items():
            out.append(f"- {k}：{v} 篇")
        out.append("")
    for i, r in enumerate(rows, 1):
        p = r["_profile"]
        b = p["bias"]
        out.append(f"**{i}. {p['title']}**")
        out.append("")
        out.append(f"- 研究设计：{p['design']}（{p['design_layer']}）"
                   f"｜证据等级参考：{p['cebm'][0]}（{p['cebm'][1]}）")
        if not b["flags"]:
            out.append("- 未自动发现需要提示的项——不等于没有偏倚，只是摘要层面看不出线索。")
        for f in b["flags"]:
            ev = f"（依据：{f['evidence']}）" if f["evidence"] else ""
            out.append(f"- [{f['level']}] {f['label']}：{f['reason']}{ev}")
        out.append("")
    return "\n".join(out)


# ---- 临床适用性（B4） ----
# 这一节**不做匹配判断**：工具不知道你的患者是谁。它只把文献一侧的四个关键
# 维度（人群、干预、结局、场景）先抽出来摆好，再列出"你需要拿什么去比"，
# 让医生的比对动作变得具体、不漏项。
APPLICABILITY_DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("人群", "年龄、性别、合并症、疾病分期 / 严重度、既往治疗线数是否与你的患者一致？"
             "文中若有排除标准（如肝肾功能不全、妊娠），你的患者是否恰好被排除在外？"),
    ("干预", "剂量、疗程、给药途径、联合方案能否复制？开展者经验与技术水平是否可比？"
             "在你所在机构是否可及、是否可负担？"),
    ("结局", "文中终点是否是你真正关心的那个？若为替代终点，是否有硬终点数据？"
             "随访时长是否覆盖你关心的时点？"),
    ("对照", "比较对象是安慰剂、标准治疗还是不治疗？与你的临床实际做法是否一致——"
             "若标准治疗已经不同，效应量未必能直接搬用。"),
    ("场景", "单中心还是多中心？地区、人种、医疗体系与基线风险不同，"
             "绝对效应（而非相对效应）可能相差很大。"),
)


def assess_applicability(article: dict, profile: dict | None = None) -> dict:
    """抽取"这个研究是在谁身上、用什么、看了什么、看了多久"，供人工比对。

    刻意**不给**"适用 / 不适用"的结论——那需要知道具体患者，工具没有这个信息。
    """
    p = profile or {}
    population = p.get("population") or extract_population(article)
    intervention = p.get("intervention") or extract_intervention(article)
    design = p.get("design") or judge_design(article)[0]
    outcome = classify_outcome(article)
    follow_txt, follow_months = extract_followup(article)
    low = f"{article.get('title') or ''}. {article.get('abstract') or ''}".lower()

    if _first_hit(low, _MULTICENTER_CUES):
        setting = "多中心（摘要自述）"
    elif _first_hit(low, _SINGLE_CENTER_CUES):
        setting = "单中心（摘要自述）"
    else:
        setting = "摘要未说明"

    if design == "基础 / 动物实验":
        availability = "机制 / 动物研究，不直接适用于临床决策"
    elif not intervention:
        availability = "摘要未写明具体干预，需回原文核对"
    else:
        availability = "需核对在你所在机构是否可及、可负担"

    if design in _EVIDENCE_SYNTHESIS:
        population = population or "（二次研究，人群随纳入研究而定，需看亚组）"

    follow_text = follow_txt or "摘要未说明"
    if follow_months is not None and follow_months < 6:
        follow_flag = "偏短"
    elif follow_months is None:
        follow_flag = "未知"
    else:
        follow_flag = ""

    return {
        "population": population or "摘要未写明",
        "intervention": intervention or "摘要未写明",
        "outcome_class": outcome["class"],
        "outcome_cue": outcome["cue"],
        "followup": follow_text,
        "followup_months": follow_months,
        "followup_flag": follow_flag,
        "setting": setting,
        "availability": availability,
        "note": (
            f"研究在「{population or '摘要未写明人群'}」中进行，主要终点为"
            f"「{outcome['class']}」，随访 {follow_text}，{setting}。"
            "能否套用到你的患者，取决于上表五维是否逐项对得上——这一步必须由你判断。"
        ),
    }


def applicability_markdown(rows: list[dict], topic: str = "") -> str:
    """临床适用性对照表（Markdown）。"""
    out = [f"### 临床适用性对照（{topic}）" if topic else "### 临床适用性对照", ""]
    out.append("> 本表只把文献一侧的信息摆出来，**不做适用与否的判断**——"
               "那需要结合具体患者，请逐维比对后再决定。")
    out.append("")
    head = "| # | 研究设计 | 证据等级 | 人群 | 干预 | 主要终点类型 | 随访 | 场景 |"
    out += [head, "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        p = r["_profile"]
        a = p["applicability"]
        cells = [
            str(i), _md_cell(p["design"]), _md_cell(p["cebm"][0]),
            _md_cell(a["population"]), _md_cell(a["intervention"]),
            _md_cell(a["outcome_class"]),
            _md_cell(a["followup"] + (f"（{a['followup_flag']}）" if a["followup_flag"] else "")),
            _md_cell(a["setting"]),
        ]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    out.append("**逐维比对清单（请你逐条回答）**")
    out.append("")
    for dim, q in APPLICABILITY_DIMENSIONS:
        out.append(f"- **{dim}**：{q}")
    out.append("")
    return "\n".join(out)


def extract_profile(article: dict) -> dict:
    """把一篇文献压成一张"结构化卡片"，供对比表、冲突识别与证据评估使用（纯离线）。"""
    design, design_ev = judge_design(article)
    n, n_ev = extract_sample_size(article)
    effects = extract_effects(article)
    conclusion, concl_src = extract_conclusion(article)
    polarity, cue = judge_polarity(conclusion or article.get("abstract", ""))
    return {
        "pmid": article.get("pmid", ""),
        "title": article.get("title", ""),
        "journal": article.get("journal", ""),
        "year": str(article.get("year", "") or ""),
        "authors": article.get("authors", []) or [],
        "doi": article.get("doi", ""),
        "pmcid": article.get("pmcid", ""),
        "design": design,
        "design_evidence": design_ev,
        "design_layer": design_layer(design),
        "cebm": cebm_level(design),
        "n": n,
        "n_evidence": n_ev,
        "population": extract_population(article),
        "intervention": extract_intervention(article),
        "primary_outcome": extract_primary_outcome(article),
        "effects": effects,
        "effect_direction": effect_direction(effects),
        "conclusion": conclusion,
        "conclusion_source": concl_src,
        "polarity": polarity,
        "polarity_cue": cue,
        "evidence": evidence_strength(design, n, effects),
        "bias": assess_bias(article),
        "applicability": assess_applicability(article),
        "followup": extract_followup(article)[0],
        "has_abstract": bool((article.get("abstract") or "").strip()),
    }


# ---------------------------------------------------------------------------
# 四、横向对比
# ---------------------------------------------------------------------------
def effect_text(effects: dict) -> str:
    """把效应量压成一行可读文本，如 ``HR 0.72（95% CI 0.58–0.90）; P=0.004``。"""
    if not effects:
        return ""
    parts = []
    for key in ("HR", "OR", "RR", "IRR", "MD"):
        if effects.get(key):
            parts.append(f"{key} {'/'.join(effects[key][:2])}")
    if effects.get("CI"):
        parts.append(effects["CI"][0])
    if effects.get("P"):
        parts.append(effects["P"][0].replace(" ", ""))
    return "；".join(parts)


def build_comparison(articles: list[dict]) -> list[dict]:
    """生成横向对比行（表头见 ``COMPARISON_COLUMNS``）。"""
    rows = []
    for i, a in enumerate(articles, 1):
        p = extract_profile(a)
        rows.append({
            "序号": i,
            "标题": p["title"],
            "年份": p["year"],
            "期刊": p["journal"],
            "研究设计": p["design"],
            "证据等级": p["cebm"][0],
            "样本量": p["n"] if p["n"] else "",
            "人群": p["population"],
            "主要终点": p["primary_outcome"],
            "关键效应量": effect_text(p["effects"]),
            "结论": p["conclusion"],
            "结论倾向": p["polarity"],
            "证据强度": p["evidence"]["label"],
            "偏倚提示": p["bias"]["brief"],
            "_profile": p,
        })
    return rows


COMPARISON_COLUMNS = ("序号", "标题", "年份", "期刊", "研究设计", "证据等级",
                      "样本量", "人群", "主要终点", "关键效应量", "结论",
                      "结论倾向", "证据强度", "偏倚提示")


def _md_cell(v) -> str:
    s = str(v if v is not None else "")
    s = s.replace("|", "／").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= 240 else s[:240] + "…"


def comparison_markdown(rows: list[dict], topic: str = "") -> str:
    """对比表 → Markdown 表格（可直接粘进 Word / 综述草稿）。"""
    head = "| " + " | ".join(COMPARISON_COLUMNS) + " |"
    sep = "|" + "|".join(["---"] * len(COMPARISON_COLUMNS)) + "|"
    lines = [head, sep]
    for r in rows:
        lines.append("| " + " | ".join(_md_cell(r.get(c, "")) for c in COMPARISON_COLUMNS) + " |")
    title = f"### 纳入文献基本特征对比（{topic}）\n" if topic else "### 纳入文献基本特征对比\n"
    return title + "\n" + "\n".join(lines) + "\n"


def comparison_csv(rows: list[dict]) -> bytes:
    """对比表 → CSV（utf-8-sig，Excel 直接打开不乱码）。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COMPARISON_COLUMNS)
    for r in rows:
        w.writerow([r.get(c, "") for c in COMPARISON_COLUMNS])
    return buf.getvalue().encode("utf-8-sig")


def summary_stats(rows: list[dict]) -> dict:
    """纳入文献的概况统计：设计分布、年份区间、样本量合计、结论倾向分布。"""
    from collections import Counter

    designs = Counter(r["研究设计"] for r in rows)
    polarity = Counter(r["结论倾向"] for r in rows)
    cebm = Counter((r.get("_profile") or {}).get("cebm", ("—",))[0] for r in rows)
    years = sorted(int(r["年份"][:4]) for r in rows if str(r["年份"])[:4].isdigit())
    ns = [r["样本量"] for r in rows if isinstance(r["样本量"], int)]
    n_missing = len(rows) - len(ns)
    return {
        "total": len(rows),
        "designs": dict(designs.most_common()),
        "polarity": dict(polarity.most_common()),
        "cebm": dict(cebm.most_common()),
        "bias": bias_overview(rows),
        "year_from": years[0] if years else None,
        "year_to": years[-1] if years else None,
        "n_total": sum(ns) if ns else 0,
        "n_missing": n_missing,
        "with_fulltext": len([r for r in rows if r["_profile"]["pmcid"]]),
    }


# ---------------------------------------------------------------------------
# 五、结论冲突识别
# ---------------------------------------------------------------------------
_STOP_TERMS = {"study", "studies", "patients", "results", "conclusion", "conclusions",
               "significant", "outcome", "outcomes", "analysis", "trial", "trials",
               "group", "groups", "risk", "effect", "method", "methods", "review"}


def _docs_containing(term: str, docs: list[str]) -> int:
    """统计词真正出现在几篇文献里。

    朴素子串匹配会把词形截断的产物也算进来——英文抽取会把 status 归一成 statu，
    于是 "performance statu" 成了 "performance status" 的子串，看着像术语其实是残词。
    所以额外要求命中处**词尾干净**（后面不是字母），残词自然被剔除。
    """
    k = term.lower()
    tail_is_alpha = k[-1:].isalpha()
    n = 0
    for d in docs:
        start = 0
        while True:
            i = d.find(k, start)
            if i == -1:
                break
            after = d[i + len(k):i + len(k) + 1]
            if not (tail_is_alpha and after.isalpha()):
                n += 1
                break
            start = i + 1
    return n


def topic_terms(rows: list[dict], top_n: int = 8, min_docs: int = 2) -> list[tuple[str, int]]:
    """抽取这批文献共同关心的主题词，返回 ``[(词, 覆盖篇数), ...]``。

    做法：用抽取式引擎在"标题 + 结论"上取关键词，再统计每个词实际出现在几篇文献里，
    只保留覆盖 ≥2 篇的词——单篇特有的词无法构成"同一问题下的分歧"。
    """
    blob = " ".join(f"{r['标题']} {r['结论']}" for r in rows)
    kws = summarizer.extract_keywords(blob, top_n=top_n * 4)
    docs = [(r["标题"] + " " + r["结论"]).lower() for r in rows]
    out: list[tuple[str, int]] = []
    for kw in kws:
        k = kw.lower()
        if k in _STOP_TERMS or len(k) < 4:
            continue
        cov = _docs_containing(kw, docs)
        if cov >= min_docs:
            out.append((kw, cov))
        if len(out) >= top_n:
            break
    return out


def _study_ref(row: dict) -> dict:
    p = row["_profile"]
    authors = p["authors"]
    first = authors[0] if authors else "（作者未获取）"
    return {
        "pmid": p["pmid"],
        "title": p["title"],
        "year": p["year"],
        "journal": p["journal"],
        "cite": f"{first} 等, {p['year'] or '年份不详'}",
        "design": p["design"],
        "n": p["n"],
        "polarity": p["polarity"],
        "conclusion": p["conclusion"],
        "snippet": _clean_snippet(p["conclusion"], 220),
    }


def detect_conflicts(rows: list[dict], top_n_terms: int = 8) -> dict:
    """识别同一主题下的结论不一致，返回 ``{"terms": [...], "conflicts": [...]}``。

    判两类冲突：
    1. **结论极性冲突**：同一主题词下，既有效果支持型研究、又有无差异型/不利型研究；
    2. **效应方向冲突**：同一主题词下不同研究报告的 HR / OR / RR 方向相反
       （一批 <1、一批 >1）——这类是硬证据，可信度标为"高"。

    重要：本函数**不做对错判断**。结论不一致的原因可能是人群、剂量、终点定义或
    随访时长差异，界面必须同时给出"请核对设计差异"的提示，而不是替用户下结论。
    """
    terms = topic_terms(rows, top_n=top_n_terms)
    conflicts: list[dict] = []

    for term, _cov in terms:
        hit_rows = [
            r for r in rows
            if _docs_containing(term, [(r["标题"] + " " + r["结论"]).lower()])
        ]
        if len(hit_rows) < 2:
            continue

        # --- 1) 极性冲突 ---
        buckets: dict[str, list[dict]] = {}
        for r in hit_rows:
            pol = r["结论倾向"]
            if pol == POLARITY_UNKNOWN:
                continue
            buckets.setdefault(pol, []).append(_study_ref(r))
        if len(buckets) >= 2:
            order = [POLARITY_POS, POLARITY_NULL, POLARITY_HARM]
            sides = [{"label": k, "studies": buckets[k]} for k in order if k in buckets]
            # 阳性 vs 无差异（或不利）是最典型的"结论打架"，给最高可信度
            high = POLARITY_POS in buckets and (
                POLARITY_NULL in buckets or POLARITY_HARM in buckets
            )
            conflicts.append({
                "type": "结论极性",
                "term": term,
                "confidence": "高" if high else "中",
                "sides": sides,
                "count": sum(len(s["studies"]) for s in sides),
                "note": "同一主题词下出现相反的研究结论，通常是人群、剂量、终点定义或随访时长不同所致，需回原文核对后再判断。",
            })

        # --- 2) 效应方向冲突 ---
        down = [_study_ref(r) for r in hit_rows if r["_profile"]["effect_direction"] < 0]
        up = [_study_ref(r) for r in hit_rows if r["_profile"]["effect_direction"] > 0]
        if down and up:
            conflicts.append({
                "type": "效应方向",
                "term": term,
                "confidence": "高",
                "sides": [
                    {"label": "效应偏向降低（HR/OR/RR < 1）", "studies": down},
                    {"label": "效应偏向升高（HR/OR/RR > 1）", "studies": up},
                ],
                "count": len(down) + len(up),
                "note": "不同研究报告的效应量方向相反。请重点核对各研究的暴露/干预定义、对照设置与终点事件，方向相反往往意味着研究对象不是同一回事。",
            })

    # 依据可比性排序：类型 + 覆盖篇数
    conflicts.sort(key=lambda c: (0 if c["type"] == "效应方向" else 1, -c["count"]))
    return {"terms": terms, "conflicts": _dedupe_conflicts(conflicts)}


def _dedupe_conflicts(conflicts: list[dict]) -> list[dict]:
    """合并"同一批研究"的重复冲突。

    同一处分歧会在多个近义主题词下反复命中（lung cancer / chemotherapy /
    overall survival 指的都是同一批文献），逐条列出会把真正要看的分歧淹掉
    ——实测 5 篇文献能产出 16 条"冲突"，其中大半是同一件事。
    规则：同类型下研究集合相同或为子集时，只保留覆盖面最大的那条。
    """
    kept: list[tuple[dict, frozenset]] = []
    for c in conflicts:
        studies = frozenset(s["pmid"] for side in c["sides"] for s in side["studies"])
        if not studies:
            continue
        same_type = [k for k in kept if k[0]["type"] == c["type"]]
        # 冲突已按覆盖篇数降序排过，所以先到的集合一定不比后来的小；
        # 只要当前这批研究已被已有条目覆盖（相同或更大），就是同一件事的另一种说法。
        if any(k[1] >= studies for k in same_type):
            continue
        for k in [k for k in same_type if k[1] < studies]:
            kept.remove(k)               # 兜底：后来的集合更大时，去掉被覆盖的小集合
        kept.append((c, studies))
    return [c for c, _ in kept]


def conflicts_markdown(conflicts: list[dict], topic: str = "") -> str:
    if not conflicts:
        return (f"### 结论一致性核查（{topic}）\n\n"
                "本次纳入文献中**未发现**同一主题下的结论冲突。\n"
                "需要说明的是：未发现冲突不等于结论一致——也可能是主题词覆盖不足或摘要未写明结论，"
                "建议人工通读一遍结论段。\n")
    out = [f"### 结论冲突核查（{topic}）", ""]
    for i, c in enumerate(conflicts, 1):
        out.append(f"**{i}. [{c['type']}] 主题词「{c['term']}」（可信度：{c['confidence']}）**")
        out.append("")
        for side in c["sides"]:
            out.append(f"- **{side['label']}**")
            for s in side["studies"]:
                out.append(f"  - {s['cite']}｜{s['design']}｜样本量 {s['n'] or '未抽取'}：{s['snippet']}")
        out.append(f"  - 提示：{c['note']}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 六、PRISMA 式筛选记录
# ---------------------------------------------------------------------------
def blank_prisma(query: str = "", total_hits: int = 0, retrieved: int = 0,
                 topic: str = "") -> dict:
    return {
        "topic": topic,
        "query": query,
        "database": "PubMed（NCBI E-utilities）",
        "date_range": "",
        "search_date": datetime.now().strftime("%Y-%m-%d"),
        "total_hits": int(total_hits or 0),
        "retrieved": int(retrieved or 0),
        "duplicates": 0,
        "excluded_screening": 0,
        "excluded_fulltext": 0,
        "excluded_reasons": [],
        "included": int(retrieved or 0),
        "notes": "",
    }


def auto_duplicates(articles: list[dict]) -> int:
    """按 PMID / DOI / 标题归一化统计重复条数（多来源合并时用）。"""
    seen_pmid, seen_title, dup = set(), set(), 0
    for i, a in enumerate(articles):
        key_p = (a.get("pmid") or "").strip()
        key_t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (a.get("title") or "").lower())[:80]
        if (key_p and key_p in seen_pmid) or (key_t and key_t in seen_title):
            dup += 1
            continue
        if key_p:
            seen_pmid.add(key_p)
        if key_t:
            seen_title.add(key_t)
        _ = i
    return dup


def prisma_counts(rec: dict) -> dict:
    """由记录推导各级数字，保证"识别 - 筛除 = 纳入"在表里自洽。"""
    identified = int(rec.get("total_hits") or 0)
    retrieved = int(rec.get("retrieved") or 0)
    dup = int(rec.get("duplicates") or 0)
    screened = max(0, retrieved - dup)
    ex_screen = int(rec.get("excluded_screening") or 0)
    ex_full = int(rec.get("excluded_fulltext") or 0)
    assessed = max(0, screened - ex_screen)
    included = max(0, assessed - ex_full)
    return {
        "identified": identified,
        "retrieved": retrieved,
        "duplicates": dup,
        "screened": screened,
        "excluded_screening": ex_screen,
        "assessed": assessed,
        "excluded_fulltext": ex_full,
        "included": included,
        "unretrieved": max(0, identified - retrieved),
    }


def prisma_markdown(rec: dict, rows: list[dict] | None = None) -> str:
    """生成可直接写进综述「资料与方法」的筛选流程记录。"""
    c = prisma_counts(rec)
    rows = rows or []
    if rows and not rec.get("included"):
        rec = dict(rec)
        rec["included"] = len(rows)
        c = prisma_counts(rec)
    reasons = rec.get("excluded_reasons") or []
    lines = [
        f"### 文献筛选流程（PRISMA 式记录）",
        "",
        f"- 检索数据库：{rec.get('database', 'PubMed')}",
        f"- 检索日期：{rec.get('search_date', '')}",
        f"- 检索时限：{rec.get('date_range') or '未限定'}",
        f"- 检索式：`{rec.get('query') or '未填写'}`",
        "",
        "| 阶段 | 条目 | 篇数 |",
        "|---|---|---|",
        f"| 识别 Identification | 数据库检索命中 | {c['identified']} |",
        f"| 识别 Identification | 实际下载题录 | {c['retrieved']} |",
        f"| 筛选 Screening | 去重后进入筛查 | {c['screened']}（去重 {c['duplicates']}） |",
        f"| 筛选 Screening | 阅读题名/摘要后排除 | {c['excluded_screening']} |",
        f"| 评估 Eligibility | 进入全文评估 | {c['assessed']} |",
        f"| 评估 Eligibility | 全文评估后排除 | {c['excluded_fulltext']} |",
        f"| **纳入 Included** | **最终纳入定性分析** | **{c['included']}** |",
        "",
    ]
    if reasons:
        if len(reasons) == 1 and "：" in reasons[0]:
            lines += ["**排除原因及篇数：**", ""]
            lines += [f"- {r}" for r in reasons]
        else:
            lines += ["**排除原因及篇数：**", ""]
            lines += [f"- {r}" for r in reasons]
        lines.append("")
    if rows:
        s = summary_stats(rows)
        lines += ["**纳入文献概况：**", ""]
        lines.append(f"- 纳入 {s['total']} 篇，其中 {s['with_fulltext']} 篇有 PMC 开放全文")
        if s["year_from"]:
            lines.append(f"- 发表年份：{s['year_from']}–{s['year_to']}")
        dist = "、".join(f"{k} {v} 篇" for k, v in s["designs"].items())
        lines.append(f"- 研究设计分布：{dist}")
        if s["n_total"]:
            note = f"（另有 {s['n_missing']} 篇未从摘要抽取到样本量，未计入）" if s["n_missing"] else ""
            lines.append(f"- 可统计样本量合计：{s['n_total']} 例{note}")
        lines.append("")
    if rec.get("notes"):
        lines += ["**补充说明：**", "", str(rec["notes"]), ""]
    lines += [
        "> 说明：本记录由工具依据检索参数与纳入文献自动生成，"
        "排除理由与篇数需使用者核对后填写/修正，方可写入正式方法学部分。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 七、综述初稿骨架
# ---------------------------------------------------------------------------
def references_markdown(rows: list[dict], start: int = 1) -> str:
    """Vancouver 风格参考文献列表（含 PMID / DOI，便于回查）。"""
    out = []
    for i, r in enumerate(rows, start):
        p = r["_profile"]
        authors = p["authors"]
        if len(authors) > 6:
            author_txt = ", ".join(authors[:6]) + ", et al"
        elif authors:
            author_txt = ", ".join(authors)
        else:
            author_txt = "作者信息未获取"
        bits = [f"[{i}] {author_txt}. {p['title']}."]
        if p["journal"]:
            bits.append(f"{p['journal']}.")
        if p["year"]:
            bits.append(f"{p['year']}.")
        if p["pmid"]:
            bits.append(f"PMID: {p['pmid']}.")
        if p["doi"]:
            bits.append(f"doi: {p['doi']}")
        out.append(" ".join(bits).strip())
    return "\n".join(out)


def _group_by_design(rows: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["研究设计"], []).append(r)
    out = []
    for design, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cites = "、".join(
            f"{(r['_profile']['authors'] or ['佚名'])[0]} 等（{r['年份'] or '年份不详'}）"
            for r in items
        )
        out.append(f"- **{design}**（{len(items)} 篇）：{cites}")
    return "\n".join(out) if out else "- （无）"


def build_review_draft(topic: str, rows: list[dict], conflicts: list[dict],
                       prisma: dict | None = None, extra: dict | None = None) -> str:
    """生成综述初稿骨架：背景 — 方法 — 结果 — 讨论 — 结论 — 参考文献。

    定位是**骨架**而不是成稿：所有需要作者判断的地方都写成显式占位
    （``【待补充：…】``），已由工具抽取的事实则直接填入并标注来源。
    """
    extra = extra or {}
    stats = summary_stats(rows)
    c = prisma_counts(prisma) if prisma else None
    topic_txt = topic or "【待补充：综述主题】"
    today = datetime.now().strftime("%Y-%m-%d")

    L: list[str] = []
    L.append(f"# {topic_txt}：文献综述初稿（自动生成骨架）")
    L.append("")
    L.append(f"> 生成日期：{today}　|　纳入文献：{stats['total']} 篇　|　"
             f"本文件由「医学文献智能摘要与检索系统」自动生成，"
             f"抽取内容均来自 PubMed 摘要，**须经作者核对原文后方可使用**。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 摘要")
    L.append("")
    L.append("【待补充：按「目的—方法—结果—结论」四句结构撰写，200–300 字。"
             "结果部分建议直接引用表 1 的研究数、样本量合计与主要结论倾向。】")
    L.append("")

    # ---------- 1 背景 ----------
    L.append("## 1　引言")
    L.append("")
    L.append(f"### 1.1　研究背景")
    L.append("")
    L.append(f"【待补充：{topic_txt} 的疾病负担、临床意义与当前认识的空白。"
             f"可参考下列高频主题词所在文献的引言部分："
             f"{'、'.join(t for t, _ in (extra.get('terms') or [])) or '（本次未抽取到稳定的共同主题词）'}。】")
    L.append("")
    L.append("### 1.2　本综述拟解决的问题")
    L.append("")
    L.append("【待补充：用一句可回答的问题描述，例如「X 干预能否改善 Y 人群的 Z 结局」。"
             "问题写得越具体，后面的结论冲突分析越有意义。】")
    L.append("")

    # ---------- 2 方法 ----------
    L.append("## 2　资料与方法")
    L.append("")
    L.append("### 2.1　检索策略")
    L.append("")
    if prisma:
        L.append(f"- 检索数据库：{prisma.get('database', 'PubMed')}")
        L.append(f"- 检索日期：{prisma.get('search_date', '')}")
        L.append(f"- 检索时限：{prisma.get('date_range') or '未限定'}")
        L.append(f"- 检索式：`{prisma.get('query') or '【待补充】'}`")
        L.append(f"- 数据库命中：{c['identified']} 篇，实际纳入题录 {c['retrieved']} 篇"
                 if c else "")
    else:
        L.append("【待补充：检索数据库、检索日期、检索式与时限。检索式可在「文献检索」页"
                 "的检索式预览处直接复制。】")
    L.append("")
    L.append("### 2.2　纳入与排除标准")
    L.append("")
    L.append("【待补充：纳入标准（研究类型、人群、干预、结局、语种）与排除标准"
             "（重复发表、无法获取全文、数据不完整等）。】")
    L.append("")
    L.append("### 2.3　文献筛选流程")
    L.append("")
    if prisma and c:
        L.append(f"检索命中 {c['identified']} 篇，去重后 {c['screened']} 篇进入题名/摘要筛查，"
                 f"排除 {c['excluded_screening']} 篇；{c['assessed']} 篇进入全文评估，"
                 f"排除 {c['excluded_fulltext']} 篇，最终纳入 **{c['included']} 篇**"
                 f"（完整流程表见随附的「筛选记录」文件）。")
    else:
        L.append("【待补充：可直接引用随附的 PRISMA 式筛选记录文件，替换本段。】")
    L.append("")
    L.append("### 2.4　数据提取与质量评价")
    L.append("")
    L.append("数据提取内容包括：第一作者、发表年份、研究设计、样本量、人群特征、"
             "主要终点与关键效应量（HR/OR/RR 及 95% CI）、主要结论。")
    L.append("研究质量采用【待补充：填写所用工具，如 Cochrane RoB 2 / NOS / JBI】评价。")
    L.append("")
    L.append("> 注：随附的「证据等级」「证据强度」「偏倚风险提示清单」均为工具基于"
             "**摘要**自动生成的**自查线索**，用于加快逐篇筛查的速度：")
    L.append(">")
    L.append("> - 「证据等级」按研究设计粗略对应牛津 CEBM 分级，未考虑偏倚风险、"
             "间接性与不一致性，**不是**正式分级；")
    L.append("> - 「证据强度」是「研究设计 + 样本量 + 是否报告区间估计」的可解释加权，"
             "**不是** GRADE；")
    L.append("> - 「偏倚提示」只列出摘要层面可见的线索（如小样本、无对照、未报告区间估计），"
             "**不是** RoB 2 / NOS 的正式评估结果。")
    L.append(">")
    L.append("> 以上三项**都不能直接写入方法学部分**，请自行用规范工具评价后填写。")
    L.append("")

    # ---------- 3 结果 ----------
    L.append("## 3　结果")
    L.append("")
    L.append("### 3.1　纳入文献的基本特征")
    L.append("")
    L.append(f"共纳入 {stats['total']} 篇文献"
             + (f"，发表年份介于 {stats['year_from']}–{stats['year_to']} 年" if stats["year_from"] else "")
             + (f"，其中 {stats['with_fulltext']} 篇可获取 PMC 开放全文。" if stats["with_fulltext"] else "。"))
    if stats["n_total"]:
        L.append("")
        L.append(f"可统计样本量合计约 **{stats['n_total']}** 例"
                 + (f"（{stats['n_missing']} 篇未从摘要抽取到样本量）" if stats["n_missing"] else "")
                 + "。")
    L.append("")
    L.append("研究类型分布：")
    L.append("")
    L.append(_group_by_design(rows))
    L.append("")
    L.append("详细特征见随附的「横向对比表」（表 1）。")
    L.append("")
    L.append("### 3.2　主要结局与效应量汇总")
    L.append("")
    with_eff = [r for r in rows if r["关键效应量"]]
    if with_eff:
        L.append(f"共有 {len(with_eff)} 篇文献在摘要中报告了可提取的效应量：")
        L.append("")
        for r in with_eff:
            p = r["_profile"]
            first = (p["authors"] or ["佚名"])[0]
            L.append(f"- {first} 等（{r['年份'] or '年份不详'}，{r['研究设计']}）："
                     f"{r['关键效应量']}")
        L.append("")
        L.append("【待补充：按结局指标（如总生存期、缓解率、不良事件）重新分组，"
                 "并将同类结局的效应量合并叙述或做 Meta 分析。】")
    else:
        L.append("【待补充：本次纳入文献的摘要中未提取到结构化效应量，"
                 "需阅读全文补充数据。】")
    L.append("")
    L.append("### 3.3　结论一致性")
    L.append("")
    if conflicts:
        L.append(f"经主题词交叉核对，发现 **{len(conflicts)} 处**结论可能不一致：")
        L.append("")
        for i, cf in enumerate(conflicts, 1):
            L.append(f"**（{i}）主题词「{cf['term']}」· {cf['type']}（可信度 {cf['confidence']}）**")
            L.append("")
            for side in cf["sides"]:
                n_items = len(side["studies"])
                L.append(f"- {side['label']}（{n_items} 篇）：" + "；".join(
                    f"{s['cite']}〔{s['design']}，样本量 {s['n'] or '未抽取'}〕"
                    for s in side["studies"]
                ))
            L.append("")
            L.append(f"　分析提示：{cf['note']}")
            L.append("")
        L.append("【待补充：逐条给出你的判断——是人群/剂量/终点定义差异，还是真的结果矛盾，"
                 "并据此决定是否做亚组分析。】")
    else:
        L.append("本次纳入文献中未自动发现明显的结论冲突。")
        L.append("")
        L.append("> 注意：结论倾向分布为 "
                 + "、".join(f"{k} {v} 篇" for k, v in stats["polarity"].items())
                 +                    "。未检出冲突不等于结论一致，可能只是摘要未写明结论或主题词覆盖不足，"
                   "建议人工通读全部结论段。")
    L.append("")

    # ---------- 3.4 偏倚风险与适用性概览（P2 主线 B） ----------
    L.append("### 3.4　偏倚风险与临床适用性概览")
    L.append("")
    ov = stats["bias"]
    if ov["flags"]:
        L.append(f"对纳入的 {ov['total']} 篇文献按摘要可核实的线索做了自动核对，"
                 f"其中 **{ov['focus_docs']} 篇**存在需要重点核对的提示项。"
                 "出现频次较高的提示项如下（逐篇明细见随附的「偏倚风险提示清单」）：")
        L.append("")
        for k, v in ov["flags"].items():
            L.append(f"- {k}：**{v}** 篇")
        L.append("")
    else:
        L.append("自动核对未发现需要提示的偏倚线索。**这不等于研究没有偏倚**——"
                 "摘要层面看不出线索，只能说明需要回原文逐篇评价。")
        L.append("")
    L.append("研究类型分层与证据等级参考：")
    L.append("")
    for r in rows:
        p = r["_profile"]
        L.append(f"- {r['序号']}. {p['design']}（{p['design_layer']}）"
                 f"→ 等级参考 {p['cebm'][0]}；{p['bias']['label']}。"
                 f"适用性：{p['applicability']['population']}｜"
                 f"终点 {p['applicability']['outcome_class']}｜"
                 f"随访 {p['applicability']['followup']}｜{p['applicability']['setting']}")
    L.append("")
    L.append(f"> {CEBM_CAVEAT}")
    L.append("")
    L.append("**向临床外推前，请逐维核对（详见随附「临床适用性对照」）**")
    L.append("")
    for dim, q in APPLICABILITY_DIMENSIONS:
        L.append(f"- **{dim}**：{q}")
    L.append("")

    # ---------- 4 讨论 ----------
    L.append("## 4　讨论")
    L.append("")
    L.append("### 4.1　主要发现")
    L.append("")
    L.append(f"【待补充：用 2–3 句概括 {topic_txt} 领域目前证据的整体走向。"
             "可参考结论倾向分布：" + "、".join(f"{k} {v} 篇" for k, v in stats["polarity"].items()) + "。】")
    L.append("")
    L.append("### 4.2　研究间差异的可能原因")
    L.append("")
    if conflicts:
        L.append("针对 3.3 中列出的不一致结论，可从以下角度分析：人群入选标准"
                 "（如分期、既往治疗线数）、干预剂量与疗程、对照设置、"
                 "终点定义与随访时长、样本量导致的把握度不足。")
    else:
        L.append("【待补充：即便结论方向一致，也建议讨论人群、剂量、随访时长的差异。】")
    L.append("")
    L.append("### 4.3　本综述的局限性")
    L.append("")
    L.append("- 数据提取基于 PubMed 摘要，未纳入未被数据库收录或未发表的研究，可能存在发表偏倚；")
    L.append("- 摘要常省略关键方法学细节，效应量与样本量存在抽取不全的情况；")
    L.append("- 结论倾向由规则引擎判定，仅用于提示，**最终判断须由作者核对原文**；")
    L.append("- 【待补充：检索语种限制、单数据库检索、未能获取全文的文献数量等】。")
    if ov["flags"]:
        top = "、".join(f"{k}（{v} 篇）" for k, v in list(ov["flags"].items())[:4])
        L.append("")
        L.append(f"从**纳入研究本身**看，自动核对提示较集中的问题为：{top}。"
                 "这些都是削弱证据可靠性的常见来源，建议在讨论中结合具体文献说明"
                 "它们对结论可能的影响方向与程度。")
        if ov["focus_docs"]:
            L.append("")
            L.append(f"尤其需要留意：{ov['focus_docs']} 篇存在需重点核对的提示项"
                     "（如无对照、观察性设计却使用因果表述、基础/动物研究），"
                     "引用其结论时请在文中标明研究类型与相应限制。")
    L.append("")

    # ---------- 5 结论 ----------
    L.append("## 5　结论")
    L.append("")
    L.append("【待补充：直接回答 1.2 提出的问题，并说明证据强度与适用人群边界。"
             "避免使用超出证据的表述，也避免写成临床建议。】")
    L.append("")

    # ---------- 6 参考文献 ----------
    L.append("## 6　参考文献")
    L.append("")
    L.append(references_markdown(rows))
    L.append("")
    return "\n".join(L)


def draft_with_llm(api_base: str, api_key: str, model: str, topic: str,
                   rows: list[dict], conflicts: list[dict]) -> str:
    """可选：让 LLM 基于工具抽取好的结构化事实，撰写「结果」与「讨论」的叙述段。

    关键约束（写进系统提示）：只能使用给定的结构化事实，不得编造数字或结论；
    事实缺失处必须显式写「摘要未提供」。宁可输出保守的段落，也不要流畅但虚假的内容。
    """
    facts = []
    for r in rows:
        p = r["_profile"]
        facts.append(
            f"- {(p['authors'] or ['佚名'])[0]} 等（{p['year'] or '年份不详'}，"
            f"{p['design']}，样本量 {p['n'] or '未抽取'}，"
            f"效应量 {r['关键效应量'] or '未报告'}）：{p['conclusion'] or '摘要未写明结论'}"
        )
    conf_txt = "\n".join(
        f"- [{c['term']}｜{c['type']}] " + " ／ ".join(
            f"{s['label']}：" + "；".join(x["cite"] for x in s["studies"])
            for s in c["sides"]
        )
        for c in conflicts
    ) or "（未自动检出明显冲突）"
    system = (
        "你是一名医学文献综述写作助手。用户会给你一篇综述主题、若干篇文献的结构化事实"
        "（研究设计、样本量、效应量、结论）以及已检出的结论不一致点。"
        "请用中文撰写两段综述正文：\n"
        "第一段「结果概述」：概括纳入研究的特征与主要发现，按研究设计分组叙述；\n"
        "第二段「讨论」：分析结论不一致的可能原因，并指出证据的局限。\n"
        "硬性要求：\n"
        "1. 只能使用用户提供的事实，**绝对不得编造样本量、效应量、P 值或结论**；\n"
        "2. 某处需要的事实缺失时，直接写「摘要未提供」，不要推测；\n"
        "3. 不做临床推荐，不使用「建议临床使用」这类表述；\n"
        "4. 直接输出这两段正文，不要额外解释你的写作过程。"
    )
    user = (
        f"综述主题：{topic or '（未指定）'}\n\n"
        f"纳入文献结构化事实（共 {len(rows)} 篇）：\n" + "\n".join(facts) +
        f"\n\n已检出的结论不一致：\n{conf_txt}"
    )
    return summarizer.llm_chat(
        system, user, api_base, api_key, model,
        cache_task="综述叙述", max_tokens=2000,
    )
