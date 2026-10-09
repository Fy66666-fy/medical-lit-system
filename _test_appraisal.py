"""P3-C4 自测：结构化评价工具入口与 GRADE 分级自查。

覆盖点：
- 研究设计 → 工具的映射（含未识别设计不给工具）
- 工具本身的完整性（域非空、题项非空、出处非空、id 唯一）
- **契约测试**：TOOLKIT_BY_DESIGN 的键必须与 review.DESIGN_LAYERS 完全一致——否则
  新增研究设计时 appraisal 会静默漏配工具，这种"看起来没事"的漏洞最难发现
- GRADE 起始等级 / 降级 / 升级
- 两份 Markdown 导出的内容与边界（空批次、未识别、工具去重）

全部离线，不访问任何外部接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_appraisal_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import appraisal, review  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def rows_of(*designs: str) -> list[dict]:
    return [{"_profile": {"design": d, "title": f"研究 {i + 1}"}} for i, d in enumerate(designs)]


def main() -> int:
    print("[1] 工具库完整性")
    ids = [t["id"] for t in appraisal.ALL_TOOLKITS]
    check("工具 id 唯一", len(ids) == len(set(ids)), str(ids))
    check("工具数量 >= 8", len(appraisal.ALL_TOOLKITS) >= 8, str(len(appraisal.ALL_TOOLKITS)))
    all_ok = True
    for t in appraisal.ALL_TOOLKITS:
        if not (t["name"] and t["full"] and t["scope"] and t["output"] and t["source"]):
            all_ok = False
        if not t["groups"]:
            all_ok = False
        for _group, questions in t["groups"]:
            if not questions:
                all_ok = False
            for q in questions:
                if not str(q).strip():
                    all_ok = False
    check("每个工具都有名称/适用/判定/出处，且域与题项非空", all_ok)
    check("TOOLKITS 字典与 ALL_TOOLKITS 一致",
          set(appraisal.TOOLKITS) == set(ids))

    print("\n[2] 设计 → 工具映射（含契约测试）")
    checks = [
        ("随机对照试验", "rob2"),
        ("队列研究", "nos_cohort"),
        ("病例对照研究", "nos_case_control"),
        ("横断面研究", "nos_cross"),
        ("系统评价 / Meta 分析", "amstar2"),
        ("临床指南 / 专家共识", "agree2"),
        ("叙述性综述", "sanra"),
        ("病例报告 / 病例系列", "care"),
        ("基础 / 动物实验", "syrcle"),
    ]
    for design, tool_id in checks:
        got = [t["id"] for t in appraisal.tools_for_design(design)]
        check(f"{design} → {tool_id}", got == [tool_id], str(got))
    check("未识别设计不给工具", appraisal.tools_for_design("未识别") == [])
    check("未知设计（越界输入）不给工具", appraisal.tools_for_design("某某研究") == [])

    # 契约测试：两个模块的"研究设计全集"必须一致，否则新增设计会漏配工具
    check("TOOLKIT_BY_DESIGN 的键与 review.DESIGN_LAYERS 完全一致",
          set(appraisal.TOOLKIT_BY_DESIGN) == set(review.DESIGN_LAYERS),
          f"appraisal={sorted(set(appraisal.TOOLKIT_BY_DESIGN) ^ set(review.DESIGN_LAYERS))}")
    designed = {k for k in appraisal.TOOLKIT_BY_DESIGN if k != "未识别"}
    check("除未识别外每种设计都配了工具",
          all(appraisal.TOOLKIT_BY_DESIGN[k] for k in designed))

    print("\n[3] tools_for_article（走真实设计识别）")
    art = {"title": "A randomized, double-blind, placebo-controlled trial of drug X",
           "abstract": "METHODS: We randomly assigned 400 patients to drug X or placebo."}
    check("RCT 文献匹配到 RoB 2",
          [t["id"] for t in appraisal.tools_for_article(art)] == ["rob2"])
    art2 = {"title": "A systematic review and meta-analysis of statins",
            "abstract": "METHODS: We searched PubMed and Embase. RESULTS: Pooled OR 1.2."}
    check("系统评价文献匹配到 AMSTAR-2",
          [t["id"] for t in appraisal.tools_for_article(art2)] == ["amstar2"])
    art3 = {"title": "A cohort study of coffee and mortality",
            "abstract": "METHODS: We followed 5000 adults for 10 years."}
    check("队列文献匹配到 NOS（队列）",
          [t["id"] for t in appraisal.tools_for_article(art3)] == ["nos_cohort"])

    print("\n[4] appraisal_overview / grade_overview")
    rows = rows_of("随机对照试验", "随机对照试验", "系统评价 / Meta 分析", "未识别")
    ov = appraisal.appraisal_overview(rows)
    check("总篇数正确", ov["total"] == 4)
    check("设计分布正确", ov["by_design"].get("随机对照试验") == 2)
    check("工具计数正确", dict(ov["toolkits"]).get("RoB 2") == 2)
    check("未匹配篇数正确", ov["unmapped"] == 1)
    gov = appraisal.grade_overview(rows)
    check("GRADE 起始等级：高 3 篇 / 待定 1 篇",
          dict(gov["levels"]).get("高") == 3 and dict(gov["levels"]).get("待定") == 1)
    gov2 = appraisal.grade_overview(rows_of("基础 / 动物实验", "叙述性综述"))
    check("GRADE 不适用篇数正确", gov2["not_applicable"] == 2)
    check("空批次不报错",
          appraisal.appraisal_overview([])["total"] == 0
          and appraisal.grade_overview([])["total"] == 0)

    print("\n[5] GRADE 起始等级 / 降级 / 升级")
    check("RCT 起始等级为高", appraisal.grade_start_level("随机对照试验")[0] == "高")
    check("队列起始等级为低", appraisal.grade_start_level("队列研究")[0] == "低")
    check("病例报告起始等级为极低",
          appraisal.grade_start_level("病例报告 / 病例系列")[0] == "极低")
    check("动物实验 GRADE 不适用",
          appraisal.grade_start_level("基础 / 动物实验")[0] == "不适用")
    check("未知设计返回待定", appraisal.grade_start_level("没这个设计")[0] == "待定")
    dn_names = [n for n, _, _, _ in appraisal.GRADE_DOWNGRADE]
    check("5 个降级因素齐全",
          dn_names == ["偏倚风险", "不一致性", "间接性", "不精确性", "发表偏倚"], str(dn_names))
    up_names = [n for n, _, _, _ in appraisal.GRADE_UPGRADE]
    check("3 个升级因素齐全", len(up_names) == 3, str(up_names))
    check("降级 / 升级每项都写了判据与查法",
          all(w and a and h for _, w, a, h in appraisal.GRADE_DOWNGRADE)
          and all(w and a and h for _, w, a, h in appraisal.GRADE_UPGRADE))

    print("\n[6] appraisal_markdown 导出")
    md = appraisal.appraisal_markdown(rows, "他汀与心血管事件")
    check("含标题与主题", "结构化评价自查清单（他汀与心血管事件）" in md)
    check("含简化声明", "大幅简化" in md)
    check("含「不能仅凭摘要作答」提示", "不能仅凭摘要作答" in md)
    check("含可勾选题项", md.count("- [ ] ") >= 5)
    check("含 RoB 2 与 AMSTAR-2", "RoB 2" in md and "AMSTAR-2" in md)
    check("含出处（BMJ / 原量表）", "BMJ" in md)
    check("列出逐篇适用工具", "逐篇适用的工具" in md)
    check("未识别篇给出提示", "请先判断设计" in md)
    check("工具清单不逐篇重复（RoB 2 只列一次）",
          md.count("##### RoB 2") == 1)
    md_empty = appraisal.appraisal_markdown([], "空")
    check("空批次导出不报错且给出说明", "未匹配到任何工具" in md_empty)
    md_un = appraisal.appraisal_markdown(rows_of("未识别"), "全未识别")
    check("全未识别时不出现工具章节", "##### " not in md_un)

    print("\n[7] grade_markdown 导出")
    gm = appraisal.grade_markdown(rows, "他汀与心血管事件")
    check("含标题与主题", "GRADE 证据分级自查表（他汀与心血管事件）" in gm)
    check("含免责声明（不代填）", "不代替分级" in gm)
    check("含起始等级表", "起始等级（按研究设计）" in gm)
    check("含全部降级因素", all(n in gm for n in dn_names))
    check("含全部升级因素", all(n in gm for n in up_names))
    check("含逐篇起始等级", "逐篇起始等级" in gm)
    check("含证据体层面提醒", "证据体层面" in gm)
    gm_empty = appraisal.grade_markdown([], "空")
    check("空批次 GRADE 导出不报错", "GRADE 证据分级自查表" in gm_empty)

    print("\n[8] 与 review 的职责不重叠（回归护栏）")
    check("appraisal 不导出 assess_bias（避免两处实现漂移）",
          not hasattr(appraisal, "assess_bias"))
    # 只看 import 语句行：文档字符串里提到 appraisal 是正常的，不能误判。
    import re as _re
    _review_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "core", "review.py"), encoding="utf-8").read()
    _imports = "\n".join(l for l in _review_src.splitlines()
                         if _re.match(r"\s*(?:from|import)\s", l))
    check("review 的 import 语句未反向依赖 appraisal（无循环导入）",
          "appraisal" not in _imports)
    # 真跑一次：只导入 review 时，appraisal 不应被连带加载
    import subprocess
    cp = subprocess.run(
        [sys.executable, "-c",
         "import os,tempfile,sys;os.environ['MEDLIT_DATA_DIR']=tempfile.mkdtemp();"
         "sys.path.insert(0,'.');import core.review as r;"
         "print('core.appraisal' in sys.modules)"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True, text=True)
    check("只导入 review 时 appraisal 不被连带加载（无循环导入）",
          cp.stdout.strip().endswith("False"), cp.stdout.strip() or cp.stderr[-200:])

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED: " + f)
        return 1
    print("✅ 结构化评价工具自测全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
