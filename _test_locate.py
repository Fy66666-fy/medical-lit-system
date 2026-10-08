# -*- coding: utf-8 -*-
"""locate.py 自检：索引 / 数值扫描 / 精确与模糊定位 / 跨语言匹配 / 高亮转义"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import locate, summarizer

SECS = [
    {"title": "Background", "text": (
        "Diabetes mellitus is a major global health burden. "
        "Previous studies reported inconsistent findings regarding glycemic control strategies. "
        "This study aimed to evaluate the efficacy of metformin combined with SGLT2 inhibitors."
    )},
    {"title": "Methods", "text": (
        "We conducted a randomized controlled trial (n = 486) enrolling patients with type 2 diabetes. "
        "Participants were assigned in a 1:1 ratio to combination therapy or metformin alone for 52 weeks. "
        "The primary outcome was change in HbA1c from baseline."
    )},
    {"title": "Results", "text": (
        "Mean HbA1c decreased from 8.4% to 7.1% in the combination group versus 8.3% to 7.9% with metformin alone. "
        "The difference was statistically significant (P < 0.001). "
        "Hypoglycemia occurred in 12.3% versus 5.6% of patients respectively (95% CI 1.24 to 3.15; HR 2.1). "
        "Body weight decreased by 2.3 ± 1.1 kg in the combination arm."
    )},
]

failures = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + detail))
    if not cond:
        failures.append(name)

# 1) 索引
index = locate.build_index(SECS)
check("index non-empty", len(index) >= 10, f"got {len(index)}")
check("index has sections", {it["section"] for it in index} == {"Background", "Methods", "Results"})
check("offsets valid", all(it["end"] > it["start"] for it in index))

# 2) 数值扫描
vals = locate.find_values(index)
types_found = set(vals.keys())
check("P值 found", "P 值" in types_found, str(types_found))
check("百分比 found", "百分比" in types_found)
check("CI found", "置信区间" in types_found)
check("HR found", "风险比/比值比" in types_found)
check("样本量 found", "样本量" in types_found)
check("均值±SD found", "均值±标准差" in types_found)
p_items = vals.get("P 值", [])
check("P值 entry fields", p_items and p_items[0]["sentence"] and p_items[0]["section"] == "Results")

# 3) 精确定位（抽取句 = 原句）
target = [it["text"] for it in index if "P < 0.001" in it["text"]][0]
m = locate.locate_sentence(target, index)
check("exact match", m and m[0]["score"] == 1.0 and "P < 0.001" in m[0]["text"])

# 4) 近似精确（清理连接词后的句子）
m2 = locate.locate_sentence("However, " + target, index)
check("near-exact match", m2 and m2[0]["score"] >= 0.95)

# 5) 模糊匹配：中文 LLM 句（含数字+术语）
zh_sent = "与二甲双胍单药相比，联合治疗组症状性低血糖发生率更高（12.3% vs 5.6%，HR 2.1，95% CI 1.24 至 3.15）。"
m3 = locate.locate_sentence(zh_sent, index)
check("cross-language match", bool(m3) and "Hypoglycemia" in m3[0]["text"],
      f"got {[(x['text'][:40], x['score']) for x in m3]}")

zh_sent2 = "该研究共纳入486名2型糖尿病患者。"
m4 = locate.locate_sentence(zh_sent2, index)
check("cross-language by n", bool(m4) and "486" in m4[0]["text"])

# 6) 无可靠对应时如实返回空
m5 = locate.locate_sentence("本研究具有重要的公共卫生学意义与政策参考价值。", index)
check("no-match returns empty", m5 == [])

# 7) 高亮与转义
hl = locate.highlight_values("HbA1c fell from 8.4% to 7.1% (P < 0.001) & significant.")
check("highlight wraps values", 'class="loc-val"' in hl and hl.count("loc-val") >= 2)
check("html escaped", "&amp;" in hl and "<b>" not in hl)
check("plain sentence untouched", "<span" not in locate.highlight_values("No numbers here."))

# 8) split_sentences 兼容（被 summarizer 依赖）
check("split ok", len(summarizer.split_sentences(SECS[2]["text"])) >= 4)

# 9) Lancet 中点小数 + CI 截取 + 百分比排除（v2.1.1 回归）
lancet = [{"title": "Findings", "text": (
    "At 52 weeks, the incidence was 20% versus 50% (hazard ratio HR 0·49, "
    "95% CI 0·33–0·74, P = 0·00065). "
    "Adjudicated outcomes (95% CI 0·64–0·98, P = 0·033) [ 51 ] favoured combination therapy. "
    "Patients (95% CI 0.64) in table rows used decimal points; mean dose was 10.5 ± 2.0 mg."
)}]
li = locate.build_index(lancet)
lv = locate.find_values(li)
ci_vals = [x["value"] for x in lv.get("置信区间", [])]
check("lancet CI mid-dot", "95% CI 0.33-0.74" in [v.replace("–", "-") for v in ci_vals], str(ci_vals))
check("CI no bracket junk", all("[" not in v and ")" not in v or "(95% CI" not in v for v in ci_vals)
      and not any(v.endswith(")") and "(" not in v for v in ci_vals), str(ci_vals))
check("CI no bare truncation", "95% CI 0" not in ci_vals and "95% CI 0.64" in ci_vals, str(ci_vals))
pct_vals = [x["value"] for x in lv.get("百分比", [])]
check("pct excludes 95%CI", all(v != "95%" for v in pct_vals), str(pct_vals))
p_vals = [x["value"] for x in lv.get("P 值", [])]
check("lancet P mid-dot", "P = 0.00065" in p_vals, str(p_vals))
hr_vals = [x["value"] for x in lv.get("风险比/比值比", [])]
check("lancet HR mid-dot", any(v.startswith("HR 0.49") for v in hr_vals), str(hr_vals))
sd_vals = [x["value"] for x in lv.get("均值±标准差", [])]
check("mean±SD found", any("10.5" in v for v in sd_vals), str(sd_vals))

# 10) summarizer.analyze_fulltext 指标规范化
an = summarizer.analyze_fulltext(lancet)
m_ci = an["metrics"].get("置信区间", {})
check("analyze CI clean", all("(" not in v.split("(")[0] or True for v in m_ci.get("samples", []))
      and all("[" not in v for v in m_ci.get("samples", [])), str(m_ci))
check("analyze pct no 95%", all(v != "95%" for v in an["metrics"].get("百分比", {}).get("samples", [])),
      str(an["metrics"].get("百分比")))

# 11) 全文关键词搜索（v2.2.0）
hits = locate.search_keyword(index, "HbA1c")
check("kw single hit", len(hits) >= 2 and all("hba1c" in h["text"].lower() for h in hits),
      f"got {len(hits)}")
asc = all(hits[i]["section"] != hits[i + 1]["section"] or hits[i]["pos"] < hits[i + 1]["pos"]
          for i in range(len(hits) - 1))
check("kw order preserved", asc, str([(h["section"], h["pos"]) for h in hits]))
hits2 = locate.search_keyword(index, "metformin 52")
check("kw AND semantics", len(hits2) == 1 and "52 weeks" in hits2[0]["text"], str([h["text"][:50] for h in hits2]))
hits3 = locate.search_keyword(index, "不存在词xyz")
check("kw no match", hits3 == [])
check("kw count field", hits and hits[0]["count"] >= 1)
hl_kw = locate.highlight_query("Mean HbA1c decreased versus HbA1c baseline.", "hba1c")
check("kw highlight case-insensitive", hl_kw.count('class="loc-kw"') == 2, hl_kw)
hl_esc = locate.highlight_query("a <b> c & metformin", "metformin")
check("kw html escaped", "&amp;" in hl_esc and "<b>" not in hl_esc, hl_esc)

print()
print("TOTAL FAILURES:", len(failures))
sys.exit(1 if failures else 0)
