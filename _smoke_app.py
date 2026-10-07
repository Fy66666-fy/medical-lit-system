"""app.py 冒烟测试（v2.4.0）

用 Streamlit 官方 AppTest 框架在无浏览器环境下真实执行 app.py 脚本，
验证：脚本能跑通不抛异常、页脚免责声明与数据来源署名确实渲染出来。
"""
import sys

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest  # noqa: E402


def main() -> int:
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()

    if at.exception:
        print("❌ 脚本执行抛出异常：")
        for e in at.exception:
            print("  -", type(e.value).__name__, ":", e.value)
        return 1
    print("✅ 脚本执行无异常")

    texts = [m.value for m in at.markdown]
    blob = "\n".join(texts)
    print(f"markdown 块数量：{len(texts)}")

    checks = [
        # 页脚合规件套（st.markdown + unsafe_allow_html）
        "医疗免责声明",
        "不能作为临床诊断",
        "PubMed / PMC",
        "NLM",
        "隐私说明",
    ]
    ok = True
    for k in checks:
        hit = k in blob
        ok = ok and hit
        print(f"  {'OK ' if hit else 'NG '} {k}")

    # 侧边栏诊断区位于 st.expander 内，AppTest 不收集 expander 标签与其中的
    # caption/code 元素，因此不做断言，仅打印可供人工核对的信息
    side = ""
    try:
        side = "\n".join(m.value for m in getattr(at.sidebar, "markdown", []))
    except Exception:
        side = ""
    print(f"  INFO 侧边栏 markdown {len(side.splitlines())} 行；运行诊断区在 expander 内，AppTest 不收集，跳过断言")

    # 日志系统是否真的落盘
    import os
    from datetime import datetime

    from core import logger

    log_file = os.path.join(logger.LOG_DIR, f"app_{datetime.now():%Y-%m-%d}.log")
    exists = os.path.exists(log_file)
    print(f"  {'OK ' if exists else 'NG '} 日志文件已生成 -> {log_file}")
    if exists:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        print(f"     日志首行：{lines[0] if lines else '(空)'}")
        print(f"     日志行数：{len(lines)}")
    ok = ok and exists
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
