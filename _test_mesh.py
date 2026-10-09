"""P3-C5 自测：MeSH 词表联动（core/mesh.py）+ MeSH 主题词解析（core/pubmed.py）。

覆盖：
- lookup 的**精确校验**策略：候选里挑出正确描述符、入口词命中、
  限定词（qualifier）被排除、无把握命中返回 None 而不是猜
- split_concepts 的最长匹配贪心切分（含停用词与未命中词）
- is_plain_keyword 对手写检索式（字段限定 / 布尔运算符 / 引号）的拒判
- expand_expression 的语法、括号正确性、入口词上限、超长保护
- 与 pubmed.build_query 组合后不破坏 AND / OR 优先级
- 缓存：同一词只查一次，第二次不再发起请求
- pubmed.fetch_articles 对 MeshHeadingList 的解析（MajorTopic / Qualifier 标记）
- 拼写建议改名兼容（mesh_suggest → spelling_suggest）

**全部离线**：`http.get` 被替换为按 URL 分发的桩函数，不发任何真实请求。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_mesh_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import mesh, pubmed  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


# --------------------------------------------------------------------------
# 桩：按 URL 分发的假 http.get（记录调用次数，用于验证缓存）
# --------------------------------------------------------------------------
CALLS = {"esearch": 0, "esummary": 0}


def _rec(uid, heading, entries, rtype="descriptor", scope="", trees=()):
    return {
        "ds_meshterms": [heading] + list(entries),
        "ds_recordtype": rtype,
        "ds_scopenote": scope,
        "ds_idxlinks": [{"treenum": t} for t in trees],
    }


IDS = {
    # 关键点：首条是干扰项——db=mesh 的 esearch 是模糊检索，
    # 搜 "aspirin" 首条返回的其实是 "Asthma, Aspirin-Induced"
    "aspirin": ["D1", "D2", "D3"],
    "heart attack": ["D10"],
    "lung cancer": ["D20"],
    "immunotherapy": ["D30"],
    "prevention": ["Q1"],          # 只有限定词
    "pembrolizumab": ["S1"],       # 补充概念记录
    "zzz": [],
}
RECS = {
    "D1": _rec("D1", "Asthma, Aspirin-Induced", ["Asthma, Aspirin Induced"],
               trees=["C08.127.108.054"]),
    "D2": _rec("D2", "Aspirin",
               ["Acetylsalicylic Acid", "2-Acetoxybenzoic Acid", "Aspirin, Aluminum"],
               scope="The prototypical analgesic used in the treatment of mild to moderate pain.",
               trees=["D02.455.426.559.389.657.410.595.176", "D02.455.426.559.389.657.410.595"]),
    "D3": _rec("D3", "Sodium Salicylate", ["Salicylate, Sodium"], trees=["D02.241.223"]),
    "D10": _rec("D10", "Myocardial Infarction",
                ["Heart Attack", "Heart Attacks", "Myocardial Infarct",
                 "Infarction, Myocardial"],
                trees=["C14.280.647.500"]),
    "D20": _rec("D20", "Lung Neoplasms",
                ["Lung Cancer", "Cancer of the Lung", "Pulmonary Neoplasms",
                 "Cancer, Pulmonary", "Neoplasms, Lung", "Lung Neoplasm",
                 "Pulmonary Cancer", "Neoplasm, Lung", "Cancer of Lung"],
                trees=["C04.588.894.797.520", "C08.381.540"]),
    "D30": _rec("D30", "Immunotherapy",
                ["Immunotherapies", "Therapy, Immunologic"],
                trees=["E02.095.465.425"]),
    "Q1": _rec("Q1", "prevention  and  control", ["Prevention"], rtype="qualifier",
               trees=["Y11.040"]),
    "S1": _rec("S1", "pembrolizumab",
               ["Pembrolizumab Biosimilar", "Keytruda"],
               rtype="supplemental-record", trees=["@215512"]),
}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _fake_get(url, **kw):
    params = kw.get("params") or {}
    if "esearch" in url:
        CALLS["esearch"] += 1
        term = (params.get("term") or "").strip()
        return _Resp({"esearchresult": {"idlist": IDS.get(term, [])}})
    if "esummary" in url:
        CALLS["esummary"] += 1
        ids = [i for i in (params.get("id") or "").split(",") if i]
        return _Resp({"result": {i: RECS[i] for i in ids if i in RECS}})
    raise AssertionError("测试桩收到了意外的 URL：" + url)


mesh.http.get = _fake_get


# --------------------------------------------------------------------------
print("\n[1] lookup 的精确校验策略")
r = mesh.lookup("aspirin")
check("首条是干扰项时仍能挑出真正的描述符 Aspirin",
      bool(r) and r["heading"] == "Aspirin", str(r and r["heading"]))
check("命中方式记为标题精确匹配", bool(r) and r["matched_by"] == "heading",
      str(r and r["matched_by"]))
check("树号已带出", bool(r) and r["tree_numbers"][0].startswith("D02.455"),
      str(r and r["tree_numbers"][:1]))
check("定义（scope note）已带出", bool(r) and "analgesic" in r["scope_note"])

r = mesh.lookup("heart attack")
check("入口词命中：heart attack → Myocardial Infarction",
      bool(r) and r["heading"] == "Myocardial Infarction", str(r and r["heading"]))
check("命中方式记为命中入口词表", bool(r) and r["matched_by"] == "entry_term",
      str(r and r["matched_by"]))

r = mesh.lookup("lung cancer")
check("lung cancer → Lung Neoplasms（入口词）",
      bool(r) and r["heading"] == "Lung Neoplasms" and r["matched_by"] == "entry_term")

r = mesh.lookup("pembrolizumab")
check("补充概念记录（药物）保留",
      bool(r) and r["type"] == "supplemental-record" and r["heading"] == "pembrolizumab")
check("SCR 的 @ 占位树号被过滤掉",
      bool(r) and r["tree_numbers"] == [], str(r and r["tree_numbers"]))

check("限定词单独出现时不算命中（prevention → None）",
      mesh.lookup("prevention") is None)
check("词表里没有同名描述符时返回 None 而不是猜（zzz → None）",
      mesh.lookup("zzz") is None)
check("空串 / 单字符直接返回 None",
      mesh.lookup("") is None and mesh.lookup("a") is None)

# --------------------------------------------------------------------------
print("\n[2] is_plain_keyword：手写检索式不做改写")
for kw, want in [("immunotherapy lung cancer", True),
                 ("aspirin", True),
                 ("aspirin[tiab]", False),
                 ("aspirin[MeSH Terms]", False),
                 ("a AND b", False),
                 ("a OR b", False),
                 ('"heart attack"', False),
                 ("", False),
                 ("   ", False)]:
    check(f"is_plain_keyword({kw!r}) == {want}", mesh.is_plain_keyword(kw) is want)

check("含布尔运算符的关键词不触发任何查询",
      mesh.analyze("a AND b")["skipped"] is True)

# --------------------------------------------------------------------------
print("\n[3] split_concepts：最长匹配贪心切分")
cs = mesh.split_concepts("immunotherapy lung cancer")
check("切成 2 个概念（不是 3 个单词）", len(cs) == 2, str([c["text"] for c in cs]))
check("先取 2 词窗口 lung cancer",
      cs[1]["text"] == "lung cancer" and cs[0]["text"] == "immunotherapy",
      str([c["text"] for c in cs]))
check("两个概念都命中主题词", all(c["mesh"] for c in cs))

cs = mesh.split_concepts("heart attack prevention")
check("未命中的词单独成概念并保留原位",
      [c["text"] for c in cs] == ["heart attack", "prevention"],
      str([c["text"] for c in cs]))
check("prevention 概念没挂 MeSH（限定词不算命中）", cs[1]["mesh"] is None)

cs = mesh.split_concepts("aspirin the of in")
check("停用词被剔除", [c["text"] for c in cs] == ["aspirin"], str([c["text"] for c in cs]))
check("空关键词返回空列表", mesh.split_concepts("") == [])

# --------------------------------------------------------------------------
print("\n[4] expand_expression：检索式语法与保护")
expr = mesh.expand_expression("immunotherapy lung cancer")
check("含描述符的 [MeSH Terms] 限定", '"Immunotherapy"[MeSH Terms]' in expr)
check("含入口词的 [tiab] 限定", '"Immunotherapies"[tiab]' in expr)
check("概念之间用 AND 连接，且各概念整体加括号",
      ") AND (" in expr and expr.startswith("(") and expr.endswith(")"), expr[:60])
check("用户原话已被入口词覆盖时不重复追加（lung cancer ↔ Lung Cancer 同义）",
      '"Lung Cancer"[tiab]' in expr and '"lung cancer"[tiab]' not in expr)
check("未命中主题词的概念保持原样（无 MeSH 时不编造）",
      mesh.expand_expression("zzz") == "zzz")

# 入口词上限：D20 有 9 个入口词，应最多只取 _MAX_ENTRY_TERMS 个
one = mesh.lookup("lung cancer")
used = mesh._entry_terms_for(one)
check(f"入口词最多取 {mesh._MAX_ENTRY_TERMS} 个", len(used) == mesh._MAX_ENTRY_TERMS,
      f"{len(used)} 个：{used}")
check("入口词里不含与标题同义的重复项",
      all(mesh._key(t) != mesh._key(one["heading"]) for t in used))
check("并列入口词（Pulmonary Cancer / Cancer, Pulmonary）也能进检索式",
      '"Pulmonary Neoplasms"[tiab]' in expr)

# 超长保护：构造 20 个概念、每个 30 个长入口词，总长必然越界
def _big_record(i):
    return {
        "ui": "L%d" % i,
        "heading": "Heading %d" % i,
        "entry_terms": ["Heading %d" % i]
                       + ["Entry term number %d for padding purposes" % j for j in range(30)],
        "type": "descriptor", "mapped_to": "", "scope_note": "", "tree_numbers": [],
        "matched_by": "heading", "query": "concept-%d" % i,
    }


long_report = {"skipped": False, "matched": 20, "keyword": "a b",
               "concepts": [{"text": "concept-%d" % i, "mesh": _big_record(i)}
                            for i in range(20)]}
long_expr = mesh.expand_expression("a b", long_report)
check(f"超长时停止展开剩余概念（总长 <= {mesh._MAX_EXPR_LEN + 200}）",
      len(long_expr) <= mesh._MAX_EXPR_LEN + 200, f"{len(long_expr)} 字符")
check("被放弃展开的概念退回原词（不丢概念）", "concept-19" in long_expr)

# --------------------------------------------------------------------------
print("\n[5] 与 pubmed.build_query 组合：括号不能破坏 AND / OR 优先级")
q = pubmed.build_query(expr, "biomarker", "OR", author="Smith J")
check("组合后过滤条件仍被整体括起",
      q.startswith("((") and "AND Smith J[Author]" in q, q[:80])

# ---- 多个副关键词的组合逻辑（v3.7.1） ----
check("单副关键词 AND 组合",
      pubmed.build_query("kw", "biomarker", "AND") == "(kw) AND (biomarker)",
      pubmed.build_query("kw", "biomarker", "AND"))
check("多个副关键词 AND：主关键词与全部副关键词同时出现",
      pubmed.build_query("kw", "a, b", "AND") == "(kw) AND (a AND b)",
      pubmed.build_query("kw", "a, b", "AND"))
check("多个副关键词 OR：任一出现即可",
      pubmed.build_query("kw", "a, b", "OR") == "(kw) OR (a OR b)",
      pubmed.build_query("kw", "a, b", "OR"))
check("多个副关键词 NOT：含任一副关键词的全部排除",
      pubmed.build_query("kw", "a, b", "NOT") == "(kw) NOT (a OR b)",
      pubmed.build_query("kw", "a, b", "NOT"))
check("含空格的副关键词自动按精确短语加引号",
      pubmed.build_query("kw", "PD-1 biomarker", "AND") == '(kw) AND ("PD-1 biomarker")',
      pubmed.build_query("kw", "PD-1 biomarker", "AND"))
check("中英文逗号 / 分号均可作分隔符",
      pubmed.build_query("kw", "a，b；c, d", "OR") == "(kw) OR (a OR b OR c OR d)",
      pubmed.build_query("kw", "a，b；c, d", "OR"))
check("多副关键词 + 过滤条件：组合整体括起不被 AND 优先级吞掉",
      pubmed.build_query("kw", "a, b", "OR", author="Smith J").startswith("((kw) OR (a OR b))"),
      pubmed.build_query("kw", "a, b", "OR", author="Smith J"))
check("空副关键词不产生组合段",
      pubmed.build_query("kw", "  ", "AND") == "kw",
      pubmed.build_query("kw", "  ", "AND"))

# --------------------------------------------------------------------------
print("\n[6] 缓存：同一词第二次不再请求")
before = dict(CALLS)
mesh.lookup("aspirin")
mesh.lookup("aspirin")
check("缓存命中后不再发起 esearch / esummary",
      CALLS == before, f"前 {before} → 后 {CALLS}")

# --------------------------------------------------------------------------
print("\n[7] expand_markdown 导出")
md = mesh.expand_markdown(mesh.analyze("immunotherapy lung cancer"))
check("含标题与关键词", "# MeSH 概念分析" in md and "immunotherapy lung cancer" in md)
check("含概念命中情况", "命中" in md and "Immunotherapy" in md)
check("含扩展后检索式代码块", "## 扩展后的检索式" in md and "```" in md)
check("明确声明未增删官方词表", "未做任何增删" in md)
md2 = mesh.expand_markdown(mesh.analyze("aspirin[tiab]"))
check("手写检索式的报告说明「未做分析」", "未做分析" in md2)

# --------------------------------------------------------------------------
print("\n[8] pubmed.fetch_articles 解析 MeshHeadingList（离线，桩替 _ncbi_get）")
XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111</PMID>
      <Article>
        <ArticleTitle>A randomized trial of aspirin</ArticleTitle>
        <Journal><Title>Test J</Title>
          <JournalIssue><PubDate><Year>2020</Year></PubDate>
            <Volume>10</Volume><Issue>2</Issue></JournalIssue></Journal>
        <AuthorList><Author><LastName>Smith</LastName><Initials>J</Initials></Author></AuthorList>
        <Language>eng</Language>
        <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
        <Abstract><AbstractText Label="METHODS">We randomized 200 patients.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Aspirin reduced events.</AbstractText></Abstract>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D001241" MajorTopicYN="Y">Aspirin</DescriptorName>
          <QualifierName UI="Q000627" MajorTopicYN="N">therapeutic use</QualifierName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D006801" MajorTopicYN="N">Humans</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D002318" MajorTopicYN="N">Cardiovascular Diseases</DescriptorName>
          <QualifierName UI="Q000517" MajorTopicYN="Y">prevention &amp; control</QualifierName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData><ArticleIdList>
      <ArticleId IdType="doi">10.1/test</ArticleId>
    </ArticleIdList></PubmedData>
  </PubmedArticle>
  <PubmedBookArticle><BookDocument><PMID>222</PMID></BookDocument></PubmedBookArticle>
</PubmedArticleSet>
"""


class _XmlResp:
    content = XML.encode("utf-8")
    status_code = 200

    def raise_for_status(self):
        return None


import core.pubmed as _pm  # noqa: E402

_pm._ncbi_get = lambda *a, **kw: _XmlResp()
arts = _pm.fetch_articles(["111"])
check("返回 1 篇（书籍章节被跳过而不是混进结果）", len(arts) == 1, str(len(arts)))
a = arts[0]
check("MeSH 主题词数量正确（3 条）", len(a["mesh"]) == 3, str(len(a["mesh"])))
check("主要主题被单独列出", a["mesh_major"] == ["Aspirin"], str(a["mesh_major"]))
check("主题词带 MeSH UI", a["mesh"][0]["ui"] == "D001241")
check("副主题词被解析", [q["name"] for q in a["mesh"][0]["qualifiers"]] == ["therapeutic use"])
check("副主题词各自的 major 标记被保留",
      a["mesh"][2]["qualifiers"][0]["major"] is True)
check("副主题词的 major 与主题词的 major 相互独立",
      a["mesh"][2]["major"] is False and a["mesh"][2]["qualifiers"][0]["major"] is True)
check("未标 major 的主题词 major 为 False", a["mesh"][1]["major"] is False)
check("摘要分段与 MeSH 解析共存（v3.3.1 未回归）",
      a["abstract_sections"].get("CONCLUSIONS", "").startswith("Aspirin reduced"))

# --------------------------------------------------------------------------
print("\n[9] 旧名兼容")
check("spelling_suggest 与 mesh_suggest 指向同一实现",
      pubmed.mesh_suggest("x") == pubmed.spelling_suggest("x"))

# --------------------------------------------------------------------------
print("\n[10] review.mesh_topics：MeSH 主题词进综述对比表")
from core import review  # noqa: E402

A_MAJOR = {"mesh": [
    {"heading": "Lung Neoplasms", "major": True, "qualifiers": []},
    {"heading": "Immunotherapy", "major": True, "qualifiers": []},
    {"heading": "Humans", "major": False, "qualifiers": []},
]}
check("有主要主题时只列主要主题并加 ★",
      review.mesh_topics(A_MAJOR) == "★Lung Neoplasms、Immunotherapy",
      review.mesh_topics(A_MAJOR))
A_ONLY = {"mesh": [{"heading": "Humans", "major": False, "qualifiers": []},
                   {"heading": "Aged", "major": False, "qualifiers": []},
                   {"heading": "Female", "major": False, "qualifiers": []}]}
check("没有主要主题时退而列全文主题词并注明",
      review.mesh_topics(A_ONLY) == "Humans、Aged、Female（全文主题词）",
      review.mesh_topics(A_ONLY))
check("无 MeSH 时返回空串（不编造；新文献尚未标引是常态）",
      review.mesh_topics({}) == "" and review.mesh_topics({"mesh": []}) == "")
_many = {"mesh": [{"heading": "H%d" % i, "major": True, "qualifiers": []} for i in range(9)]}
check("主要主题过多时截断并给出总数", review.mesh_topics(_many).endswith("等 9 个"),
      review.mesh_topics(_many))
check("MeSH 主要主题已进入对比表列定义",
      "MeSH 主要主题" in review.COMPARISON_COLUMNS)
_rows = review.build_comparison([{"pmid": "1", "title": "T", "abstract": "", **A_MAJOR}])
check("对比表行已填充 MeSH 主要主题", _rows[0]["MeSH 主要主题"].startswith("★"))
check("对比表 Markdown 导出含该列",
      "MeSH 主要主题" in review.comparison_markdown(_rows))

# --------------------------------------------------------------------------
print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败清单：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
