"""P2 四项修复的离线测试。

对应四件事：

1. **P2-6 研究类型识别率可实测** —— ``design_report`` 给出识别率与未识别清单
   （附 PubMed 文献类型原值），``extract_profile`` 带出 ``pubtypes``。
2. **P2-7 叙述段分批生成** —— 篇数超阈值时 ``draft_with_llm`` 改走「各批并发写
   结果概述 → 统一写讨论」，``on_progress`` 报真实进度；≤阈值时与旧版逐字一致。
3. **P2-5 全文抓取并发** —— ``fetch_fulltext_many`` 并发抓取、单篇失败不阻断、
   进度回调真实。
4. **P2-4 摘要托底** 由既有 ``_test_fulltext_extract`` / ``_test_design_embed`` 锁定。

全部离线，桩替网络，不访问任何接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_p2_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import pubmed, review  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def _art(i: int, pubtypes=(), abstract="A total of 100 patients were randomly assigned."):
    return {"pmid": str(1000 + i), "title": f"Study {i}", "year": "2020",
            "abstract": abstract, "pubtypes": list(pubtypes)}


# ============================================================
print("=" * 78)
print("一、P2-6 研究类型识别率（design_report）")
print("=" * 78)

_arts = [
    _art(1, ["Randomized Controlled Trial"]),
    _art(2, ["Cohort Studies"]),
    _art(3, [], "We measured things."),            # 标题/摘要/类型均无线索 → 未识别
    _art(4, ["Comparative Study"], "We measured things."),  # 类型不足以判定 → 未识别
]
_rows = review.build_comparison(_arts)
_dr = review.design_report(_rows)
check("design_report 统计总数", _dr["total"] == 4, str(_dr["total"]))
check("design_report 识别数", _dr["recognized"] == 2, str(_dr["recognized"]))
check("design_report 未识别数", _dr["unrecognized"] == 2, str(_dr["unrecognized"]))
check("design_report 识别率 50%", abs(_dr["rate"] - 50.0) < 1e-6, str(_dr["rate"]))
check("未识别清单带 PubMed 文献类型原值",
      _dr["items"][1]["pubtypes"] == ["Comparative Study"], str(_dr["items"][1]["pubtypes"]))
check("未识别清单带标题", _dr["items"][0]["title"].startswith("Study 3"), _dr["items"][0]["title"])
check("空批次不炸、识别率 0", review.design_report([])["rate"] == 0.0)
check("extract_profile 带出 pubtypes",
      review.extract_profile(_art(9, ["Meta-Analysis"]))["pubtypes"] == ["Meta-Analysis"])

# ============================================================
print()
print("=" * 78)
print("二、P2-7 叙述段分批生成")
print("=" * 78)

check("分批阈值与批大小已定义",
      review.DRAFT_BATCH_THRESHOLD == 50 and review.DRAFT_BATCH_SIZE == 40,
      f"{review.DRAFT_BATCH_THRESHOLD}/{review.DRAFT_BATCH_SIZE}")
check("split_draft_batches 按 40 切 120 篇 → 3 批",
      [len(b) for b in review.split_draft_batches(list(range(120)))] == [40, 40, 40])
check("split_draft_batches 不丢尾批",
      [len(b) for b in review.split_draft_batches(list(range(51)))] == [40, 11])
check("_strip_leading_title 去掉英文标题",
      review._strip_leading_title("### Discussion\nD 段") == "D 段")
check("_strip_leading_title 去掉中文标题",
      review._strip_leading_title("结果概述\nR 段") == "R 段")
check("_strip_leading_title 不改正文", review._strip_leading_title("就是正文") == "就是正文")

_big = review.build_comparison(
    [_art(i, ["Randomized Controlled Trial"]) for i in range(120)])
_calls: list[str] = []
_orig_chat = review.summarizer.llm_chat


def _fake_chat(system, user, api_base, api_key, model, cache_task="", max_tokens=None):
    _calls.append(cache_task)
    if "综述讨论" in cache_task:
        return "D 段"
    return "结果概述\nR 段"   # 模拟模型自加小标题


review.summarizer.llm_chat = _fake_chat  # type: ignore[assignment]
try:
    _prog: list[tuple[int, int]] = []
    _out = review.draft_with_llm("u", "k", "m", "主题", _big, [], style="rigorous",
                                 language="zh", on_progress=lambda d, t: _prog.append((d, t)))
    _batch_calls = [c for c in _calls if c.startswith("综述叙述分批/")]
    _disc_calls = [c for c in _calls if c.startswith("综述讨论/")]
finally:
    review.summarizer.llm_chat = _orig_chat  # type: ignore[assignment]

check("分批路径发起 3 次结果概述请求", len(_batch_calls) == 3, str(len(_batch_calls)))
check("分批路径发起 1 次统一讨论请求", len(_disc_calls) == 1, str(len(_disc_calls)))
check("输出含「结果概述」与「讨论」两个标题",
      _out.count("结果概述") == 1 and "讨论\n\nD 段" in _out, _out[:60])
check("输出把各批结果拼接（3 段 R 段）", _out.count("R 段") == 3, str(_out.count("R 段")))
check("模型自加的小标题已被剥掉", "结果概述\nR 段" not in _out)
check("进度回调报真实步数（3 批 + 1 讨论 = 4）",
      bool(_prog) and max(d for d, _ in _prog) == 4 and _prog[-1] == (4, 4), str(_prog))
check("讨论请求在进度里也算一步", all(t == 4 for _, t in _prog), str(_prog))

# 阈值以内：与旧版逐字一致（单次、缓存键不变、额度不变）
_small = review.build_comparison([_art(i, ["Randomized Controlled Trial"]) for i in range(5)])
_calls2: list[tuple] = []
_orig2 = review.summarizer.llm_chat


def _fake2(system, user, api_base, api_key, model, cache_task="", max_tokens=None):
    _calls2.append((cache_task, max_tokens))
    return "【桩】结果概述\n\n【桩】讨论"


review.summarizer.llm_chat = _fake2  # type: ignore[assignment]
try:
    _out_small = review.draft_with_llm("u", "k", "m", "t", _small, [],
                                       style="rigorous", language="zh")
finally:
    review.summarizer.llm_chat = _orig2  # type: ignore[assignment]
check("≤阈值走单次生成（不产生分批请求）",
      len(_calls2) == 1 and _calls2[0][0] == "综述叙述/rigorous/zh", str(_calls2))
check("≤阈值严谨版额度仍为 6000", _calls2[0][1] == 6000, str(_calls2[0][1]))
check("≤阈值返回模型原始输出", _out_small == "【桩】结果概述\n\n【桩】讨论", _out_small)

# ============================================================
print()
print("=" * 78)
print("三、P2-5 全文抓取并发（fetch_fulltext_many）")
print("=" * 78)

_orig_fetch = pubmed.fetch_fulltext_any


def _fake_fetch(a):
    if a.get("pmid") == "bad":
        raise RuntimeError("该文献很可能受付费墙保护")
    return [{"title": "全文", "text": "正文" * 10}], "PMC 开放全文"


pubmed.fetch_fulltext_any = _fake_fetch  # type: ignore[assignment]
try:
    _arts2 = [{"pmid": "1"}, {"pmid": "2"}, {"pmid": "bad"}, {"pmid": "3"}]
    _prog2: list[tuple[int, int]] = []
    _res, _fails = pubmed.fetch_fulltext_many(
        _arts2, workers=3, on_progress=lambda d, t: _prog2.append((d, t)))
    # 单篇分支
    _prog1: list[tuple[int, int]] = []
    _res1, _fails1 = pubmed.fetch_fulltext_many(
        [{"pmid": "1"}], workers=3, on_progress=lambda d, t: _prog1.append((d, t)))
finally:
    pubmed.fetch_fulltext_any = _orig_fetch  # type: ignore[assignment]

check("并发抓取返回成功篇数", len(_res) == 3, str(len(_res)))
check("单篇失败进 fails 不阻断整批",
      len(_fails) == 1 and _fails[0][0]["pmid"] == "bad", str(_fails))
check("失败原因被保留", "付费墙" in _fails[0][1], _fails[0][1])
check("成功结果带来源标注",
      all(src == "PMC 开放全文" for _, _, src in _res), str(_res[:1]))
check("并发进度回调覆盖全部（总数 4）",
      sorted(d for d, _ in _prog2) == [1, 2, 3, 4] and all(t == 4 for _, t in _prog2),
      str(_prog2))
check("单篇分支进度为 (1,1)", _prog1 == [(1, 1)], str(_prog1))
check("单篇分支正常返回", len(_res1) == 1 and not _fails1)

print()
print("=" * 78)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 78)
if FAIL:
    for name in FAIL:
        print("  ✗ " + name)
    sys.exit(1)
print("✅ P2 四项（识别率 / 分批生成 / 并发抓取）自测全部通过")
