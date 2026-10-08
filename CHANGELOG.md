# 更新日志

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


