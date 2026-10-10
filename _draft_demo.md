## v3.9.0 · 2026-10-10

<!-- 主题句：一句话说清这次是什么（写完后删掉本行） -->

<!-- 背景段：用户反馈原话 / 为什么做 / 解决了什么歧义（写完后删掉本行） -->


### 素材清单（正文写完后删掉这一节）


- 起点 `v3.8.0`，共 **7** 项已提交：文档 4、杂项 1、CI / 构建 1、修复 1


**改动量**（按行数排序，前 10）：

- `app.py`  344 行（+176 / −168）
- `_make_release_zip.py`  122 行（+122 / −0）
- `.github/workflows/release-desktop.yml`  83 行（+83 / −0）
- `_f11_scan.py`  76 行（+76 / −0）
- `ROADMAP.md`  35 行（+26 / −9）
- `LICENSE`  21 行（+21 / −0）
- `README.md`  12 行（+11 / −1）
- `CHANGELOG.md`  7 行（+7 / −0）
- `.gitignore`  6 行（+6 / −0）
- `version.py`  6 行（+3 / −3）


**新增文件**：`.github/workflows/release-desktop.yml`、`LICENSE`、`_f11_scan.py`、`_make_release_zip.py`


**新增 / 改动的顶层函数与类**（写条目时优先提这些）：

- `_f11_scan.py`：`scan()`、`main()`
- `_make_release_zip.py`：`main()`、`extract_notes()`


**提交明细**：

- `faa3536` docs(changelog): 网页端更新日志改写覆盖全量（v3.3.1~v1.0.0 共 140 条）
- `1870bfe` docs(changelog): 网页端更新日志改写，去 AI 味（v3.4.0~v3.8.1 共 28 条）
- `533f5f9` docs: 添加 MIT License 与 README 许可/免责一节
- `f475587` docs: ROADMAP 记录多平台分发可行性结论（小程序观察项 / 分发渠道优先级 / NCBI Key 不内置定案）
- `8266a87` chore: .gitattributes 将 index.html 标记为 linguist-documentation 修正语言徽章
- `f86aff0` ci: 新增 release-desktop.yml，打 v* 标签自动打包桌面版并发布 GitHub Release
- `6671518` fix: v3.8.1 修复 CI 3.11 语法检查失败（f-string 表达式跨行）


### 条目按这个格式写（写完删掉本提示行）


- **小标题**（`模块.函数`）：做了什么 → 为什么这么做 → 边界 / 纪律 / 不做什么。

- **另一条**：同上。每条都要能被用户感知，不要写「优化了内部逻辑」这种空话。


- 收尾固定补一行：测试与打包情况（几套件 / 多少条断言 / 桌面版 dist_vN 三段式验证）。

