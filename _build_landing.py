"""生成单文件落地页 index.html（P1 任务 5）。

为什么要生成器而不是手写 HTML：落地页要内嵌真实界面截图（base64），
图片会随版本变。写成生成器后，`_shot.py` 重拍一次再跑本脚本即可同步更新。

图片来源：按基名在 `_preview/`（CDP 实拍，本地工作目录）与 `docs/shots/`
（已入库的存档图）里依次查找，先找 `.png` 再找 `.jpg`；找到 PNG 时会自动
降采样并转成 JPEG 再内嵌，避免落地页体积失控。

用法：
    python _shot.py _preview 8501 --flow --privacy   # 先拍真实截图
    python _shot.py _preview 8501 --review           # 再拍综述工作台
    python _build_landing.py                         # 最后生成 index.html
"""
from __future__ import annotations

import base64
import html
import io
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIRS = [os.path.join(ROOT, "_preview"), os.path.join(ROOT, "docs", "shots")]
OUT = os.path.join(ROOT, "index.html")

MAX_W = 1280          # 内嵌前的最大宽度
QUALITY = 82          # 内嵌 JPEG 质量

REPO = "https://github.com/Fy66666-fy/medical-lit-system"
CLOUD = "https://medical-lit-system-fy.streamlit.app/"


def version() -> str:
    try:
        sys.path.insert(0, ROOT)
        from version import APP_VERSION

        return APP_VERSION
    except Exception:
        return "v2.7.0"


def _find(base: str) -> str:
    """按基名查图：png 优先（无损、便于再压缩），其次 jpg。"""
    for d in SHOTS_DIRS:
        for ext in (".png", ".jpg"):
            p = os.path.join(d, base + ext)
            if os.path.exists(p):
                return p
    return ""


def _to_jpeg_bytes(path: str) -> bytes:
    """PNG 原图 → 最宽 MAX_W、质量 QUALITY 的 JPEG；已经是 JPEG 就直接用。"""
    if path.lower().endswith((".jpg", ".jpeg")):
        with open(path, "rb") as f:
            return f.read()
    try:
        from PIL import Image
    except ImportError:                      # 没有 Pillow 就退回原图
        with open(path, "rb") as f:
            return f.read()
    im = Image.open(path).convert("RGB")
    w, h = im.size
    if w > MAX_W:
        im = im.resize((MAX_W, int(h * MAX_W / w)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


def data_uri(base: str) -> str:
    path = _find(base)
    if not path:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(_to_jpeg_bytes(path)).decode("ascii")


# 落地页能力清单。第三个元素为 True 表示 v3.x 迭代新增，列表里会打「新」角标。
FEATURES = [
    ("🔍", "文献检索", "直连 PubMed 官方接口，主关键词 / 副关键词 / 作者 / 期刊 / "
                     "日期区间 / 排序自由组合，结果卡片直接给出 DOI、PMC 全文与 PDF 入口。", False),
    ("📝", "智能摘要", "抽取式摘要离线可用，按章节结构与信息量给句子打分；"
                     "配置大模型后可生成「目的 / 方法 / 结果 / 结论」结构化总结。", False),
    ("🌏", "中英对照翻译", "腾讯云机器翻译为主（每月 500 万字符免费额度），"
                        "自动回退 MyMemory 免费接口；摘要、关键词、图表说明都能译。", False),
    ("🔍", "原文定位溯源", "摘要里的每一句、每一个关键数值都能点回原文位置，"
                        "并高亮显示前后文——核查结论时不必再翻原文。", False),
    ("📊", "统计指标提取", "自动从正文抽取 P 值、置信区间、样本量、风险比、"
                        "均值±标准差，按句高亮并可溯源。", False),
    ("🖼", "图表解读", "解析开放获取（PMC）文献的图表图片与图注，"
                     "逐图生成中文解读并总结图表共同讲述的研究故事。", False),
    ("🧾", "综述工作台", "把已检索 / 已收藏的一批文献摆到桌面上：自动生成横向对比表"
                     "（设计 / 样本量 / 终点 / 效应量 / 结论），同一主题下结论打架自动提示，"
                     "PRISMA 式筛选记录与综述初稿骨架一键导出；叙述段可选"
                     "<b>学术严谨 / 简明扼要</b>、<b>中文 / 英文</b>与所用模型。"
                     "空单元格标明是<b>摘要未提及</b>还是<b>有摘要未抽到</b>，"
                     "抽错的字段可直接在表格里手工修正。", True),
    ("🩺", "证据与适用性", "为每篇文献标注研究类型与牛津 CEBM 简化证据等级，"
                        "按 32 条规则提示小样本、无对照、单中心、替代终点、企业资助、"
                        "未提及意向性分析等偏倚线索，并从人群 / 干预 / 终点 / 随访 / 场景"
                        "五个维度对照临床适用性。", True),
    ("🧰", "结构化评价与 GRADE", "按研究设计自动匹配规范量表：随机对照试验 → RoB 2，"
                            "队列 / 病例对照 / 横断面 → NOS，系统评价 → AMSTAR-2，"
                            "指南 → AGREE II，动物实验 → SYRCLE；并给出 GRADE 起始等级与"
                            "5 个降级 / 3 个升级因素的自查入口——<b>只列问题，不替你判定</b>。", True),
    ("🗂", "文献库管理", "收藏可归档到课题分组，用标签标记研究类型 / 干预 / 人群，"
                      "并写下阅读笔记；支持批量整理与「分组 + 标签 + 关键词」三档筛选，"
                      "筛选结果连同标注导出 Markdown。", True),
    ("📄", "本地 PDF 解析", "上传 PDF 直接解析：分栏版面重建、章节识别、表格抽取与整页渲染。"
                        "付费订阅文献不再卡在拿不到全文——解析结果可直接做全文摘要、"
                        "原文定位，并纳入综述工作台与六种引用格式导出。", True),
    ("📦", "导出与引用", "批量抓取多篇文献全文，摘要、关键词、图表说明一键导出 Excel；"
                       "文献可按 BibTeX / RIS / EndNote / MEDLINE / Vancouver / GB/T 7714 "
                       "六种格式导出，直接导入 Zotero、EndNote 等参考文献管理器。", True),
    ("🛡", "隐私与配额", "不收集任何个人身份信息；云端按会话隔离数据；"
                       "内置用量配额，成本封顶，可随时切回自带密钥。", False),
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
     "唯一经过第三方的是你主动发起的翻译与大模型请求——请不要粘贴含患者身份信息的文本。"
     "补充一句（v3.7.0 起）：工具会<b>在本机</b>记一个「你检索了几次」的数字，用于决定"
     "要不要在侧边栏邀请你填一份<b>自愿的</b>体验问卷——计数与问卷答案都只存你自己的设备，"
     "<b>绝不自动上传</b>；问卷填不填、发不发给我们，都由你决定。"),
    ("综述工作台能直接产出可投稿的综述吗？",
     "不能，它产出的是<b>初稿骨架</b>。对比表、筛选记录（PRISMA）与参考文献由规则引擎从摘要中自动抽取，"
     "需要作者判断的地方一律写成 <code>【待补充：…】</code> 占位，不会被误当成已写好的结论。"
     "证据等级与偏倚提示是<b>可解释的核对清单</b>，不是 GRADE / RoB 2 的正式分级。"),
    ("对比表里的空白格代表什么？",
     "空白格现在是三种明确含义：<b>摘要未提及</b>（原文确实没写，没什么可补的）、"
     "<b>有摘要未抽到</b>（摘要里有该字段的痕迹、工具却没抽出来，<b>建议回原文核对</b>）、"
     "<b>无摘要</b>（数据库未提供摘要）。过去一律留白，用户没法判断是「原文没写」还是「工具漏了」——"
     "后者是工具的能力边界，而不是原文的问题。每篇还会给出<b>结构化完整度 x/6</b>，"
     "一眼看出哪几篇值得回原文补字段。"),
    ("抽错了怎么办？",
     "样本量 / 人群 / 主要终点 / 关键效应量 / 结论这 5 列<b>可以直接在表格里改</b>，"
     "回原文核对后填真实值即可，修正值优先生效、随导出一起走（刷新或切页都不丢）。"
     "改「样本量」会重算证据强度、改「结论」会重判结论倾向；研究设计 / 证据等级 / 偏倚提示读的是"
     "原始摘要，不随手工修正变化——想改那几项请按规范工具评价全文后作判断。"),
    ("为什么「证据与适用性」不说「低风险 / 高风险」？",
     "因为正式的风险偏倚判定必须逐条回答信号问题并阅读全文，本工具读到的只是摘要。"
     "所以我们只用「重点核对 / 建议核对 / 信息缺失」三档，并把「摘要未提及」单独归类——"
     "摘要没写研究中心数，不等于单中心。需要正式评价时，页面会按研究设计给出"
     "<b>RoB 2 / NOS / AMSTAR-2 的信号问题清单与 GRADE 降级 / 升级自查入口</b>，"
     "照着回全文逐条核对即可。"),
    ("上传 PDF 安全吗？会不会涉及版权问题？",
     "上传的文件<b>只在内存中解析，不写磁盘、不进缓存、不外传</b>，会话结束即释放。"
     "但<b>版权责任在使用者一方</b>——上传即表示你有权访问该文献，所以上传区前有一道确认门。"
     "扫描件（无文本层）目前会明确提示需先 OCR，不会给出「假装能读」的结果。"),
]

STEPS = [
    ("打开链接", "浏览器访问在线版，或下载桌面版双击打开。无需注册、无需安装 Python。"),
    ("输入检索式", "先用一个宽泛的英文关键词试水，例如 <code>metformin cardiovascular outcomes</code>，"
                   "再逐步加上作者、期刊、日期等限定。"),
    ("读摘要并溯源", "点开任意一篇的中文摘要；觉得哪句关键，点它就能跳回原文高亮位置核对。"),
    ("汇总成综述", "把要纳入的文献勾选收藏，进「综述工作台」一键生成横向对比表、结论冲突核查、"
                   "证据与适用性评估和初稿骨架。"),
]

# 典型场景案例（v3.6.0，C7 内容运营）。每条都写成「照着做即可」的步骤，
# 且每一步都对应界面上真实存在的入口——不写没有对应功能的空话。
CASES = [
    {
        "emoji": "🧭",
        "title": "开题前 30 分钟，摸清一个课题的证据家底",
        "who": "开题报告 · 选题论证 · 组会汇报",
        "goal": "这个方向到底有多少可用证据？主要研究之间的结论一致吗？",
        "steps": [
            "先用一个宽泛的英文关键词试水（如 <code>metformin cardiovascular outcomes</code>），"
            "不加任何限定，先看总命中量与年份分布。",
            "再逐层加限定收敛：日期区间取近 5 年、文献类型勾选 RCT 与 Meta 分析，按被引或年份排序。",
            "读 10~15 篇的中文摘要；觉得哪句关键，点它就跳回英文原文的高亮位置核对，不必来回翻页。",
            "相关文献当场收藏，归入分组「开题 · 二甲双胍 CV」，顺手打上研究类型与人群标签。",
            "进综述工作台看横向对比表，把主要终点的效应量并排摆开——结论打架的地方会自动提示。",
        ],
        "output": "横向对比表（CSV / Markdown）+ PRISMA 式筛选记录 + 「有多少 RCT、结论是否一致」的判断依据",
        "time": "约 30 分钟（摘要与对比表是秒级生成，时间主要花在读）",
        "caveat": "",
    },
    {
        "emoji": "✍️",
        "title": "写文献综述：从一批文献到一份可改的初稿",
        "who": "课程作业 · 毕业论文综述 · 投稿前的草稿",
        "goal": "把「读过的文献」变成「结构完整、事实可查的初稿」，而不是从空白页开始凑字。",
        "steps": [
            "在「我的文献库」把纳入的文献归到一个分组，排除掉的移到「排除」分组并写一句理由"
            "——PRISMA 的筛选记录就是从这一步长出来的。",
            "进综述工作台生成横向对比表，先看设计 / 样本量 / 终点 / 效应量是否齐全；"
            "空白格会标明是「摘要未提及」还是「有摘要未抽到」——后者回原文核对后，"
            "直接在表格里改就行，改完连导出一起生效。",
            "看「结论冲突核查」：同一主题下打架的地方会列出人群 / 剂量 / 终点定义 / 随访时长等可能原因，"
            "<b>只提示要核对，不判断谁对谁错</b>。",
            "用「证据与适用性」给每篇标注研究类型与牛津 CEBM 简化等级，再看偏倚提示"
            "（小样本 / 无对照 / 单中心 / 替代终点 / 企业资助…）。",
            "需要正式评价时，「结构化评价与 GRADE 自查」会按研究设计给出 RoB 2 / NOS / AMSTAR-2 "
            "的信号问题清单，回全文逐条回答即可。",
            "生成初稿骨架；再让大模型写「结果概述 + 讨论」，风格可选学术严谨 / 简明扼要，语言可选中文 / 英文。",
            "导出骨架与叙述段、对比表、参考文献（BibTeX / RIS / EndNote / MEDLINE / Vancouver / GB/T 7714）。",
        ],
        "output": "带占位符的初稿骨架 + 横向对比表 + 参考文献条目",
        "time": "首次约 1 小时；之后同一课题补文献只要几分钟",
        "caveat": "骨架是<b>初稿</b>不是成品：<code>【待补充：…】</code> 必须自己回原文补，"
                  "叙述段每一句都要核对事实——提示词里已硬性禁止编造样本量 / 效应量 / P 值 / 结论。",
    },
    {
        "emoji": "📄",
        "title": "手里只有付费订阅的 PDF，也要读透并引用",
        "who": "机构订阅下载的 PDF · 导师发来的文献 · 扫描件",
        "goal": "拿不到 PMC 开放全文时，别让「读不了」变成「不纳入」。",
        "steps": [
            "上传 PDF（先勾选版权与合规确认）。文件只在内存中解析——不写磁盘、不进缓存、不外传，"
            "会话结束即释放。",
            "自动解析出标题 / 作者 / 期刊 / 年份与分章节正文（摘要 / 引言 / 方法 / 结果 / 讨论）。",
            "做全文摘要，用关键词定位实时列出所有命中原句，表格与图表也能单独解析。",
            "需要时把它一并纳入综述工作台，和 PMC 免费文献混排对比。",
            "导出引用（BibTeX / RIS 等六种格式），直接导入 Zotero / EndNote。",
        ],
        "output": "一份可检索的全文 + 规范的引用条目 + 进入综述对比表的一行",
        "time": "单篇解析约 10~30 秒",
        "caveat": "单篇默认限 20 MB / 200 页；扫描件（无文本层）会明确提示需先 OCR，"
                  "不会给出「假装能读」的结果。",
    },
    {
        "emoji": "📚",
        "title": "科室小讲课 / 读书报告：一周内跟上一个新进展",
        "who": "临床医生 · 规培带教 · 组会分享",
        "goal": "快速攒齐一节课的素材，且每个数字都能指回原文。",
        "steps": [
            "关键词 + 日期区间限定最近 6~12 个月，必要时再按高影响期刊收窄。",
            "用中文摘要快速过一遍，选出 5~8 篇要讲的；图表说明也能中文解读，直接拿来当讲义配图。",
            "关键数值（P 值 / 95%CI / HR·OR·RR / 样本量）自动扫出并标在原句上，讲课前核对一遍不吃力。",
            "用「证据与适用性」判断每条结论适不适合你们的患者人群"
            "（人群 / 干预 / 终点 / 随访 / 场景五维对照）。",
            "导出 Excel 汇总（文献汇总 / 章节明细 / 统计指标三个工作表）当讲义底稿。",
        ],
        "output": "Excel 讲义素材 + 每条结论的原文出处与适用性备注",
        "time": "5~8 篇约 40 分钟",
        "caveat": "",
    },
]

# 使用技巧（v3.6.0）。每条都是「第一次用容易漏掉」的具体操作，不写泛泛而谈的提示。
TIPS = [
    ("召回太少？先看「实际执行的检索式」",
     "加了字段限定（<code>aspirin[tiab]</code>）或用引号扩住短语，会<b>静默关掉</b> PubMed 的自动词表映射，"
     "同义词就此丢失。检索结果页的折叠区展示的是映射之后真正执行的检索式——"
     "如果它只是把你的原话原样回显，说明映射没生效。"),
    ("用 MeSH 词表把同义词显式补回去",
     "查 NLM 官方词表拿到主题词与全部入口词，一键 OR 进检索式："
     "<code>(\"Lung Neoplasms\"[MeSH Terms] OR \"Lung Cancer\"[tiab] …)</code>。"
     "刻意不做词形还原、不猜缩写——只增删你能看见的东西。"),
    ("读英文摘要吃力，就开中英对照",
     "每句都能点回原文，关键数值自动扫出并定位到原句。中文摘要走机器翻译，"
     "质量优于免费兜底接口，但关键术语仍建议对照原文核对。"),
    ("收藏 ≠ 管理",
     "分组管课题、标签管跨组维度（研究类型 / 干预 / 人群）、笔记放判断（为什么纳入 / 排除）。"
     "三者各管一层；导出 Markdown 时标注一并带上，写综述时不必再回忆当初为什么留下它。"),
    ("综述纳入多少篇合适？",
     "3 篇以下的对比表意义有限；超过 30 篇建议先按分组收窄到同一人群、同一终点再对比。"
     "结论冲突核查在 5~20 篇时最好用。"),
    ("大模型额度怎么省？",
     "抽取式摘要、对比表、证据等级、偏倚提示<b>全部离线</b>，不花任何额度；"
     "只有「结构化总结」和综述「叙述段」需要你自己的 Key。叙述段按风格 + 语言分开缓存，"
     "切风格不会命中旧结果，重复生成同一组合也不会重复计费。"),
    ("桌面版可以离线跑",
     "除检索与翻译外，本地 PDF 解析、综述工作台、证据化与引用导出都在本机完成。"
     "Windows 免安装，整个文件夹一起分发即可。"),
]


def cases_html() -> str:
    out = []
    for c in CASES:
        steps = "\n".join(f"            <li>{s}</li>" for s in c["steps"])
        caveat = (f'\n        <p class="case-caveat">{c["caveat"]}</p>'
                  if c.get("caveat") else "")
        out.append(f"""      <article class="case">
        <div class="case-head">
          <span class="case-emoji" aria-hidden="true">{c['emoji']}</span>
          <div>
            <h3>{c['title']}</h3>
            <p class="case-who">适用：{c['who']}</p>
          </div>
        </div>
        <p class="case-goal"><b>要解决的问题</b>　{c['goal']}</p>
        <ol class="case-steps">
{steps}
        </ol>{caveat}
        <div class="case-foot">
          <p><b>产出</b>　{c['output']}</p>
          <p><b>耗时</b>　{c['time']}</p>
        </div>
      </article>""")
    return "\n".join(out)


def tips_html() -> str:
    return "\n".join(
        f"""      <div class="tip">
        <h3>{t}</h3>
        <p>{d}</p>
      </div>""" for t, d in TIPS)


def build() -> str:
    v = version()
    home = data_uri("01_home")
    results = data_uri("02_results")
    rv_table = data_uri("06_review_table")
    rv_evidence = data_uri("10_review_evidence")
    rv_appraisal = data_uri("14_appraisal")
    rv_conflicts = data_uri("07_review_conflicts")
    rv_draft = data_uri("09_review_draft")
    cite_shot = data_uri("11_cite_export")
    lib_shot = data_uri("12_library")
    lib_cards = data_uri("12b_library_cards")
    pdf_shot = data_uri("13_pdf")

    feat_html = "\n".join(
        f"""      <article class="feat">
        <div class="feat-ico">{html.escape(ico)}</div>
        <h3>{html.escape(title)}{' <span class="tag-new">新</span>' if is_new else ''}</h3>
        <p>{desc}</p>
      </article>""" for ico, title, desc, is_new in FEATURES)

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

    case_html = cases_html()
    tip_html = tips_html()

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
    if pdf_shot:
        shots.append(f"""      <figure>
        <img src="{pdf_shot}" alt="PDF 全文分析：上传本地 PDF 后自动解析出标题 / 作者 / 期刊 / 年份与分章节正文" loading="lazy">
        <figcaption><b>本地 PDF 解析（v3.2.0 新增）</b>　付费订阅的文献常常拿不到开放全文，而手里下载的 PDF 恰恰是最常见的形态。现在可以直接上传 PDF：自动解析出标题、作者、期刊、年份与 <b>分章节正文</b>（摘要 / 引言 / 方法 / 结果 / 讨论），再接上全文摘要、原文定位、图表表格解析与六种引用格式导出。解析全程在内存中进行，<b>文件不落盘、不上传第三方</b>；上传前需先勾选版权与合规确认，单篇默认限 20 MB / 200 页。</figcaption>
      </figure>""")
    if lib_cards:
        shots.append(f"""      <figure>
        <img src="{lib_cards}" alt="文献卡片：顶部标出所属分组、标签与「有笔记」状态，展开即可编辑分组 / 标签 / 笔记" loading="lazy">
        <figcaption><b>文献库管理（v3.1.0 新增）</b>　收藏不再是平铺的一列：每篇可归入课题分组、打上跨组标签（研究类型 / 干预 / 人群），并写下自己的阅读笔记——「为什么纳入 / 排除」「样本量存疑」这类只在脑子里过的判断，终于有地方放。卡片顶部直接标出分组、标签与「有笔记」状态；点开「摘要全文」仍能回看原文。</figcaption>
      </figure>""")
    if lib_shot:
        shots.append(f"""      <figure>
        <img src="{lib_shot}" alt="我的文献库：分组 / 标签 / 笔记统计，分组与标签管理、批量整理，以及分组 + 标签 + 关键词三档筛选" loading="lazy">
        <figcaption><b>分组 · 标签 · 批量整理</b>　四张统计卡一眼看清存量；分组与标签都可随时新建、重命名、删除（<b>删除分组不会丢文献</b>，组内文献退回「未分组」）；勾选多篇即可批量移动分组、打标签或移出收藏，再按「分组 + 标签 + 关键词」筛选，导出时连同标注一起写进 Markdown——「先筛后导」比「全量导出再手动删」省事得多。</figcaption>
      </figure>""")
    if cite_shot:
        shots.append(f"""      <figure>
        <img src="{cite_shot}" alt="引用导出：BibTeX / RIS / EndNote / MEDLINE / Vancouver / GB/T 7714 六种格式，页面上就地预览" loading="lazy">
        <figcaption><b>引用导出（v3.0.1 新增）</b>　六种格式任选，先在页面上看清生成结果再下载。检索结果、我的文献库、综述纳入文献三处都能导出，文件可直接导入 Zotero / EndNote / NoteExpress，不必再手抄参考文献。</figcaption>
      </figure>""")
    shots_html = "\n".join(shots)

    # ---------- 综述工作台（v3.0 新增，落地页的第二组截图） ----------
    rv = []
    if rv_table:
        rv.append(f"""      <figure>
        <img src="{rv_table}" alt="综述工作台 · 横向对比表：研究设计、样本量、人群、主要终点、效应量、结论、证据等级并排呈现" loading="lazy">
        <figcaption><b>① 横向对比表</b>　把 5 篇文献的设计、样本量、人群、主要终点、效应量与结论摆在同一张表上；每个字段都附原文片段，可回查判定依据。导出 CSV / Markdown。</figcaption>
      </figure>""")
    if rv_evidence:
        rv.append(f"""      <figure>
        <img src="{rv_evidence}" alt="证据与适用性：研究类型分层、证据等级参考、偏倚风险提示（附原文依据）、临床适用性五维对照" loading="lazy">
        <figcaption><b>② 证据与适用性（v3.0 新增）</b>　每篇标注研究类型与牛津 CEBM 简化等级，逐条给出偏倚提示并附原文依据；右侧是人群 / 干预 / 终点 / 随访 / 场景五维适用性对照。</figcaption>
      </figure>""")
    if rv_conflicts:
        rv.append(f"""      <figure>
        <img src="{rv_conflicts}" alt="结论冲突核查：同一主题下不同研究的结论不一致时给出提示与可能原因" loading="lazy">
        <figcaption><b>③ 结论冲突核查</b>　同一主题下不同研究结论打架时高亮提示，并给出人群 / 剂量 / 终点定义 / 随访时长等可能原因。<b>只提示需要核对，不判断谁对谁错。</b></figcaption>
      </figure>""")
    if rv_draft:
        rv.append(f"""      <figure>
        <img src="{rv_draft}" alt="综述初稿骨架：按引言—方法—结果—讨论—结论—参考文献组织，需作者判断处留占位符" loading="lazy">
        <figcaption><b>④ 综述初稿骨架</b>　按「引言—资料与方法—结果—讨论—结论—参考文献」组织，事实来自自动抽取，需作者判断处写成 <code>【待补充：…】</code>，参考文献按 Vancouver 格式。v3.5.0 起还可让大模型补写「结果概述 + 讨论」叙述段，风格选<b>学术严谨 / 简明扼要</b>、语言选<b>中文 / 英文</b>——风格只改表述，<b>不得编造数据</b>的硬约束在任何组合下都不放宽。</figcaption>
      </figure>""")
    if rv_appraisal:
        rv.append(f"""      <figure>
        <img src="{rv_appraisal}" alt="结构化评价工具与 GRADE 自查入口：按研究设计自动匹配 RoB 2 / AMSTAR-2 / NOS 的信号问题清单，并列出 GRADE 起始等级与降级 / 升级因素" loading="lazy">
        <figcaption><b>⑤ 结构化评价工具与 GRADE 自查（v3.3.0 新增）</b>　摘要层面只能给线索，正式评价必须回全文。这里按研究设计自动匹配规范量表的信号问题清单——随机对照试验 → <b>RoB 2</b>（5 个域）、队列 / 病例对照 / 横断面 → <b>NOS</b>、系统评价 → <b>AMSTAR-2</b>（16 项，标出 7 个关键域）、指南 → <b>AGREE II</b>、动物实验 → <b>SYRCLE</b>，并给出 <b>GRADE</b> 起始等级与 5 个降级 / 3 个升级因素的判据。<b>只列问题，不替你判定</b>——每份工具都注明真实出处，并声明为便于核对做了大幅简化。</figcaption>
      </figure>""")
    rv_html = "\n".join(rv)

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
  .tag-new {{
    display: inline-block; vertical-align: middle; font-size: 11px; font-weight: 600;
    color: #fff; background: var(--brand-2); border-radius: 999px;
    padding: 1px 7px; margin-left: 6px; letter-spacing: .5px;
  }}

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

  .case {{
    border: 1px solid var(--line); border-radius: var(--radius);
    background: #fff; padding: 26px; margin-bottom: 18px;
  }}
  .case-head {{ display: flex; gap: 14px; align-items: flex-start; margin-bottom: 14px; }}
  .case-emoji {{ font-size: 24px; line-height: 1.2; }}
  .case-who {{ font-size: 13px; color: var(--ink-3); margin-top: 4px; }}
  .case-goal {{
    font-size: 14.5px; color: var(--ink-2);
    background: var(--bg-2); border-radius: 10px; padding: 11px 15px;
  }}
  ol.case-steps {{ margin: 15px 0 0; padding-left: 22px; display: grid; gap: 9px; }}
  ol.case-steps li {{ font-size: 14.5px; color: var(--ink-2); }}
  .case-caveat {{
    margin-top: 12px; font-size: 13.5px; color: #7c2d12;
    background: var(--warn-soft); border-radius: 10px; padding: 10px 14px;
  }}
  .case-foot {{
    margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line);
    display: grid; gap: 6px;
  }}
  .case-foot p {{ font-size: 14px; color: var(--ink-2); }}

  .tips {{ display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }}
  .tip {{ border-left: 3px solid var(--brand-2); padding: 2px 0 2px 15px; }}
  .tip h3 {{ font-size: 15.5px; }}
  .tip p {{ font-size: 14px; color: var(--ink-2); margin-top: 6px; }}

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
      再一路走到综述初稿——不用再在检索、翻译、笔记、参考文献管理器之间来回切换。
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
      <h2>从一批文献，到一篇综述初稿</h2>
      <p>v3.0 新增的<b>综述工作台</b>把一个课题下的文献一次性摆到桌面上。横向对比表、结论冲突核查、PRISMA 筛选记录与初稿骨架全部由<b>离线规则引擎</b>完成，不调用大模型、不消耗任何额度；只有可选的「叙述段」（v3.5.0）才会用到你自己配置的模型。</p>
    </div>
    <div class="shots">
{rv_html}
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <h2>能做什么</h2>
      <p>十三项能力，覆盖从检索、精读到综述写作与导出的完整链路（带「新」角标为 v3.x 迭代新增）。</p>
    </div>
    <div class="grid">
{feat_html}
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <h2>四步开始</h2>
    </div>
    <ol class="steps">
{steps_html}
    </ol>
  </div>
</section>

<section class="sec-alt">
  <div class="wrap">
    <div class="sec-head">
      <h2>典型场景</h2>
      <p>四个真实用法，从「开题前摸清一个课题」到「把付费 PDF 读透并引用」。
        每一步都对应界面上真实存在的入口，照着做即可。</p>
    </div>
{case_html}
  </div>
</section>

<section>
  <div class="wrap">
    <div class="sec-head">
      <h2>使用技巧</h2>
      <p>七条省时间的用法——多数人第一次用会漏掉。</p>
    </div>
    <div class="tips">
{tip_html}
    </div>
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

<section class="sec-alt">
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