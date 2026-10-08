"""PDF 全文分析页「渲染链路」测试（v3.2.0，P3-C3）。

为什么单独一个文件：
    AppTest 官方**不支持**给 st.file_uploader 注入文件，因此 _smoke_app.py 只能验证
    路由与上传门。但「上传 → 解析 → 概览 / 章节 / 摘要 / 定位 / 图表表格 / 引用导出
    → 加入文献架 → 综述工作台纳入」这条主链路才是本功能的核心，必须真跑一遍。

做法：在测试进程里 monkeypatch `streamlit.file_uploader`，让它直接返回内存中生成的
PDF（复用 _test_pdfdoc.py 的极简 PDF 生成器）。app.py 与测试同进程、共用同一个
streamlit 模块对象，因此 patch 对被测脚本同样生效。

断言分六段：上传门 → 概览与章节 → 全文摘要与定位 → 图表表格 → 引用导出 →
文献架与综述工作台纳入。写盘只落在临时数据目录。
"""
import os
import sys
import tempfile

os.environ["MEDLIT_DATA_DIR"] = tempfile.mkdtemp(prefix="medlit_pdfpage_")
os.environ["MEDLIT_SCOPE"] = "local"

sys.path.insert(0, ".")

import streamlit as st  # noqa: E402

from _test_pdfdoc import make_pdf, sample_pages, table_page_content  # noqa: E402

PDF_NAME = "heart_failure_trial.pdf"
PDF_BYTES = make_pdf(sample_pages() + [table_page_content()])
PDF_TITLE = "Randomized Trial of Drug X in Chronic Heart Failure"

_OK = True
_FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global _OK
    print(f"  {'OK ' if cond else 'NG '} {name}" + (f"（{detail}）" if detail else ""))
    if not cond:
        _OK = False
        _FAILS.append(name)


class _FakeUpload:
    """最小可用的 UploadedFile 替身：页面只用到 name / getvalue / size / type。"""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self.size = len(data)
        self.type = "application/pdf"
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _install_fake_uploader() -> None:
    def _fake(label=None, type=None, key=None, disabled=False, help=None, **kw):  # noqa: A002
        # 与真实控件一致：未确认版权时不可用，返回 None
        if disabled:
            return None
        return _FakeUpload(PDF_NAME, PDF_BYTES)

    st.file_uploader = _fake


def _blob(at) -> str:
    parts = [m.value for m in at.markdown]
    parts += [c.value for c in at.caption]
    parts += [i.value for i in at.info]
    parts += [w.value for w in at.warning]
    parts += [c.value for c in at.code]
    return "\n".join(parts)


def _run(at):
    at.run()
    if at.exception:
        print("  NG   脚本抛出异常：")
        for e in at.exception:
            print("    -", type(e.value).__name__, ":", e.value)
        _FAILS.append("脚本异常")
        return False
    return True


def _goto(at, page_label: str, settle: int = 1):
    """option_menu 选中态不跨 run 保留，必须每次 run 前重新声明目标页。

    这一点很关键：任何控件交互（点按钮 / 勾选）之后如果直接 at.run()，页面会退回
    「系统首页」，而首页的能力卡片里也含「全文数据分析」「原文定位」等字样 ——
    断言会出现**假阳性**。因此交互后一律用本函数重进目标页，并在每段开头断言
    「解析概览」仍在，作为仍停留在 PDF 页的守卫。

    ``settle``：页面里若有 `st.rerun()`（如「加入文献架」），一次 run 之后脚本会被
    再跑一遍，而那一遍没有我们声明的目标页 —— 需要多 run 一次才能落稳。
    """
    for _ in range(max(1, settle)):
        at.session_state["pending_page"] = page_label
        if not _run(at):
            return False
    return True


def main() -> int:
    _install_fake_uploader()

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("app.py", default_timeout=300)
    if not _run(at):
        return 1
    for b in at.checkbox:
        if "数据处理方式" in (b.label or ""):
            b.check()
            break
    if not _run(at):
        return 1

    # ---------- 1. 上传门 ----------
    print("【1】上传与版权门")
    if not _goto(at, "PDF 全文分析"):
        return 1
    check("页面标题出现", "PDF 全文分析" in _blob(at))
    check("资源上限提示出现", "MEDLIT_PDF_MAX_MB" in _blob(at))
    ack = next((b for b in at.checkbox if "版权与合规确认" in (b.label or "")), None)
    check("存在版权与合规确认门", ack is not None)
    if ack is None:
        return 1
    check("未确认时不渲染解析结果",
          "解析概览" not in _blob(at) and "章节浏览" not in _blob(at))

    ack.check()
    if not _goto(at, "PDF 全文分析"):
        return 1

    # ---------- 2. 解析概览与章节 ----------
    print("\n【2】解析概览与章节")
    blob = _blob(at)
    check("仍停留在 PDF 页（守卫）", "解析概览" in blob)
    check("出现「解析概览」", "解析概览" in blob)
    check("识别出论文标题", PDF_TITLE in blob, PDF_TITLE[:40])
    check("识别出作者", "John A Smith" in blob)
    check("识别出期刊", "Journal of Clinical Medicine" in blob)
    check("出现「章节浏览」", "章节浏览" in blob)
    check("出现「全文摘要与数据挖掘」", "全文摘要与数据挖掘" in blob)
    check("出现「图表与表格解析」", "图表与表格解析" in blob)
    check("出现「引用导出」", "引用导出" in blob)
    check("解析错误未出现", "❌" not in blob)
    # 章节标题是以 st.expander 渲染的；AppTest 能读到 expander 标签（读不到其中的正文），
    # 正好用来验证「章节识别」这一核心能力。
    exp = [e.label or "" for e in at.expander]
    for chap in ("Abstract", "Introduction", "Methods", "Results", "Discussion", "References"):
        check(f"识别出章节「{chap}」",
              any(chap in e for e in exp), f"实际 expander：{exp[:8]}")

    # ---------- 3. 全文摘要 + 原文定位 ----------
    print("\n【3】全文摘要与原文定位")
    btn = next((b for b in at.button if "生成全文摘要" in (b.label or "")), None)
    check("存在「生成全文摘要」按钮", btn is not None)
    if btn is not None:
        btn.click()
        if not _goto(at, "PDF 全文分析"):
            return 1
        blob = _blob(at)
        check("仍停留在 PDF 页（守卫）", "解析概览" in blob)
        check("出现全文摘要正文（含章节小标题）", "【" in blob and "】" in blob)
        check("出现「原文定位」", "原文定位" in blob)
        check("出现「全文数据分析」", "全文数据分析" in blob)
        check("抽取出关键统计指标（HR / CI / P）",
              ("HR" in blob or "hazard" in blob.lower() or "0.72" in blob))

    # ---------- 4. 图表与表格 ----------
    print("\n【4】图表与表格解析")
    blob = _blob(at)
    check("仍停留在 PDF 页（守卫）", "解析概览" in blob)
    check("识别到 1 个表格", "表格（共 1 个）" in blob)
    exp = [e.label or "" for e in at.expander]
    check("表格以展开区呈现（含页码与行列数）",
          any("表 1" in e and "行" in e for e in exp), f"实际：{[e for e in exp if '表' in e]}")
    dl = [b.label or "" for b in at.download_button]
    check("存在表格 CSV 下载按钮", any("下载 CSV" in l for l in dl))
    check("存在页面渲染选择器", any((m.label or "") == "选择要渲染的页面" for m in at.multiselect))
    rend = next((b for b in at.button if "视觉分析" in (b.label or "")), None)
    check("未配置 LLM 时不出现视觉分析按钮", rend is None)

    # ---------- 5. 引用导出 ----------
    print("\n【5】引用导出")
    check("仍停留在 PDF 页（守卫）", "解析概览" in _blob(at))
    codes = "\n".join(c.value for c in at.code)
    check("预览区渲染出 BibTeX 条目", "@" in codes and "{" in codes)
    check("BibTeX 中含论文标题片段", "Heart Failure" in codes)
    fmts = []
    for s in at.selectbox:
        if (s.label or "") == "导出格式":
            fmts = list(s.options)
    check("引用导出格式下拉含 6 种格式", len(fmts) == 6, f"实际 {len(fmts)}")
    dls = [b.label or "" for b in at.download_button]
    check("存在引用文件下载按钮", any("下载" in l and "篇" in l for l in dls))
    check("存在解析全文导出按钮", any("导出解析全文" in l for l in dls))

    # ---------- 6. 文献架与综述工作台纳入 ----------
    print("\n【6】文献架与综述工作台纳入")
    add = next((b for b in at.button if "加入文献架" in (b.label or "")), None)
    check("存在「加入文献架」按钮", add is not None)
    if add is not None:
        add.click()
        # 「加入文献架」的处理函数里有 st.rerun()，需要多跑一次才能落稳。
        # 注意：脚本内 st.rerun() 之后，AppTest 会丢掉之前由 .check() 写入的控件态
        # （真实浏览器不会——控件态在会话里是持久的），所以这里补勾一次版权确认。
        _goto(at, "PDF 全文分析", settle=2)
        if not at.session_state.get("pdf_copyright_ack"):
            ack2 = next((b for b in at.checkbox if "版权与合规确认" in (b.label or "")), None)
            if ack2 is not None:
                ack2.check()
        if not _goto(at, "PDF 全文分析"):
            return 1
        blob = _blob(at)
        check("仍停留在 PDF 页（守卫）", "解析概览" in blob)
        check("文献架出现且含该文献", "PDF 文献架" in blob and PDF_TITLE in blob)
        # 文献架的引用导出区包在 st.expander 里，读 expander 标签即可确认它存在
        exp = [e.label or "" for e in at.expander]
        check("文献架附带引用导出区", any("文献架引用导出" in e for e in exp), f"实际：{exp}")
        n_fmt = len([s for s in at.selectbox if (s.label or "") == "导出格式"])
        check("出现 2 个引用导出格式下拉（文献架 + 本篇）", n_fmt == 2, f"实际 {n_fmt}")

        if not _goto(at, "综述工作台"):
            return 1
        blob = _blob(at)
        check("综述池提示含「本地 PDF」", "本地 PDF" in blob)
        # 勾选该 PDF 文献（无 pmid，键为标题前缀），走与真实页面相同的数据通路
        at.session_state["rv_picked"] = [PDF_TITLE[:60]]
        if not _goto(at, "综述工作台"):
            return 1
        blob = _blob(at)
        check("本地 PDF 已进入综述对比表", "纳入文献基本特征对比" in blob)
        check("对比表中出现该 PDF 标题", PDF_TITLE[:40] in blob)
        check("综述页未停在空态", "请至少勾选 1 篇文献" not in blob)

    print(f"\n{'全部通过' if _OK else '存在失败项：' + '；'.join(_FAILS)}")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
