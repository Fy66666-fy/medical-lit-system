# 更新日志

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


