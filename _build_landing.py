"""生成单文件落地页 index.html（P1 任务 5）。

为什么要生成器而不是手写 HTML：落地页要内嵌真实界面截图（base64），
图片会随版本变。写成生成器后，`_shot.py` 重拍一次再跑本脚本即可同步更新。

用法：
    python _shot.py docs/shots 8501 --flow     # 先拍真实截图
    python _build_landing.py                   # 再生成 index.html
"""
from __future__ import annotations

import base64
import html
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(ROOT, "docs", "shots")
OUT = os.path.join(ROOT, "index.html")

REPO = "https://github.com/Fy66666-fy/medical-lit-system"
CLOUD = "https://medical-lit-system-fy.streamlit.app/"


def version() -> str:
    try:
        sys.path.insert(0, ROOT)
        from version import APP_VERSION

        return APP_VERSION
    except Exception:
        return "v2.7.0"


def data_uri(name: str) -> str:
    path = os.path.join(SHOTS, name)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


FEATURES = [
    ("🔍", "文献检索", "直连 PubMed 官方接口，主关键词 / 副关键词 / 作者 / 期刊 / 籍 / "
                     "日期区间 / 排序自由组合，结果卡片直接给出 DOI、PMC 全文与 PDF 入口。"),
    ("📝", "智能摘要", "抽取式摘要离线可用，按章节结构与信息量给句子打分；"
                     "配置大模型后可生成「目的 / 方法 / 结果 / 结论」结构化总结。"),
    ("🌏", "中英对照翻译", "腾讯云机器翻译为主（每月 500 万字符免费额度），"
                        "自动回退 MyMemory 免费接口；摘要、关键词、图表说明都能译。"),
    ("🔍", "原文定位溯源", "摘要里的每一句、每一个关键数值都能点回原文位置，"
                        "并高亮显示前后文——核查结论时不必再翻原文。"),
    ("📊", "统计指标提取", "自动从正文抽取 P 值、置信区间、样本量、风险比、"
                        "均值±标准差，按句高亮并可溯源。"),
    ("🖼", "图表解读", "解析开放获取（PMC）文献的图表图片与图注，"
                     "逐图生成中文解读并总结图表共同讲述的研究故事。"),
    ("📦", "批量与导出", "批量抓取多篇文献全文，摘要、关键词、图表说明"
                       "一键导出 Excel（保留 Markdown 格式，粘进笔记不丢格式）。"),
    ("🛡", "隐私与配额", "不收集任何个人身份信息；云端按会话隔离数据；"
                       "内置用量配额，成本封顶，可随时切回自带密钥。"),
]

FAQ = [
    ("完全免费吗？",
     "是。数据来自 PubMed 官方公开接口（NCBI E-utilities），无需注册、无需付费。"
     "可选的翻译走腾讯云免费额度，大模型摘要需要你自己的 API Key（填在侧边栏即可，不填也能用抽取式摘要）。"),
    ("需要注册账号吗？",
     "不需要，打开即用。收藏与检索历史存在本机；云端版按浏览器会话隔离，"
     "不注册也不会串号。"),
    ("会保存我的检索内容吗？",
     "检索历史与收藏只存在你本机（或你当前这次会话）。翻译与摘要的结果会进入共享缓存以节省公共接口配额，"
     "但缓存内容全部来自 PubMed 公开文献，不含任何身份信息。"),
    ("摘要能直接用于临床决策吗？",
     "<b>不能。</b>所有摘要、翻译与数据分析均由算法或大模型自动生成，可能存在遗漏、偏差或曲解。"
     "诊疗决策必须核对文献原文，并以专业医师的判断为准。"),
    ("中文摘要质量如何？",
     "配置腾讯云密钥后走机器翻译，质量明显优于免费兜底接口；"
     "关键术语建议对照原文核对。每句摘要都能点回原文，方便你快速确认。"),
    ("数据会被用于训练模型吗？",
     "不会。本项目不开做任何用户画像与行为追踪，也不把你的检索内容用于训练。"
     "唯一经过第三方的是你主动发起的翻译与大模型请求——请不要粘贴含患者身份信息的文本。"),
]

STEPS = [
    ("打开链接", "浏览器访问在线版，或下载桌面版双击打开。无需注册、无需安装 Python。"),
    ("输入检索式", "先用一个宽泛的英文关键词试水，例如 <code>metformin cardiovascular outcomes</code>，"
                   "再逐步加上作者、期刊、日期等限定。"),
    ("读摘要并溯源", "点开任意一篇的中文摘要；觉得哪句关键，点它就能跳回原文高亮位置核对。"),
]


def build() -> str:
    v = version()
    home = data_uri("01_home.png")
    results = data_uri("02_results.png")

    feat_html = "\n".join(
        f"""      <article class="feat">
        <div class="feat-ico">{html.escape(ico)}</div>
        <h3>{html.escape(title)}</h3>
        <p>{desc}</p>
      </article>""" for ico, title, desc in FEATURES)

    faq_html = "\n".join(
        f"""      <details class="faq">
        <summary>{q}</summary>
        <p>{a}</p>
      </details>""" for q, a in FAQ)

    steps_html = "\n".join(
        f"""      <li>
        <span class="step-n">{i}</span>
        <div><h3>{t}</h3><p>{d}</p></div>
      </li>""" for i, (t, d) in enumerate(STEPS, 1))

    shots = []
    if home:
        shots.append(f"""      <figure>
        <img src="{home}" alt="系统首页：功能导航、能力卡片与用量统计" loading="lazy">
        <figcaption>打开就是完整工作台：左侧功能导航 + 四项核心能力卡片 + 本次用量统计，不需要在多个网站之间来回切换。</figcaption>
      </figure>""")
    if results:
        shots.append(f"""      <figure>
        <img src="{results}" alt="检索结果：10 篇文献，含 PMID、DOI、PMC 与 PDF 入口" loading="lazy">
        <figcaption>检索结果卡片直接给出 PMID、DOI、PMC 开放全文与 PDF 链接；能免费看全文的会标出 PMC 入口。</figcaption>
      </figure>""")
    shots_html = "\n".join(shots)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>医学文献智能摘要与检索系统 · 从 PubMed 检索到论文全文中文摘要</title>
<meta name="description" content="直连 PubMed 官方接口的免费医学文献工具：一键检索、中文摘要、原文溯源、统计指标提取、图表解读与批量导出。不注册即用，不收集个人信息。">
<style>
  :root {{
    --ink: #16211f;
    --ink-2: #4a5b57;
    --ink-3: #7b8a86;
    --line: #e3e8e6;
    --bg: #ffffff;
    --bg-2: #f6f8f7;
    --brand: #0f766e;
    --brand-2: #14b8a6;
    --brand-soft: #e6f5f2;
    --warn: #b45309;
    --warn-soft: #fef3c7;
    --radius: 14px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; color: var(--ink); background: var(--bg);
    font: 16px/1.75 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 0 24px; }}
  a {{ color: var(--brand); }}
  code {{
    background: var(--bg-2); padding: 1px 6px; border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px;
  }}
  h1, h2, h3 {{ line-height: 1.35; margin: 0; font-weight: 600; }}
  h1 {{ font-size: clamp(30px, 4.6vw, 46px); letter-spacing: -0.5px; }}
  h2 {{ font-size: clamp(22px, 3vw, 30px); margin-bottom: 12px; }}
  h3 {{ font-size: 17px; margin-bottom: 6px; }}
  p {{ margin: 0; }}

  header {{
    background: linear-gradient(180deg, var(--brand-soft), #fff 92%);
    border-bottom: 1px solid var(--line); padding: 56px 0 44px;
  }}
  .badge {{
    display: inline-flex; align-items: center; gap: 6px; font-size: 13px;
    color: var(--brand); background: #fff; border: 1px solid var(--brand);
    padding: 4px 12px; border-radius: 999px; margin-bottom: 18px;
  }}
  .lede {{ font-size: 18px; color: var(--ink-2); max-width: 720px; margin-top: 14px; }}
  .cta {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
  .btn {{
    display: inline-block; padding: 12px 24px; border-radius: 10px;
    font-weight: 600; text-decoration: none; border: 1px solid transparent;
  }}
  .btn-main {{ background: var(--brand); color: #fff; }}
  .btn-main:hover {{ background: #0b5f59; }}
  .btn-ghost {{ border-color: var(--line); color: var(--ink); background: #fff; }}
  .btn-ghost:hover {{ border-color: var(--brand); color: var(--brand); }}
  .trust {{
    margin-top: 26px; font-size: 14px; color: var(--ink-3);
    display: flex; flex-wrap: wrap; gap: 8px 20px;
  }}

  section {{ padding: 60px 0; border-bottom: 1px solid var(--line); }}
  .sec-alt {{ background: var(--bg-2); }}
  .sec-head {{ max-width: 720px; margin-bottom: 32px; }}
  .sec-head p {{ color: var(--ink-2); }}

  .shots {{ display: grid; gap: 28px; }}
  .shots figure {{ margin: 0; }}
  .shots img {{
    width: 100%; border: 1px solid var(--line); border-radius: var(--radius);
    display: block; box-shadow: 0 1px 3px rgba(22, 33, 31, .06);
  }}
  .shots figcaption {{ margin-top: 12px; font-size: 14px; color: var(--ink-3); }}

  .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(248px, 1fr)); }}
  .feat {{
    border: 1px solid var(--line); border-radius: var(--radius);
    padding: 20px; background: #fff;
  }}
  .feat-ico {{ font-size: 22px; margin-bottom: 10px; }}
  .feat p {{ font-size: 14.5px; color: var(--ink-2); }}

  ol.steps {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 14px; }}
  ol.steps li {{ display: flex; gap: 16px; align-items: flex-start; }}
  .step-n {{
    flex: 0 0 30px; height: 30px; border-radius: 50%; background: var(--brand);
    color: #fff; display: grid; place-items: center; font-size: 14px; font-weight: 600;
  }}
  ol.steps p {{ font-size: 14.5px; color: var(--ink-2); }}

  .faq {{ border-bottom: 1px solid var(--line); }}
  .faq summary {{
    cursor: pointer; padding: 16px 0; font-weight: 600; list-style: none;
    display: flex; justify-content: space-between; gap: 16px;
  }}
  .faq summary::-webkit-details-marker {{ display: none; }}
  .faq summary::after {{ content: "+"; color: var(--brand); font-weight: 400; font-size: 20px; }}
  .faq[open] summary::after {{ content: "−"; }}
  .faq p {{ padding: 0 0 18px; color: var(--ink-2); font-size: 14.5px; }}

  .notice {{
    background: var(--warn-soft); border: 1px solid #fde68a; border-radius: var(--radius);
    padding: 22px; color: #7c2d12;
  }}
  .notice h3 {{ color: #7c2d12; }}
  .notice p {{ font-size: 14.5px; }}

  footer {{ padding: 34px 0 46px; color: var(--ink-3); font-size: 14px; }}
  .foot-links {{ display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 10px; }}
</style>
</head>
<body>

<header>
  <div class="wrap">
    <span class="badge">◆ 免费 · 开源 · 无需注册</span>
    <h1>医学文献智能摘要与检索系统</h1>
    <p class="lede">
      直连 PubMed 官方接口。从一个关键词到论文全文的中文摘要、原文溯源、统计指标与图表解读，
      一次做完——不用再在检索、翻译、笔记、截图之间来回切换。
    </p>
    <div class="cta">
      <a class="btn btn-main" href="{CLOUD}" target="_blank" rel="noopener">在线直接使用</a>
      <a class="btn btn-ghost" href="{REPO}#readme" target="_blank" rel="noopener">查看源码与说明</a>
    </div>
    <div class="trust">
      <span>数据来源：PubMed / PMC（NCBI 下属 NLM）</span>
      <span>当前版本 {v}</span>
      <span>不收集个人身份信息</span>
      <span>Windows 桌面版可离线运行</span>
    </div>
  </div>
</header>

<section>
  <div class="wrap">
    <div class="sec-head">
      <h2>它长什么样</h2>
      <p>下面是真实运行界面的截图，不是设计稿。</p>
    </div>
    <div class="shots">
{shots_html}
    </div>
  </div>
</section>

<section class="sec-alt">
  <div class="wrap">
    <div class="sec-head">
      <h2>能做什么</h2>
      <p>八项能力，覆盖从检索到写作的完整链路。</p>
    </div>
    <div class="grid">
{feat_html}
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <h2>三步开始</h2>
    </div>
    <ol class="steps">
{steps_html}
    </ol>
  </div>
</section>

<section class="sec-alt">
  <div class="wrap">
    <div class="sec-head">
      <h2>常见问题</h2>
    </div>
{faq_html}
  </div>
</section>

<section>
  <div class="wrap">
    <div class="notice">
      <h3>⚕️ 使用前必读</h3>
      <p>
        本工具生成的摘要、翻译与数据分析均由算法或大模型自动完成，<b>可能存在遗漏、偏差或曲解</b>。
        <b>它不能作为临床诊断、用药或治疗方案的依据。</b>
        任何诊疗决策都请核对文献原文，并以专业医师的判断为准。
      </p>
      <p style="margin-top:10px">
        文献元数据来自 PubMed，请遵守 NCBI 的使用条款，仅供学习与研究使用。
        不要在检索框里粘贴含患者姓名、住院号等身份信息的文本。
      </p>
    </div>
  </div>
</section>

<footer>
  <div class="wrap">
    <div class="foot-links">
      <a href="{CLOUD}" target="_blank" rel="noopener">在线使用</a>
      <a href="{REPO}" target="_blank" rel="noopener">GitHub 仓库</a>
      <a href="{REPO}/issues" target="_blank" rel="noopener">报错与建议</a>
      <a href="{REPO}#privacy" target="_blank" rel="noopener">隐私说明</a>
    </div>
    <p>医学文献智能摘要与检索系统 · {v} · 数据来源 PubMed / PMC（NCBI 下属 NLM）</p>
  </div>
</footer>

</body>
</html>
"""


def main() -> int:
    out = build()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    kb = os.path.getsize(OUT) // 1024
    has_home = "01_home" in out or "data:image" in out
    print(f"已生成 {OUT}（{kb} KB，内嵌截图：{'有' if has_home else '无'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())