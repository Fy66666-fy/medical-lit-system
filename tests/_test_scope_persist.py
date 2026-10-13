"""自测：作用域令牌校验 + 「跨刷新保留」的数据搬迁（2026-10-13）。

为什么单独测这两件事——它们都在「用户数据会不会丢、会不会串」的关键路径上：

1. **令牌来自网址、又会被拼进目录名**，路径穿越的防线只有 `storage.is_valid_token` 这一道；
2. **`promote_scope` 决定开启保留时数据搬不搬、会不会覆盖既有数据**。规则写错，
   用户看到的是「我明明开了保留、收藏反而没了」，或「我另一个浏览器的文献库被冲掉了」。

离线运行，不联网、不依赖 Streamlit 运行时。全部落在临时数据目录，不碰真实 data/。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TMP = tempfile.mkdtemp(prefix="medlit_scope_")
os.environ["MEDLIT_DATA_DIR"] = _TMP   # 必须在导入 core.* 之前
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, ROOT)

from core import storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def main() -> int:
    # ---------------- 1. 令牌校验 ----------------
    # 这是唯一一道路径穿越防线：令牌合法才可能进目录名。
    print("\n[1] 令牌校验")
    for t in ["abcdefgh", "ABCD1234", "a-b_c-d_e", "x" * 32, "Ab3_-Zz9"]:
        check(f"接受合法令牌 {t[:12]!r}", storage.is_valid_token(t))
    for t in ["", "   ", "short", "a" * 33, "../etc", "a/../b", "a/b", "a\\b", "a:b",
              "a b", "tok en12", "中文中文中文", "a.b", "a;b", "a%2Fb", "a#b", "a?b"]:
        check(f"拒绝可疑令牌 {t[:12]!r}", not storage.is_valid_token(t))
    check("拒绝 None", not storage.is_valid_token(None))
    check("两侧空白被 strip 后判定（落库用的是 strip 后的值）",
          storage.is_valid_token("  abcdefgh  "))

    # ---------------- 2. 新令牌生成 ----------------
    print("\n[2] 新令牌生成")
    toks = [storage.new_token() for _ in range(20)]
    check("20 次生成互不重复", len(set(toks)) == 20)
    check("长度均为 12（URL 安全、不超长）", all(len(t) == 12 for t in toks), toks[0])
    check("全部通过自身校验", all(storage.is_valid_token(t) for t in toks))

    # ---------------- 3. 默认作用域 ----------------
    print("\n[3] 默认作用域")
    check("未注入时默认为 local（桌面版沿用旧路径，旧数据可读）",
          storage.current_scope() == "local", storage.current_scope())

    # ---------------- 4. 搬迁：把临时会话的数据带到持久作用域 ----------------
    print("\n[4] promote_scope 正常搬迁")
    storage.set_scope("s1234567890ab")
    storage.add_favorite({"pmid": "111", "title": "first"})
    storage.add_history("aspirin cardiovascular", 12)
    storage.save_last_search({"main": "aspirin"})
    src = os.path.join(_TMP, "users", "s1234567890ab")
    check("源作用域已写入收藏", os.path.exists(os.path.join(src, "favorites.json")))
    check("源作用域已写入历史", os.path.exists(os.path.join(src, "history.json")))

    tok = storage.new_token()
    moved = storage.promote_scope("u" + tok)
    dst = os.path.join(_TMP, "users", "u" + tok)
    check("搬动了已有文件的三个（没建的 library.json 不搬）",
          set(moved) == {"favorites.json", "history.json", "last_search.json"}, str(moved))
    check("目标作用域拿到收藏", os.path.exists(os.path.join(dst, "favorites.json")))
    check("源目录仍保留——只复制不删除",
          os.path.exists(os.path.join(src, "favorites.json")))
    with open(os.path.join(dst, "favorites.json"), encoding="utf-8") as fh:
        _fav = json.load(fh)
    check("内容逐字一致", _fav and _fav[0].get("pmid") == "111", str(_fav[:1]))

    # ---------------- 5. 绝不覆盖既有数据 ----------------
    print("\n[5] promote_scope 不覆盖")
    storage.set_scope("u" + tok)
    storage.remove_favorite("111")
    storage.add_favorite({"pmid": "999", "title": "persistent"})
    storage.set_scope("s1234567890ab")
    moved2 = storage.promote_scope("u" + tok)
    check("目标已有同名文件时再次搬迁返回空", moved2 == [], str(moved2))
    storage.set_scope("u" + tok)
    _favs = storage.list_favorites()
    check("目标数据未被临时会话的数据覆盖",
          len(_favs) == 1 and _favs[0].get("pmid") == "999", str([f.get("pmid") for f in _favs]))

    # ---------------- 6. 非法目标与桌面版 ----------------
    print("\n[6] 非法目标与桌面版")
    storage.set_scope("s1234567890ab")
    for bad in ["", "u", "x" + tok, "u" + "a" * 33, "u" + "a/b12345", "u../../../etc",
                "ua.b12345", "local"]:
        check(f"拒绝非法目标 {bad[:16]!r}", storage.promote_scope(bad) == [])
    check("作用域目录始终落在数据根目录内（穿越的最终防线）",
          os.path.abspath(storage.scoped_path("favorites.json")).startswith(os.path.abspath(_TMP)),
          storage.scoped_path("favorites.json"))

    storage.set_scope("local")
    check("桌面版（local）不搬迁：否则会把整库摊一份到 user 目录",
          storage.promote_scope("u" + storage.new_token()) == [])
    check("桌面版数据仍在原位", os.path.exists(os.path.join(_TMP, "favorites.json"))
          or storage.list_favorites() == [])

    # ---------------- 7. 端到端：?sid= 真的被 app.py 用上了 ----------------
    # 前面测的都是纯函数。规则写得再对，没接到 app.py 上也是白搭，所以这里跑真应用。
    print("\n[7] 端到端：?sid= 决定数据作用域")
    from streamlit.testing.v1 import AppTest  # 延迟导入：前面几节不依赖 Streamlit 运行时

    _app = os.path.join(ROOT, "app.py")

    def run_app(params=None):
        at = AppTest.from_file(_app)
        for k, v in (params or {}).items():
            at.query_params[k] = v
        at.run()
        return at

    tok2 = storage.new_token()
    at = run_app({"sid": tok2})
    check("带合法 sid 时作用域变成 u<令牌>",
          storage.current_scope() == "u" + tok2, storage.current_scope())
    check("应用无异常", len(at.exception) == 0, str(at.exception))
    _labels = [b.label for b in at.sidebar.button]
    check("侧边栏出现「关闭保留」按钮", any("关闭保留" in x for x in _labels))
    _caps = [c.value for c in at.sidebar.caption]
    check("侧边栏明确告知已开启跨刷新保留",
          any("已开启跨刷新保留" in c for c in _caps))
    # 这一条锁住的是"别再把它塞回折叠面板":原先作用域说明就在「运行诊断」里,多数人从未展开
    check("控件在折叠面板之外（否则用户根本找不到）",
          not any("保留" in b.label for b in at.expander[0].button),
          str([b.label for b in at.expander[0].button]))

    for bad in ["../../etc", "short", "a b c d e", "a.b.c.d.e"]:
        at_bad = run_app({"sid": bad})
        check(f"非法 sid {bad!r} 不生效，回落到会话作用域",
              not storage.current_scope().startswith("u"), storage.current_scope())
        check(f"非法 sid {bad!r} 时显示的是「开启」按钮",
              any("开启跨刷新保留" in b.label for b in at_bad.sidebar.button))
        check(f"非法 sid {bad!r} 时应用仍无异常", len(at_bad.exception) == 0)

    at_none = run_app()
    check("完全不带 sid 时也不是持久作用域",
          not storage.current_scope().startswith("u"), storage.current_scope())

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
