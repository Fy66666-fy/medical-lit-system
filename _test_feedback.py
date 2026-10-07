"""反馈渠道自测（P1 任务 6）：留档、去重上限、隐私清洗、Issue 链接。

全部用临时数据目录，不污染真实 data/。
"""
import os
import sys
import tempfile
import urllib.parse

_TMP = tempfile.mkdtemp(prefix="medlit_fb_t_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import feedback, storage  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


def main() -> int:
    print("\n[1] 留档")
    check("空内容不入档", feedback.save("bug", "   ") is False)
    check("正常留档成功", feedback.save("bug", "翻译一直返回英文") is True)
    check("计数为 1", feedback.local_count() == 1, str(feedback.local_count()))
    check("summary 可读", "1 条" in feedback.summary_line(), feedback.summary_line())
    for i in range(5):
        feedback.save("feature", f"建议 {i}")
    check("多次留档累加", feedback.local_count() == 6, str(feedback.local_count()))

    print("\n[2] 未知类型归到 other")
    feedback.save("不存在的类型", "内容")
    check("计数继续累加", feedback.local_count() == 7)

    print("\n[3] 隐私清洗")
    dirty = "患者 13800138000，邮箱 zhangsan@hospital.com，另有 zha.wei@163.com"
    clean = feedback.sanitize(dirty)
    check("手机号被隐去", "13800138000" not in clean, clean)
    check("邮箱被隐去", "zhangsan@hospital.com" not in clean)
    check("第二个邮箱也被隐去", "zha.wei@163.com" not in clean)
    check("其余文字保留", "患者" in clean and "另有" in clean)
    check("无敏感信息时原样返回",
          feedback.sanitize("页面卡死") == "页面卡死")

    print("\n[4] Issue 链接")
    url = feedback.issue_url("feature", "希望支持 MeSH 主题词筛选", "版本 v2.8.0")
    check("指向本仓库 issues/new",
          url.startswith("https://github.com/Fy66666-fy/medical-lit-system/issues/new?"))
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    check("带 title 参数", "title" in q)
    check("标题含类型标签", "[建议]" in q["title"][0], q["title"][0])
    check("正文含用户描述", "MeSH" in q["body"][0])
    check("正文含诊断信息", "v2.8.0" in q["body"][0])
    check("正文含防误贴提示", "个人身份" in q["body"][0])

    print("\n[5] 特殊字符不破坏链接")
    tricky = feedback.issue_url("bug", "报错 100% & <script>alert(1)</script> 中文")
    q2 = urllib.parse.parse_qs(urllib.parse.urlparse(tricky).query)
    check("含 & 与尖括号仍可解析", "script" in q2["body"][0])
    check("长度合理", 300 < len(tricky) < 4000, str(len(tricky)))

    print("\n[6] 会话隔离")
    storage.set_scope("s_fb_test")
    check("新作用域看不到旧留档", feedback.local_count() == 0, str(feedback.local_count()))
    feedback.save("question", "这是另一个会话的反馈")
    check("新作用域可独立留档", feedback.local_count() == 1)
    storage.set_scope("local")
    check("原作用域数据仍在", feedback.local_count() == 7, str(feedback.local_count()))

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())