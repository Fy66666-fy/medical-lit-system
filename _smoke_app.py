"""app.py 冒烟测试（v3.0.1）

用 Streamlit 官方 AppTest 框架在无浏览器环境下真实执行 app.py 脚本，验证：
1. 首次进入的隐私同意门确实拦住了页面（未勾选时不应渲染业务内容）；
2. 勾选后主界面正常渲染，页脚免责声明与数据来源署名确实出现；
3. 运行日志真的落盘；
4. 「综述工作台」页面能真实渲染出对比表（v2.9.0 新增——这页曾因为少了一行
   路由分支而「点进去只有页脚、正文空白」，只有真跑一遍才测得出来）；
5. 「我的收藏」页的引用导出区能渲染出 6 种格式与 BibTeX 预览（v3.0.1 新增）。

写盘动作全部落在临时数据目录，不碰真实 data/。
"""
import os
import sys
import tempfile

os.environ["MEDLIT_DATA_DIR"] = tempfile.mkdtemp(prefix="medlit_smoke_")
os.environ["MEDLIT_SCOPE"] = "local"

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest  # noqa: E402

# 综述工作台渲染需要数据来源：本地作用域里放两篇合成文献（含矛盾结论）
DEMO_ARTICLES = [
    {
        "pmid": "9001",
        "title": "Drug X plus chemotherapy in advanced lung cancer: a randomized controlled trial",
        "journal": "J Test Oncol", "year": "2023", "authors": ["Alpha A"],
        "abstract": ("METHODS: In this randomized controlled trial, a total of 640 patients with "
                     "advanced lung cancer were randomly assigned to drug X plus chemotherapy or "
                     "chemotherapy alone.\nRESULTS: Drug X significantly improved overall survival "
                     "(HR 0.70, 95% CI 0.55-0.89, P=0.003). The primary outcome was overall survival.\n"
                     "CONCLUSIONS: Drug X significantly improved survival in advanced lung cancer."),
    },
    {
        "pmid": "9002",
        "title": "Drug X in elderly lung cancer patients: a cohort study",
        "journal": "J Test Oncol", "year": "2024", "authors": ["Beta B"],
        "abstract": ("METHODS: This retrospective cohort study included 900 elderly patients with "
                     "lung cancer treated with drug X plus chemotherapy.\nRESULTS: Drug X was "
                     "associated with an increased risk of death (HR 1.42, 95% CI 1.10-1.83, P=0.007). "
                     "The primary outcome was overall survival.\nCONCLUSIONS: Drug X plus chemotherapy "
                     "was associated with an increased risk of death in elderly patients."),
    },
]

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

    # ---------- 3. 综述工作台（v2.9.0） ----------
    print("\n【3】综述工作台")
    from core import storage

    storage.set_scope("local")
    for _a in DEMO_ARTICLES:
        storage.add_favorite(dict(_a))
    print(f"  INFO 已写入 {len(storage.list_favorites())} 篇演示文献（临时数据目录）")

    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "综述工作台"
    # 勾选框在 st.data_editor 里（AppTest 点不到），直接把"已勾选文献"塞进会话状态，
    # 走的是同一条数据通路：页面据此生成对比表与冲突分析。
    at.session_state["rv_picked"] = [a["pmid"] for a in DEMO_ARTICLES]
    at.run()
    if at.exception:
        print("  NG   综述工作台抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   综述工作台执行无异常")
    blob3 = "\n".join(m.value for m in at.markdown)
    for k in ("确定主题并勾选纳入文献", "纳入文献基本特征对比", "结论冲突核查",
              "证据与适用性核查", "向你的患者外推前，请逐维回答",
              "筛选记录（PRISMA 式）", "综述初稿骨架"):
        h = k in blob3
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现「{k}」")
    if "请至少勾选 1 篇文献" in blob3:
        ok = False
        print("  NG   页面停在「未勾选文献」的空态，说明勾选数据没有传进去")

    # ---------- 4. 引用导出（v3.0.1，P3-C2） ----------
    print("\n【4】我的收藏 · 引用导出")
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "我的收藏"
    at.run()
    if at.exception:
        print("  NG   我的收藏页抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   我的收藏页执行无异常")
    dl_labels = [b.label for b in at.download_button]
    hit_dl = any("下载 BibTeX" in (l or "") for l in dl_labels)
    ok = ok and hit_dl
    print(f"  {'OK ' if hit_dl else 'NG '} 出现 BibTeX 下载按钮（共 {len(dl_labels)} 个下载按钮）")
    fmt_opts = []
    for s in at.selectbox:
        if (s.label or "") == "导出格式":
            fmt_opts = list(s.options)
    hit_fmt = len(fmt_opts) == 6 and any("BibTeX" in o for o in fmt_opts) \
        and any("GB/T 7714" in o for o in fmt_opts)
    ok = ok and hit_fmt
    print(f"  {'OK ' if hit_fmt else 'NG '} 导出格式下拉含 6 种格式")
    code_txt = "\n".join(c.value for c in at.code)
    hit_code = "@article{" in code_txt
    ok = ok and hit_code
    print(f"  {'OK ' if hit_code else 'NG '} 预览区真实渲染出 BibTeX 条目")

    # ---------- 5. 日志落盘 ----------
    print("\n【5】运行日志")
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