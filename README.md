# 医学文献智能摘要与检索系统

基于 Streamlit 的医学文献检索与智能摘要工具。数据源为 PubMed 官方 API（NCBI E-utilities，免费无需注册），全文获取覆盖 PMC 开放存档、Unpaywall 开放副本与浏览器网页提取三通道。

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

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
```

Python 3.10+。数据（收藏 / 检索历史）自动保存在本地 `%APPDATA%/MedLitSummary`。

## 桌面版

`dist_v7/医学文献智能摘要/` 内为 PyInstaller 打包的 Windows 桌面版，双击 `医学文献智能摘要.exe` 免安装运行（需整个文件夹一起分发）。

## 部署

1. Fork 或克隆本仓库
2. 在 [share.streamlit.io](https://share.streamlit.io) 用 GitHub 账号登录
3. Deploy an app → 选择仓库 / `main` 分支 / Main file path 填 `app.py`
4. 之后每次 `git push` 到 `main`，线上应用自动更新

## 版本

当前版本 **v2.2.0**，完整更新见 [Releases](https://github.com/Fy66666-fy/medical-lit-system/releases) 与应用内「更新日志」。
