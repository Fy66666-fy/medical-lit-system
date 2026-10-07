# 更新日志

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


