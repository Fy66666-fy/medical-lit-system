# 医学文献智能摘要与检索系统

基于 Streamlit 的医学文献检索与智能摘要工具。数据源为 PubMed 官方 API（NCBI E-utilities，免费无需注册），全文获取覆盖 PMC 开放存档、Unpaywall 开放副本与浏览器网页提取三通道。

**产品落地页（含真实界面截图）**：[`index.html`](index.html) —— 用浏览器直接打开即可，也可作为 GitHub Pages 发布。

## 在线使用

| 入口 | 链接 |
|---|---|
| Streamlit Cloud（主推） | https://medical-lit-system-fy.streamlit.app/ |
| WorkBuddy 应用（备用） | https://med-lit-summarizer.app.workbuddy.host/ |

无需安装，浏览器打开即用；Streamlit Cloud 版随本仓库 `main` 分支自动同步更新。

## 功能亮点

- **智能检索**：主/副关键词 AND·OR·NOT 组合、期刊筛选（期刊名自动转 MEDLINE 缩写）、作者国籍筛选、检索式实时预览、拼写纠错
- **全文获取三通道**：PMC 开放存档 → Unpaywall OA 副本 → 无头浏览器网页提取（带反拦截策略）
- **智能摘要**：章节加权抽取式摘要 + 可选 LLM 深度总结（OpenAI 兼容接口，可选配置）；英文摘要与中文翻译对照
- **原文定位**：摘要句子回溯原文出处（章节 · 句序 · 高亮原句）；LLM 中文总结跨语言溯源（数字 + 术语加权匹配）
- **全文关键词搜索定位**：输入关键词实时列出所有命中原句（中英文均可，多词 AND），关键词高亮
- **关键数值提取**：P 值 / 95%CI / HR·OR·RR / 百分比 / 样本量 n / 均值±SD 自动扫描定位，兼容 Lancet 中点小数
- **图表解析**：PMC 开放全文的图片抓取与说明概括
- **批量处理**：多篇文献并行抓取摘要，后台任务不阻塞界面，一键导出
- **统计导出**：Excel 三工作表（文献汇总 / 章节明细 / 统计指标）、Markdown 摘要导出

## 为什么它能扛住多人同时使用

| 措施 | 效果 |
|---|---|
| **持久化缓存**（检索 / 全文 / 摘要 / 译文 / LLM 五类） | 同一检索式的 8 路并发从 7.7 秒降到近乎瞬时；命中缓存**不消耗**翻译额度与 NCBI 限速配额 |
| **NCBI API Key**（免费） | 检索限速从约 3 次/秒提升到约 10 次/秒 |
| **会话级数据隔离** | 云端每个浏览器会话一份独立数据，收藏与历史不会串号 |
| **用量配额与成本开关** | 单会话与宿主每日双重上限，超限给明确提示；自带密钥即不受限 |
| **统一请求层** | 超时分离 + 指数退避重试 + 按域名限流 + 全量埋点，故障可定位 |
| **外部依赖健康监控** | 六大依赖按天统计成功率，区分「自家代码问题」与「上游接口波动」 |

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

更省事：双击 `一键启动.bat`（会等端口真正就绪再打开浏览器）。

Python 3.10+。数据（收藏 / 检索历史）自动保存在本地 `%APPDATA%/MedLitSummary`。

## 配置（全部可选，不配也能用）

在 `.streamlit/secrets.toml` 或 Streamlit Cloud 的 Secrets 里填写：

```toml
# 腾讯云机器翻译：每月 500 万字符免费额度，中文摘要质量明显优于免费兜底接口
TENCENT_SECRET_ID = "..."
TENCENT_SECRET_KEY = "..."

# NCBI API Key：检索限速 3 → 10 次/秒，免费申请
# https://account.ncbi.nlm.nih.gov/settings/#page=api_keys
NCBI_API_KEY = "..."
```

所有密钥只存于进程内存，不写磁盘、不进日志。

## 桌面版

`dist_v12/医学文献智能摘要/` 内为 PyInstaller 打包的 Windows 桌面版，双击 `医学文献智能摘要.exe` 免安装运行（需整个文件夹一起分发）。

重新构建：

```bash
python -m PyInstaller desktop_app.spec --noconfirm --distpath dist_v12 --workpath build_v12
python _verify_exe.py dist_v12 8603      # 自动启动并验证
```

## 隐私

**一句话：本工具不收集任何个人身份信息。**

| 数据 | 存在哪 | 谁能看到 |
|---|---|---|
| 检索历史、收藏 | 桌面版：本机 `data/`；云端：你这次浏览器会话专属的目录 | 只有你 |
| 检索结果 / 全文 / 译文缓存 | 所有人**共享**一份 | 共享，但内容全部来自 PubMed 公开文献，不含身份信息 |
| 运行日志与健康统计 | 服务器本地，按天滚动，保留 14 天 | 仅用于排查故障 |
| 你填写的第三方密钥 | **仅存于本次进程内存** | 只有你 |

**不会做的事**：不收集姓名 / 手机号 / 邮箱 / 身份证；不做用户画像与行为追踪；不接入广告与统计 SDK；不把你的检索内容用于训练模型。

**需要你知情的三件事**

1. 翻译会经过第三方服务：使用腾讯云机器翻译时，待翻译的英文摘要文本会发送至腾讯云；使用你自填的大模型 API 时同理。**请不要在检索框里粘贴含患者身份信息的文本**。
2. NCBI 有自己的使用政策：文献元数据来自 PubMed，请遵守其使用条款，不得批量抓取或用于商业用途。
3. 医疗免责：所有输出由算法自动生成，**不能作为临床诊断或用药依据**。

## 部署

1. Fork 或克隆本仓库
2. 在 [share.streamlit.io](https://share.streamlit.io) 用 GitHub 账号登录
3. Deploy an app → 选择仓库 / `main` 分支 / Main file path 填 `app.py`
4. 之后每次 `git push` 到 `main`，线上应用自动更新

## 开发

```bash
python _test_http.py        # 请求层（离线 mock）
python _test_logger.py      # 日志系统
python _test_p1.py          # 会话隔离 / 配额 / 健康监控
python _test_cache.py       # 缓存层
python _test_ncbi_key.py    # NCBI API Key
python _test_feedback.py    # 反馈渠道
python _smoke_app.py        # AppTest 冒烟
python release.py --bump patch      # 一键发布（跑测试 → 改版本 → 同步部署目录 → 提交打标签 → 推送）
```

CI 每次 push 自动跑上述全部测试。

## 版本

当前版本见 [`version.py`](version.py) 的 `APP_VERSION`，完整更新见 [Releases](https://github.com/Fy66666-fy/medical-lit-system/releases) 与应用内「更新日志」。