"""为落地页截图播种一份演示数据（只写临时目录，绝不碰真实 data/）。

用法：
    python _seed_demo.py
    # 关键：必须同时给 MEDLIT_DATA_DIR 和 MEDLIT_SCOPE=local。
    # 只给 DATA_DIR 不够 —— app.py 在没设 MEDLIT_SCOPE 时会按**浏览器会话 id** 分片
    # （storage.set_scope(_init_scope())），数据会落到 data/users/s<sid>/ 下，页面照样是空的。
    MEDLIT_DATA_DIR="<项目>/_demo_data" MEDLIT_SCOPE=local \\
        python launch.py --port 8512 --no-browser
    python _shot.py _preview 8512 --lib
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(ROOT, "_demo_data")

ARTICLES = [
    {
        "pmid": "37721856", "title": "Metformin and cardiovascular outcomes in type 2 diabetes: a randomized controlled trial",
        "authors": ["Zhang Y", "Liu H", "Wang J", "Chen X", "Sun Q"],
        "journal": "Cardiovasc Diabetol", "year": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/37721856/",
        "abstract": "BACKGROUND: Metformin is the first-line therapy for type 2 diabetes, yet its effect on major adverse cardiovascular events (MACE) remains debated. METHODS: In this multicenter randomized controlled trial, 4,812 patients with type 2 diabetes and established cardiovascular disease were assigned to metformin or placebo. The primary outcome was a composite of cardiovascular death, myocardial infarction, or stroke. RESULTS: Over a median follow-up of 4.2 years, MACE occurred in 8.1% of the metformin group and 10.4% of the placebo group (hazard ratio 0.77, 95% CI 0.66-0.90; p=0.001). CONCLUSIONS: Metformin reduced cardiovascular events in high-risk patients with type 2 diabetes.",
        "saved_at": "2026-09-28 14:12",
    },
    {
        "pmid": "36872141", "title": "SGLT2 inhibitors in heart failure with preserved ejection fraction: a systematic review and meta-analysis",
        "authors": ["Kondo T", "Nakamura S", "Ito M"],
        "journal": "Eur J Heart Fail", "year": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/36872141/",
        "abstract": "AIMS: To evaluate the efficacy of sodium-glucose cotransporter-2 (SGLT2) inhibitors in heart failure with preserved ejection fraction (HFpEF). METHODS AND RESULTS: We searched PubMed, Embase and the Cochrane Library through November 2022. Thirteen randomized trials comprising 21,947 patients were included. SGLT2 inhibitors reduced the composite of cardiovascular death or heart failure hospitalization (risk ratio 0.80, 95% CI 0.73-0.87). CONCLUSION: SGLT2 inhibitors provide consistent benefit in HFpEF regardless of diabetes status.",
        "saved_at": "2026-09-28 14:31",
    },
    {
        "pmid": "37110993", "title": "GLP-1 receptor agonists and body weight in adults without diabetes: a dose-response meta-analysis",
        "authors": ["Ahmed R", "Bergström L", "Novak P"],
        "journal": "Lancet Diabetes Endocrinol", "year": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/37110993/",
        "abstract": "BACKGROUND: Glucagon-like peptide-1 receptor agonists (GLP-1 RAs) induce weight loss in people with type 2 diabetes, but their effects in adults without diabetes are less certain. METHODS: We performed a dose-response meta-analysis of 28 randomized trials (n=41,203). FINDINGS: Each 1 mg increment of semaglutide was associated with a mean weight reduction of 2.1 kg. INTERPRETATION: GLP-1 RAs produce clinically meaningful weight loss in adults without diabetes, with gastrointestinal events as the main limitation.",
        "saved_at": "2026-09-28 15:02",
    },
    {
        "pmid": "36533012", "title": "Intensive versus moderate statin therapy in adults aged 75 years or older: a randomized trial",
        "authors": ["Rossi G", "Petrov D", "Meyer K", "Dubois A"],
        "journal": "JAMA Cardiol", "year": "2022", "url": "https://pubmed.ncbi.nlm.nih.gov/36533012/",
        "abstract": "IMPORTANCE: Older adults are underrepresented in statin trials. OBJECTIVE: To compare intensive and moderate statin therapy in patients aged 75 years or older after acute coronary syndrome. RESULTS: The primary composite endpoint occurred in 14.2% versus 16.8% (hazard ratio 0.84, 95% CI 0.72-0.98). Adverse events including myopathy were more frequent with intensive therapy. CONCLUSIONS AND RELEVANCE: Intensive statin therapy provided a modest benefit with increased adverse events in this population.",
        "saved_at": "2026-09-29 09:20",
    },
    {
        "pmid": "36251290", "title": "Aspirin for primary prevention of cardiovascular disease in older adults: a randomized trial",
        "authors": ["McAllister J", "Huang W", "Okafor N", "Lindqvist E", "Tanaka H"],
        "journal": "N Engl J Med", "year": "2022", "url": "https://pubmed.ncbi.nlm.nih.gov/36251290/",
        "abstract": "BACKGROUND: Aspirin is widely used for secondary prevention, but its role in primary prevention among older adults is uncertain. METHODS: 19,114 community-dwelling adults aged 70 years or older were randomly assigned to aspirin or placebo. RESULTS: Cardiovascular disease occurred in 448 participants in the aspirin group and 474 in the placebo group (hazard ratio 0.95, 95% CI 0.83-1.08). Major hemorrhage was significantly more common with aspirin (3.8% vs 2.7%). CONCLUSIONS: Aspirin did not significantly reduce cardiovascular events and increased bleeding.",
        "saved_at": "2026-09-29 09:44",
    },
    {
        "pmid": "36999211", "title": "Colchicine after myocardial infarction: a systematic review and meta-analysis of randomized trials",
        "authors": ["Berghe V", "Silva M", "Kaur R"],
        "journal": "Eur Heart J", "year": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/36999211/",
        "abstract": "BACKGROUND: Inflammation contributes to recurrent events after myocardial infarction. METHODS: We pooled 7 randomized trials of colchicine versus placebo after myocardial infarction (n=12,678). RESULTS: Colchicine reduced the composite of cardiovascular death, myocardial infarction, or stroke (risk ratio 0.71, 95% CI 0.60-0.84). Gastrointestinal intolerance was the most frequent reason for discontinuation. CONCLUSIONS: Colchicine reduces recurrent cardiovascular events with an acceptable safety profile.",
        "saved_at": "2026-09-30 10:05",
    },
    {
        "pmid": "37044517", "title": "Direct oral anticoagulants versus warfarin in patients with atrial fibrillation and valvular heart disease",
        "authors": ["Zhang L", "Andersen K", "Yamamoto R", "Ibrahim S"],
        "journal": "Circulation", "year": "2023", "url": "https://pubmed.ncbi.nlm.nih.gov/37044517/",
        "abstract": "BACKGROUND: The efficacy of direct oral anticoagulants (DOACs) in patients with atrial fibrillation and valvular heart disease is incompletely defined. METHODS: In this retrospective cohort of 62,330 patients, DOAC users were compared with warfarin users using propensity-score matching. RESULTS: DOAC use was associated with lower risks of ischemic stroke (hazard ratio 0.79) and intracranial hemorrhage (hazard ratio 0.63). CONCLUSIONS: DOACs appear safe and effective in this population, except for mechanical valves.",
        "saved_at": "2026-09-30 10:31",
    },
]

FOLDERS = [
    {"id": "f1a2b3c4", "name": "糖尿病心血管获益", "created_at": "2026-09-28 14:10"},
    {"id": "f5d6e7f8", "name": "心衰新药", "created_at": "2026-09-28 14:29"},
    {"id": "f9a8b7c6", "name": "一级预防与老年人群", "created_at": "2026-09-29 09:18"},
]

META = {
    "37721856": {"folder": "f1a2b3c4", "tags": ["RCT", "二甲双胍", "MACE"],
                 "note": "本组唯一一项以 MACE 为主要终点的 RCT，样本量 4812、随访 4.2 年。\n纳入：随机化充分、终点由盲法委员会裁定。",
                 "note_updated": "2026-09-28 14:20"},
    "36872141": {"folder": "f5d6e7f8", "tags": ["Meta分析", "SGLT2", "HFpEF"],
                 "note": "13 项 RCT 合并，异质性可接受。注意纳入标准里 HFpEF 的 EF 阈值各研究不一致。",
                 "note_updated": "2026-09-28 14:35"},
    "37110993": {"folder": "f1a2b3c4", "tags": ["Meta分析", "GLP-1", "体重"],
                 "note": "剂量-反应模型；非糖尿病患者人群，与本文「糖心共病」主线相关性中等，暂列待定。",
                 "note_updated": "2026-09-28 15:10"},
    "36533012": {"folder": "f9a8b7c6", "tags": ["RCT", "老年人群", "他汀"],
                 "note": "75 岁以上人群，获益幅度小且肌病增加——写讨论时作为「强度需个体化」的关键证据。",
                 "note_updated": "2026-09-29 09:25"},
    "36251290": {"folder": "f9a8b7c6", "tags": ["RCT", "老年人群", "阿司匹林", "一级预防"],
                 "note": "阴性结果 + 出血增加，直接支撑「不再推荐老年人常规一级预防用阿司匹林」。",
                 "note_updated": "2026-09-29 09:50"},
    "36999211": {"folder": "f5d6e7f8", "tags": ["Meta分析", "抗炎", "秋水仙碱"],
                 "note": "待核查：是否与 COLCOT / LoDoCo2 有重叠人群（避免重复计数）。",
                 "note_updated": "2026-09-30 10:12"},
    "37044517": {"folder": "", "tags": ["观察性研究", "抗凝", "房颤"],
                 "note": "回顾性队列，非随机——按 GRADE 降级处理，仅作参考。",
                 "note_updated": "2026-09-30 10:38"},
}


def main():
    if os.path.isdir(DEST):
        shutil.rmtree(DEST, ignore_errors=True)
    os.makedirs(DEST, exist_ok=True)
    with open(os.path.join(DEST, "favorites.json"), "w", encoding="utf-8") as f:
        json.dump(ARTICLES, f, ensure_ascii=False, indent=2)
    with open(os.path.join(DEST, "library.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "folders": FOLDERS, "meta": META},
                  f, ensure_ascii=False, indent=2)
    print("已播种演示数据 ->", DEST)
    print(f"  收藏 {len(ARTICLES)} 篇 / 分组 {len(FOLDERS)} 个 / 有元数据的 {len(META)} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
