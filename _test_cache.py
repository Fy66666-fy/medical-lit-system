"""缓存层自测：作用域无关性 / TTL / LRU / 大小条目 / 异常降级 / 接入点。

全部用临时数据目录，不污染真实 data/。
"""
import os
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="medlit_cache_t_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ.pop("MEDLIT_SCOPE", None)
os.environ.pop("MEDLIT_CACHE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import cache, storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def main() -> int:
    print("\n[1] 基本读写")
    k = cache.digest("hello world", "en|zh-CN")
    check("首次读为未命中", cache.get("trans", k) is None)
    check("写入成功", cache.put("trans", k, "你好世界") is True)
    check("命中且值正确", cache.get("trans", k) == "你好世界")
    check("不同键不串号", cache.get("trans", cache.digest("other")) is None)

    print("\n[2] digest 稳定性")
    check("同输入同键", cache.digest("a", "b") == cache.digest("a", "b"))
    check("不同输入不同键", cache.digest("a", "b") != cache.digest("a", "c"))
    check("分隔符防碰撞", cache.digest("ab", "c") != cache.digest("a", "bc"))

    print("\n[3] 全局共享（不按会话分片）")
    d_local = cache.cache_dir()
    storage.set_scope("s_another_session")
    d_other = cache.cache_dir()
    check("切换会话后缓存目录不变", d_local == d_other, d_other)
    check("跨会话可复用（省上游配额）", cache.get("trans", k) == "你好世界")
    storage.set_scope("local")

    print("\n[4] 过期 TTL")
    kt = cache.digest("ttl test")
    cache.put("llm", kt, "old")
    with cache._lock:
        cache._load_mem("llm")[kt]["t"] = time.time() - cache._ttl("llm") - 10
        cache._save_mem("llm")
    check("超期视为未命中", cache.get("llm", kt) is None)

    print("\n[5] LRU 淘汰")
    cache._mem["abs"] = {}
    cache._loaded.add("abs")
    limit = cache._limit("abs")
    base = time.time()
    for i in range(limit + 20):
        cache.put("abs", cache.digest("lru", i), i)
    n = len(cache._load_mem("abs"))
    check("条数不超上限", n <= limit, f"{n} ≤ {limit}")
    check("最新写入仍在", cache.get("abs", cache.digest("lru", limit + 19)) == limit + 19)
    check("最旧写入已被淘汰", cache.get("abs", cache.digest("lru", 0)) is None)
    check("淘汰计数有增加", cache.stats()["evicted"] >= 20, str(cache.stats()["evicted"]))

    print("\n[6] 大条目（一物一文件）")
    big = [{"t": f"Sec{i}", "text": "x" * 500} for i in range(200)]
    kb = cache.digest("PMC12345")
    check("写入大条目", cache.put("fulltext", kb, {"sections": big, "source": "PMC 开放全文"}))
    got = cache.get("fulltext", kb)
    check("大条目完整读回", got and len(got["sections"]) == 200)
    check("来源字段保留", got and got["source"] == "PMC 开放全文")
    files = os.listdir(os.path.join(cache.cache_dir(), "fulltext"))
    check("确实是一物一文件", f"{kb}.json" in files, str(files[:3]))
    cache._drop_file("fulltext", kb)

    print("\n[7] 异常降级（缓存坏了不能影响主流程）")
    bad = cache.digest("bad json")
    path = os.path.join(cache.cache_dir(), "fulltext", f"{bad}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    check("坏文件读作未命中而非抛异常", cache.get("fulltext", bad) is None)
    errs_before = cache.stats()["errors"]
    cache.put("fulltext", bad, {"sections": []})
    check("写入仍不抛异常", True)

    print("\n[8] 接入点")
    import core.summarizer as summarizer
    import core.pubmed as pubmed

    txt = ("Diabetes is common. This randomised trial of metformin showed HbA1c reduction of "
           "0.64% (95% CI 0.53-0.80; P<0.001). We enrolled 4001 adults. "
           "Conclusion: metformin reduced cardiovascular events.") * 3
    t0 = time.time()
    r1 = summarizer.extractive_summary(txt, title="Metformin")
    first = time.time() - t0
    t0 = time.time()
    r2 = summarizer.extractive_summary(txt, title="Metformin")
    second = time.time() - t0
    check("摘要缓存结果一致", r1["summary"] == r2["summary"])
    check("第二次明显更快", second < first, f"{first * 1000:.1f}ms → {second * 1000:.2f}ms")

    art = {"pmid": "99999999", "pmcid": "PMC9999999", "doi": "10.9999/test"}
    ck_ft = cache.digest("fulltext", art["pmid"], art["pmcid"], art["doi"])
    cache.put("fulltext", ck_ft, {"sections": [{"t": "Intro", "text": "cached body"}],
                                 "source": "PMC 开放全文"})
    secs, src = pubmed.fetch_fulltext_any(art)
    check("全文缓存拦截了真实抓取", len(secs) == 1 and secs[0]["text"] == "cached body", src)

    print("\n[9] 统计与清空")
    s = cache.stats()
    check("统计字段齐全", all(k in s for k in
                        ("hits", "misses", "puts", "evicted", "errors", "hit_rate", "sizes")))
    check("summary 可读", "命中率" in cache.format_summary(), cache.format_summary()[:56])
    cache.clear("trans")
    check("按类清空生效", cache.get("trans", k) is None)

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())