"""app.py 冒烟测试（v3.1.0）

用 Streamlit 官方 AppTest 框架在无浏览器环境下真实执行 app.py 脚本，验证：
1. 首次进入的隐私同意门确实拦住了页面（未勾选时不应渲染业务内容）；
2. 勾选后主界面正常渲染，页脚免责声明与数据来源署名确实出现；
3. 运行日志真的落盘；
4. 「综述工作台」页面能真实渲染出对比表（v2.9.0 新增——这页曾因为少了一行
   路由分支而「点进去只有页脚、正文空白」，只有真跑一遍才测得出来）；
5. 「我的文献库」页能渲染出分组 / 标签 / 笔记的统计与「分组 · 标签 · 关键词」三档
   筛选控件，并让引用导出区输出 6 种格式与 BibTeX 预览；同时**用旧页面名
   「我的收藏」进入**，验证 v3.1.0 改名后历史深链与书签没有变成死链；
   并断言卡片里的「分组」下拉回显的是**已存分组**——这条曾有个静默数据丢失：
   首次渲染时控件状态为 None 被一律归零成「未分组」，覆盖掉真实分组，
   用户不改下拉直接保存就把分组清空了（v3.1.1 修）。
   （v3.0.1 引入引用导出区，v3.1.0 由「我的收藏」升级为「我的文献库」。）
5. 「PDF 全文分析」页能真实渲染：出现页面标题、资源上限提示与**版权与合规确认门**；
   未勾选时不给上传，勾选后开放上传（v3.2.0 新增，P3-C3）。
   注：AppTest 无法给 st.file_uploader 注入文件，因此「解析结果渲染」这一层由
   `_test_pdfdoc.py`（99 条断言，含下游对接）承担，本冒烟只保证路由与上传门不坏
   ——这页曾因为少一行路由分支就「点进去只有页脚」，值得单独断言。

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
              # P3-C4：结构化评价工具与 GRADE 自查入口
              "结构化评价工具（按研究设计自动匹配）", "GRADE 证据分级自查入口",
              "判定方式", "降级因素", "升级因素",
              "筛选记录（PRISMA 式）", "综述初稿骨架"):
        h = k in blob3
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现「{k}」")
    if "请至少勾选 1 篇文献" in blob3:
        ok = False
        print("  NG   页面停在「未勾选文献」的空态，说明勾选数据没有传进去")
    # 演示数据里有 RCT 与队列研究，应分别匹配到 RoB 2 与 NOS（队列）
    for tool in ("RoB 2", "NOS（队列）"):
        h = tool in blob3
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 演示数据匹配到工具「{tool}」")
    _dl = [d.label or "" for d in at.download_button]
    for lbl in ("结构化评价自查清单", "GRADE 分级自查表"):
        h = any(lbl in x for x in _dl)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现导出按钮「{lbl}」")

    # ---------- 4. 我的文献库（v3.1.0，P3-C1）+ 引用导出（v3.0.1，P3-C2） ----------
    print("\n【4】我的文献库 · 分组 / 标签 / 笔记 + 引用导出")
    from core import library

    ok_f, fmsg, folder = library.add_folder("综述选题 A")
    if not ok_f:
        print(f"  NG   建分组失败：{fmsg}")
        return 1
    library.set_folder(DEMO_ARTICLES[0]["pmid"], folder["id"])
    library.set_tags(DEMO_ARTICLES[0]["pmid"], ["RCT", "肺癌"])
    library.set_note(DEMO_ARTICLES[0]["pmid"], "主要证据来源，样本量 640")
    library.set_tags(DEMO_ARTICLES[1]["pmid"], ["队列", "老年"])
    print(f"  INFO 已建分组「{folder['name']}」并标注 {len(DEMO_ARTICLES)} 篇文献")

    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    # 故意用**旧页面名**进入：v3.1.0 把「我的收藏」升级为「我的文献库」，
    # 侧边栏显示新名，但已发出的深链（?page=我的收藏）与用户书签必须仍可用。
    at.session_state["pending_page"] = "我的收藏"
    at.run()
    if at.exception:
        print("  NG   文献库页抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   文献库页执行无异常（经旧名 pending_page 进入，验证改名兼容）")

    blob4 = "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])
    for k in ("⭐ 我的文献库", "文献列表", "已写笔记", "共收藏 2 篇"):
        h = k in blob4
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现「{k}」")

    sel_labels = [s.label or "" for s in at.selectbox]
    multi_labels = [m.label or "" for m in at.multiselect]
    txt_labels = [t.label or "" for t in at.text_input]
    for label, bucket, what in (("分组", sel_labels, "分组筛选"),
                                ("标签（含全部所选）", multi_labels, "标签筛选"),
                                ("关键词", txt_labels, "关键词筛选")):
        h = label in bucket
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现{what}控件「{label}」")

    dl_labels = [b.label for b in at.download_button]
    hit_md = any("导出筛选结果" in (l or "") for l in dl_labels)
    ok = ok and hit_md
    print(f"  {'OK ' if hit_md else 'NG '} 出现「导出筛选结果 (Markdown)」按钮")
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

    # 卡片编辑区的初值必须是**已存的分组**，而不是「未分组」。
    # 曾经这里有个静默数据丢失：首次渲染时 widget 状态为 None，被一律归零成未分组，
    # 覆盖掉 index= 传入的真实分组 —— 用户不改下拉直接点保存就把分组清空了。
    card = [s for s in at.selectbox if (s.key or "") == f"lib_f_{DEMO_ARTICLES[0]['pmid']}"]
    if not card:
        ok = False
        print("  NG   未找到卡片内的「分组」下拉（key=lib_f_<pmid>）")
    else:
        got = card[0].value
        want = folder["id"]
        h = got == want
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 卡片分组下拉回显已存分组"
              f"（期望 {want}，实际 {got}）")

    # ---------- 5. PDF 全文分析页（v3.2.0，P3-C3） ----------
    print("\n【5】PDF 全文分析页")
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "PDF 全文分析"
    at.run()
    if at.exception:
        print("  NG   PDF 全文分析页抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   PDF 全文分析页执行无异常")

    blob5 = "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])
    for k in ("PDF 全文分析", "MEDLIT_PDF_MAX_MB"):
        h = k in blob5
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现「{k}」")

    ack_labels = [b.label or "" for b in at.checkbox]
    hit_ack = any("版权与合规确认" in l for l in ack_labels)
    ok = ok and hit_ack
    print(f"  {'OK ' if hit_ack else 'NG '} 出现版权与合规确认门（共 {len(ack_labels)} 个勾选框）")
    # 未确认时的提示走 st.info（AppTest 里是 at.info，不是 markdown/caption）
    infos5 = [i.value for i in at.info]
    hit_gate = any("请先勾选上方的版权与合规确认" in v for v in infos5)
    ok = ok and hit_gate
    print(f"  {'OK ' if hit_gate else 'NG '} 未确认时给出上传前提示、不开放上传")

    ack = next((b for b in at.checkbox if "版权与合规确认" in (b.label or "")), None)
    if ack is None:
        ok = False
        print("  NG   未找到版权确认勾选框，无法继续")
    else:
        ack.check()
        # option_menu 的选中态在 AppTest 里不会跨 run 保留，必须每次 run 前重新声明目标页，
        # 否则这一次 run 会退回「系统首页」（实测如此，非页面缺陷）。
        at.session_state["pending_page"] = "PDF 全文分析"
        at.run()
        if at.exception:
            print("  NG   勾选版权确认后抛出异常：")
            for e in at.exception:
                print("    -", type(e.value).__name__, ":", e.value)
            return 1
        blob5b = "\n".join([m.value for m in at.markdown] + [c.value for c in at.caption])
        infos5b = [i.value for i in at.info]
        hit_ready = ("选择 PDF 后自动开始解析" in blob5b
                     and not any("请先勾选上方的版权与合规确认" in v for v in infos5b))
        ok = ok and hit_ready
        print(f"  {'OK ' if hit_ready else 'NG '} 勾选版权确认后开放上传")

    # ---------- 6. 日志落盘 ----------
    print("\n【6】运行日志")
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