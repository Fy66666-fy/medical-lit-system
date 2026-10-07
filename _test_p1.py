"""P1 自测：会话级数据隔离 + 配额与成本开关 + 健康监控统计。

全部用临时数据目录，不污染真实 data/。
"""
import os
import sys
import tempfile
import time

_TMP = tempfile.mkdtemp(prefix="medlit_p1_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import health, quota, storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def main() -> int:
    # ---------------- 1. 会话级数据隔离 ----------------
    print("\n[1] 会话级数据隔离")
    storage.set_scope("local")
    storage.add_favorite({"pmid": "111", "title": "本地收藏"})
    storage.add_history("本地查询", 3)
    check("local 作用域写入成功", len(storage.list_favorites()) == 1)

    storage.set_scope("s_aaa")
    check("新会话看不到 local 的数据", storage.list_favorites() == [])
    check("新会话历史为空", storage.list_history() == [])
    storage.add_favorite({"pmid": "222", "title": "会话A收藏"})

    storage.set_scope("s_bbb")
    check("会话 B 看不到会话 A 的收藏", storage.list_favorites() == [])
    storage.add_favorite({"pmid": "333", "title": "会话B收藏"})

    storage.set_scope("s_aaa")
    favs = storage.list_favorites()
    check("回到会话 A 数据仍在", len(favs) == 1 and favs[0]["pmid"] == "222")

    storage.set_scope("local")
    check("local 数据未被污染", len(storage.list_favorites()) == 1)

    users_dir = os.path.join(_TMP, "users")
    check("分片目录按会话建立",
          os.path.isdir(os.path.join(users_dir, "s_aaa")) and os.path.isdir(os.path.join(users_dir, "s_bbb")))
    check("local 仍用旧路径（平滑升级）", os.path.exists(os.path.join(_TMP, "favorites.json")))
    check("current_scope 读取正确", storage.current_scope() == "local")

    # ---------------- 2. 配额：会话级 ----------------
    print("\n[2] 配额（会话级）")
    quota.reset_session("test_scope")
    quota._LIMITS["trans_chars"]["session"] = 1000
    quota._LIMITS["trans_chars"]["daily"] = 10 ** 9  # 排除每日上限干扰
    ok, _ = quota.consume("trans_chars", 600, scope="test_scope")
    check("额度内允许", ok)
    ok, msg = quota.consume("trans_chars", 600, scope="test_scope")
    check("超出会话上限被拦截", not ok, msg[:24])
    check("拦截原因被记录", quota.last_block().get("message") == msg)
    ok2, _ = quota.consume("trans_chars", 100, scope="test_scope")
    check("额度内的小额请求仍放行", ok2)
    check("remaining 计算正确", quota.remaining("trans_chars", "test_scope") == 300,
          str(quota.remaining("trans_chars", "test_scope")))

    # ---------------- 3. 配额：自带密钥免限 ----------------
    print("\n[3] 成本开关（自带密钥）")
    quota._LIMITS["llm_calls"]["session"] = 1
    ok, _ = quota.consume("llm_calls", 1, scope="test_scope", own_key=True)
    check("自带密钥时不受配额限制", ok)
    ok, _ = quota.consume("llm_calls", 1, scope="test_scope", own_key=True)
    check("自带密钥可继续调用", ok)
    ok, msg = quota.consume("llm_calls", 1, scope="test_scope", own_key=False)
    check("未带密钥受配额限制", not ok, msg[:20])
    check("自带密钥时 remaining 为 None（不限）", quota.remaining("llm_calls", "t", own_key=True) is None)

    # ---------------- 4. 配额：全局每日 ----------------
    print("\n[4] 配额（全局每日）")
    quota._LIMITS["trans_chars"]["session"] = 10 ** 9
    quota._LIMITS["trans_chars"]["daily"] = 500
    ok, msg = quota.consume("trans_chars", 600, scope="another_scope")
    check("超出每日上限被拦截", not ok, msg[:20])
    daily = quota.daily_usage()
    check("每日用量已落盘", os.path.exists(os.path.join(_TMP, "stats")))
    check("每日用量未被超额累加", daily.get("trans_chars", 0) < 10 ** 9)

    # ---------------- 5. 健康监控 ----------------
    print("\n[5] 健康监控")
    for _ in range(8):
        health.record("pubmed", True)
    for _ in range(2):
        health.record("pubmed", False)
    health.record("translate", True)
    health.record_error("测试异常")
    health.flush()
    s = health.summary(7)
    check("pubmed 成功率 80%", s["deps"]["pubmed"]["rate"] == 80.0,
          str(s["deps"]["pubmed"]))
    check("translate 成功率 100%", s["deps"]["translate"]["rate"] == 100.0)
    check("错误计数累加", s["errors"] >= 1, str(s["errors"]))
    check("无调用记录的依赖为 None", s["deps"]["unpaywall"]["rate"] is None)
    check("format_summary 可读", "pubmed" in health.format_summary(7), health.format_summary(7)[:60])

    # 缓冲：连续小写不应每次都落盘（只验证最终一致性）
    before = health.today()["deps"]["figures"]["ok"]
    for _ in range(30):
        health.record("figures", True)
    health.flush()
    after = health.today()["deps"]["figures"]["ok"]
    check("批量记录最终全部落盘", after - before == 30, f"{before} → {after}")

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
