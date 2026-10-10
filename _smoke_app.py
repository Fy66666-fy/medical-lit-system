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
5b. 综述初稿的叙述段区在**已配置大模型**时出现「写作风格 / 输出语言 / 叙述段使用模型」
   三个选择器，默认「学术严谨 · 中文」与「跟随侧边栏设置」，并真实切换一次风格
   验证界面随之更新（v3.5.0，P3-C6；提示词本身由 `_test_review.py` 离线断言）。
3b. 综述工作台的对比表**从只读表格改成可编辑表格**：手工修正的字段会带着 ✎ 角标
   进入表格与导出；三态图例（摘要未提及 / 有摘要未抽到 / 无摘要）与结构化完整度
   汇总都渲染出来；「信息缺失」类偏倚提示在表 2 只给条数（v3.7.0，P3-C4.1-B）。
   三态判定与修正回写逻辑本身由 `_test_review.py` 第 [9] 节离线断言。

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

    # ---------- 2b. 使用体验问卷：邀请 → 弹窗 → 提交 → 本机落盘（v3.7.0） ----------
    print("\n【2b】使用体验问卷（自愿参与；计数与答案都只在本机）")
    from core import feedback as _fb
    from core import storage as _st

    def _all_buttons(at):
        return list(at.button) + list(at.sidebar.button)

    # 未到阈值：侧边栏不应出现邀请
    _st.set_scope("local")
    _fb.save_usage(_fb.new_usage())
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
    at.run()
    h = not any(b.key == "fb_sv_yes" for b in _all_buttons(at))
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 用了 0 次不出现问卷邀请")

    # 写到阈值：侧边栏出现邀请卡（文案 + 三个按钮）
    _u = _fb.new_usage()
    _u = _fb.bump(_u, _fb.PROMPT_AT)
    _fb.save_usage(_u)
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
    at.run()
    _btn_yes = [b for b in _all_buttons(at) if b.key == "fb_sv_yes"]
    _btn_mute = [b for b in _all_buttons(at) if b.key == "fb_sv_mute"]
    h = bool(_btn_yes and _btn_mute)
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 用满 {_fb.PROMPT_AT} 次后出现邀请（含「填写」与「不再提醒」）")
    _side = ""
    try:
        _side = "\n".join(m.value for m in at.sidebar.markdown) + \
                "\n".join(c.value for c in at.sidebar.caption)
    except Exception:
        pass
    h = "只存本机" in _side or "不会上传" in _side
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 邀请文案说明数据只存本机")

    # 点「填写」：弹窗出现，含全部问题
    _btn_yes[0].click()
    at.run()
    if at.exception:
        print("  NG   打开问卷弹窗抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    _labels = [r.label for r in at.radio] + [m.label for m in at.multiselect] \
        + [t.label for t in at.text_area]
    h = any("多久用一次" in (l or "") for l in _labels) \
        and any("总体满意度" in (l or "") for l in _labels) \
        and any("最有用" in (l or "") for l in _labels) \
        and any("最想改进" in (l or "") for l in _labels)
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 问卷弹窗含 4 类问题（频率 / 满意度 / 有用功能 / 改进建议）")

    # 填写并提交：答案落盘本机 survey_*.json，且含清洗
    for m in at.multiselect:
        if m.label and "最有用" in m.label:
            m.select("中文摘要与原文定位")
    for t in at.text_area:
        if t.label and "最想改进" in t.label:
            t.set_value("建议支持导出 EndNote；联系我 test@example.com")
    _sub = [b for b in at.button if "提交问卷" in (b.label or "")]
    h = bool(_sub)
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 出现「提交问卷」按钮")
    if _sub:
        _sub[0].click()
        at.run()
        if at.exception:
            print("  NG   提交问卷抛出异常：")
            for e in at.exception:
                print("    -", type(e.value).__name__, ":", e.value)
            return 1
        h = any("已保存到本机" in s.value for s in at.success)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 提交后提示「已保存到本机」")
        # st.link_button 不被 AppTest 收集为 button，这里退而断言它的内容来源：
        # 一键 GitHub 链接由 fb_survey_text（问卷渲染文本）预填生成
        h = bool(at.session_state.get("fb_survey_text")) \
            and "使用体验问卷" in str(at.session_state.get("fb_survey_text"))
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 问卷文本已在会话中（GitHub 一键链接由它预填；"
              f"link_button 本身 AppTest 不收集）")
        _fb_dir = os.path.dirname(_fb._path())
        _sv_files = [f for f in os.listdir(_fb_dir) if f.startswith("survey_")] \
            if os.path.isdir(_fb_dir) else []
        h = bool(_sv_files)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 问卷已落盘：{_sv_files}")
        if _sv_files:
            import json as _json
            _data = _json.load(open(os.path.join(_fb_dir, _sv_files[0]), encoding="utf-8"))
            _last = _data[-1]
            h = "EndNote" in _last.get("improve", "") \
                and "[邮箱已隐去]" in _last.get("improve", "")
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} 答案内容与隐私清洗都正确（邮箱被隐去）")
            h = _last.get("usage_count") == _fb.PROMPT_AT
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} 问卷记录提交时的使用次数（{_fb.PROMPT_AT}）")
        _u_now = _fb.load_usage()
        h = _u_now.get("survey_done") is True
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 提交后不再邀请（survey_done=True）")

    # 「不再提醒」路径
    _fb.save_usage({**_fb.new_usage(), "count": 99})
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
    at.run()
    _btn_mute2 = [b for b in _all_buttons(at) if b.key == "fb_sv_mute"]
    if _btn_mute2:
        _btn_mute2[0].click()
        at.run()
        h = _fb.load_usage().get("muted") is True \
            and not any(b.key == "fb_sv_yes" for b in _all_buttons(at))
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 点「不再提醒」后落盘 muted=True 且邀请消失")
    else:
        ok = False
        print("  NG   未找到「不再提醒」按钮")

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

    # ---------- 3b. 综述工作台 · 空态三态 / 完整度 / 表格人工修正（v3.7.0，P3-C4.1-B） ----------
    print("\n【3b】综述工作台 · 空态三态 / 结构化完整度 / 表格人工修正")
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "综述工作台"
    at.session_state["rv_picked"] = [a["pmid"] for a in DEMO_ARTICLES]
    # 预置一条人工修正：要验的是"修正真的进到表格与导出"，而不只是躺在会话状态里
    at.session_state["rv_corrections"] = {"9001": {"样本量": "6400"}}
    at.run()
    if at.exception:
        print("  NG   综述工作台（C4.1-B）抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   综述工作台（C4.1-B）执行无异常")
    _cap = "\n".join(c.value for c in at.caption)
    for k in ("结构化完整度", "空格的三种含义", "摘要未提及", "有摘要未抽到", "无摘要"):
        h = k in _cap
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 三态 / 完整度说明出现「{k}」")
    # 对比表必须是可编辑的 data_editor（不是只读 dataframe），且修正值带 ✎ 角标落地
    try:
        _ed = at.get_by_key("rv_cmp_editor")
        _recs = _ed.value.to_dict("records")
        # 行序由"检索结果 + 收藏"的合并顺序决定，别假定第 0 行就是 9001——全表找
        _vals = " ".join(str(v) for _r in _recs for v in _r.values())
        h = "6400" in _vals and "✎已修正" in _vals
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 对比表可编辑，人工修正值已生效并带 ✎ 角标")
        _cols = list(_ed.value.columns)
        h = all(c in _cols for c in ("样本量", "人群", "主要终点", "关键效应量", "结论"))
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 对比表含 5 个可修正列（共 {len(_cols)} 列）")
        # 未修正的行必须保持自动抽取的原值（9002 的 900 不该被 9001 的修正带偏）
        h = any(str(_r.get("样本量")) == "900" for _r in _recs)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 修正只作用于被改的那一行（其余行仍是原值）")
    except Exception as e:
        ok = False
        print(f"  NG   取不到对比表控件 rv_cmp_editor：{type(e).__name__}: {e}")
    # 「信息缺失」类提示只给条数：逐条明细在 expander 内（AppTest 不收集），
    # 因此这里断言表 2 的计数列存在——它就是"默认折叠"在界面上的落点。
    _bio = None
    for _d in at.dataframe:
        try:
            if "信息缺失项" in list(_d.value.columns):
                _bio = _d.value
                break
        except Exception:
            continue
    _n_info = 0 if _bio is None else int(_bio["信息缺失项"].sum())
    h = _bio is not None
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 表 2 出现「信息缺失项」计数列（本次共 {_n_info} 条）")
    h = any("清除全部人工修正" in (b.label or "") for b in at.button)
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 有修正时出现「清除全部人工修正」按钮")
    # 清掉磁盘上的修正记录：否则它会随 _rv_seed 漏进后面几节的会话
    _saved = storage.load_review_state()
    _saved["rv_corrections"] = {}
    storage.save_review_state(_saved)

    # ---------- 3c. 综述初稿自动成稿 + LLM 补抽入口（v3.8.0，用户实测反馈） ----------
    print("\n【3c】综述初稿 · 摘要/主要发现/局限性自动成稿 + 斜体下划线占位")
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "综述工作台"
    at.session_state["rv_picked"] = [a["pmid"] for a in DEMO_ARTICLES]
    at.run()
    if at.exception:
        print("  NG   综述工作台（v3.8.0 初稿）抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   综述工作台（v3.8.0 初稿）执行无异常")
    _btn = next((b for b in at.button if "生成综述初稿骨架" in (b.label or "")), None)
    if _btn is None:
        ok = False
        print("  NG   未找到「生成综述初稿骨架」按钮")
    else:
        # pending_page 每次运行都会被消费：点按钮触发的新一轮必须重新注入，
        # 否则 AppTest 里 option_menu 会退回首页，按钮根本不在渲染树里
        at.session_state["pending_page"] = "综述工作台"
        _btn.click()
        at.run()
        if at.exception:
            print("  NG   生成初稿抛出异常：")
            for e in at.exception:
                print("    -", type(e.value).__name__, ":", e.value)
            return 1
        # 只检查初稿那一块 markdown——页面其它标签页（如 PRISMA）可能自带别的占位文案
        _draft_md = next((m.value for m in at.markdown if "## 摘要" in m.value), "")
        h = bool(_draft_md)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 找到渲染出的初稿块（含摘要节）")
        for k in ("**目的**", "**方法**", "**结果**", "**结论**",
                  "仅检索了单一数据库", "灰色文献", "<u>【待补充"):
            h = k in _draft_md
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} 初稿含「{k}」")
        _bare = [ln for ln in _draft_md.splitlines()
                 if "【待补充" in ln and "<u>【待补充" not in ln]
        h = not _bare
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 界面渲染的初稿无裸【待补充（全部斜体下划线）")
    # C4.1-C：补抽入口只在「有可补目标」时出现（AppTest 配不了真 Key，
    # 这里验证入口与未配置提示；补抽/解析/应用本身由 _test_review.py [11] 离线断言）
    from core import review as _rv
    _tg = _rv.llm_fill_targets(at.session_state.get("rv_rows") or [])
    print(f"  INFO 本次演示数据可补抽目标：{len(_tg)} 篇（入口仅在有目标时出现）")
    if _tg:
        h = any("让大模型补抽未识别字段" in (e.label or "") for e in at.expander)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 对比表出现「🤖 让大模型补抽未识别字段」入口")
        h = any("未配置大模型" in (c.value or "") for c in at.caption)
        print(f"  INFO 未配置 Key 时的提示{'已出现' if h else '在 expander 内（AppTest 不收集），跳过'}")

    # ---------- 4. 文献检索页 · MeSH 词表联动（v3.4.0，P3-C5） ----------
    print("\n【4】文献检索 · MeSH 词表联动控件")
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "文献检索"
    at.run()
    if at.exception:
        print("  NG   文献检索页抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   文献检索页执行无异常")
    # 主关键词 / 副关键词等是 widget 标签（不是 markdown），要从控件上断言
    ti_labels = " | ".join((t.label or "") for t in at.text_input)
    for k in ("主关键词", "副关键词", "作者", "来源期刊"):
        h = k in ti_labels
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现输入控件「{k}」")
    h = "文献检索" in "\n".join(m.value for m in at.markdown)
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 出现页面标题「文献检索」")
    # MeSH 模式选择器：默认「仅提示」，且必须给出「关闭 / 自动扩展」两个极端档
    mesh_radios = [r for r in at.radio if "MeSH" in (r.label or "")]
    if not mesh_radios:
        ok = False
        print("  NG   未找到 MeSH 词表联动选择器")
    else:
        opts = list(mesh_radios[0].options or [])
        for want in ("关闭", "仅提示", "自动扩展同义词"):
            h = want in opts
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} MeSH 模式含「{want}」")
        h = mesh_radios[0].value == "仅提示"
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} MeSH 模式默认为「仅提示」（实际 {mesh_radios[0].value!r}）")
    # 空关键词时不得发起任何 MeSH 查询（离线冒烟环境中网络不可用，
    # 一旦误触发就会把异常带进页面）
    h = not at.session_state.get("mesh_report")
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 未点按钮时不预先查询词表（无多余请求）")

    # ---------- 4b. 会话丢失后自动回填最近检索条件（v3.7.1） ----------
    # 浏览器刷新 / 云端预览重载 / 桌面版重启会让 session_state 清空，
    # 此前主副关键词和条数跟着消失、只能重打一遍。现在最近一次成功检索的
    # 原始条件落盘 data/last_search.json，新会话进检索页自动回填。
    print("\n【4b】会话丢失后自动回填最近检索条件（v3.7.1）")
    from core import storage as _sto

    _sto.save_last_search({
        "keyword": "immunotherapy lung cancer",
        "secondary": "PD-1 biomarker, survival",
        "retmax": 50,
        "query": '(immunotherapy lung cancer) AND ("PD-1 biomarker" AND survival)',
        "total": 321,
    })
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "文献检索"
    at.run()
    if at.exception:
        print("  NG   回填流程抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    kw_box = next((t for t in at.text_input if t.key == "kw"), None)
    kw2_box = next((t for t in at.text_input if t.key == "kw2"), None)
    n_slider = next((s for s in at.select_slider if s.key == "kw_n"), None)
    for name, box, want in (("主关键词", kw_box, "immunotherapy lung cancer"),
                            ("副关键词", kw2_box, "PD-1 biomarker, survival")):
        h = box is not None and box.value == want
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 新会话自动回填{name}（{box.value if box else '控件缺失'!r}）")
    h = n_slider is not None and n_slider.value == 50
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 新会话自动回填返回条数（{n_slider.value if n_slider else '控件缺失'}）")
    # 回填后仍可自由修改：改关键词、重新运行，改动不被回填覆盖
    if kw_box is not None:
        kw_box.set_value("car-t therapy lymphoma")
        # pending_page 每次运行都会被消费，这里必须重新注入才能留在检索页
        at.session_state["pending_page"] = "文献检索"
        at.run()
        kw_now = next((t for t in at.text_input if t.key == "kw"), None)
        h = kw_now is not None and kw_now.value == "car-t therapy lymphoma"
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 回填后可正常修改关键词（{kw_now.value if kw_now else '控件缺失'!r}）")
    # 全新用户（无落盘记录）不受影响：默认条数 10、输入框为空
    _sto.save_last_search({})
    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    at.session_state["pending_page"] = "文献检索"
    at.run()
    kw_box = next((t for t in at.text_input if t.key == "kw"), None)
    n_slider = next((s for s in at.select_slider if s.key == "kw_n"), None)
    h = kw_box is not None and kw_box.value == ""
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 无历史记录时主关键词为空（{kw_box.value if kw_box else '控件缺失'!r}）")
    h = n_slider is not None and n_slider.value == 10
    ok = ok and h
    print(f"  {'OK ' if h else 'NG '} 无历史记录时默认条数 10（{n_slider.value if n_slider else '控件缺失'}）")
    # 恢复演示数据，免得影响后续小节的断言
    _sto.save_last_search({})

    # ---------- 5. 我的文献库（v3.1.0，P3-C1）+ 引用导出（v3.0.1，P3-C2） ----------
    print("\n【5】我的文献库 · 分组 / 标签 / 笔记 + 引用导出")
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

    # ---------- 6. PDF 全文分析页（v3.2.0，P3-C3） ----------
    print("\n【6】PDF 全文分析页")
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

    # ---------- 6b. 综述初稿 · 叙述段风格 / 语言 / 模型（v3.5.0，P3-C6） ----------
    print("\n【6b】综述初稿 · 叙述段的风格 / 语言 / 模型控件")
    from core import review  # noqa: PLC0415

    at = _run()
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    at.run()
    # 这三个选择器只在「侧边栏已配置大模型」时才渲染（llm_ready），所以必须先把
    # Base/Key/模型塞进会话状态，否则测到的永远是「未配置」那条分支，控件根本不在。
    at.session_state["llm_base"] = "https://api.example.com"
    at.session_state["llm_key"] = "sk-smoke-test"
    at.session_state["llm_model"] = "deepseek-v4-pro"
    at.session_state["pending_page"] = "综述工作台"
    at.session_state["rv_picked"] = [a["pmid"] for a in DEMO_ARTICLES]
    at.run()
    if at.exception:
        print("  NG   综述工作台（已配置大模型）抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        return 1
    print("  OK   已配置大模型时综述工作台执行无异常")

    sb = {(s.label or ""): s for s in at.selectbox}
    for lbl in ("写作风格", "输出语言", "叙述段使用模型"):
        h = lbl in sb
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现选择器「{lbl}」")
    if all(l in sb for l in ("写作风格", "输出语言", "叙述段使用模型")):
        # 注意：AppTest 暴露的 `options` 是**经 format_func 映射后的显示串**，不是内部键，
        # 因此这里断言显示串；再配合 session_state 断言真实提交值（内部键）。
        h = list(sb["写作风格"].options) == ["学术严谨", "简明扼要"]
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 风格选项为严谨 / 简明两档（实际 {list(sb['写作风格'].options)}）")
        h = list(sb["输出语言"].options) == ["中文", "英文"]
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 语言选项为中 / 英两档（实际 {list(sb['输出语言'].options)}）")
        h = review.DRAFT_STYLE_KEYS == ("rigorous", "concise") and review.DRAFT_LANG_KEYS == ("zh", "en")
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 显示串背后的提交键仍是 rigorous/concise 与 zh/en")
        mopts = list(sb["叙述段使用模型"].options)
        h = bool(mopts) and mopts[0] == "跟随侧边栏设置" and "deepseek-v4-pro" in mopts
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 模型下拉首项为「跟随侧边栏设置」且含常用预设"
              f"（共 {len(mopts)} 项）")
        h = sb["叙述段使用模型"].value == "跟随侧边栏设置"
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 模型默认「跟随侧边栏设置」（实际 {sb['叙述段使用模型'].value!r}）")
        cap = "\n".join(c.value for c in at.caption)
        h = "学术严谨" in cap and "中文" in cap
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 默认展示「学术严谨 · 中文」")
        # 「硬性禁止编造」的纪律在 UI 上也要有交代（用户得知道模型能说什么）
        h = "禁止编造" in cap and "摘要未提供" in cap
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 叙述段区说明「禁止编造 / 缺失写摘要未提供」约束")
        # 选了预设模型必须提醒「模型要存在于你自己的 API 地址下」，不能让用户以为能随便选
        h = "必须存在于你上面配置的 API 地址下" in cap
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 提示预设模型需与自配 API 地址配套")
        h = any("撰写叙述段" in (b.label or "") for b in at.button)
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 出现「撰写叙述段」按钮")
        # 真的动一下控件：切成「简明扼要」后，rerun 出来的汇总说明必须跟着变
        sb["写作风格"].select("concise")
        at.session_state["pending_page"] = "综述工作台"
        at.run()
        if at.exception:
            print("  NG   切换风格后抛出异常：")
            for e in at.exception:
                print("    -", type(e.value).__name__, ":", e.value)
            return 1
        cap2 = "\n".join(c.value for c in at.caption)
        h = "简明扼要" in cap2
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 切换风格为「简明扼要」后界面同步更新")
        h = at.session_state.get("rv_llm_style") == "concise"
        ok = ok and h
        print(f"  {'OK ' if h else 'NG '} 风格变更真的落到会话状态"
              f"（rv_llm_style={at.session_state.get('rv_llm_style')!r}）")

        # 动态模型列表：侧边栏「拉取接口的模型列表」把真实列表写进 llm_models 后，
        # 叙述段下拉必须改用这份真实列表（这是「内置预设必然过期」的解法）。
        at.session_state["llm_models"] = ["vendor-model-a", "vendor-model-b"]
        at.session_state["pending_page"] = "综述工作台"
        at.run()
        if at.exception:
            print("  NG   设置 llm_models 后抛出异常：")
            for e in at.exception:
                print("    -", type(e.value).__name__, ":", e.value)
            return 1
        sb2 = {(s.label or ""): s for s in at.selectbox}
        if "叙述段使用模型" in sb2:
            mopts2 = list(sb2["叙述段使用模型"].options)
            h = mopts2 == ["跟随侧边栏设置", "vendor-model-a", "vendor-model-b"]
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} 拉到模型列表后下拉改用真实列表（实际 {mopts2}）")
            h = sb2["叙述段使用模型"].value == "跟随侧边栏设置"
            ok = ok and h
            print(f"  {'OK ' if h else 'NG '} 候选项变化后已选值自动归位「跟随侧边栏设置」")

    # ---------- 6. 日志落盘 ----------
    print("\n【7】运行日志")
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