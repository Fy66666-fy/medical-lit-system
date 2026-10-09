"""反馈渠道自测（P1 任务 6）：留档、去重上限、隐私清洗、Issue 链接。

全部用临时数据目录，不污染真实 data/。
"""
import json
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


def _write_bad_json(path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        return True
    except Exception:
        return False


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

    print("\n[7] 使用计数与问卷邀请（v3.7.0）")
    u = feedback.new_usage()
    check("全新计数不邀请", feedback.should_prompt(u) is False)
    check("首次邀请阈值 = 15", feedback.next_prompt_at(u) == 15,
          str(feedback.next_prompt_at(u)))
    for _ in range(feedback.PROMPT_AT):
        u = feedback.bump(u)
    check("用满 15 次开始邀请", feedback.should_prompt(u) is True)
    feedback.record_prompt(u)
    check("邀请过一次后安静（下次阈值 = 40）",
          feedback.should_prompt(u) is False and feedback.next_prompt_at(u) == 40,
          str(feedback.next_prompt_at(u)))
    u = feedback.bump(u, 40 - u["count"])
    check("用满 40 次再次邀请", feedback.should_prompt(u) is True)
    feedback.record_prompt(u)
    u = feedback.bump(u, feedback.REPEAT_EVERY)
    check("第三次邀请照常", feedback.should_prompt(u) is True)
    feedback.record_prompt(u)
    u = feedback.bump(u, feedback.REPEAT_EVERY)
    check("邀请满 3 次后彻底安静（哪怕用 100 次）",
          feedback.should_prompt(u) is False)
    check("静音后不再邀请",
          feedback.should_prompt(feedback.mute_prompts(
              {**feedback.new_usage(), "count": 99})) is False)
    check("填过问卷后不再邀请",
          feedback.should_prompt(feedback.complete_survey(
              {**feedback.new_usage(), "count": 99})) is False)
    feedback.save_usage(u)
    u2 = feedback.load_usage()
    check("计数落盘往返（count / prompts / muted）",
          u2["count"] == u["count"] and u2["prompts"] == u["prompts"]
          and u2["muted"] == u["muted"])
    check("损坏的计数文件回退为全新计数（不抛异常）",
          _write_bad_json(feedback._usage_path())
          and feedback.load_usage()["count"] == 0)

    print("\n[8] 问卷：保存 / 清洗 / 渲染")
    ans = {"freq": "每周 1–2 次",
           "useful": "中文摘要与原文定位、引用导出（.bib / .ris / ZIP）",
           "satisfaction": "⭐⭐⭐⭐ 不错，有小问题",
           "improve": "联系我: test@example.com 或 13812345678",
           "recommend": "会", "contact": "li@example.com"}
    check("空答案拒绝保存", feedback.save_survey({}, 0) is None)
    p = feedback.save_survey(ans, 23)
    check("问卷落盘成功", bool(p), os.path.basename(p or ""))
    data = json.load(open(p, encoding="utf-8"))
    last = data[-1]
    check("答案里的邮箱被清洗", "[邮箱已隐去]" in last["improve"])
    check("答案里的手机号被清洗", "[手机号已隐去]" in last["improve"])
    check("记录使用次数", last["usage_count"] == 23)
    txt = feedback.render_survey_text(ans, 23)
    check("渲染文本含各题", all(k in txt for k in ("使用频率", "总体满意度", "愿意推荐")))
    check("渲染文本含清洗后的改进建议", "[邮箱已隐去]" in txt)
    q3 = urllib.parse.parse_qs(urllib.parse.urlparse(
        feedback.issue_url("feature", txt)).query)
    check("问卷文本可预填进 Issue", "使用体验问卷" in q3["body"][0])

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())