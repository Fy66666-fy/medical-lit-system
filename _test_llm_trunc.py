"""LLM 请求层的额度自愈测试（离线，桩替网络）。

对应 v3.8.2 修的两个缺陷：

1. **正文被截断却当正常结果返回**——推理模型（deepseek-flash 等）的思考 token
   也计入 max_tokens，额度大半被思考吃掉后正文只写了半句，响应里
   ``finish_reason == "length"``。旧逻辑只判"正文是否为空"，于是这半句话被当作
   成功结果返回，用户看到的就是"叙述段只输出一句话"。
2. **缓存键不含 max_tokens**——改了额度也刷不掉那条被截断的旧结果；
   且截断结果本身还写进了缓存，反复点击命中的永远是同一句。

用假响应把五种情形逐个锁死：正常 / 截断后加大额度重试成功 / 重试仍截断 /
正文为空（思考耗尽额度）/ 加大额度被上游拒绝。全部离线，不访问任何接口。
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_llm_trunc_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import summarizer  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


class _Resp:
    """最小可用的 requests.Response 替身。"""

    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._p


def _resp(text: str = "正文完整", finish: str = "stop") -> dict:
    """构造一个 OpenAI 兼容响应；带 reasoning_content 模拟推理模型。"""
    return {"choices": [{"message": {"content": text, "reasoning_content": "（思考过程）"},
                         "finish_reason": finish}]}


_calls: list[dict] = []
_seq: list = []
_orig_post = summarizer.http.post
_orig_get_json = summarizer.http.get_json


def _fake_post(url: str, **kw):
    _calls.append({"url": url, **kw})
    if not _seq:
        return _Resp(_resp())
    item = _seq.pop(0)
    if isinstance(item, Exception):
        raise item
    return _Resp(item)


def _set(seq) -> None:
    _calls.clear()
    _seq[:] = list(seq)


summarizer.http.post = _fake_post  # type: ignore[assignment]

_HDR = {"Authorization": "Bearer sk-test", "Content-Type": "application/json"}
_URL = "https://api.example.com/v1/chat/completions"


def _call(max_tokens=6000):
    return summarizer._chat_post_ex(_URL, {"model": "m", "max_tokens": max_tokens}, _HDR, timeout=5)


try:
    # 缓存命中与额度自愈两条路径都会写日志；summarizer 曾漏导入 logger，
    # 导致"缓存命中"这条日常路径直接 NameError。这里把它钉死。
    check("[前置] summarizer 已导入 logger（缓存命中 / 重试都要留痕）",
          hasattr(summarizer, "logger") and summarizer.logger is not None)

    print("[1] 正常结束（finish_reason=stop）")
    _set([_resp("完整正文", "stop")])
    text, trunc = _call(6000)
    check("返回正文", text == "完整正文", repr(text))
    check("未标记截断", trunc is False)
    check("只请求一次（不无谓重试）", len(_calls) == 1, f"{len(_calls)} 次")
    check("首次即用调用方给的额度", _calls[0]["json"]["max_tokens"] == 6000)

    print("\n[2] 正文被截断 → 加大额度重试成功")
    _set([_resp("Results: The included evidence", "length"), _resp("完整两段正文", "stop")])
    text, trunc = _call(6000)
    check("拿到重试后的完整正文", text == "完整两段正文", repr(text))
    check("未标记截断", trunc is False)
    check("确实重试了一次", len(_calls) == 2, f"{len(_calls)} 次")
    check("重试额度加大到 16000",
          _calls[1]["json"]["max_tokens"] == summarizer._LLM_RETRY_TOKENS,
          str(_calls[1]["json"]["max_tokens"]))
    check("截断的正文没有被当成结果返回", text != "Results: The included evidence")

    print("\n[3] 两次都被截断 → 如实返回并标记截断")
    _set([_resp("半句话A", "length"), _resp("半句话B", "length")])
    text, trunc = _call(6000)
    check("返回正文而不是抛异常（不白花已花的额度）", bool(text), repr(text))
    check("明确标记为截断", trunc is True)
    check("两次调用都用上了", len(_calls) == 2)

    print("\n[4] 正文为空（思考把额度耗尽）→ 重试后仍空则抛可操作错误")
    _set([_resp("", "length"), _resp("", "length")])
    try:
        _call(2400)
        check("应当抛 RuntimeError", False, "没有抛异常")
    except RuntimeError as e:
        check("抛出 RuntimeError", True)
        check("错误信息指向思考额度而非网络", "思考" in str(e), str(e)[:40])
        check("错误信息给出可操作建议", "非推理模型" in str(e) or "分批" in str(e))

    print("\n[5] 加大额度的重试被上游拒绝 → 保住已有正文，不把可用结果变报错")
    _set([_resp("第一次的正文", "length"), RuntimeError("max_tokens 超出模型上限")])
    try:
        text, trunc = _call(6000)
        check("没有因重试失败而抛异常", True)
        check("沿用第一次拿到的正文", text == "第一次的正文", repr(text))
        check("标记为截断（提示用户结果可能不完整）", trunc is True)
    except Exception as e:  # noqa: BLE001
        check("没有因重试失败而抛异常", False, f"{type(e).__name__}: {e}")

    print("\n[6] 调用方不传额度时不构造 max_tokens")
    _set([_resp("ok", "stop")])
    summarizer._chat_post_ex(_URL, {"model": "m"}, _HDR, timeout=5)
    check("payload 里没有 max_tokens 键", "max_tokens" not in _calls[0]["json"])

    print("\n[7] llm_chat：截断结果不入缓存（反复点击会真的重新请求）")
    _set([_resp("半句1", "length"), _resp("半句2", "length"),
          _resp("半句3", "length"), _resp("半句4", "length")])
    summarizer.llm_chat("sys", "同一段用户输入-截断", "https://api.example.com", "k", "m",
                        cache_task="t", max_tokens=6000)
    summarizer.llm_chat("sys", "同一段用户输入-截断", "https://api.example.com", "k", "m",
                        cache_task="t", max_tokens=6000)
    check("两次调用共发出 4 次请求（第二次没有命中缓存）", len(_calls) == 4, f"{len(_calls)} 次")

    print("\n[8] llm_chat：完整结果会入缓存（不重复计费）")
    _set([_resp("完整正文", "stop"), _resp("完整正文", "stop")])
    out1 = summarizer.llm_chat("sys", "同一段用户输入-完整", "https://api.example.com", "k", "m",
                               cache_task="t", max_tokens=6000)
    out2 = summarizer.llm_chat("sys", "同一段用户输入-完整", "https://api.example.com", "k", "m",
                               cache_task="t", max_tokens=6000)
    check("两次结果一致", out1 == out2 == "完整正文")
    check("第二次命中缓存（总请求数仍为 1）", len(_calls) == 1, f"{len(_calls)} 次")

    print("\n[9] llm_chat：缓存键带 max_tokens（改额度必须重新生成）")
    _set([_resp("额度六千", "stop"), _resp("额度三千", "stop")])
    a = summarizer.llm_chat("sys", "同一段用户输入-额度", "https://api.example.com", "k", "m",
                            cache_task="t", max_tokens=6000)
    b = summarizer.llm_chat("sys", "同一段用户输入-额度", "https://api.example.com", "k", "m",
                            cache_task="t", max_tokens=3000)
    check("换额度后没有命中旧缓存", len(_calls) == 2 and a == "额度六千" and b == "额度三千",
          f"{len(_calls)} 次 / {a!r} / {b!r}")

    print("\n[10] list_models：从 /v1/models 取真实模型名")
    _seen: dict = {}

    def _fake_get_json(url, **kw):
        _seen["url"] = url
        return {"data": [{"id": "vendor-b"}, {"id": "vendor-a"}, {"id": "vendor-a"}, {"nope": 1}]}

    summarizer.http.get_json = _fake_get_json  # type: ignore[assignment]
    try:
        models = summarizer.list_models("https://api.example.com/", "k")
        check("解析出去重排序后的模型名", models == ["vendor-a", "vendor-b"], str(models))
        check("自动补 /v1 前缀", _seen["url"] == "https://api.example.com/v1/models", _seen["url"])
    finally:
        summarizer.http.get_json = _orig_get_json  # type: ignore[assignment]

    print("\n[11] 叙述段的基线额度已抬高（旧的 2400/1400 在几十篇以上必截断）")
    from core import review  # noqa: PLC0415

    _cap: dict = {}
    _orig_chat = review.summarizer.llm_chat

    def _capture(system, user, api_base, api_key, model, cache_task="", max_tokens=None):
        _cap["mt"] = max_tokens
        return "【桩】"

    review.summarizer.llm_chat = _capture  # type: ignore[assignment]
    try:
        review.draft_with_llm("https://x", "k", "m", "t", [], [], style="rigorous", language="zh")
        mt_rig = _cap["mt"]
        review.draft_with_llm("https://x", "k", "m", "t", [], [], style="concise", language="zh")
        mt_con = _cap["mt"]
    finally:
        review.summarizer.llm_chat = _orig_chat  # type: ignore[assignment]
    check("严谨版基线为 6000", mt_rig == 6000, str(mt_rig))
    check("简明版基线为 3000", mt_con == 3000, str(mt_con))
    check("严谨 > 简明", mt_rig > mt_con)

finally:
    summarizer.http.post = _orig_post            # type: ignore[assignment]
    summarizer.http.get_json = _orig_get_json    # type: ignore[assignment]

print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    for name in FAIL:
        print("  [FAIL]", name)
    sys.exit(1)
print("全部通过")
