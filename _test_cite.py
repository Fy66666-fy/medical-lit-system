"""P3-C2 自测：引用格式导出（core/cite.py）。

覆盖六种格式的骨架正确性、字段缺失时的降级行为、姓名/年份/页码的边界处理、
BibTeX key 批内唯一性，以及元数据补全后的 `pubmed.fetch_articles` 新增字段。

全部离线，不访问任何外部接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_cite_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import cite  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 测试数据：一篇字段齐全的 RCT + 一篇只有最低限度字段的队列研究
# --------------------------------------------------------------------------
FULL = {
    "pmid": "32000000",
    "title": "Metformin & cardiovascular outcomes: a randomized trial",
    "journal": "The Lancet",
    "year": "2020 Jan-Feb",
    "authors": ["Smith JA", "van der Waals PB", "Lee M", "Chen X",
                "Kumar R", "Garcia S", "Muller T", "The ESPRIT Study Group"],
    "abstract": "BACKGROUND: Metformin is widely used.\nCONCLUSION: It reduced events.",
    "doi": "10.1016/S0140-6736(20)30001-1",
    "pmcid": "PMC7000000",
    "volume": "395",
    "issue": "10224",
    "pages": "123-130",
    "issn": "0140-6736",
    "pubtypes": ["Randomized Controlled Trial"],
    "language": "eng",
    "url": "https://pubmed.ncbi.nlm.nih.gov/32000000/",
}

THIN = {
    "pmid": "32000001",
    "title": "A cohort study of something",
    "journal": "BMJ",
    "year": "2019",
    "authors": ["Lee M"],
    "doi": "10.1136/bmj.l1234",
}

NO_META = {
    "pmid": "32000002",
    "title": "",
    "journal": "",
    "year": "",
    "authors": [],
}

# ==========================================================================
print("\n【1】格式注册表")
# ==========================================================================
check("六种格式", len(cite.FORMATS) == 6, str(cite.FORMAT_KEYS))
check("格式键完整",
      set(cite.FORMAT_KEYS) == {"bibtex", "ris", "endnote", "medline", "vancouver", "gbt7714"})
check("每种格式都有 label/ext/mime/hint",
      all(f.get("label") and f.get("ext") and f.get("mime") and f.get("hint")
          for f in cite.FORMATS))
check("label/extension/mime 查询可用",
      cite.label("bibtex") == "BibTeX" and cite.extension("ris") == "ris"
      and cite.mime("bibtex").startswith("application/x-"))
check("未知格式 label 回退原值", cite.label("nope") == "nope")

# ==========================================================================
print("\n【2】字段工具（姓名 / 年份 / 页码）")
# ==========================================================================
check("姓名拆分：普通", cite.split_name("Smith JA") == ("Smith", "JA", False))
check("姓名拆分：多段姓", cite.split_name("van der Waals PB") == ("van der Waals", "PB", False))
check("姓名拆分：单字母缩写", cite.split_name("Lee M") == ("Lee", "M", False))
check("姓名拆分：团体作者", cite.split_name("The ESPRIT Study Group")[2] is True)
check("姓名拆分：空串安全", cite.split_name("") == ("", "", False))
check("姓名拆分：None 安全", cite.split_name(None) == ("", "", False))

check("年份：MedlineDate 取四位", cite._year({"year": "2020 Jan-Feb"}) == "2020")
check("年份：纯数字", cite._year({"year": "2019"}) == "2019")
check("年份：缺失为空", cite._year({}) == "")

check("页码：双连字符归一", cite._pages({"pages": "123--130"}) == "123-130")
check("页码：单页", cite._split_pages("e12345") == ("e12345", ""))
check("页码：区间拆分", cite._split_pages("123-130") == ("123", "130"))

# ==========================================================================
print("\n【3】BibTeX")
# ==========================================================================
bib = cite.to_bibtex([FULL, THIN])
check("含 @article", bib.count("@article{") == 2)
check("key 含姓+年+关键词", "smith2020metformin" in bib, )
check("& 被转义", r"Metformin \& cardiovascular" in bib)
check("标题双层花括号保大小写", "title   = {{Metformin" in bib)
check("团体作者用花括号", "{The ESPRIT Study Group}" in bib)
check("多段姓保留", "van der Waals, PB" in bib)
check("year 取四位", "year    = {2020}" in bib)
check("volume/number/pages 齐全",
      "volume  = {395}" in bib and "number  = {10224}" in bib and "pages   = {123-130}" in bib)
check("PMID 写入 note", "note    = {PMID: 32000000}" in bib)
check("缺卷期的条目不留空字段",
      "@article{lee2019cohort," in bib and "volume" not in bib.split("@article{lee2019cohort,")[1])
check("批内 key 唯一",
      len(set(__import__("re").findall(r"@article\{([^,]+),", bib))) == 2)

# key 冲突：同姓同年同关键词的两篇
k1 = {"title": "Metformin trial one", "year": "2020", "authors": ["Smith JA"]}
k2 = {"title": "Metformin trial two", "year": "2020", "authors": ["Smith JA"]}
keys = __import__("re").findall(r"@article\{([^,]+),", cite.to_bibtex([k1, k2]))
check("key 重名自动加后缀", len(set(keys)) == 2 and keys[0] + "a" == keys[1], str(keys))

# ==========================================================================
print("\n【4】RIS")
# ==========================================================================
ris = cite.to_ris([FULL, THIN])
check("两条记录", ris.count("TY  - JOUR") == 2 and ris.count("ER  - ") == 2)
check("TY 在首、ER 在末",
      ris.strip().startswith("TY  - JOUR") and ris.strip().endswith("ER  -"))
check("SP/EP 拆分", "SP  - 123" in ris and "EP  - 130" in ris)
check("AU 写成 姓, 缩写", "AU  - Smith, JA" in ris)
check("团体作者不拆缩写", "AU  - The ESPRIT Study Group" in ris)
check("PY/DO/AN/UR 齐全",
      "PY  - 2020" in ris and "DO  - 10.1016/" in ris
      and "AN  - 32000000" in ris and "UR  - https://pubmed" in ris)
check("缺页码的条目无 SP/EP",
      "SP  - " not in ris.split("TY  - JOUR")[2])

# ==========================================================================
print("\n【5】EndNote / MEDLINE")
# ==========================================================================
enw = cite.to_endnote([FULL, THIN])
check("EndNote 头 %0", enw.count("%0 Journal Article") == 2)
check("EndNote %A 数量 = 作者数", enw.count("%A Smith, JA") == 1 and "%A Lee, M" in enw)
check("EndNote 字段齐全",
      all(t in enw for t in ("%T ", "%J The Lancet", "%D 2020", "%V 395", "%N 10224",
                             "%P 123-130", "%R 10.1016/", "%M 32000000")))
check("EndNote 缺卷期则不写 %V", "%V" not in enw.split("%0 Journal Article")[2])

med = cite.to_medline([FULL, THIN])
check("MEDLINE PMID- 开头", med.startswith("PMID- 32000000"))
check("MEDLINE 两条记录", med.count("PMID- ") == 2)
check("MEDLINE 作者格式", "AU  - Smith JA" in med)
check("MEDLINE 摘要逐行 AB", "AB  - BACKGROUND: Metformin is widely used." in med)
check("MEDLINE LID/AID 双写",
      "LID - 10.1016/S0140-6736(20)30001-1 [doi]" in med
      and "AID - 10.1016/S0140-6736(20)30001-1 [doi]" in med)
check("MEDLINE PMC 编号", "AID - PMC7000000 [pmc]" in med)
check("MEDLINE PT 文献类型", "PT  - Randomized Controlled Trial" in med)

# ==========================================================================
print("\n【6】Vancouver / GB/T 7714")
# ==========================================================================
van = cite.to_vancouver([FULL, THIN])
check("Vancouver 编号", van.startswith("1. Smith JA") and "\n2. Lee M." in van)
check("Vancouver 超 6 作者用 et al", "et al" in van)
check("Vancouver 卷期页", "2020;395(10224):123-130" in van)
check("Vancouver doi/PMID", "doi:10.1016/S0140-6736(20)30001-1." in van and "PMID: 32000000." in van)
check("Vancouver 缺卷期只给年份", ". BMJ. 2019." in van)

gbt = cite.to_gbt7714([FULL, THIN])
check("GB/T 编号用方括号", gbt.startswith("[1] "))
check("GB/T 类型标识 [J]", "[J]." in gbt)
check("GB/T 姓全大写", "SMITH J A" in gbt and "LEE M." in gbt)
check("GB/T 第一卷期页", "The Lancet, 2020, 395(10224): 123-130." in gbt)
check("GB/T 超 3 作者 et al", "et al" in gbt)

# ==========================================================================
print("\n【7】统一入口与边界")
# ==========================================================================
check("render 逐格式可用",
      all(cite.render([FULL], f).strip() for f in cite.FORMAT_KEYS))
check("render 空列表返回空串", all(cite.render([], f) == "" for f in cite.FORMAT_KEYS))
try:
    cite.render([FULL], "nope")
    check("render 未知格式抛错", False)
except ValueError:
    check("render 未知格式抛错", True)

check("filename 带篇数与扩展名",
      cite.filename([FULL, THIN], "bibtex", "20261008") == "参考文献_2篇_20261008.bib")
check("filename ris 扩展名", cite.filename([FULL], "ris", "20261008").endswith(".ris"))
check("preview 单篇不带尾换行", not cite.preview(FULL, "ris").endswith("\n"))

check("completeness 全字段为空", cite.completeness(FULL) == [])
check("completeness 检出缺失",
      set(cite.completeness(NO_META)) == {"作者", "标题", "期刊", "年份"})
check("completeness 不把卷期页当缺陷", "卷" not in "".join(cite.completeness(THIN)))

# 极端输入不应崩
try:
    for f in cite.FORMAT_KEYS:
        cite.render([NO_META], f)
    check("空元数据记录六种格式均不崩", True)
except Exception as e:                                   # pragma: no cover
    check("空元数据记录六种格式均不崩", False, repr(e))

# ==========================================================================
print("\n【8】元数据抽取（pubmed 侧新增字段）+ ZIP 集成")
# ==========================================================================
try:
    import inspect

    from core import pubmed
    src = inspect.getsource(pubmed.fetch_articles)
    check("fetch_articles 抽取 volume", '"volume"' in src)
    check("fetch_articles 抽取 issue/pages", '"issue"' in src and '"pages"' in src)
    check("fetch_articles 抽取 issn/pubtypes/language",
          '"issn"' in src and '"pubtypes"' in src and '"language"' in src)
    check("fetch_articles 保留团体作者", "CollectiveName" in src)
except Exception as e:                                   # pragma: no cover
    check("pubmed 抽取逻辑检查", False, repr(e))

try:
    import re as _re
    app_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"),
                   encoding="utf-8").read()
    check("ZIP 内含 .bib", "_rv_zip" in app_src and '参考文献_{stamp}.bib' in app_src)
    check("ZIP 内含 .ris", '参考文献_{stamp}.ris' in app_src)
    check("检索结果页有引用导出", 'cite_export_block(results, "search"' in app_src)
    check("收藏页有引用导出", 'cite_export_block(\n            favs, "favs' in app_src
          or 'cite_export_block(favs' in app_src or '"favs", expanded=True' in app_src)
    check("综述页有引用导出", 'cite_export_block(\n            selected, "rv"' in app_src
          or '"rv",\n' in app_src)
    check("app.py 已导入 cite", _re.search(r"from core import \([^)]*\bcite\b", app_src) is not None)
except Exception as e:                                   # pragma: no cover
    check("app.py 集成检查", False, repr(e))

# ==========================================================================
print("\n" + "=" * 60)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
sys.exit(1 if FAIL else 0)
