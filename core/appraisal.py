"""证据化深化（P3-C4）：结构化评价工具入口与 GRADE 自查引导。

与 ``core/review.py`` 的分工说清楚，免得混淆：

- ``review.assess_bias()`` 读的是**摘要**——摘要里看得见什么，就自动提示一条。
  它是"不点开原文也能先扫一眼"的粗筛，覆盖面受限于摘要本身写没写。
- 本模块提供的是**必须回全文逐条回答**的规范工具：把 Cochrane RoB 2（随机试验）、
  纽卡斯尔-渥太华量表 NOS（观察性研究）、AMSTAR-2（系统评价）、AGREE II（指南）、
  SYRCLE（动物实验）等量表的**信号问题**整理成清单，外加 GRADE 分级的降级 / 升级
  因素自查入口。

三条纪律（与 review 一致，不能破）：

1. **只给问题，不给判定**。工具读不到全文、不了解具体研究，永远不能替医生回答
   "这篇是低风险还是高风险"。它只负责把"该核对什么"列全，避免漏项。
2. **标清来源与简化程度**。每个工具都注明真实出处，并声明本工具的题项是**大幅度
   简化的改写**，不是官方量表的完整复现——正式评价请用原版量表。
3. **不制造权威错觉**。GRADE 的起始等级、降级 / 升级都写清判据，最终级别必须由
   评价者按指南作出，工具不代填。
"""
from __future__ import annotations

from collections import Counter

# ---------------------------------------------------------------------------
# 一、结构化评价工具（按研究设计匹配）
# ---------------------------------------------------------------------------
APPRAISAL_CAVEAT = (
    "以下信号问题依据 Cochrane RoB 2、纽卡斯尔-渥太华量表（NOS）、AMSTAR-2、"
    "AGREE II、SYRCLE 等工具整理，**为便于快速核对做了大幅简化**，题项与措辞均非"
    "官方量表的完整复现，也不能替代原版量表。正式评价请使用对应工具的原版量表"
    "（RoB 2 需配套 Excel 宏或 robvis 作图；NOS 满分 9 星；AMSTAR-2 需回答 16 项后"
    "给出总体可信度评级）。"
)

_APPRAISAL_DISCLAIMER = (
    "本清单只把「该核对什么」列全，不判断「结果是什么」。"
    "每条信号问题的答案都应取自**原文全文**，不能仅凭摘要作答——"
    "摘要没写不等于研究没做。"
)


def _toolkit(id_: str, name: str, full: str, scope: str, output: str,
             groups: tuple, source: str, note: str = "") -> dict:
    return {"id": id_, "name": name, "full": full, "scope": scope,
            "output": output, "groups": groups, "source": source, "note": note}


# ---- 随机对照试验：RoB 2（5 个域） ----
_ROB2 = _toolkit(
    "rob2", "RoB 2", "Cochrane 随机试验偏倚风险工具（Risk of Bias 2，2019）",
    "随机对照试验（含交叉设计、整群随机）",
    "每个域判定为「低风险 / 有一定顾虑 / 高风险」，再按规则合成总体判断",
    (
        ("域 1　随机化过程",
         ("随机序列如何产生（计算机 / 随机数字表 / 最小化 / 抽签）？有无描述？",
          "分配是否隐藏（中心化分配 / 密封不透明信封 / 药房分配）？",
          "两组基线特征是否可比？有无统计学显著差异或基线不均衡的说明？")),
        ("域 2　偏离既定干预",
         ("是否对受试者、实施者采用盲法（安慰剂 / 假手术 / 双盲）？",
          "若无盲法，是否存在影响结局的偏离（交叉、加用其他治疗、依从性差）？",
          "分析是基于意向性（ITT）还是仅限完成者（per-protocol）？")),
        ("域 3　结局数据缺失",
         ("各组失访 / 退出 / 剔除的例数与比例是多少？组间差异是否明显？",
          "缺失数据的处理方式是否说明（ITT、多重插补、末次观测结转）？",
          "缺失是否可能与结局相关（如病情恶化者退出）？")),
        ("域 4　结局测量",
         ("结局是客观指标（死亡、检验值）还是主观判断（量表、影像判读）？",
          "结局评估者、受试者是否保持盲法？主观结局尤其关键。",
          "测量工具是否统一、是否经过验证？有无系统性的测量差异？")),
        ("域 5　结果选择性报告",
         ("是否有试验注册号（NCT / ChiCTR / ISRCTN）与预设主要终点？",
          "报告的主要终点是否与注册 / 方案一致？有无事后更换或新增？",
          "有无选择性报告有利亚组、时间点或分析人群？")),
    ),
    "Sterne JAC, Savović J, Page MJ, et al. RoB 2: a revised tool for assessing risk of bias "
    "in randomised trials. BMJ 2019;366:l4898.",
)

# ---- 观察性研究：NOS（队列 / 病例对照 / 横断面改良版） ----
_NOS_COHORT = _toolkit(
    "nos_cohort", "NOS（队列）", "纽卡斯尔-渥太华量表 · 队列研究版",
    "队列研究（前瞻性或回顾性）",
    "每个条目给 1 星，「可比性」域最多 2 星，满分 9 星（星数越高偏倚风险越低）",
    (
        ("选择（最多 4 星）",
         ("暴露队列的代表性：暴露组能否代表目标人群？（1 星）",
          "非暴露组的选取：是否来自同一人群？（1 星）",
          "暴露的确定方式：是否来自可靠记录或盲法确认？（1 星）",
          "研究开始时结局是否已经存在？（结局不存在才给 1 星）")),
        ("可比性（最多 2 星）",
         ("在设计与分析中是否控制了最重要的混杂因素？（1 星）",
          "是否还控制了其他混杂因素？（1 星）")),
        ("结局（最多 3 星）",
         ("结局评估是否充分可靠（独立盲法判定 / 记录链接）？（1 星）",
          "随访时间是否足够长，使结局得以发生？（1 星）",
          "随访是否完整？失访率是否可接受？（1 星）")),
    ),
    "Wells GA, Shea B, O'Connell D, et al. The Newcastle-Ottawa Scale (NOS) for assessing "
    "the quality of nonrandomised studies in meta-analyses. Ottawa Hospital Research Institute.",
)

_NOS_CASE_CONTROL = _toolkit(
    "nos_case_control", "NOS（病例对照）", "纽卡斯尔-渥太华量表 · 病例对照研究版",
    "病例对照研究",
    "每个条目给 1 星，「可比性」域最多 2 星，满分 9 星",
    (
        ("选择（最多 4 星）",
         ("病例的定义是否充分（有独立确认 / 记录）？（1 星）",
          "病例的代表性如何（连续纳入还是便利样本）？（1 星）",
          "对照的选取是否合适（同一人群、无目标疾病）？（1 星）",
          "对照的定义是否明确（是否说明无该病）？（1 星）")),
        ("可比性（最多 2 星）",
         ("在设计与分析中是否控制了最重要的混杂因素？（1 星）",
          "是否还控制了其他混杂因素？（1 星）")),
        ("暴露（最多 3 星）",
         ("暴露的确定方式是否可靠（盲法 / 结构化记录）？（1 星）",
          "病例与对照的暴露确定方法是否相同？（1 星）",
          "无应答率在两组间是否相近？（1 星）")),
    ),
    "Wells GA, Shea B, O'Connell D, et al. The Newcastle-Ottawa Scale (NOS). "
    "Ottawa Hospital Research Institute.",
)

_NOS_CROSS = _toolkit(
    "nos_cross", "改良 NOS（横断面）", "纽卡斯尔-渥太华量表的横断面改良版",
    "横断面研究",
    "三个域共 10 星（选择 5 / 可比性 2 / 结局 3）",
    (
        ("选择（最多 5 星）",
         ("样本的代表性：抽样框架能否代表目标人群？（1 星）",
          "样本量是否经过论证 / 是否足够？（1 星）",
          "无应答偏倚：应答率是否报告、是否可接受？（1 星）",
          "暴露的确定方式是否可靠？（1 星）",
          "结局的确定方式是否可靠？（1 星）")),
        ("可比性（最多 2 星）",
         ("是否控制了最重要的混杂因素（统计调整 / 分层）？（1 星）",
          "是否还控制了其他混杂因素？（1 星）")),
        ("结局（最多 3 星）",
         ("结局评估是否使用独立盲法或客观记录？（1 星）",
          "统计检验是否恰当、是否报告了精确度？（1 星）",
          "有无对无应答 / 缺失数据的处理说明？（1 星）")),
    ),
    "Modesti PA, Reboldi G, Cappuccio FP, et al. Panethnic differences in blood pressure in "
    "Europe: a systematic review and meta-analysis.（横断面研究的 NOS 改良用法）",
    note="横断面设计本身不能确定暴露与结局的先后顺序，无论星数高低都不能据此推断因果。",
)

# ---- 系统评价 / Meta 分析：AMSTAR-2（16 项，7 项关键域） ----
_AMSTAR2 = _toolkit(
    "amstar2", "AMSTAR-2", "A MeaSurement Tool to Assess systematic Reviews 2（2017）",
    "系统评价 / Meta 分析（含纳入 RCT 或非随机研究的系统评价）",
    "16 个条目，其中 7 个为关键域；按关键域缺陷数量给出总体可信度：高 / 中 / 低 / 极低",
    (
        ("条目 1–8（问题、方案、检索、筛选、提取、描述）",
         ("1. 研究问题与纳入标准是否包含 PICO 各要素？",
          "2. 【关键】是否说明评价方法**事先**确立（注册 / 预发表方案），并解释重大偏离？",
          "3. 是否解释了选择纳入研究类型（如仅纳入 RCT）的原因？",
          "4. 【关键】检索策略是否全面（多库 + 检索词 + 时限 + 灰色文献 + 手工检索）？",
          "5. 研究筛选是否由两人独立完成？",
          "6. 数据提取是否由两人独立完成？",
          "7. 【关键】是否提供被排除研究的清单及排除理由？",
          "8. 是否充分描述了纳入研究的基本特征（人群、干预、对照、结局、随访）？")),
        ("条目 9–16（偏倚、合并、异质性、发表偏倚、利益冲突）",
         ("9. 【关键】是否使用恰当工具评估了纳入研究的偏倚风险？",
          "10. 是否报告了纳入研究的资助来源？",
          "11. 【关键】若做了 Meta 分析，合并方法是否恰当、是否探究了异质性来源？",
          "12. 若做了 Meta 分析，是否评估了纳入研究偏倚风险对合并结果的影响？",
          "13. 【关键】解释结果时是否考虑了纳入研究的偏倚风险？",
          "14. 是否对观察到的异质性给出了合理解释与讨论？",
          "15. 【关键】若做了定量合并，是否充分调查了发表偏倚并讨论其影响？",
          "16. 是否报告了潜在利益冲突（含本评价自身的资助来源）？")),
    ),
    "Shea BJ, Reeves BC, Wells G, et al. AMSTAR 2: a critical appraisal tool for systematic "
    "reviews that include randomised or non-randomised studies of healthcare interventions, "
    "or both. BMJ 2017;358:j4008.",
)

# ---- 临床指南 / 专家共识：AGREE II ----
_AGREE2 = _toolkit(
    "agree2", "AGREE II", "Appraisal of Guidelines for Research and Evaluation II",
    "临床实践指南 / 专家共识",
    "6 个域共 23 个条目，每项 1–7 分；分域计算标准化百分比",
    (
        ("域 1　范围与目的",
         ("总体目标、所覆盖的健康问题、适用人群是否明确描述？")),
        ("域 2　参与人员",
         ("指南制定组是否包含所有相关专业、是否纳入了目标人群（患者）代表？")),
        ("域 3　制定的严谨性",
         ("是否采用系统方法检索证据、明确纳入 / 排除标准、说明证据强度与推荐强度的关系？",
          "推荐意见是否考虑了健康获益、不良反应与风险？",
          "是否经过外部专家评审？是否有更新程序？")),
        ("域 4　呈现的清晰性",
         ("推荐意见是否具体、明确、无歧义？关键推荐是否易于识别？")),
        ("域 5　适用性",
         ("是否描述了促进与阻碍应用的因素、提供了实施建议与资源投入说明？",
          "是否提供监控 / 审计标准？")),
        ("域 6　编辑独立性",
         ("资助方的观点是否影响指南内容？是否披露了制定组成员的利益冲突？")),
    ),
    "Brouwers MC, Kho ME, Browman GP, et al. AGREE II: advancing guideline development, "
    "reporting and evaluation in health care. CMAJ 2010;182(18):E839-42.",
)

# ---- 叙述性综述：SANRA ----
_SANRA = _toolkit(
    "sanra", "SANRA", "Scale for the Assessment of Narrative Review Articles",
    "叙述性综述（非系统检索的综述）",
    "6 个条目，每项 0–2 分，满分 12 分",
    (
        ("6 个条目",
         ("1. 是否说明了该综述对读者**重要**的理由？",
          "2. 是否明确陈述了**具体目标**或提出的问题？",
          "3. 是否描述了**文献检索**方法（检索库、检索词、时限）？",
          "4. 是否提及所引用文献的**质量**（如是否含原始研究、样本量）？",
          "5. 是否提供了所引用证据的**科学推理**？",
          "6. 是否呈现了**相关数据**（如终点指标、效应量）？")),
    ),
    "Baethge C, Goldbeck-Wood S, Mertens S. SANRA—a scale for the quality assessment of "
    "narrative review articles. Res Integr Peer Rev 2019;4:5.",
    note="叙述性综述未做系统检索，无论得分高低都不能作为某一临床问题的完整证据基础。",
)

# ---- 病例报告 / 病例系列：CARE（报告规范） ----
_CARE = _toolkit(
    "care", "CARE", "Case REport 报告规范（CARE guidelines，2013/2017）",
    "病例报告 / 病例系列",
    "13 个条目的**报告完整性**清单（注意：这是报告规范，不是偏倚风险评估工具）",
    (
        ("关键条目",
         ("标题是否标明「病例报告」及所关注的焦点？",
          "患者信息：去标识化的人口学特征、主诉、既往史与合并用药是否完整？",
          "临床发现：体格检查与重要检验结果（含阴性结果）是否描述？",
          "时间轴：诊疗经过是否按时间线交代清楚？",
          "诊断评估：诊断方法、鉴别诊断的依据与结果是否说明？",
          "治疗干预：干预类型、剂量、疗程、有无调整及理由是否清楚？",
          "结局与随访：是否说明结局指标的评估方式与随访时长？",
          "讨论：是否说明了结论的**局限**，以及可能的因果解释（含不良反应）？",
          "知情同意与伦理：是否说明取得了患者知情同意？")),
    ),
    "Gagnier JJ, Kienle G, Altman DG, et al. The CARE guidelines: consensus-based clinical "
    "case report guideline development. J Clin Epidemiol 2014;67(1):46-51.",
    note="病例报告无对照组，只能用于提示罕见事件或提出假设，不能据以判断疗效。",
)

# ---- 基础 / 动物实验：SYRCLE ----
_SYRCLE = _toolkit(
    "syrcle", "SYRCLE", "SYstematic Review Centre for Laboratory animal Experimentation 偏倚风险工具（2014）",
    "动物实验 / 基础研究",
    "10 个条目，每个判定「是 / 否 / 不明确」，逐项对应 RoB 2 式的域概念",
    (
        ("10 个条目（对应域）",
         ("1. 是否随机分配动物到各组（选择偏倚）？",
          "2. 各组基线特征是否相似（选择偏倚）？",
          "3. 是否对动物实施盲法分配（选择偏倚）？",
          "4. 是否随机安置动物（实施偏倚）？",
          "5. 动物照护者 / 实验者是否施盲（实施偏倚）？",
          "6. 结局评估者是否施盲（检测偏倚）？",
          "7. 是否随机选取动物进行结局评估（检测偏倚）？",
          "8. 结局数据是否完整（失访偏倚）？",
          "9. 是否报告了所有预设结局（报告偏倚）？",
          "10. 其他偏倚来源是否被说明？")),
    ),
    "Hooijmans CR, Rovers MM, de Vries RB, et al. SYRCLE's risk of bias tool for animal "
    "studies. BMC Med Res Methodol 2014;14:43.",
    note="动物实验结果不能直接外推至临床；可用于解释机制、提出假设或设计后续试验。",
)

ALL_TOOLKITS: tuple[dict, ...] = (
    _ROB2, _NOS_COHORT, _NOS_CASE_CONTROL, _NOS_CROSS,
    _AMSTAR2, _AGREE2, _SANRA, _CARE, _SYRCLE,
)

TOOLKITS: dict[str, dict] = {t["id"]: t for t in ALL_TOOLKITS}

# 研究设计 → 推荐工具。与 core.review.DESIGN_LAYERS 的键保持一致。
TOOLKIT_BY_DESIGN: dict[str, tuple[str, ...]] = {
    "随机对照试验": ("rob2",),
    "队列研究": ("nos_cohort",),
    "病例对照研究": ("nos_case_control",),
    "横断面研究": ("nos_cross",),
    "系统评价 / Meta 分析": ("amstar2",),
    "临床指南 / 专家共识": ("agree2",),
    "叙述性综述": ("sanra",),
    "病例报告 / 病例系列": ("care",),
    "基础 / 动物实验": ("syrcle",),
    "未识别": (),
}


def tools_for_design(design: str) -> list[dict]:
    """按研究设计返回推荐的结构化评价工具（可能为空，例如设计未识别）。"""
    return [TOOLKITS[i] for i in TOOLKIT_BY_DESIGN.get(design, ()) if i in TOOLKITS]


def tools_for_article(article: dict) -> list[dict]:
    """按文献的研究设计返回工具；懒加载 ``review`` 以避免模块级循环依赖。"""
    from core import review
    design, _ = review.judge_design(article)
    return tools_for_design(design)


def appraisal_overview(rows: list[dict]) -> dict:
    """汇总一批文献各自适用的结构化评价工具，供页面概览。

    返回 ``{"total", "by_design", "toolkits", "unmapped"}``：
    ``toolkits`` 为 ``[(工具名, 篇数), ...]``，按篇数降序；``unmapped`` 为设计未识别
    或因设计未识别而拿不到工具的篇数。
    """
    by_design: Counter = Counter()
    by_tool: Counter = Counter()
    unmapped = 0
    for r in rows:
        design = ((r.get("_profile") or {}).get("design")) or "未识别"
        by_design[design] += 1
        tools = tools_for_design(design)
        if not tools:
            unmapped += 1
            continue
        for t in tools:
            by_tool[t["name"]] += 1
    return {
        "total": len(rows),
        "by_design": dict(by_design.most_common()),
        "toolkits": by_tool.most_common(),
        "unmapped": unmapped,
    }


def appraisal_markdown(rows: list[dict], topic: str = "") -> str:
    """导出「结构化评价自查清单」（Markdown）：按工具分组列出信号问题。

    同一批文献若横跨多种设计，各工具的清单只列一次（清单是给评价者照做的，
    不必逐篇重复），再列出每篇适用哪个工具，便于分工。
    """
    ov = appraisal_overview(rows)
    out = [f"### 结构化评价自查清单（{topic}）" if topic else "### 结构化评价自查清单", ""]
    out.append(f"> {APPRAISAL_CAVEAT}")
    out.append("")
    out.append(f"> {_APPRAISAL_DISCLAIMER}")
    out.append("")
    out.append(f"- 纳入文献：{ov['total']} 篇；研究设计分布："
               + "、".join(f"{k} {v} 篇" for k, v in ov["by_design"].items())
               + (f"；其中 {ov['unmapped']} 篇因研究类型未识别而无法匹配工具。" if ov["unmapped"] else "。"))
    out.append("")

    out.append("#### 一、本研究批次用到的工具")
    out.append("")
    if ov["toolkits"]:
        for name, cnt in ov["toolkits"]:
            out.append(f"- **{name}**：适用于 {cnt} 篇")
    else:
        out.append("- 本批次未匹配到任何工具（研究类型均未识别）。")
    out.append("")

    used_ids: list[str] = []
    for r in rows:
        design = ((r.get("_profile") or {}).get("design")) or "未识别"
        for t in tools_for_design(design):
            if t["id"] not in used_ids:
                used_ids.append(t["id"])
    # 未识别的设计也把对应设计一并列出，避免遗漏
    out.append("#### 二、逐篇适用的工具")
    out.append("")
    for i, r in enumerate(rows, 1):
        p = r.get("_profile") or {}
        design = p.get("design") or "未识别"
        tools = tools_for_design(design)
        names = "、".join(t["name"] for t in tools) if tools else "（研究类型未识别，请先判断设计）"
        out.append(f"- {i}. {p.get('title', '（无标题）')}　→　{design}｜适用工具：{names}")
    out.append("")

    out.append("#### 三、信号问题逐条自查")
    out.append("")
    for tid in used_ids:
        t = TOOLKITS[tid]
        out.append(f"##### {t['name']}　—　{t['full']}")
        out.append("")
        out.append(f"- 适用：{t['scope']}")
        out.append(f"- 判定方式：{t['output']}")
        if t.get("note"):
            out.append(f"- 提醒：{t['note']}")
        out.append(f"- 出处：{t['source']}")
        out.append("")
        for group, questions in t["groups"]:
            out.append(f"**{group}**")
            out.append("")
            for q in questions:
                out.append(f"- [ ] {q}")
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 二、GRADE 分级自查入口
# ---------------------------------------------------------------------------
# GRADE（Grading of Recommendations Assessment, Development and Evaluation）:
# 先按研究设计定**起始等级**（RCT 为高，观察性为低），再按 5 个因素降级、3 个因素升级，
# 得到最终四级：高 / 中 / 低 / 极低。本工具不代用户给等级，只把判据摆开。
GRADE_CAVEAT = (
    "GRADE 的最终等级由评价者依据完整证据体作出，**本工具不代替分级**。"
    "下表只列出起始等级与降级 / 升级因素的判据，供逐条核对避免漏项。"
    "证据体的最终等级 = 起始等级 经过降级 / 升级后落在 高 / 中 / 低 / 极低 四级之一。"
)

GRADE_START: dict[str, tuple[str, str]] = {
    "随机对照试验": ("高", "随机对照试验是 GRADE 的最高起始等级（4 级）"),
    "系统评价 / Meta 分析": ("高", "若纳入研究以 RCT 为主，起始为高；若纳入观察性研究则从低起步"),
    "队列研究": ("低", "观察性研究（队列）起始为低（2 级）"),
    "病例对照研究": ("低", "观察性研究（病例对照）起始为低（2 级）"),
    "横断面研究": ("低", "观察性研究起始为低；横断面设计通常不支持因果推断"),
    "病例报告 / 病例系列": ("极低", "无对照的描述性证据，起始为极低"),
    "基础 / 动物实验": ("不适用", "非临床证据体，GRADE 不适用于动物 / 体外研究"),
    "叙述性综述": ("不适用", "未系统检索，不构成完整证据体，GRADE 不适用"),
    "临床指南 / 专家共识": ("不适用", "推荐意见文件；应追溯其证据基础至原始研究后再评"),
    "未识别": ("待定", "研究类型未识别，无法给出起始等级"),
}

# (因素, 何时降级, 降几级, 怎么查)
GRADE_DOWNGRADE: tuple[tuple[str, str, str, str], ...] = (
    ("偏倚风险", "多数证据来自存在严重局限的研究", "降 1~2 级",
     "用 RoB 2（RCT）、NOS（观察性）逐篇评估后汇总到证据体层面"),
    ("不一致性", "研究间效应方向或大小差异大、I² 高、且无法用亚组或人群差异解释", "降 1~2 级",
     "看森林图与 I²，检查预设亚组能否解释差异"),
    ("间接性", "人群、干预、对照或结局与临床问题不直接对应", "降 1~2 级",
     "替代终点、动物数据外推、人群 / 剂型 / 疗程差异都属间接"),
    ("不精确性", "置信区间宽、跨过无效线，或总样本量 / 事件数不足", "降 1~2 级",
     "看每项结局的 95% CI 与最优信息量（OIS）是否达到"),
    ("发表偏倚", "存在小样本研究、阴性结果缺失，或漏斗图不对称", "降 1 级",
     "看漏斗图 / Egger 检验，或纳入研究的数量与规模分布"),
)

# (因素, 何时升级, 升几级, 怎么查)
GRADE_UPGRADE: tuple[tuple[str, str, str, str], ...] = (
    ("效应量大", "RR > 2 或 < 0.5（且无明显混杂）", "升 1 级",
     "观察性研究中尤为适用；RR > 5 或 < 0.2 可升 2 级"),
    ("剂量-反应关系", "存在明确的剂量-反应梯度", "升 1 级",
     "注意区分预设分析与事后分析"),
    ("可能的混杂都会削弱效应", "所有合理的残余混杂均只会低估真实效应（或掩蔽有害效应）", "升 1 级",
     "罕见情形，需作者提供论证"),
)


def grade_start_level(design: str) -> tuple[str, str]:
    """按研究设计给出 GRADE 起始等级，返回 ``(等级, 说明)``。"""
    return GRADE_START.get(design, ("待定", "研究类型未识别，无法给出起始等级"))


def grade_overview(rows: list[dict]) -> dict:
    """汇总一批文献的 GRADE 起始等级分布与不适用篇数。"""
    c: Counter = Counter()
    na = 0
    for r in rows:
        design = ((r.get("_profile") or {}).get("design")) or "未识别"
        level, _ = grade_start_level(design)
        c[level] += 1
        if level == "不适用":
            na += 1
    return {"total": len(rows), "levels": c.most_common(), "not_applicable": na}


def grade_markdown(rows: list[dict], topic: str = "") -> str:
    """导出「GRADE 分级自查表」（Markdown）。"""
    ov = grade_overview(rows)
    out = [f"### GRADE 证据分级自查表（{topic}）" if topic else "### GRADE 证据分级自查表", ""]
    out.append(f"> {GRADE_CAVEAT}")
    out.append("")
    out.append(f"- 纳入文献：{ov['total']} 篇；起始等级分布："
               + "、".join(f"{k} {v} 篇" for k, v in ov["levels"])
               + (f"（其中 {ov['not_applicable']} 篇为 GRADE 不适用）" if ov["not_applicable"] else "")
               + "。")
    out.append("")

    out.append("#### 一、起始等级（按研究设计）")
    out.append("")
    out.append("| 研究设计 | 起始等级 | 说明 |")
    out.append("|---|---|---|")
    for design in sorted({((r.get("_profile") or {}).get("design") or "未识别") for r in rows}):
        lv, why = grade_start_level(design)
        out.append(f"| {design} | {lv} | {why} |")
    out.append("")

    out.append("#### 二、降级因素（在起始等级上逐条核对）")
    out.append("")
    out.append("| 因素 | 何时降级 | 幅度 | 怎么查 |")
    out.append("|---|---|---|---|")
    for name, when, amount, how in GRADE_DOWNGRADE:
        out.append(f"| {name} | {when} | {amount} | {how} |")
    out.append("")

    out.append("#### 三、升级因素（观察性证据体尤其适用）")
    out.append("")
    out.append("| 因素 | 何时升级 | 幅度 | 怎么查 |")
    out.append("|---|---|---|---|")
    for name, when, amount, how in GRADE_UPGRADE:
        out.append(f"| {name} | {when} | {amount} | {how} |")
    out.append("")

    out.append("#### 四、逐篇起始等级")
    out.append("")
    for i, r in enumerate(rows, 1):
        p = r.get("_profile") or {}
        design = p.get("design") or "未识别"
        lv, why = grade_start_level(design)
        out.append(f"- {i}. {p.get('title', '（无标题）')}　→　{design}｜起始等级：**{lv}**（{why}）")
    out.append("")
    out.append("> 逐篇起始等级只是**起点**；最终等级还要在证据体层面按上述降级 / 升级因素调整，"
               "同一结局的多项研究需合并考虑，不能把单篇的起始等级当作最终结论。")
    return "\n".join(out)
