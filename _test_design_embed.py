"""研究类型识别（PubMed 文献类型接入）与叙述段嵌入骨架的离线测试。

对应两个用户反馈的修复：

1. **研究类型未识别是大问题**——旧版 ``judge_design`` 只靠标题/摘要里的措辞
   （"randomized controlled""cohort study"……），而大量 PubMed 摘要根本不写这些
   字眼。但抓取层早就带回了 NLM 标引的权威文献类型（``pubtypes``），只是从没被
   用上。现在文献类型作为最高优先级来源接入，并扩充了文本线索。
2. **导出「骨架 + 叙述段」时叙述段附在文末**——现在按章节嵌入：
   「结果概述」→ 3.5、「讨论」→ 4.4；切不开标题时整体并入 4.4，内容不丢。

全部离线，不访问任何接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_design_embed_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import review  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


print("=" * 78)
print("一、judge_design 接入 PubMed 文献类型（最高优先级）")
print("=" * 78)

_CASES = [
    (["Randomized Controlled Trial"], "随机对照试验"),
    (["Pragmatic Clinical Trial"], "随机对照试验"),
    (["Meta-Analysis"], "系统评价 / Meta 分析"),
    (["Systematic Review"], "系统评价 / Meta 分析"),
    (["Network Meta-Analysis"], "系统评价 / Meta 分析"),
    (["Practice Guideline"], "临床指南 / 专家共识"),
    (["Guideline"], "临床指南 / 专家共识"),
    (["Consensus Development Conference, NIH"], "临床指南 / 专家共识"),
    (["Cohort Studies"], "队列研究"),
    (["Case-Control Studies"], "病例对照研究"),
    (["Cross-Sectional Studies"], "横断面研究"),
    (["Case Reports"], "病例报告 / 病例系列"),
    (["Animals"], "基础 / 动物实验"),
    (["In Vitro"], "基础 / 动物实验"),
    (["Review"], "叙述性综述"),
    (["Scoping Review"], "叙述性综述"),
]
for pts, want in _CASES:
    got, ev = review.judge_design({"title": "Some study", "abstract": "", "pubtypes": pts})
    check(f"文献类型 {pts[0]} → {want}", got == want, got)

# 多类型按优先级取最高档；文献类型压过标题/摘要措辞
got, _ = review.judge_design({"title": "x", "pubtypes": ["Review", "Meta-Analysis"]})
check("多类型按优先级：Review + Meta-Analysis → 系统评价", got == "系统评价 / Meta 分析", got)
got, ev = review.judge_design({"title": "randomized trial of X",
                               "abstract": "patients were randomly assigned",
                               "pubtypes": ["Cohort Studies"]})
check("文献类型压过标题/摘要措辞（RCT 措辞 + Cohort 类型 → 队列研究）",
      got == "队列研究", got)
check("文献类型命中的依据可溯源", "PubMed 文献类型" in ev, ev)

print()
print("=" * 78)
print("二、文本线索扩充（无 pubtypes 字段时的召回率）")
print("=" * 78)

_CUES = [
    ({"title": "Trial A", "abstract": "patients were randomly divided into two groups"},
     "随机对照试验"),
    ({"title": "Trial B", "abstract": "eligible patients were randomized to receive drug or placebo"},
     "随机对照试验"),
    ({"title": "Study C", "abstract": "we conducted a retrospective study of 340 patients"},
     "队列研究"),
    ({"title": "Study D", "abstract": "a registry analysis of 1200 consecutive patients"},
     "队列研究"),
    ({"title": "Study E", "abstract": "we performed a prospective analysis of outcomes"},
     "队列研究"),
    ({"title": "A case of refractory pemphigoid", "abstract": ""},
     "病例报告 / 病例系列"),
    ({"title": "A review of recent advances in immunotherapy", "abstract": ""},
     "叙述性综述"),
]
for art, want in _CUES:
    got, ev = review.judge_design(art)
    check(f"新线索命中 → {want}", got == want, f"{got}｜{ev}")

# 零回归：没有 pubtypes、旧线索、无线索三种老行为逐字保持
got, ev = review.judge_design({"title": "Trial", "abstract": "patients were randomly assigned"})
check("旧线索不回归：randomly assigned → 随机对照试验", got == "随机对照试验", got)
got, ev = review.judge_design({"title": "Some paper", "abstract": "We measured things."})
check("无线索仍标未识别", got == "未识别", got)
got, ev = review.judge_design({"title": "Some paper", "abstract": "We measured things.",
                               "pubtypes": ["Comparative Study"]})
check("不可确证的文献类型（Comparative Study）不乱映射 → 落回文本线索 → 未识别",
      got == "未识别", got)
got, _ = review.judge_design({"title": "t", "abstract": "", "pubtypes": []})
check("pubtypes 为空列表时与旧版一致", got == "未识别", got)

print()
print("=" * 78)
print("三、split_narrative：叙述段切分")
print("=" * 78)

r, d, ok = review.split_narrative("**结果概述**\n\nR1 段落。\n\n**讨论**\n\nD1 段落。")
check("加粗标题两段可切分", ok and r == "R1 段落。" and d == "D1 段落。", f"{r!r}/{d!r}")
r, d, ok = review.split_narrative("### Results\n\nR1.\n\n### Discussion\n\nD1.")
check("英文 ### 标题可切分", ok and r == "R1." and d == "D1.", f"{r!r}/{d!r}")
r, d, ok = review.split_narrative("结果概述\nR1\n讨论\nD1")
check("裸标题可切分", ok and r == "R1" and d == "D1", f"{r!r}/{d!r}")
r, d, ok = review.split_narrative("讨论\nD1")
check("只有讨论标题：前文并入结果概述", ok and r == "" and d == "D1", f"{r!r}/{d!r}")
r, d, ok = review.split_narrative("没有标题的一整段叙述。")
check("无标题 → 整体兜底（ok=False）", (not ok) and r.startswith("没有标题"), f"{r!r}")
r, d, ok = review.split_narrative("")
check("空文本 → 不切分", r == "" and d == "" and not ok)
r, d, ok = review.split_narrative("讨论\nD1\n结果概述\nR1")
check("标题顺序反常 → 整体兜底不乱放", not ok, f"{r!r}")

print()
print("=" * 78)
print("四、embed_narrative：叙述段嵌入骨架")
print("=" * 78)

_SKELETON = (
    "# 主题\n\n"
    "## 3　结果\n\n"
    "### 3.4　偏倚风险与临床适用性概览\n\n"
    "3.4 的内容。\n\n"
    "## 4　讨论\n\n"
    "### 4.1　主要发现\n\n"
    "4.1 的内容。\n\n"
    "## 5　结论\n\n"
    "结论内容。\n"
)
merged = review.embed_narrative(_SKELETON, "**结果概述**\n\nR 段。\n\n**讨论**\n\nD 段。")
i35 = merged.find("### 3.5　结果概述")
i4 = merged.find("## 4　讨论")
i44 = merged.find("### 4.4　讨论")
i5 = merged.find("## 5　结论")
check("结果概述落位 3.5 且在讨论章之前", i35 > 0 and i35 < i4, str(i35))
check("讨论落位 4.4 且在结论章之前", i44 > i4 and i44 < i5, f"{i44}<{i5}")
check("章节顺序 3.5 < 4 < 4.4 < 5", i35 < i4 < i44 < i5)
check("嵌入后不再是文末附录（无「附：」标题）", "附：大模型撰写的叙述段" not in merged)
check("嵌入内容带核对提示", "须逐句核对事实" in merged)
check("骨架原有内容不丢", "4.1 的内容。" in merged and "3.4 的内容。" in merged)

merged2 = review.embed_narrative(_SKELETON, "切不开标题的一整段叙述。")
check("切不开标题 → 整体并入 4.4", "### 4.4　大模型撰写的叙述段" in merged2
      and "### 3.5" not in merged2)
merged3 = review.embed_narrative("", "**结果概述**\n\nR。\n\n**讨论**\n\nD。")
check("骨架还没生成 → 原样返回叙述段", merged3.startswith("**结果概述**"))
check("叙述段为空 → 骨架原样返回", review.embed_narrative(_SKELETON, "") == _SKELETON)
merged4 = review.embed_narrative("没有章节标题的骨架", "**结果概述**\n\nR。")
check("找不到章节标题 → 文末兜底不丢内容", "### 3.5　结果概述" in merged4 and "R。" in merged4)

print()
print("=" * 78)
print("五、摘要托底链路（未抓到全文的文献照常抽取）")
print("=" * 78)

_abs_only = {
    "pmid": "2001", "title": "A randomized trial of drug X",
    "abstract": "BACKGROUND: Drug X for hypertension. "
                "METHODS: A total of 320 patients were randomly assigned to drug X or placebo. "
                "RESULTS: HR 0.72 (95% CI 0.58-0.90), P=0.004. "
                "CONCLUSIONS: Drug X reduced systolic blood pressure.",
}
_prof = review.extract_profile(_abs_only)
check("无全文（未抓到）也能识别研究设计", _prof["design"] == "随机对照试验", _prof["design"])
check("无全文也能抽到样本量", _prof["n"] == 320, str(_prof["n"]))
check("无全文也能抽到效应量", _prof["effects"].get("HR") == ["0.72"], str(_prof["effects"]))
check("无全文的来源标注为「摘要」", _prof["source"] == "摘要", _prof["source"])
check("文献类型 + 摘要双来源：文献类型优先",
      review.judge_design({**_abs_only, "pubtypes": ["Randomized Controlled Trial"]})[0]
      == "随机对照试验")

print()
print("=" * 78)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 78)
if FAIL:
    for name in FAIL:
        print("  ✗ " + name)
    sys.exit(1)
print("✅ 研究类型识别 / 叙述段嵌入自测全部通过")
