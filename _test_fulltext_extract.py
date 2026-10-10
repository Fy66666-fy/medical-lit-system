"""P3-C8 自测：「尽量全文抽取」。

覆盖四件事：
1. **全文优先**：同一篇文献带上全文后，样本量 / 主要终点 / 效应量 / 结论改从全文
   相应章节抽取，且比只给摘要时抽得更全；
2. **无全文时零回归**：``source_text()`` 退回摘要，抽取结果与旧版逐字一致 ——
   这是本功能的红线，必须钉死；
3. **抽取来源如实标注**：``source_label()`` / 对比表「数据来源」列 / 三态文案
   在全文来源时改用「原文」措辞（不再说"摘要未提及"）；
4. **接入点正确**：``pdfdoc.to_article()`` 带出全文章节；``storage.add_favorite()``
   入库前剔除全文（避免收藏文件被撑大）；``llm_fill_prompt()`` 有全文时附全文章节、
   无全文时与旧版一致；``llm_fill_with_llm()`` 分批并发并回报进度。

全部离线（桩替 HTTP / LLM），不访问任何外部接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_ft_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import pdfdoc, review, storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 测试数据：同一篇研究，摘要版 vs 全文版
# 摘要里**故意不写**样本量、主要终点、效应量，只在全文中给出 —— 用来验证
# "全文在手却只抽摘要"这个问题确实被修掉了。
# --------------------------------------------------------------------------
ABSTRACT = (
    "BACKGROUND: Hypertension is common in older adults.\n"
    "METHODS: We assessed an antihypertensive drug in a controlled study.\n"
    "RESULTS: The drug lowered blood pressure compared with control.\n"
    "CONCLUSIONS: The drug may be beneficial, but larger studies are needed."
)

FULLTEXT = [
    {"title": "Introduction", "text": "Hypertension is a leading cause of stroke worldwide."},
    {"title": "Methods",
     "text": "This was a randomized, double-blind, placebo-controlled trial conducted at 12 "
             "centers. A total of 1500 patients with hypertension were enrolled and randomly "
             "assigned to drug X or placebo. The primary outcome was change in systolic blood "
             "pressure at 12 weeks. Follow-up was 48 weeks."},
    {"title": "Results",
     "text": "Systolic blood pressure decreased by 12.5 mmHg with drug X versus placebo. "
             "HR 0.72 (95% CI 0.58-0.90, P=0.004) for major cardiovascular events. "
             "Grade 3 adverse events occurred in 6% of patients."},
    {"title": "Conclusions",
     "text": "Drug X significantly reduced systolic blood pressure compared with placebo in "
             "adults with hypertension, with an acceptable safety profile at 48 weeks."},
]

ABS_ONLY = {
    "pmid": "2001",
    "title": "Antihypertensive drug X versus placebo in older adults",
    "journal": "J Hypertens",
    "year": "2024",
    "abstract": ABSTRACT,
}

FULL_ART = dict(ABS_ONLY, fulltext_sections=FULLTEXT)


print("=" * 78)
print("一、全文来源抽象（source_text / has_fulltext / source_label）")
print("=" * 78)

check("无全文：has_fulltext 为 False", review.has_fulltext(ABS_ONLY) is False)
check("有全文：has_fulltext 为 True", review.has_fulltext(FULL_ART) is True)
check("无全文：source_text 退回摘要（红线）",
      review.source_text(ABS_ONLY) == ABS_ONLY["abstract"])
check("有全文：source_text 取全文（含 Methods 首句）",
      "multi-center" not in review.source_text(FULL_ART)
      and "randomized, double-blind" in review.source_text(FULL_ART))
check("source_label：全文 / 摘要 / 无",
      review.source_label(FULL_ART) == "全文"
      and review.source_label(ABS_ONLY) == "摘要"
      and review.source_label({"pmid": "x", "title": "t"}) == "无")
check("fulltext_sections 过滤空文本",
      len(review.fulltext_sections(
          {"pmid": "x", "fulltext_sections": [{"title": "A", "text": " "},
                                              {"title": "B", "text": "ok"}]})) == 1)
check("fulltext_sections 容错（非 list / 非 dict 元素）",
      review.fulltext_sections({"pmid": "x", "fulltext_sections": "bad"}) == []
      and len(review.fulltext_sections(
          {"pmid": "x", "fulltext_sections": [None, "s", {"title": "T", "text": "v"}]})) == 1)


print()
print("=" * 78)
print("二、全文章节 → 规范段落（_norm_fulltext_label / _split_sections）")
print("=" * 78)

check("全文章节标题归一化（含编号剥离）",
      review._norm_fulltext_label("1.2 Methods") == ["METHODS"]
      and review._norm_fulltext_label("III. Results") == ["RESULTS"]
      and review._norm_fulltext_label("Discussion") == ["DISCUSSION"]
      and review._norm_fulltext_label("Statistical Analysis") == ["METHODS"])
check("_split_sections：全文优先，段名落到全文章节",
      "randomly assigned to drug X" in review._split_sections(FULL_ART).get("METHODS", "")
      and "HR 0.72" in review._split_sections(FULL_ART).get("RESULTS", ""))
check("_split_sections：无全文时退回摘要分段（与旧版一致）",
      "may be beneficial" in review._split_sections(ABS_ONLY).get("CONCLUSIONS", ""))
check("_split_sections：全文 Introduction 映射到 BACKGROUND",
      bool(review._split_sections(FULL_ART).get("BACKGROUND")))


print()
print("=" * 78)
print("三、抽取器「全文优先」：摘要抽不到、全文能抽到")
print("=" * 78)

n_abs, _ = review.extract_sample_size(ABS_ONLY)
n_ft, n_ctx = review.extract_sample_size(FULL_ART)
check("样本量：摘要版抽不到", n_abs is None, str(n_abs))
check("样本量：全文版抽到 1500", n_ft == 1500, str(n_ft))

eff_abs = review.extract_effects(ABS_ONLY)
eff_ft = review.extract_effects(FULL_ART)
check("效应量：摘要版没有 HR", not eff_abs.get("HR"), str(eff_abs))
check("效应量：全文版抽到 HR 0.72", eff_ft.get("HR") == ["0.72"], str(eff_ft.get("HR")))

po_abs = review.extract_primary_outcome(ABS_ONLY)
po_ft = review.extract_primary_outcome(FULL_ART)
check("主要终点：摘要版无明确终点", "systolic blood pressure" not in po_abs.lower(), po_abs)
check("主要终点：全文版抽到主要终点",
      "systolic blood pressure" in po_ft.lower(), po_ft[:60])

concl_abs, src_abs = review.extract_conclusion(ABS_ONLY)
concl_ft, src_ft = review.extract_conclusion(FULL_ART)
check("结论：摘要版取摘要结论", "larger studies are needed" in concl_abs, concl_abs[:50])
check("结论：全文版取全文结论章",
      "acceptable safety profile" in concl_ft, concl_ft[:60])

design_ft, ev_ft = review.judge_design(FULL_ART)
check("研究设计：全文命中并如实标注来源",
      design_ft == "随机对照试验" and "全文命中" in ev_ft, f"{design_ft}｜{ev_ft}")

check("随访：全文版抽到 48 周（≈11.0 月）",
      review.extract_followup(FULL_ART)[1] == 11.0, str(review.extract_followup(FULL_ART)))

p_abs = review.extract_profile(ABS_ONLY)
p_ft = review.extract_profile(FULL_ART)
check("画像：source 字段如实反映来源",
      p_abs["source"] == "摘要" and p_ft["source"] == "全文")
check("画像：全文版结构化完整度更高",
      review.structure_completeness(p_ft)["filled"]
      > review.structure_completeness(p_abs)["filled"],
      f"{review.structure_completeness(p_ft)['filled']} vs "
      f"{review.structure_completeness(p_abs)['filled']}")
check("画像：全文版五列状态全 ok",
      all(v == review.CELL_OK for v in p_ft["states"].values()), str(p_ft["states"]))
check("画像：has_source 在有全文时为 True",
      p_ft["has_source"] is True and p_abs["has_source"] is True)


print()
print("=" * 78)
print("四、无全文时零回归（与旧行为逐字一致）")
print("=" * 78)

# 旧行为 = 直接读 article["abstract"]。这里逐项比对，确保没被全文改造带偏。
check("样本量：无全文时等价于只读摘要",
      review.extract_sample_size(ABS_ONLY) == review.extract_sample_size(
          {"pmid": "2001", "title": ABS_ONLY["title"], "abstract": ABSTRACT}))
check("结论来源说明：无全文时仍是「结构化结论段」",
      review.extract_conclusion(ABS_ONLY)[1] == "结构化结论段")
check("无摘要且无全文 → 结论返回「无摘要」",
      review.extract_conclusion({"title": "x"}) == ("", "无摘要"))
check("无原文 → 五列一律「无摘要」",
      all(v == review.CELL_NO_ABSTRACT
          for v in review.extract_profile({"title": "x"})["states"].values()))


print()
print("=" * 78)
print("五、三态文案：全文来源改用「原文」措辞")
print("=" * 78)

check("全文来源：未提及 → 原文未提及",
      review.annotate_cell("", review.CELL_NOT_MENTIONED, source="全文")
      == review.MARK_NOT_MENTIONED_FT)
check("全文来源：未抽到 → 有全文未抽到",
      review.annotate_cell("", review.CELL_NOT_EXTRACTED, source="全文")
      == review.MARK_NOT_EXTRACTED_FT)
check("摘要来源：文案与旧版一致",
      review.annotate_cell("", review.CELL_NOT_MENTIONED) == review.MARK_NOT_MENTIONED
      and review.annotate_cell("", review.CELL_NOT_EXTRACTED) == review.MARK_NOT_EXTRACTED)
check("有值时仍原样返回（不受 source 影响）",
      review.annotate_cell("1500", review.CELL_OK, source="全文") == "1500")
check("strip_marker 能剥离新标注",
      review.strip_marker(review.MARK_NOT_EXTRACTED_FT) == ""
      and review.strip_marker(review.MARK_NOT_MENTIONED_FT) == "")
check("三态常量与标签仍是三种（未新增状态种类）",
      len(set(review.CELL_STATE_LABELS.values())) == 3)


print()
print("=" * 78)
print("六、对比表「数据来源」列")
print("=" * 78)

check("COMPARISON_COLUMNS 含「数据来源」", "数据来源" in review.COMPARISON_COLUMNS)
rows = review.build_comparison([ABS_ONLY, FULL_ART])
check("对比行带出数据来源值",
      rows[0]["数据来源"] == "摘要" and rows[1]["数据来源"] == "全文",
      f"{rows[0]['数据来源']} / {rows[1]['数据来源']}")
csv_bytes = review.comparison_csv(rows)
md = review.comparison_markdown(rows)
check("CSV 导出含该列且不带三态标记",
      "数据来源" in csv_bytes.decode("utf-8-sig")
      and review.MARK_NOT_EXTRACTED not in csv_bytes.decode("utf-8-sig"))
check("Markdown 导出含该列",
      "数据来源" in md and md.count("|") > 0)


print()
print("=" * 78)
print("七、接入点：PDF / 收藏 / LLM 补抽")
print("=" * 78)

# 7.1 pdfdoc.to_article 带出全文章节
_parsed = {
    "meta": {"title": "A PDF trial", "authors": ["Li Y"], "journal": "BMJ", "year": "2025",
             "doi": "10.1/x"},
    "sections": [
        {"title": "Abstract", "text": "A randomized trial was conducted."},
        {"title": "Methods", "text": "A total of 800 patients were enrolled."},
        {"title": "Results", "text": "The risk ratio was 0.65 (95% CI 0.50-0.85)."},
        {"title": "Conclusions", "text": "The intervention was effective."},
    ],
    "quality": {},
}
_art = pdfdoc.to_article(_parsed, "trial.pdf")
check("to_article 带出 fulltext_sections",
      len(_art.get("fulltext_sections") or []) == 4, str(len(_art.get("fulltext_sections") or [])))
check("to_article 全文可直接被抽取器消费",
      review.source_label(_art) == "全文"
      and review.extract_sample_size(_art)[0] == 800)
check("to_article 未改动既有字段（pmid 仍为空）",
      _art["pmid"] == "" and _art["is_pdf"] is True)

# 7.2 storage.add_favorite 剔除全文（收藏文件不应被全文撑大）
storage.add_favorite(dict(_art))
_favs = storage.list_favorites()
check("收藏入库前剔除 fulltext_sections",
      len(_favs) == 1 and "fulltext_sections" not in _favs[0], str(list(_favs[0].keys())[:8]))

# 7.3 llm_fill_prompt：有全文附全文章节，无全文与旧版一致
_tgt = [{"key": review.article_key(ABS_ONLY), "title": ABS_ONLY["title"], "fields": ["样本量"]}]
_tgt_ft = [{"key": review.article_key(FULL_ART), "title": FULL_ART["title"], "fields": ["样本量"]}]
prompt_abs = review.llm_fill_prompt(_tgt, [ABS_ONLY])
prompt_ft = review.llm_fill_prompt(_tgt_ft, [FULL_ART])
check("无全文：提示词不含全文章节，只给摘要原文",
      "全文章节（节选）" not in prompt_abs and "Hypertension is common" in prompt_abs)
check("有全文：提示词附上全文章节节选",
      "全文章节（节选）" in prompt_ft and "randomly assigned" in prompt_ft)
check("有全文：只挑方法 / 结果 / 结论章（不含 Introduction）",
      "Introduction" not in prompt_ft and "Methods" in prompt_ft)
check("系统提示词已改为「摘要或全文章节」",
      "摘要或全文章节" in review.LLM_FILL_SYSTEM)

# 7.4 llm_fill_with_llm：分批并发 + 进度回调（桩替 LLM）
_calls: list = []
_orig_chat = review.summarizer.llm_chat


def _fake_chat(system, user, base, key, model, cache_task="", max_tokens=None):
    _calls.append(cache_task)
    return '{"fills": []}'


review.summarizer.llm_chat = _fake_chat
try:
    # 20 篇 → 3 批（8/8/4），并发 3 路
    _many_rows, _many_arts = [], []
    for i in range(20):
        a = {"pmid": f"9{i:03d}", "title": f"Study {i}", "abstract": "patients were studied"}
        p = review.extract_profile(a)
        _many_arts.append(a)
        _many_rows.append({"标题": a["title"], "序号": i, "_profile": p, "_states": p["states"]})
    _seen: list = []
    review.llm_fill_with_llm("http://x/v1", "k", "m", _many_rows, _many_arts,
                             on_progress=lambda d, t: _seen.append((d, t)))
    check("补抽分批并发：20 篇 → 3 批各自发了请求", len(_calls) == 3, str(len(_calls)))
    check("进度回调收到 (1,3)(2,3)(3,3)",
          sorted(_seen) == [(1, 3), (2, 3), (3, 3)], str(_seen))
finally:
    review.summarizer.llm_chat = _orig_chat


print()
print("=" * 78)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  - " + f)
    sys.exit(1)
print("✅ 全文抽取（P3-C8）自测全部通过")
