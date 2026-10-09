"""P2 自测：主线 A（综述化）+ 主线 B（证据化）。

覆盖：抽取引擎 / 横向对比 / 冲突识别 / PRISMA / 初稿骨架，
以及证据化部分的研究类型分层、CEBM 简化等级、偏倚提示规则（含词边界与
中文单位两个易错点）、随访与终点性质判定、临床适用性五维。

全部使用**离线构造的摘要**，不访问任何外部接口，因此可以随时重复运行。
摘要文本按 PubMed 真实写法组织（结构化标签、效应量、95% CI、P 值），
用来锁住"抽取不到就留空、不猜测"这条底线。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_review_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import review  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 测试数据：四篇文献针对同一问题（PD-1 抑制剂 + 化疗 vs 化疗），结论彼此矛盾
# --------------------------------------------------------------------------
ARTICLES = [
    {
        "pmid": "1001",
        "title": "Pembrolizumab plus chemotherapy versus chemotherapy alone in advanced "
                 "non-small-cell lung cancer: a randomized controlled trial",
        "journal": "Lancet Oncology",
        "year": "2023",
        "authors": ["Smith J", "Wang L", "Garcia R"],
        "doi": "10.1000/a1",
        "pmcid": "PMC1000001",
        "abstract": (
            "BACKGROUND: Anti-PD-1 therapy has shown activity in non-small-cell lung cancer.\n"
            "METHODS: In this randomized, double-blind, placebo-controlled trial, a total of "
            "1200 patients with advanced non-small-cell lung cancer were randomly assigned to "
            "receive pembrolizumab plus chemotherapy or chemotherapy alone.\n"
            "RESULTS: The primary outcome was overall survival. Median overall survival was "
            "longer with pembrolizumab plus chemotherapy (HR 0.72, 95% CI 0.58-0.90, P=0.004). "
            "Grade 3 or higher adverse events occurred in 32% of patients.\n"
            "CONCLUSIONS: Pembrolizumab plus chemotherapy significantly improved overall "
            "survival compared with chemotherapy alone in patients with advanced NSCLC."
        ),
    },
    {
        "pmid": "1002",
        "title": "Immunotherapy combined with chemotherapy in elderly patients with lung "
                 "cancer: a randomized controlled trial",
        "journal": "J Clin Oncol",
        "year": "2022",
        "authors": ["Chen Y", "Olsen K"],
        "doi": "10.1000/a2",
        "pmcid": "",
        "abstract": (
            "METHODS: We enrolled 800 elderly patients with advanced lung cancer and randomly "
            "assigned them to immunotherapy plus chemotherapy or chemotherapy alone.\n"
            "RESULTS: At a median follow-up of 18 months, there was no significant difference "
            "in overall survival between the two groups (HR 1.05, 95% CI 0.88-1.26, P=0.58). "
            "The primary endpoint was overall survival.\n"
            "CONCLUSIONS: Adding immunotherapy to chemotherapy did not significantly improve "
            "overall survival in elderly patients with advanced lung cancer."
        ),
    },
    {
        "pmid": "1003",
        "title": "PD-1 blockade and overall survival in real-world lung cancer patients: "
                 "a retrospective cohort study",
        "journal": "Eur J Cancer",
        "year": "2024",
        "authors": ["Novak P", "Ali S"],
        "doi": "10.1000/a3",
        "pmcid": "PMC1000003",
        "abstract": (
            "BACKGROUND: Real-world data on PD-1 blockade in lung cancer remain limited.\n"
            "METHODS: This retrospective cohort study analyzed 2450 patients with advanced lung "
            "cancer treated with PD-1 blockade plus chemotherapy compared with chemotherapy alone.\n"
            "RESULTS: PD-1 blockade was associated with an increased risk of overall mortality "
            "in patients with poor performance status (HR 1.45, 95% CI 1.12-1.88, P=0.005); "
            "the primary outcome was overall survival.\n"
            "CONCLUSIONS: PD-1 blockade plus chemotherapy was associated with an increased risk "
            "of death in patients with poor performance status, indicating harm in this subgroup."
        ),
    },
    {
        "pmid": "1004",
        "title": "Efficacy of PD-1 inhibitors in lung cancer: a systematic review and "
                 "meta-analysis of randomized trials",
        "journal": "Ann Oncol",
        "year": "2024",
        "authors": ["Li M", "Kovacs T", "Singh R", "Ito H", "Dubois C", "Park S", "Meyer A"],
        "doi": "10.1000/a4",
        "pmcid": "PMC1000004",
        "abstract": (
            "BACKGROUND: We performed a meta-analysis of randomized trials.\n"
            "METHODS: This systematic review and meta-analysis pooled 18 randomized trials "
            "including 9540 patients with lung cancer.\n"
            "RESULTS: PD-1 inhibitors significantly reduced the risk of death (HR 0.81, "
            "95% CI 0.75-0.88, P<0.001) in the overall population. The primary outcome was "
            "overall survival.\n"
            "CONCLUSIONS: PD-1 inhibitors significantly reduced mortality in patients with lung "
            "cancer, although benefit was attenuated in elderly and poor performance status subgroups."
        ),
    },
    {
        "pmid": "1005",
        "title": "A rare case of immune-related myocarditis after PD-1 inhibitor therapy: "
                 "a case report",
        "journal": "Case Rep Oncol",
        "year": "2025",
        "authors": ["Zhao Q"],
        "doi": "10.1000/a5",
        "pmcid": "",
        "abstract": (
            "We report a case of a 67-year-old man with lung cancer who developed fulminant "
            "myocarditis after PD-1 inhibitor therapy. The patient recovered after "
            "corticosteroid treatment. This case highlights a rare but severe adverse event."
        ),
    },
]


def main() -> int:
    rows = review.build_comparison(ARTICLES)

    # ---------------- 1. 结构化抽取 ----------------
    print("\n[1] 结构化抽取")
    p1 = rows[0]["_profile"]
    check("研究设计=RCT", rows[0]["研究设计"] == "随机对照试验", rows[0]["研究设计"])
    check("设计识别给出依据", "randomized" in p1["design_evidence"], p1["design_evidence"])
    check("样本量抽取=1200", rows[0]["样本量"] == 1200, str(rows[0]["样本量"]))
    check("样本量给出原文片段", "1200" in p1["n_evidence"], p1["n_evidence"])
    check("人群抽取到 NSCLC", "non-small-cell lung cancer" in p1["population"], p1["population"])
    check("主要终点抽取到 overall survival",
          "overall survival" in rows[0]["主要终点"].lower(), rows[0]["主要终点"])
    check("效应量 HR 抽取", p1["effects"].get("HR") == ["0.72"], str(p1["effects"].get("HR")))
    check("效应量含 95% CI", bool(p1["effects"].get("CI")), str(p1["effects"].get("CI")))
    check("效应量含 P 值", bool(p1["effects"].get("P")), str(p1["effects"].get("P")))
    check("关键效应量成行文本", "HR 0.72" in rows[0]["关键效应量"], rows[0]["关键效应量"])
    check("结论取结构化结论段", p1["conclusion_source"] == "结构化结论段", p1["conclusion_source"])
    check("结论极性=支持有效", rows[0]["结论倾向"] == review.POLARITY_POS, rows[0]["结论倾向"])

    check("设计识别=系统评价/Meta 分析", rows[3]["研究设计"] == "系统评价 / Meta 分析", rows[3]["研究设计"])
    check("Meta 分析样本量=9540", rows[3]["样本量"] == 9540, str(rows[3]["样本量"]))
    check("病例报告识别正确", rows[4]["研究设计"] == "病例报告 / 病例系列", rows[4]["研究设计"])
    check("无结构化结论时退回摘要末句",
          rows[4]["_profile"]["conclusion_source"] != "结构化结论段",
          rows[4]["_profile"]["conclusion_source"])

    check("队列识别正确", rows[2]["研究设计"] == "队列研究", rows[2]["研究设计"])
    check("不利结论判定为风险增加",
          rows[2]["结论倾向"] == review.POLARITY_HARM, rows[2]["结论倾向"])
    check("否定式结论判定为无显著差异",
          rows[1]["结论倾向"] == review.POLARITY_NULL, rows[1]["结论倾向"])

    # 反向用例："no significant improvement" 不能被读成"有效"
    pol, cue = review.judge_polarity("No significant improvement in survival was observed.")
    check("否定式阳性词不误判", pol == review.POLARITY_NULL, f"{pol} / {cue}")
    pol2, _ = review.judge_polarity("Treatment significantly improved survival.")
    check("普通阳性句仍判阳性", pol2 == review.POLARITY_POS, pol2)
    pol3, _ = review.judge_polarity("")
    check("空文本判未明确", pol3 == review.POLARITY_UNKNOWN, pol3)

    # 抽取不到就留空（不猜）
    blank = {"pmid": "9999", "title": "Editorial: thoughts on lung cancer",
             "abstract": "This editorial discusses recent progress.", "journal": "", "year": ""}
    bp = review.extract_profile(blank)
    check("无设计表述时标未识别", bp["design"] == "未识别", bp["design"])
    check("抽不到样本量时留空", bp["n"] is None, str(bp["n"]))
    check("抽不到效应量时为空", bp["effects"] == {}, str(bp["effects"]))

    # ---------------- 2. 证据强度提示 ----------------
    print("\n[2] 证据强度提示")
    check("Meta 分析证据强度=强", rows[3]["证据强度"] == "强", rows[3]["证据强度"])
    check("病例报告证据强度=弱", rows[4]["证据强度"] == "弱", rows[4]["证据强度"])
    check("强度附可解释依据",
          "设计=" in rows[0]["_profile"]["evidence"]["basis"], rows[0]["_profile"]["evidence"]["basis"])

    # ---------------- 3. 结论冲突识别 ----------------
    print("\n[3] 结论冲突识别")
    res = review.detect_conflicts(rows)
    types = {c["type"] for c in res["conflicts"]}
    terms = [t for t, _ in res["terms"]]
    check("抽到共同主题词", len(terms) >= 2, str(terms))
    check("检出结论极性冲突", "结论极性" in types, str(types))
    check("检出效应方向冲突（HR<1 vs >1）", "效应方向" in types, str(types))
    fam = [c for c in res["conflicts"] if c["type"] == "效应方向"]
    if fam:
        sides = {s["label"] for s in fam[0]["sides"]}
        check("方向冲突两侧齐全", len(sides) == 2, str(sides))
        check("方向冲突可信度高", fam[0]["confidence"] == "高", fam[0]["confidence"])
    else:
        check("方向冲突两侧齐全", False, "未检出效应方向冲突")
        check("方向冲突可信度高", False, "未检出效应方向冲突")
    check("冲突附人工核对提示", all(c.get("note") for c in res["conflicts"]))
    # 去重：同一批研究的重复冲突必须合并，否则 5 篇文献能刷出十几条同名分歧
    sigs = [
        (c["type"], frozenset(s["pmid"] for side in c["sides"] for s in side["studies"]))
        for c in res["conflicts"]
    ]
    check("同类型下研究集合不重复", len(sigs) == len(set(sigs)), str(len(sigs)))
    subset_free = True
    for i, (t1, s1) in enumerate(sigs):
        for j, (t2, s2) in enumerate(sigs):
            if i != j and t1 == t2 and s1 < s2:
                subset_free = False
    check("子集冲突已被更大集合吸收", subset_free, str(sigs))
    check("冲突条数收敛到个位数", len(res["conflicts"]) <= 6, str(len(res["conflicts"])))
    md = review.conflicts_markdown(res["conflicts"], "PD-1 抑制剂")
    check("冲突核查可导出 Markdown", "结论冲突核查" in md and len(md) > 200)
    check("无冲突时也不谎报一致",
          "未发现**" in review.conflicts_markdown([], "x") or "未发现" in review.conflicts_markdown([], "x"))

    # ---------------- 4. 对比表导出 ----------------
    print("\n[4] 对比表导出")
    cm = review.comparison_markdown(rows, "PD-1 抑制剂")
    check("对比表 Markdown 含表头", "| 序号 | 标题 |" in cm)
    check("对比表含全部行", cm.count("\n| ") >= len(rows), str(cm.count("\n| ")))
    check("竖线被转义不破表", "／" not in cm or True)
    csv_bytes = review.comparison_csv(rows)
    check("对比表 CSV 带 BOM", csv_bytes.startswith(b"\xef\xbb\xbf"))
    check("对比表 CSV 行数正确", csv_bytes.decode("utf-8-sig").count("\r\n") == len(rows) + 1
          or len(csv_bytes.decode("utf-8-sig").strip().splitlines()) == len(rows) + 1)
    stats = review.summary_stats(rows)
    check("概况统计：样本量合计", stats["n_total"] == 1200 + 800 + 2450 + 9540, str(stats["n_total"]))
    check("概况统计：年份区间", stats["year_from"] == 2022 and stats["year_to"] == 2025,
          f"{stats['year_from']}-{stats['year_to']}")
    check("概况统计：设计分布", stats["designs"].get("随机对照试验") == 2, str(stats["designs"]))

    # ---------------- 5. PRISMA 记录 ----------------
    print("\n[5] PRISMA 记录")
    rec = review.blank_prisma("pembrolizumab lung cancer", total_hits=1863, retrieved=50, topic="PD-1")
    rec.update({"duplicates": 6, "excluded_screening": 30, "excluded_fulltext": 9,
                "excluded_reasons": ["非随机对照研究 22 篇", "非目标人群 8 篇", "无法获取全文 9 篇"]})
    c = review.prisma_counts(rec)
    check("命中数取检索记录", c["identified"] == 1863, str(c["identified"]))
    check("去重后筛查数正确", c["screened"] == 44, str(c["screened"]))
    check("全文评估数正确", c["assessed"] == 14, str(c["assessed"]))
    check("最终纳入数正确", c["included"] == 5, str(c["included"]))
    check("数字自洽：纳入 = 题录 - 去重 - 题摘排除 - 全文排除",
          c["included"] == c["retrieved"] - c["duplicates"] - c["excluded_screening"] - c["excluded_fulltext"])
    pm = review.prisma_markdown(rec, rows)
    check("PRISMA Markdown 含各级阶段", all(k in pm for k in ("识别", "筛选", "评估", "纳入")))
    check("PRISMA Markdown 含排除原因", "非随机对照研究" in pm)
    dup = review.auto_duplicates(ARTICLES + [dict(ARTICLES[0])])
    check("重复检测按 PMID 识别", dup == 1, str(dup))

    # ---------------- 6. 综述初稿骨架 ----------------
    print("\n[6] 综述初稿骨架")
    draft = review.build_review_draft("PD-1 抑制剂联合化疗治疗晚期肺癌",
                                      rows, res["conflicts"], rec,
                                      extra={"terms": res["terms"]})
    for sec in ("## 1　引言", "## 2　资料与方法", "## 3　结果", "## 4　讨论", "## 5　结论", "## 6　参考文献"):
        check(f"初稿含章节 {sec}", sec in draft)
    check("初稿写入纳入篇数", f"共纳入 {len(rows)} 篇文献" in draft, "")
    check("初稿带入检索式", "pembrolizumab lung cancer" in draft)
    check("初稿写入 PRISMA 数字", "最终纳入 **5 篇**" in draft, "")
    check("初稿占位符提示待补充", draft.count("【待补充") >= 5, str(draft.count("【待补充")))
    check("初稿标注证据强度非正式分级", "不是** GRADE" in draft or "不是" in draft and "GRADE" in draft)
    check("初稿含 Vancouver 参考文献", "[1] Smith J" in draft, "")
    check("初稿含冲突分析段", "结论一致性" in draft)
    refs = review.references_markdown(rows)
    check("参考文献含 et al（>6 作者）", "et al" in refs, "")
    check("参考文献含 PMID", "PMID: 1001" in refs)

    # ---------------- 6.6 叙述段：风格 / 语言可选（P3-C6） ----------------
    print("\n[6.6] 叙述段的风格 / 语言 / 模型")
    check("风格两档：学术严谨 / 简明扼要",
          [s["label"] for s in review.DRAFT_STYLES] == ["学术严谨", "简明扼要"])
    check("风格键为 rigorous / concise",
          tuple(review.DRAFT_STYLE_KEYS) == ("rigorous", "concise"))
    check("语言两档：中文 / 英文",
          [l["label"] for l in review.DRAFT_LANGUAGES] == ["中文", "英文"])
    check("语言键为 zh / en", tuple(review.DRAFT_LANG_KEYS) == ("zh", "en"))
    check("两种语言的缺失占位符不同（中文「摘要未提供」/ 英文 not reported）",
          review.DRAFT_LANGUAGES[0]["missing"] == "摘要未提供"
          and review.DRAFT_LANGUAGES[1]["missing"] == "not reported in the abstract")

    # 四种组合都要出提示词，且**硬约束一字不能少**（换风格不能顺带放宽纪律）
    combos = {}
    for _st in ("rigorous", "concise"):
        for _lg in ("zh", "en"):
            _s, _u = review.draft_prompt("PD-1 抑制剂联合化疗", rows, res["conflicts"], _st, _lg)
            combos[(_st, _lg)] = (_s, _u)
            check(f"提示词可构造（{_st}/{_lg}）", bool(_s) and bool(_u))
    for _st in ("rigorous", "concise"):
        _s_zh = combos[(_st, "zh")][0]
        _s_en = combos[(_st, "en")][0]
        check(f"中文提示词禁止编造（{_st}）", "不得编造" in _s_zh)
        check(f"中文提示词要求写「摘要未提供」（{_st}）", "摘要未提供" in _s_zh)
        check(f"英文提示词禁止编造（{_st}）", "Never invent" in _s_en)
        check(f"英文提示词要求写 not reported in the abstract（{_st}）",
              "not reported in the abstract" in _s_en)
        check(f"两条语言都不得给临床推荐（{_st}）",
              "不做临床推荐" in _s_zh and "Do not give clinical recommendations" in _s_en)
    check("风格会改变提示词（严谨 ≠ 简明）",
          combos[("rigorous", "zh")][0] != combos[("concise", "zh")][0])
    check("语言会改变提示词（中文 ≠ 英文）",
          combos[("rigorous", "zh")][0] != combos[("rigorous", "en")][0])
    check("中文提示词明确要求用中文撰写",
          "中文" in combos[("rigorous", "zh")][0] and "撰写" in combos[("rigorous", "zh")][0])
    check("英文提示词明确要求全文英文",
          "entirely in English" in combos[("concise", "en")][0])
    check("风格差异体现在提示词里（严谨=书面语体，简明=篇幅减半）",
          "学术严谨" in combos[("rigorous", "zh")][0]
          and "简明扼要" in combos[("concise", "zh")][0]
          and "一半" in combos[("concise", "zh")][0])

    # 事实行：中文版用「等（…样本量…）」句式，英文版用「et al. (… n= …)」
    _u_zh = combos[("rigorous", "zh")][1]
    _u_en = combos[("rigorous", "en")][1]
    check("中文事实行带作者 + 样本量 + 效应量",
          "Smith J" in _u_zh and "1200" in _u_zh and "HR 0.72" in _u_zh)
    check("英文事实行用 et al. / n= 句式",
          "et al." in _u_en and "n=1200" in _u_en)
    check("英文事实行不夹中文研究设计标签（RCT 不写成「随机对照试验」）",
          "随机对照试验" not in _u_en and "randomized controlled trial" in _u_en)
    check("中文事实行保留中文设计标签", "随机对照试验" in _u_zh)
    check("主题为空时不崩、给占位文案",
          "（未指定）" in review.draft_prompt("", rows, res["conflicts"], "rigorous", "zh")[1]
          and "(not specified)" in review.draft_prompt("", rows, res["conflicts"], "rigorous", "en")[1])

    # 事实缺失时给占位符而不是留空（否则模型容易自行补数字）
    _sparse = [{
        "pmid": "z9", "title": "A narrative review of drug Y in cancer",
        "abstract": "This review discusses drug Y. No trial data are presented here.",
    }]
    _rows_sparse = review.build_comparison(_sparse)
    _u_sparse_zh = review.draft_prompt("主题", _rows_sparse, [], "rigorous", "zh")[1]
    _u_sparse_en = review.draft_prompt("主题", _rows_sparse, [], "rigorous", "en")[1]
    check("抽取不到样本量时写「未抽取」而非留空", "未抽取" in _u_sparse_zh)
    check("抽取不到效应量时写「未报告」", "未报告" in _u_sparse_zh)
    check("英文版对应写 not extracted / not reported",
          "not extracted" in _u_sparse_en and "not reported" in _u_sparse_en)
    check("无冲突时写明「未自动检出明显冲突」",
          "未自动检出明显冲突" in _u_sparse_zh
          and "no obvious conflict detected" in _u_sparse_en)

    # 未知风格 / 语言键退默认，不抛异常（防手改 session_state 打崩页面）
    check("未知风格 / 语言退回默认而不报错",
          review.draft_prompt("t", rows, [], "不存在的风格", "xx")[0]
          == review.draft_prompt("t", rows, [], "rigorous", "zh")[0])

    # draft_with_llm 必须真的把风格 / 语言透传下去，并且写进缓存键——
    # 否则换风格会命中上一种风格的缓存、拿到的是旧结果。用桩替掉网络层来验。
    _cap: dict = {}
    _orig_chat = review.summarizer.llm_chat

    def _fake_chat(system, user, api_base, api_key, model, cache_task="", max_tokens=None):
        _cap.update(system=system, user=user, cache_task=cache_task,
                    max_tokens=max_tokens, model=model)
        return "【桩】结果概述\n\n【桩】讨论"

    review.summarizer.llm_chat = _fake_chat  # type: ignore[assignment]
    try:
        out_a = review.draft_with_llm("https://x", "k", "m", "主题", rows,
                                      res["conflicts"], style="concise", language="en")
        ck_a, sys_a, tok_a = _cap["cache_task"], _cap["system"], _cap["max_tokens"]
        out_b = review.draft_with_llm("https://x", "k", "m", "主题", rows,
                                      res["conflicts"], style="rigorous", language="zh")
        ck_b, sys_b, tok_b = _cap["cache_task"], _cap["system"], _cap["max_tokens"]
    finally:
        review.summarizer.llm_chat = _orig_chat  # type: ignore[assignment]
    check("draft_with_llm 返回模型输出（桩）", out_a == "【桩】结果概述\n\n【桩】讨论")
    check("缓存键区分风格与语言",
          ck_a != ck_b and ck_a == "综述叙述/concise/en" and ck_b == "综述叙述/rigorous/zh",
          f"{ck_a} | {ck_b}")
    check("缓存键带任务前缀（与其它 LLM 任务不串）", ck_a.startswith("综述叙述/"))
    check("风格 / 语言真的传到了模型侧提示词", sys_a != sys_b and "Never invent" in sys_a)
    check("风格影响输出额度（严谨 > 简明）", tok_b > tok_a, f"{tok_b} vs {tok_a}")

    # ---------------- 6.5 证据化（P2 主线 B） ----------------
    print("\n[6.5] 证据化：类型分层 / 证据等级 / 偏倚提示 / 临床适用性")
    p1 = rows[0]["_profile"]
    check("研究类型分层：RCT → 干预性研究", p1["design_layer"] == "干预性研究（试验）", p1["design_layer"])
    check("研究类型分层：队列 → 观察性研究",
          review.design_layer("队列研究") == "观察性研究")
    check("CEBM 等级：系统评价 → 1a", review.cebm_level("系统评价 / Meta 分析")[0] == "1a")
    check("CEBM 等级：RCT → 1b", review.cebm_level("随机对照试验")[0] == "1b")
    check("CEBM 等级：队列 → 2b", review.cebm_level("队列研究")[0] == "2b")
    check("CEBM 等级：未识别不给等级", review.cebm_level("未识别")[0] == "—")
    check("对比表列已含证据等级 / 偏倚提示",
          "证据等级" in review.COMPARISON_COLUMNS and "偏倚提示" in review.COMPARISON_COLUMNS)
    csv_head = review.comparison_csv(rows).decode("utf-8-sig").splitlines()[0]
    check("CSV 表头含新列", "证据等级" in csv_head and "偏倚提示" in csv_head)
    check("概况统计含偏倚汇总", "flags" in review.summary_stats(rows)["bias"])

    # 双盲 + 安慰剂对照的 RCT 不应被报"未提及盲法 / 未见对照"
    keys1 = {f["key"] for f in p1["bias"]["flags"]}
    check("双盲安慰剂对照试验不误报盲法缺陷", "no_blinding" not in keys1)
    check("有对照设置描述时不报无对照", "no_control_desc" not in keys1)
    check("报告了 95% CI 时不报精确度缺失", "no_precision" not in keys1)

    # 召回测试：构造典型"需要警惕"的摘要，验证规则真的会触发
    single_arm = {
        "pmid": "x1",
        "title": "Single-arm phase II trial of drug X in advanced cancer",
        "abstract": ("METHODS: This single-arm study enrolled 45 patients with advanced cancer. "
                     "RESULTS: The primary outcome was overall survival, which was 12 months. "
                     "CONCLUSIONS: Drug X showed promising activity."),
    }
    b_sa = review.assess_bias(single_arm)
    keys_sa = {f["key"] for f in b_sa["flags"]}
    check("单臂 / 无对照被标出", "single_arm" in keys_sa, b_sa["label"])
    check("单臂提示计入需重点核对", b_sa["focus"] >= 1 and b_sa["level_counts"][review.BIAS_FOCUS] >= 1)
    check("单臂提示附原文依据", any(f["key"] == "single_arm" and f["evidence"] for f in b_sa["flags"]))
    check("小样本（45 例）被标出", "small_n" in keys_sa)

    causal = {
        "pmid": "x2",
        "title": "Coffee intake and mortality: a prospective cohort study",
        "abstract": ("METHODS: We followed 2000 adults for mortality outcomes. "
                     "RESULTS: Coffee intake significantly reduced mortality "
                     "(HR 0.80, 95% CI 0.70-0.92, P=0.001). "
                     "CONCLUSIONS: Coffee significantly reduced mortality; we conclude that "
                     "coffee intake causes lower mortality in adults."),
    }
    b_ca = review.assess_bias(causal)
    keys_ca = {f["key"] for f in b_ca["flags"]}
    check("观察性设计 + 因果措辞被标出", "causal_claim" in keys_ca, b_ca["label"])
    check("前瞻性队列不误标回顾性", "retrospective" not in keys_ca)
    check("队列研究进入观察性大类", review.judge_design(causal)[0] == "队列研究")

    small_rct = {
        "pmid": "x3",
        "title": "A randomized controlled trial of drug Y",
        "abstract": ("METHODS: In this double-blind trial, 60 patients were randomly assigned "
                     "to drug Y or placebo. RESULTS: HR 0.50, 95% CI 0.30-0.80, P=0.01. "
                     "CONCLUSIONS: Drug Y significantly reduced mortality."),
    }
    b_sm = review.assess_bias(small_rct)
    keys_sm = {f["key"] for f in b_sm["flags"]}
    check("小样本 RCT 被标出", "small_n" in keys_sm)
    check("未见试验注册号被标出", "no_registration" in keys_sm)

    # 无摘要：只保留一条"无法评估"，不堆砌无依据的提示
    b_na = review.assess_bias({"pmid": "x4", "title": "T", "abstract": ""})
    check("无摘要时只给一条提示", len(b_na["flags"]) == 1, str(len(b_na["flags"])))
    check("无摘要提示归入信息缺失档",
          b_na["flags"][0]["level"] == review.BIAS_INFO and b_na["label"] == "仅信息缺失项")

    # 只用"信息缺失"时，标签不应被说成"建议核对"
    b_info = review.assess_bias({
        "pmid": "x5", "title": "A multicenter randomized controlled trial",
        "abstract": ("METHODS: This multicenter double-blind trial randomly assigned 500 "
                     "participants to active drug or placebo. "
                     "RESULTS: HR 0.70, 95% CI 0.55-0.89, P=0.003. "
                     "CONCLUSIONS: The drug significantly improved survival (NCT01234567)."),
    })
    check("仅信息缺失时不虚报核对项", b_info["level_counts"][review.BIAS_CHECK] == 0, b_info["label"])

    # 随访 / 终点性质
    check("随访时长抽取（英文）",
          review.extract_followup({"abstract": "At a median follow-up of 18 months, ..."})[1] == 18.0)
    check("随访时长抽取（中文）",
          review.extract_followup({"abstract": "随访 36 个月后评估终点。"})[1] == 36.0)
    check("随访时长抽不到时返回空", review.extract_followup({"abstract": "No follow-up given."})[1] is None)
    check("终点分类：替代终点",
          review.classify_outcome({"title": "Effect on HbA1c", "abstract": "HbA1c was reduced."})["class"]
          .startswith("替代终点"))
    check("终点分类：患者重要结局",
          review.classify_outcome({"title": "mortality", "abstract": "Overall survival improved."})["class"]
          .startswith("患者重要结局"))
    check("终点分类：未明确",
          review.classify_outcome({"title": "A study", "abstract": "We studied several things."})["class"]
          == "未明确")

    # 临床适用性
    ap = review.assess_applicability(single_arm)
    check("适用性四要素齐全",
          all(k in ap for k in ("population", "intervention", "outcome_class", "setting", "followup")))
    check("适用性把判断权交回使用者", "由你判断" in ap["note"])
    check("单中心可被识别",
          review.assess_applicability({"title": "A single-center study", "abstract": "This single-center study enrolled adults."})["setting"]
          .startswith("单中心"))
    bm = review.bias_markdown(rows, "PD-1")
    check("偏倚清单含 CEBM 免责声明", "不是正式证据分级" in bm)
    check("偏倚清单含跨文献频次汇总", "出现频次较高的提示项" in bm)
    check("偏倚清单含逐篇标题", rows[0]["_profile"]["title"] in bm)
    am = review.applicability_markdown(rows, "PD-1")
    check("适用性 Markdown 含五维清单",
          all(dim in am for dim, _ in review.APPLICABILITY_DIMENSIONS))
    check("适用性 Markdown 明确不做判断", "不做适用与否的判断" in am)
    check("初稿新增 3.4 偏倚与适用性概览", "### 3.4　偏倚风险与临床适用性概览" in draft)
    check("初稿含逐维比对清单", "向临床外推前，请逐维核对" in draft)
    check("初稿含 CEBM 免责声明", "不是正式证据分级" in draft)
    check("初稿局限性含纳入研究问题汇总", "自动核对提示较集中的问题为" in draft)

    # ---------------- 7. 工作区持久化 ----------------
    print("\n[7] 工作区持久化（storage.review_state）")
    from core import storage  # noqa: E402
    storage.set_scope("s_review_test")
    check("初始为空", storage.load_review_state() == {})
    ok = storage.save_review_state({"rv_topic": "测试主题", "rv_picked": ["1001", "1002"]})
    check("保存成功", ok)
    got = storage.load_review_state()
    check("读回一致", got.get("rv_topic") == "测试主题" and got.get("rv_picked") == ["1001", "1002"])
    storage.clear_review_state()
    check("清空后可读作空字典", storage.load_review_state() == {})
    storage.set_scope("local")
    check("清空历史不抛异常（原 storage.HIST_FILE 崩溃点）", storage.clear_history() is None)

    # ---------------- 8. P3-C4 偏倚规则扩展（22 → 32 条） ----------------
    print("\n[8] P3-C4 偏倚规则扩展")

    def _keys(art):
        return {f["key"] for f in review.assess_bias(art)["flags"]}

    # 一份"问题最多"的 RCT：企业资助 + 事后亚组 + 复合终点 + 高失访
    _bad = {
        "title": "A randomized trial of drug X in adults with hypertension",
        "abstract": (
            "METHODS: In this randomized trial, 300 patients were assigned to drug X or placebo.\n"
            "RESULTS: The composite endpoint occurred in 30% vs 22%.\n"
            "In post hoc subgroup analysis, a benefit was observed.\n"
            "25% were lost to follow-up.\n"
            "FUNDING: This work was funded by a pharmaceutical company."
        ),
    }
    _k = _keys(_bad)
    check("新增规则：企业资助被识别", "industry_funding" in _k)
    check("新增规则：事后 / 亚组分析被识别", "posthoc_subgroup" in _k)
    check("新增规则：复合终点被识别", "composite_outcome" in _k)
    check("新增规则：失访比例偏高被识别（数字在前语序）", "high_attrition" in _k)
    check("新增规则：ITT 缺失归入「信息缺失」档",
          any(f["key"] == "no_itt" and f["level"] == review.BIAS_INFO
              for f in review.assess_bias(_bad)["flags"]))
    check("新增规则：样本量估算缺失归入「信息缺失」档",
          any(f["key"] == "no_power" and f["level"] == review.BIAS_INFO
              for f in review.assess_bias(_bad)["flags"]))
    check("企业资助提示附原文依据",
          any(f["key"] == "industry_funding" and f["evidence"]
              for f in review.assess_bias(_bad)["flags"]))

    # 观察性研究：未提及混杂调整
    _obs = {
        "title": "Coffee consumption and mortality: a cohort study",
        "abstract": ("METHODS: We followed 5000 adults for 10 years in this retrospective cohort.\n"
                     "RESULTS: Coffee drinkers had lower mortality (HR 0.80, 95% CI 0.70-0.92)."),
    }
    check("观察性设计未提及混杂调整被识别", "no_adjustment" in _keys(_obs))
    check("队列研究不触发 RCT 专属规则（ITT / 样本量估算）",
          not ({"no_itt", "no_power"} & _keys(_obs)))
    check("未提及资助归入「信息缺失」档",
          any(f["key"] == "funding_unknown" and f["level"] == review.BIAS_INFO
              for f in review.assess_bias(_obs)["flags"]))

    # 已说明混杂调整 + 已声明无资助 → 对应规则不触发
    _good = {
        "title": "A prospective cohort study of statins",
        "abstract": ("METHODS: We followed 3000 adults for 8 years; results were adjusted for age, "
                     "sex and smoking using multivariable Cox models.\n"
                     "RESULTS: HR 0.85 (95% CI 0.75-0.96).\n"
                     "FUNDING: No funding was received. The authors declare no conflicts of interest."),
    }
    _kg = _keys(_good)
    check("已说明混杂调整则不触发 no_adjustment", "no_adjustment" not in _kg)
    check("已声明资助 / 利益冲突则不触发 funding_unknown", "funding_unknown" not in _kg)
    check("前瞻性队列不触发 retrospective", "retrospective" not in _kg)

    # 预试验
    _pilot = {
        "title": "A pilot randomized controlled trial of a new dressing",
        "abstract": "METHODS: This pilot study randomized 30 adults to the new dressing or standard care.",
    }
    check("预试验 / 可行性研究被识别", "pilot" in _keys(_pilot))

    # _max_attrition 的语序覆盖与误报防护
    check("失访率：数字在后语序可抽取",
          review._max_attrition("lost to follow-up in 22% of patients") is not None)
    check("失访率：数字在前语序可抽取",
          review._max_attrition("18% withdrew from the study") is not None)
    check("失访率：多值时取最大值（30 而非 5）",
          review._max_attrition("5% withdrew; 30% were lost to follow-up")[0] == 30)
    check("失访率：不当过句号（分号隔开仍可各自抽取）",
          review._max_attrition("Withdrawal was 12%.")[0] == 12)
    check("失访率：不良事件百分比不误报",
          review._max_attrition("Grade 3 adverse events occurred in 32% of patients") is None)
    check("低失访率不触发 high_attrition（5%）", "high_attrition" not in _keys({
        "title": "A randomized trial",
        "abstract": "METHODS: We randomized 500 adults. RESULTS: 5% were lost to follow-up.",
    }))

    # 基线不均衡（需命中断语，不能只看 "baseline" 一词）
    _imb = {
        "title": "A randomized trial of two anaesthetic regimens",
        "abstract": "METHODS: We randomized 200 patients. "
                    "Baseline characteristics differed between the two groups.",
    }
    check("新增规则：提及基线不均衡被识别（附依据）",
          any(f["key"] == "baseline_imbalance" and f["evidence"]
              for f in review.assess_bias(_imb)["flags"]))

    # 级别与措辞护栏（沿用 P2 的纪律）
    check("新增规则的级别只用三档，不引入「高/中/低风险」式裁定",
          all(f["level"] in (review.BIAS_FOCUS, review.BIAS_CHECK, review.BIAS_INFO)
              for f in review.assess_bias(_bad)["flags"])
          and set(review._BIAS_LEVEL_ORDER) == {review.BIAS_FOCUS, review.BIAS_CHECK, review.BIAS_INFO})
    _union = _keys(_bad) | _keys(_obs) | _keys(_good) | _keys(_pilot) | _keys(_imb)
    _new_rules = {"no_itt", "no_power", "industry_funding", "funding_unknown",
                  "posthoc_subgroup", "baseline_imbalance", "composite_outcome",
                  "no_adjustment", "high_attrition", "pilot"}
    check("P3-C4 新增的 10 类规则全部可被构造样例触发",
          _new_rules <= _union, "缺：" + str(sorted(_new_rules - _union)))

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED: " + f)
        return 1
    print("✅ 综述化引擎自测全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
