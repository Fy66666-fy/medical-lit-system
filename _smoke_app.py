"""app.py 冒烟测试（v2.8.2）

用 Streamlit 官方 AppTest 框架在无浏览器环境下真实执行 app.py 脚本，验证：
1. 首次进入的隐私同意门确实拦住了页面（未勾选时不应渲染业务内容）；
2. 勾选后主界面正常渲染，页脚免责声明与数据来源署名确实出现；
3. 运行日志真的落盘。
"""
import sys

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest  # noqa: E402

FOOTER_CHECKS = [
    "医疗免责声明",
    "不能作为临床诊断",
    "PubMed / PMC",
    "NLM",
    "隐私说明",
]


def _run() -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    if at.exception:
        print("❌ 脚本执行抛出异常：")
        for e in at.exception:
            print("  -", type(e.value).__name__, ":", e.value)
        raise SystemExit(1)
    return at


def main() -> int:
    ok = True

    # ---------- 1. 首次进入：同意门应拦住页面 ----------
    print("【1】首次进入（未同意隐私条款）")
    at = _run()
    print("✅ 脚本执行无异常")
    gate = [m.value for m in at.markdown if "使用前请先确认数据处理方式" in m.value]
    hit = bool(gate)
    ok = ok and hit
    print(f"  {'OK ' if hit else 'NG '} 首次进入出现隐私确认门")
    if hit:
        print(f"     提示文案：{gate[0].strip()[:60]}")
    blocked = not any("医疗免责声明" in m.value for m in at.markdown)
    ok = ok and blocked
    print(f"  {'OK ' if blocked else 'NG '} 未同意时不渲染业务内容（页脚被拦下）")

    # ---------- 2. 勾选同意后：主界面正常 ----------
    print("\n【2】勾选同意后")
    at = _run()
    boxes = at.checkbox
    target = None
    for b in boxes:
        if "数据处理方式" in (b.label or ""):
            target = b
            break
    if target is None:
        print("  NG  未找到隐私同意勾选框")
        return 1
    print(f"  OK   找到同意勾选框：{target.label}")
    target.check()
    at.run()
    if at.exception:
        print("  NG   勾选后脚本抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   勾选后脚本执行无异常")

    texts = [m.value for m in at.markdown]
    blob = "\n".join(texts)
    print(f"  INFO markdown 块数量：{len(texts)}")
    for k in FOOTER_CHECKS:
        h = k in blob
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} {k}")

    # 侧边栏诊断区位于 st.expander 内，AppTest 不收集 expander 标签与其中的
    # caption/code 元素，因此不做断言，仅打印可供人工核对的信息
    try:
        side = "\n".join(m.value for m in at.sidebar.markdown)
    except Exception:
        side = ""
    print(f"  INFO 侧边栏 markdown {len(side.splitlines())} 行；运行诊断区在 expander 内，AppTest 不收集，跳过断言")

    # ---------- 3. 日志落盘 ----------
    print("\n【3】运行日志")
    import os
    from datetime import datetime

    from core import logger

    log_file = os.path.join(logger.LOG_DIR, f"app_{datetime.now():%Y-%m-%d}.log")
    exists = os.path.exists(log_file)
    ok = ok and exists
    print(f"  {'OK ' if exists else 'NG '} 日志文件已生成 -> {log_file}")
    if exists:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        print(f"     日志行数：{len(lines)}")
        print(f"     末行：{lines[-1][:90] if lines else '(空)'}")

    print(f"\n{'全部通过' if ok else '存在失败项'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())