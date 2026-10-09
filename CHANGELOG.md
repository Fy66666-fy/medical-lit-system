# 更新日志

## v3.5.0 · 2026-10-09

P3-C6 综述初稿：叙述段支持选模型 / 选风格 / 选语言

问题：可选的大模型叙述段只有一种写法、且只会输出中文。但综述初稿的两类用户诉求并不一样——
要投英文期刊的研究生需要成段的英文，只想快速扫一遍要点的临床医生则嫌「学术严谨」啰嗦；
而工具的定位本来就允许用户自带任意 OpenAI 兼容模型，用哪一档模型写正文也应该由用户决定。

- **新增两种风格**（`core/review.py` 的 `DRAFT_STYLES`）：
  **学术严谨**（书面学术语体、按研究设计分组、逐条标注来源）与
  **简明扼要**（直陈要点、去掉背景铺垫，篇幅约为严谨版的一半，仍保留来源标注与全部关键数值）。
- **新增两种输出语言**（`DRAFT_LANGUAGES`）：中文 / 英文。语言不只是换个措辞——
  提示词本身、事实行句式、缺失占位符与冲突类型标签都随语言切换：
  - 事实行：`Smith J 等（2023，随机对照试验，样本量 1200，效应量 HR 0.72…）`
    对应 `Smith J et al. (2023, randomized controlled trial, n=1200, effect size HR 0.72...)`；
  - **研究设计标签做中文→英文映射**（`_DESIGN_EN`），否则英文段落里会夹一个「随机对照试验」；
    冲突类型「结论极性 / 效应方向」同样映射；
  - 缺失占位符：中文「摘要未提供」↔ 英文 `not reported in the abstract`。
- **只改表述、不放宽约束**（这是本次最要紧的一条纪律）：风格与语言**都不影响**四条硬要求——
  只能使用给定事实 / 不得编造样本量·效应量·P 值·结论 / 事实缺失必须写占位符 / 不做临床推荐。
  否则一选「简明扼要」，模型就可能顺手把不确定的数字写成肯定句。这条已用离线断言在
  **两种风格 × 两种语言**共 4 种组合上逐条锁死。
- **提示词构造与网络调用解耦**：新增纯函数 `draft_prompt(topic, rows, conflicts, style, language)`
  返回 `(system, user)`，`draft_with_llm()` 只负责调接口。拆开是为了让上面那条纪律**可断言**——
  提示词是从接口里拿不出来的，离线测不了就守不住。
- **可选模型**（界面）：叙述段区新增「叙述段使用模型」下拉，含 9 个常用 OpenAI 兼容模型预设，
  默认「跟随侧边栏设置」。**诚实提示**：预设只是常用模型名的快捷方式、**不是白名单**，
  所选模型必须存在于用户自己配置的 API 地址下，否则接口会直接报错；拿不准就保持跟随侧边栏。
  这样「用便宜模型做批量摘要、用强模型写正文」成为可能，而地址×模型的配套关系仍由用户掌握。
- **缓存与额度**：缓存键带上风格与语言（`综述叙述/concise/en`），切换风格不会命中上一种风格的
  旧结果；输出额度随风格调整（严谨 2400 / 简明 1400 tokens）。
- 已知边界：英文叙述段的**事实来源仍是英文摘要的原文句式**，模型只做组织与转述；
  「简明」是提示词层面的篇幅约束，不是硬截断——模型仍可能写长，界面也没有替它裁剪。
- 界面会记录「这段是谁生成的」：正文上方标明 `风格 · 语言（模型）`；若之后改了设置却没重新生成，
  会明确提示「设置已改动，需重新点击按钮」，避免把上一版结果当成新设置的产物。
- 踩坑（值得记）：模型下拉最初把「当前侧边栏模型名」拼进 `format_func` 的显示串，
  于是两次渲染得到**不同字符串**，Streamlit 按显示串回查选项下标时直接抛
  `ValueError: '跟随侧边栏设置（未设置）' is not in list`，控件状态解析失败、整页中断。
  改为显示串恒定（当前生效模型放到 caption 里说明）后正常。**凡下拉显示串依赖会话状态，早晚踩这个坑。**
- 新增 39 项离线断言（`_test_review.py` 的 6.6 节，本套件合计 **179 项全绿**）：
  覆盖两种风格 × 两种语言的提示词差异与四条硬约束、事实行句式、设计标签英文化、
  缺失占位符、主题为空的兜底、未知键退回默认、以及用桩替网络层验证
  `draft_with_llm` 真的把风格/语言透传下去且**缓存键随其变化**、输出额度随风格调整。
- 冒烟测试（`_smoke_app.py`）新增 6b 段：在「已配置大模型」的前提下真跑一遍综述工作台，
  断言三个选择器出现、选项两档、默认「学术严谨 · 中文」与「跟随侧边栏设置」、
  UI 明确写出「禁止编造 / 缺失写摘要未提供」与「模型需与自配地址配套」，
  并**真实切换一次风格**验证界面与会话状态同步。
  注：AppTest 暴露的下拉 `options` 是**经 `format_func` 映射后的显示串**而非内部键，
  断言必须按显示串写——这一点已写进测试注释，免得下次再被绊。

## v3.4.0 · 2026-10-09

P3-C5 检索增强：MeSH 词表联动（自动扩展同义词）

问题：检索是裸关键词，漏同义词就丢结果。PubMed 本身有「自动词表映射」（ATM），
但它只在关键词与 MeSH 标题 / 入口词**精确匹配**时才生效；更关键的是，一旦用户加了
字段限定（`aspirin[tiab]`）或引号短语，ATM 会被**完全绕过**——同义词就此丢失，
而用户对此毫无察觉。

- **新增 `core/mesh.py`**：查 NLM MeSH 词表（走 NCBI `db=mesh` 的 esearch + esummary，
  统一经 `core/http.py` 限流与埋点，不加新依赖）。核心是**两级精确校验**：
  `db=mesh` 的 esearch 是模糊检索（搜 `aspirin` 首条返回的是 "Asthma, Aspirin-Induced"），
  所以必须取回候选逐个比对——只有「标题精确匹配」或「出现在入口词表里」才算命中，
  没有把握一律返回 `None`，绝不把「最像的那条」当成用户的意思。
  - **限定词（qualifier）一律不算命中**：`therapy` / `diagnosis` / `prevention` 在词表里
    的首条命中都是副主题词，它们只能挂在主题词后组合使用（`Aspirin/therapy`），
    单独当检索概念是错的。
  - 补充概念记录（补充记录，如药物 `pembrolizumab`）保留——药物与化学物质都在这里。
- **多词关键词的概念切分**：`split_concepts` 用「最长匹配优先」的贪心策略，
  `immunotherapy lung cancer` 切为 `immunotherapy` + `lung cancer`（而不是三个单词），
  并对每个概念查词表；查不到的词原位保留，不丢概念。
- **三档模式**（检索页）：「关闭 / **仅提示（默认）** / 自动扩展同义词」。
  仅提示模式展示识别到的主题词、命中方式、定义、树号与全部入口词，并给出扩展后的检索式；
  自动扩展模式把它作为实际提交的检索式。带字段限定、布尔运算符或引号短语的**手写检索式
  一律不改写**，并说明原因。
- **展示 PubMed 实际执行的检索式**：`search()` 记录 esearch 返回的 `querytranslation`，
  检索后折叠展示。如果这里只是把原话原样回显，就说明自动映射没生效——这一条把
  「为什么召回是这样」直接摊在用户面前，且**不额外消耗任何配额**。
- **文献卡新增 MeSH 主题词**：解析 efetch 的 `MeshHeadingList`（DescriptorName 的
  `MajorTopicYN`、QualifierName 及其各自的 major 标记），★ 标出主要主题。
- **综述对比表新增「MeSH 主要主题」列**：`review.mesh_topics()` 把 NLM 标引压成一行
  （有主要主题只列主要主题，没有则退回全文主题词并注明），作为人群 / 疾病字段的权威补充。
- 纠错：`pubmed.mesh_suggest` 改名为 `spelling_suggest`——它一直是 NCBI espell 的
  **拼写建议**，与 MeSH 词表无关，旧名容易误导（保留旧名作兼容别名）。
- 修复：efetch 返回 `PubmedBookArticle`（书籍章节）时会被静默丢弃，现在会记日志说明。

⚠️ 已如实标注的边界：**NLM 人工标引滞后数月到一年，最新发表的文献通常还没有 MeSH 主题词**，
此时该列为空属正常现象（UI 与文档均已说明，不当成解析失败）。MeSH 词表缓存 365 天，
单次分析最多 8 次词表查询。

- 新增 `_test_mesh.py`（63 项断言，全部离线：`http.get` 桩替，含限定词排除、
  入口词上限、超长检索式保护、缓存只查一次、MeshHeadingList 解析、`mesh_topics`）；
  全量 17 套件 / 383 条离线断言；CI 增至 20 步
- 修复桌面版 `selftest` 的假失败（`desktop_app.py`）：自检里 `emit()` 用 `print()`
  回显，原注释以为「无控制台时 print 会安全跳过」——但当 stdout 是被重定向的管道、
  且带着编不了中文的 locale 编码（实测 cp1252）时，`print` 会直接抛 `UnicodeEncodeError`，
  把「exe 能否解析 PDF」这个真问题掉包成「控制台能否打中文」的假问题，自检在第一步就中断。
  现在先把 stdout 编码钉成 UTF-8，再给 `print` 加兜底，**绝不因「打不出来」而中断自检**。
- 桌面版重打包 `dist_v20`（含上述修复），三段式验证全绿：静态检查 13 项全 OK，
  `selftest` 回报 **v3.4.0** 且真解析样本 PDF（4 页 / 6 标题 / 1 表格，首页渲染 PNG 魔数正确）→ PASS，
  server 模式健康检查 2.0s、首页 HTTP 200

## v3.3.1 · 2026-10-09

P3-C4.1 综述工作台可读性：用回结构化分段，修复"大片未明确 / 未识别"（A 组）

问题：综述工作台横向对比表里，人群、主要终点等字段大量显示空白或"未明确"，
结论倾向也有近半数判为"未明确"，使工作台近乎不可用。

根因：PubMed 摘要的段标签（`AbstractText@Label`）在拼接纯文本时被抹平，
抽取器只能靠单一正则在整段文字里"猜"哪段是结论、哪段是人群；结论还因此
被误取成 RESULTS 段末句。实测 7 篇演示文献：人群空 5 篇、主要终点空 6 篇、
结论倾向"未明确" 3 篇。

- **保留摘要分段信息**（core/pubmed.py）：解析 efetch XML 时保留 `AbstractText`
  的 `Label`（缺失时退回 `NlmCategory`），存入 `article["abstract_sections"]`；
  纯文本 `abstract` 仍照旧拼接，向后兼容。PDF 解析产物（core/pdfdoc）无需改动。
- **新增摘要分段器**（core/review.py `_split_sections`）：Label 分段与纯文本
  标签切段**互补合并**。标签映射到规范段名（BACKGROUND / OBJECTIVE / METHODS /
  SETTING / PATIENTS / INTERVENTIONS / OUTCOMES / RESULTS / CONCLUSIONS），
  复合标签（`METHODS AND RESULTS`、`DESIGN, SETTING, AND PARTICIPANTS`）自动拆开；
  兼容全大写（BACKGROUND）、首字母大写（Background，BMJ / Lancet 风格）与中文
  （背景 / 目的 / 方法 / 结果 / 结论）标签；非标签词（Note: 等）被过滤，不误切正文。
- **抽取器改为"按段取"**：
  - `extract_conclusion` 取 CONCLUSIONS 段——**修掉过去取成 RESULTS 段末句的 bug**
  - `extract_population` 优先 PATIENTS / SETTING 段
  - `extract_intervention` 优先 INTERVENTIONS 段
  - `extract_primary_outcome` 优先 OUTCOMES 段
  - `extract_sample_size` 优先 METHODS / PATIENTS 段
- **扩充抽取正则**：
  - 人群：年龄限定（`adults aged 75 years or older`）、状态限定
    （`community-dwelling adults`）与中文（`…患者`）模式
  - 主要终点：放宽以允许 `primary composite endpoint`（"primary" 与 "endpoint"
    之间插入形容词）；抽不到时用终点名次级线索并明确标注"（摘要未标注主要终点）"
  - 样本量：新增"数字前置 + 状态词"模式（`19,114 community-dwelling adults…`），
    顺带修正第 5 篇演示文献此前误抽成 448（实为 19,114）的问题
  - 所有句子级返回值统一剥掉句首残留的段标签（如 `RESULTS:`）
- **极性判定改进**：补"裸方向动词"线索（reduced / reduces / reduction / lowered /
  fewer / decrease / improvement / 降低 / 减少 …），并用"效应量 < 1 且结局为不良事件"
  做**保守兜底**（其余情况仍保留"未明确"，不猜）；否定式（did not reduce /
  no reduction）由 `_NULL_CUES` 与否定检测先行拦下，不会被误判为正向。
- 新增 `_test_sections.py`（46 项断言，覆盖分段器边界、结论取段回归、正则命中、
  极性兜底与演示数据整体回归）；release.py 测试清单与 CI 增至 16 个离线套件。

修复后同一批演示文献：人群空 5 → 3 篇，主要终点空 6 → 3 篇，结论倾向"未明确" 3 → 0 篇。

## v3.3.0 · 2026-10-09

P3-C4 证据化深化：偏倚规则扩展 + 结构化评价工具与 GRADE 入口

新增 core/appraisal.py（结构化评价工具库，纯离线）：
- 按研究设计自动匹配规范量表的**信号问题清单**：RCT → RoB 2（5 个域）；队列 → NOS 队列版；
  病例对照 → NOS 病例对照版；横断面 → 改良 NOS（10 星）；系统评价 / Meta 分析 → AMSTAR-2
  （16 项，标注 7 个关键域）；临床指南 → AGREE II；叙述性综述 → SANRA；病例报告 → CARE；
  基础 / 动物实验 → SYRCLE。每份工具均含适用范围、判定方式、信号问题与**真实出处**。
- GRADE 分级自查入口：按设计给出起始等级（RCT 高 / 观察性低 / 病例报告极低 /
  动物与叙述性综述明确「不适用」），5 个降级因素（偏倚风险 / 不一致性 / 间接性 / 不精确性 /
  发表偏倚）与 3 个升级因素（效应量大 / 剂量-反应 / 混杂方向）的判据与查法。
- 导出：appraisal_markdown（结构化评价自查清单）、grade_markdown（GRADE 分级自查表），
  均纳入综述 ZIP 打包（表 4、表 5）。

core/review.py 偏倚规则由 22 条扩到 32 条（新增 10 类摘要层面线索）：
- no_itt（未提及意向性分析）、no_power（未说明样本量估算）、industry_funding（疑似企业资助）、
  funding_unknown（未提及资助与利益冲突）、posthoc_subgroup（含事后 / 亚组 / 探索性分析）、
  baseline_imbalance（提及基线不均衡）、composite_outcome（复合终点）、
  no_adjustment（观察性研究未提及混杂调整）、high_attrition（失访比例偏高）、
  pilot（预试验 / 可行性研究）。
- 新增 _max_attrition()：抽取摘要中**最大**失访百分比，覆盖「12% were lost to follow-up」与
  「lost to follow-up in 12%」两种语序，并排除「Grade 3 AE 32%」式的非失访百分比误报。
- 纪律延续：摘要**没写**造成的提示一律归入「信息缺失」档，只有摘要明确出现值得警惕的
  表述才升级——避免每篇文献都背一堆无意义提示。

设计原则（与 review 一致，不可破）：
1. 只给问题，不给判定——工具读不到全文、不了解具体研究，不能替医生回答「高风险还是低风险」；
2. 标清来源与简化程度——每份工具注明真实出处，并声明题项为便于快速核对做了大幅简化，
   不是原版量表的完整复现；
3. 不制造权威错觉——GRADE 起始等级与降级 / 升级都写清判据，最终级别必须由评价者作出。

app.py：「🩺 证据与适用性」标签页底部新增「🧰 结构化评价工具（按研究设计自动匹配）」与
「⚖️ GRADE 证据分级自查入口」两个区块，各配导出按钮；ZIP 打包新增表 4、表 5。

测试：新增 _test_appraisal.py（57 条断言，含 TOOLKIT_BY_DESIGN 与 review.DESIGN_LAYERS 的
**契约测试**、工具完整性、GRADE 表、两份导出的边界，以及「只导入 review 时 appraisal 不被
连带加载」的循环依赖护栏）；_test_review.py 增补 23 条断言覆盖新增规则与语序 / 误报边界
（117 → 140 条）；_smoke_app.py 增补结构化评价与 GRADE 区块的渲染断言。一键发布测试清单
增至 14 套件。



## v3.2.0 · 2026-10-09

P3-C3 本地 PDF 全文解析：新增「PDF 全文分析」页面与 core/pdfdoc.py（分栏版面重建 / 章节识别 / 表格抽取 / 整页渲染），解析结果与 PubMed 文献同构，全文摘要 / 原文定位 / 综述工作台 / 六种引用格式导出四项下游全打通；解析库选 pdfplumber(MIT) 以避开 PyMuPDF 的 AGPL 传染；云端与桌面版均开放上传，配版权责任确认门 + 单文件 20MB / 200 页上限 + 扫描件明确提示；桌面版重打包 dist_v17，_verify_exe.py 升级为三段式验证并新增 selftest 诊断模式；新增 _test_pdfdoc.py(99 断言) 与 _test_pdfpage.py(42 断言)，CI 增至 17 步



## v3.1.1 · 2026-10-08

P3-C1 收尾：修文献库分组的静默数据丢失，并补上落地页的文献库呈现。

修 bug（截图时发现，属真实数据丢失）：
- 卡片内「分组」下拉恒显示「未分组」——首次渲染时 session_state 里还没有该 key（读到 None），
  被一律归零成未分组，覆盖了 selectbox 的 index=，所以永远回显不出真实分组。
  用户不改下拉直接点「保存」即把分组静默清空。改为区分「key 不存在」与「key 存在但
  指向的分组已被删除」两种情况：前者用已存分组当初值，后者才归位。
- 批量移动分组 / 加标签 / 移除标签、以及标签管理的重命名与删除之后，卡片编辑区仍保留旧值，
  顺手点保存会把批量结果覆盖回去。新增 _drop_card_widgets()，在这些操作后清掉对应卡片的
  控件状态，使其重新按存储值初始化。
- 引用导出（含长代码预览）原夹在筛选区与文献卡片之间，把卡片整段挤出首屏；
  调整为「筛选 → 卡片列表 → 导出」。

落地页：
- 能力卡 10 → 11 项（新增「文献库管理」），新增两张实拍截图：卡片上的分组/标签/「有笔记」
  与展开后的编辑区；分组 · 标签 · 批量整理与三档筛选。docs/shots 增至 11 张 JPEG。

截图工具链（新增，便于以后重拍）：
- _seed_demo.py：播种演示数据到 _demo_data/，不碰真实 data/。
  关键：必须同时给 MEDLIT_SCOPE=local —— 只给 MEDLIT_DATA_DIR 会被按浏览器会话 id 分片，
  页面照样是空的。
- _shoot_demo.py：一键重拍（播种 → 起服务 → 等端口 → CDP 截图 → 杀进程树收尾）。
- _shot.py：新增 scroll_to_text()，拍长页面的下半部分。两个坑写进注释：
  Streamlit 的滚动容器不是 window（window.scrollTo 无效，scrollY 恒为 0）；
  定位要取**面积最小**的命中元素，否则会命中整页容器等于滚回页首。

测试：_smoke_app.py 新增「卡片分组下拉回显已存分组」断言（锁住上面的数据丢失），
全量 12 套件通过。文档同步 README / 使用说明 / ROADMAP，并补齐此前缺失的 v3.1.0 条目。


本次包含 1 项提交（v3.1.0..HEAD）：

- ac02d7f fix(release): 推送超时改为杀进程树，修「发版卡死 2 小时」



## v3.1.0 · 2026-10-08

P3-C1 文献库管理化：新增 core/library.py（分组 / 标签 / 笔记，独立于 favorites.json 存储，旧收藏零迁移），「我的收藏」升级为「我的文献库」——分组增删改、标签规范化与改名合并、笔记、批量整理（移动分组 / 打标签 / 移出收藏）、分组+标签+关键词三档筛选、筛选结果带标注导出 Markdown；页面改名后 ?page=我的收藏 旧深链仍有效（_norm_page 归一）。同批为迁到 Linux/WSL 做跨平台改造：stop.py 新增 POSIX 分支（lsof/ss 定位 → /proc/<pid>/cmdline 取命令行 → SIGTERM→宽限→SIGKILL），Windows 分支原样保留；新增 setup.sh / start.sh / stop.sh / release.sh 与 .gitattributes（.sh 钉 LF、.bat 钉 CRLF）；_shot.py 浏览器路径改为跨平台查找。修复 app.py 缺失 _norm_page 定义导致的启动即 NameError。测试：新增 _test_library.py（109 断言），_smoke_app.py 扩展文献库页与改名兼容断言，全量 12 套件约 460 断言全绿。


本次包含 4 项提交（v3.0.1..HEAD）：

- 22f664c fix(release): 推送链改为「直推优先」，并让死连接快速失败

- c170e12 docs(roadmap): 记录桌面版重打包 dist_v16 与旧包清理

- 00720cb chore(release): 直连推送 IP 顺序改为亚洲节点优先

- 33551c4 chore(desktop): 桌面版重打包为 dist_v16（v3.0.1），清理 dist_v15



## v3.0.1 · 2026-10-08

P3-C2 引用导出：新增 core/cite.py，六种参考文献格式（BibTeX / RIS / EndNote .enw / MEDLINE / Vancouver / GB/T 7714），检索结果、我的收藏、综述纳入文献三处共用同一导出区（选格式 → 就地预览 → 下载）；检索阶段补出卷/期/页码/ISSN/文献类型/语种与团体作者，导出的 .bib/.ris 无需再补字段；综述 ZIP 附带 .bib 与 .ris。同批完成第一档收尾：落地页补入综述工作台与证据化（八项能力 → 十项 + 专章，重建为 v3.0.1 实拍图）、清理旧打包目录约 880 MB、清理早期隧道脚本与工作区调试残留、docs/shots 统一为 JPEG。


本次包含 3 项提交（v3.0.0..HEAD）：

- 9776d6e docs: 写入项目目录结构 + 重新规划后续任务（P3/P4 三档）

- 6415670 ci: 测试步骤更名为「综述化 / 证据化引擎测试」

- 48cc415 chore(shot): 截图流程增加「证据与适用性」标签页（v3.0.0）



## v3.0.0 · 2026-10-08

P2 双主线完成：综述工作台（A 综述化，四标签页：横向对比 / 冲突核查 / PRISMA 筛选记录 / 初稿骨架）+ 证据与适用性（B 证据化：研究类型分层、牛津 CEBM 简化等级、约 16 条偏倚风险提示、临床适用性五维对照）。版本升至 v3.0.0，桌面版重打包为 dist_v15。


本次包含 2 项提交（v2.8.2..HEAD）：

- aa48b28 fix(release): push 命令显式置空 http.proxy，避免白名单代理对 github 返回 502

- 4e32faa docs: 桌面版产物指向 dist_v14（v2.8.2）



## v2.8.2 · 2026-10-07

隐私说明改为正式政策页 + 首次使用确认条 + 页面深链



## v2.8.1 · 2026-10-07

修复一键启动端口占用、一键发布推送兜底、解释器查找；新增一键停止


本次包含 1 项提交（v2.8.0..HEAD）：

- 7b5886f docs: 桌面版产物指向 dist_v13（v2.8.0 P1 收尾）



## v2.8.0 · 2026-10-07

P1 收尾：隐私说明页 + 反馈渠道 + 产品落地页 + NCBI Key 生效


本次包含 1 项提交（v2.7.0..HEAD）：

- b8cf9a5 docs: 桌面版产物指向 dist_v12（v2.7.0 含缓存层）



## v2.7.0 · 2026-10-07

持久化缓存层：检索/全文/摘要/译文/LLM 五类缓存，命中即不消耗上游配额


本次包含 1 项提交（v2.6.1..HEAD）：

- 65659fd release: v2.6.1 后续（release.py 标签推送修复 + 桌面版 dist_v11 + 容量实测记入路线图）



## v2.6.1 · 2026-10-07

支持 NCBI API Key（检索限速 3→10 req/s）+ CI 正式启用


本次包含 1 项提交（v2.6.0..HEAD）：

- f1ca00e docs: 桌面版产物指向 dist_v10（v2.6.0）



## v2.6.0 · 2026-10-07

P1：会话级数据隔离 + 用量配额/成本开关 + 外部依赖健康监控


本次包含 1 项提交（v2.5.0..HEAD）：

- 8ca6e60 docs: 补充 release.py 推送排障说明与 CI 文件启用说明



## v2.5.0 · 2026-10-07

统一外部请求层（超时/退避重试/域名限流/埋点）+ 发布流程自动化（版本单一来源、release.py、CI）


本次包含 8 项提交（v2.1.0..HEAD）：

- e9fefc7 test: add AppTest smoke test for app.py (v2.4.0 footer + logger verification)

- dad8572 feat: observability + compliance baseline (v2.4.0)

- cb87733 chore: repo hygiene (gitignore hardening) + add productization roadmap

- 93db0bc fix: bundle websocket-client/zhconv in desktop build; surface real figure-parse error (v2.3.1)

- 0e5a3ef feat: export full abstract instead of 220-char preview in batch xlsx (column renamed to full abstract)

- 9f91f64 fix: add openpyxl to requirements (ModuleNotFoundError on Streamlit Cloud batch xlsx export)

- 17ab831 feat: pluggable translation engine with Tencent TMT (v2.3.0)

- 5ff9928 docs: 新增 README，使用说明补充在线链接（v2.2.0）


