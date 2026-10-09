"""P3-C4.1 自测：摘要分段与字段抽取改进（A 组）。

覆盖：
- 结构化 Label 分段（模拟 PubMed efetch 的 AbstractText@Label）
- 纯文本标签切段（标签连排、无换行，兼容历史收藏与 PDF 解析产物）
- 复合标签拆分（METHODS AND RESULTS / DESIGN, SETTING, AND PARTICIPANTS）与中文摘要
- "按段取"带来的四项改进：
  * 结论取 CONCLUSIONS 段（修掉过去取成 RESULTS 末句的 bug）
  * 主要终点放宽（primary composite endpoint）+ 去句首标签
  * 人群新增年龄限定 / 状态限定 / 中文模式
  * 样本量新增"数字前置 + 状态词"模式
- 极性裸动词线索与"效应量 < 1 且结局为不良事件"的保守兜底

全部离线构造，不访问任何外部接口。
"""
import json
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_sections_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import review  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 1. 结构化 Label 分段（模拟 A1 之后 pubmed.fetch_articles 的返回）
# --------------------------------------------------------------------------
print("\n[1] 结构化 Label 分段")

ART_LABELED = {
    "pmid": "9001",
    "title": "Metformin and cardiovascular outcomes in type 2 diabetes: a randomized trial",
    "abstract": (
        "BACKGROUND: Metformin is first-line therapy.\n"
        "METHODS: In this multicenter randomized controlled trial, 4,812 patients with "
        "type 2 diabetes and established cardiovascular disease were assigned to metformin "
        "or placebo.\n"
        "RESULTS: MACE occurred in 8.1% versus 10.4%.\n"
        "CONCLUSIONS: Metformin reduced cardiovascular events in high-risk patients."
    ),
    "abstract_sections": {
        "BACKGROUND": "Metformin is first-line therapy.",
        "METHODS": "In this multicenter randomized controlled trial, 4,812 patients with "
                   "type 2 diabetes and established cardiovascular disease were assigned to "
                   "metformin or placebo.",
        "RESULTS": "MACE occurred in 8.1% versus 10.4%.",
        "CONCLUSIONS": "Metformin reduced cardiovascular events in high-risk patients.",
    },
}
secs = review._split_sections(ART_LABELED)
check("结构化 Label 切出 4 个规范段",
      set(secs) == {"BACKGROUND", "METHODS", "RESULTS", "CONCLUSIONS"}, str(sorted(secs)))
concl, src = review.extract_conclusion(ART_LABELED)
check("结论取自 CONCLUSIONS 段（不再取 RESULTS 末句）",
      concl.startswith("Metformin reduced") and "MACE occurred" not in concl, repr(concl[:40]))
check("结论来源标注为结构化结论段", src == "结构化结论段", src)
pol, _ = review.judge_polarity(concl)
check("结论倾向判为正向（裸动词 reduced 命中）", pol == review.POLARITY_POS, pol)
n, _ = review.extract_sample_size(ART_LABELED)
check("样本量在 METHODS 段内抽到 4812", n == 4812, str(n))

# --------------------------------------------------------------------------
# 2. 纯文本标签切段（无 abstract_sections，标签连排无换行）
# --------------------------------------------------------------------------
print("\n[2] 纯文本标签切段（连排、无换行）")

ART_PLAIN = {
    "title": "Colchicine after myocardial infarction: a systematic review and meta-analysis",
    "abstract": (
        "BACKGROUND: Inflammation contributes to recurrent events. "
        "METHODS: We pooled 7 randomized trials of colchicine versus placebo. "
        "RESULTS: Colchicine reduced the composite of cardiovascular death, myocardial "
        "infarction, or stroke (RR 0.71, 95% CI 0.60-0.84). "
        "CONCLUSIONS: Colchicine reduces recurrent cardiovascular events with an acceptable "
        "safety profile."
    ),
}
secs2 = review._split_sections(ART_PLAIN)
check("连排摘要仍能切出 CONCLUSIONS 段", "CONCLUSIONS" in secs2, str(sorted(secs2)))
c2, _ = review.extract_conclusion(ART_PLAIN)
check("连排摘要的结论正确（取 CONCLUSIONS 而非 RESULTS）",
      c2.startswith("Colchicine reduces recurrent") and "We pooled" not in c2, repr(c2[:46]))
check("连排摘要的结论不带句首标签", not c2.startswith("CONCLUSIONS"), repr(c2[:20]))
pol2, _ = review.judge_polarity(c2)
check("连排摘要结论倾向为正向", pol2 == review.POLARITY_POS, pol2)

# --------------------------------------------------------------------------
# 3. 复合标签与中文摘要
# --------------------------------------------------------------------------
print("\n[3] 复合标签与中文摘要")

check("复合标签 METHODS AND RESULTS 拆为 METHODS + RESULTS",
      set(review._norm_section_label("METHODS AND RESULTS")) == {"METHODS", "RESULTS"},
      str(review._norm_section_label("METHODS AND RESULTS")))
check("复合标签 DESIGN, SETTING, AND PARTICIPANTS 拆为三键",
      set(review._norm_section_label("DESIGN, SETTING, AND PARTICIPANTS"))
      == {"METHODS", "SETTING", "PATIENTS"},
      str(review._norm_section_label("DESIGN, SETTING, AND PARTICIPANTS")))
check("JAMA 式 MAIN OUTCOMES AND MEASURES 映射到 OUTCOMES",
      "OUTCOMES" in review._norm_section_label("MAIN OUTCOMES AND MEASURES"))
check("未知标签返回空列表（不误切正文）",
      review._norm_section_label("BMI") == [] and review._norm_section_label("") == [],
      str(review._norm_section_label("BMI")))

ART_ZH = {
    "title": "二甲双胍对 2 型糖尿病患者心血管结局的影响",
    "abstract": "目的：评估二甲双胍的心血管获益。方法：纳入 4812 例 2 型糖尿病患者进行随机对照试验。"
                "结果：主要终点事件发生率显著降低。结论：二甲双胍可减少心血管事件。",
}
secs3 = review._split_sections(ART_ZH)
check("中文摘要切出结论段", "CONCLUSIONS" in secs3, str(sorted(secs3)))
check("中文结论内容正确",
      secs3.get("CONCLUSIONS", "").startswith("二甲双胍可减少"), repr(secs3.get("CONCLUSIONS", "")[:20]))
check("中文人群可被抽取（患者）", "患者" in review.extract_population(ART_ZH),
      review.extract_population(ART_ZH))

# Title Case 标签（BMJ / Lancet 风格，也常见于本地 PDF 全文解析产物）
ART_EN_TITLE = {
    "title": "Title-case labelled abstract",
    "abstract": ("Background: Drug X is widely used. Methods: We randomised 500 adults. "
                 "Results: Mortality was lower with drug X. Conclusions: Drug X reduces mortality."),
}
secs3b = review._split_sections(ART_EN_TITLE)
check("Title Case 标签（Background:）也能切段", "CONCLUSIONS" in secs3b, str(sorted(secs3b)))
check("Title Case 摘要结论正确并去掉标签",
      secs3b.get("CONCLUSIONS", "").startswith("Drug X reduces")
      and not secs3b.get("CONCLUSIONS", "").startswith("Conclusions"),
      repr(secs3b.get("CONCLUSIONS", "")[:26]))
_segs_note = review._split_sections(
    {"abstract": "Methods: we did X. Note: this is prose. Results: y improved."})
check("非标签词不被误切（Note: 不进任何段落）",
      set(_segs_note) == {"METHODS", "RESULTS"}, str(sorted(_segs_note)))

# --------------------------------------------------------------------------
# 4. 无标签摘要：分段器拒绝切分，抽取器回落（不能因为改造而丢内容）
# --------------------------------------------------------------------------
print("\n[4] 无标签摘要的回落")

ART_BARE = {
    "title": "A study of drug X in hypertension",
    "abstract": ("We enrolled 240 adults with hypertension and randomly assigned them to drug X "
                 "or placebo. Blood pressure fell more with drug X. Drug X was well tolerated "
                 "and reduced systolic blood pressure compared with placebo."),
}
check("无标签摘要不切段（返回空 dict）", review._split_sections(ART_BARE) == {},
      str(review._split_sections(ART_BARE)))
c4, src4 = review.extract_conclusion(ART_BARE)
check("无标签摘要仍能给出结论（末句兜底）", bool(c4) and "末句" in src4, f"{src4} · {c4[:40]!r}")
check("末句兜底不残留段标签", not c4.startswith("CONCLUSIONS"), repr(c4[:24]))
check("无摘要不崩且标注无摘要",
      review.extract_conclusion({"title": "x"}) == ("", "无摘要"))

# --------------------------------------------------------------------------
# 5. 主要终点：放宽正则 + 去标签 + 次级线索
# --------------------------------------------------------------------------
print("\n[5] 主要终点的抽取改进")

ART_PO1 = {"abstract": "METHODS: m. RESULTS: The primary composite endpoint occurred in "
                       "14.2% versus 16.8% (hazard ratio 0.84, 95% CI 0.72-0.98). "
                       "CONCLUSIONS: Benefit with adverse events."}
po1 = review.extract_primary_outcome(ART_PO1)
check("primary composite endpoint 被命中", "composite" in po1, repr(po1[:46]))
check("主要终点已剥掉句首 RESULTS: 标签", not po1.startswith("RESULTS"), repr(po1[:22]))

ART_PO2 = {"abstract": "BACKGROUND: b. METHODS: m. RESULTS: We pooled 7 trials. "
                       "CONCLUSIONS: Colchicine reduces the composite of cardiovascular death."}
po2 = review.extract_primary_outcome(ART_PO2)
check("无终点标注时给出次级线索并声明", po2.startswith("（摘要未标注主要终点）"), repr(po2[:34]))

ART_PO3 = {"abstract": "METHODS: m. RESULTS: the primary outcome was all-cause mortality. "
                       "CONCLUSIONS: c."}
po3 = review.extract_primary_outcome(ART_PO3)
check("primary outcome 定义句正常抽取", "all-cause mortality" in po3, repr(po3[:50]))

# --------------------------------------------------------------------------
# 6. 人群：年龄限定 / 状态限定 / 段优先
# --------------------------------------------------------------------------
print("\n[6] 人群抽取改进")

ART_POP1 = {"title": "Intensive versus moderate statin therapy in adults aged 75 years or older: "
                     "a randomized trial",
            "abstract": "METHODS: We randomly assigned patients to intensive or moderate therapy."}
check("年龄限定人群命中且不含多余前缀",
      review.extract_population(ART_POP1) == "adults aged 75 years or older",
      review.extract_population(ART_POP1))

ART_POP2 = {"abstract": "METHODS: 19,114 community-dwelling adults aged 70 years or older were "
                        "randomly assigned to aspirin or placebo."}
pop2 = review.extract_population(ART_POP2)
check("community-dwelling adults 命中", "community-dwelling adults" in pop2 or "adults aged" in pop2,
      pop2)

ART_POP3 = {"abstract": "BACKGROUND: b. PATIENTS: 240 adults with resistant hypertension. "
                        "METHODS: m. RESULTS: r. CONCLUSIONS: c."}
check("PATIENTS 段被直接采用",
      review.extract_population(ART_POP3) == "240 adults with resistant hypertension"
      or "resistant hypertension" in review.extract_population(ART_POP3),
      review.extract_population(ART_POP3))

# --------------------------------------------------------------------------
# 7. 样本量：数字前置模式
# --------------------------------------------------------------------------
print("\n[7] 样本量抽取改进")

n7, _ = review.extract_sample_size(
    {"abstract": "METHODS: 19,114 community-dwelling adults were randomly assigned."})
check("数字前置 + 状态词命中 19114", n7 == 19114, str(n7))
n7b, _ = review.extract_sample_size(
    {"abstract": "METHODS: A total of 240 patients were enrolled."})
check("A total of N 模式仍可用", n7b == 240, str(n7b))
n7c, _ = review.extract_sample_size(
    {"abstract": "METHODS: m. PATIENTS: 205 adults with type 2 diabetes. RESULTS: r."})
check("PATIENTS 段内的样本量被优先抽取", n7c == 205, str(n7c))

# --------------------------------------------------------------------------
# 8. 极性：裸动词、否定保护、方向兜底
# --------------------------------------------------------------------------
print("\n[8] 极性判定改进")

POL = review.POLARITY_POS
NUL = review.POLARITY_NULL
HRM = review.POLARITY_HARM
UNK = review.POLARITY_UNKNOWN

check("裸动词 reduces 判正向", review.judge_polarity("Colchicine reduces events.")[0] == POL)
check("裸动词 lowered 判正向", review.judge_polarity("The drug lowered blood pressure.")[0] == POL)
check("weight loss 判正向", review.judge_polarity("It produces meaningful weight loss.")[0] == POL)
check("否定保护：did not reduce → 无差异",
      review.judge_polarity("The drug did not reduce mortality.")[0] == NUL)
check("否定保护：no reduction → 无差异",
      review.judge_polarity("No reduction in mortality was observed.")[0] == NUL)
check("不利方向：more frequent → 风险",
      review.judge_polarity("Adverse events were more frequent with intensive therapy.")[0] == HRM)
check("方向兜底：HR<1 且不良结局 → 正向",
      review.judge_polarity_ex("The incidence of myocardial infarction was 5% vs 8%.",
                               {"HR": ["0.70"]})[0] == POL)
check("方向兜底不越界：HR>1 不判正向",
      review.judge_polarity_ex("The incidence of myocardial infarction was 8% vs 5%.",
                               {"HR": ["1.40"]})[0] == UNK)
check("方向兜底不越界：非不良结局不判正向",
      review.judge_polarity_ex("Quality of life scores were recorded.",
                               {"HR": ["0.70"]})[0] == UNK)
check("judge_polarity 旧签名仍可用（向后兼容）",
      isinstance(review.judge_polarity("reduces events"), tuple))

# --------------------------------------------------------------------------
# 9. 演示数据整体回归：结论倾向不应再有"未明确"
# --------------------------------------------------------------------------
print("\n[9] 演示数据整体回归")

_demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_demo_data", "favorites.json")
if os.path.exists(_demo):
    with open(_demo, encoding="utf-8") as fh:
        arts = json.load(fh)
    rows = review.build_comparison(arts)
    unknown = [r["序号"] for r in rows if "未明确" in str(r["结论倾向"])]
    check("演示数据结论倾向无\"未明确\"", not unknown, f"仍为未明确：{unknown}")
    empty_pop = sum(1 for r in rows if not str(r["人群"]).strip())
    empty_po = sum(1 for r in rows if not str(r["主要终点"]).strip())
    check("人群空值不超过 3 篇（改造前 5 篇）", empty_pop <= 3, f"空 {empty_pop} 篇")
    check("主要终点空值不超过 3 篇（改造前 6 篇）", empty_po <= 3, f"空 {empty_po} 篇")
else:
    print("  [SKIP] 未找到 _demo_data/favorites.json，跳过整体回归")

# --------------------------------------------------------------------------
print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：" + "；".join(FAIL))
    sys.exit(1)
print("✅ 摘要分段与抽取改进自测全部通过")
