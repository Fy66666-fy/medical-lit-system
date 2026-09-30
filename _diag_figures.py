"""图表解析链路诊断工具。

用途：当「图表解析」失败时，用它逐步定位失败环节（元数据抓取 / 图片包 / 逐图接口 /
浏览器兜底 / 环境依赖）。也可用 --no-browser 模拟云端环境（无 Edge/Chrome）下的行为。

用法：
    python _diag_figures.py                 # 完整链路（本机有浏览器）
    python _diag_figures.py --no-browser    # 模拟云端：禁用浏览器兜底通道
    python _diag_figures.py PMC5648544      # 指定文献
"""
import sys
import time
import traceback

sys.path.insert(0, ".")

from core import pubmed


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    no_browser = "--no-browser" in sys.argv
    pmcid = args[0] if args else "PMC10191983"

    print(f"文献：{pmcid}   浏览器：{pubmed._find_browser()}")
    print(f"websocket 模块：{'可用' if pubmed._ws_module() else '缺失 —— ' + pubmed.WS_IMPORT_ERROR}")

    if no_browser:
        print("（--no-browser：模拟云端无浏览器环境）")
        pubmed._browser_fetch_images = lambda pmcid, missing: False
        pubmed._screenshot_figures = lambda pmcid, missing: None

    print("\n[1] 抓取图表元数据（Europe PMC 补充材料接口）")
    try:
        figures = pubmed.fetch_pmc_figures(pmcid)
    except Exception as e:
        print(f"    失败：{e.__class__.__name__}: {e}")
        return
    print(f"    解析出 {len(figures)} 张图表")
    for f in figures[:6]:
        cap = (f.get("caption") or "")[:60]
        print(f"      - {f.get('label')}: {cap}…")

    if not figures:
        return

    print("\n[2] 获取图片（zip → 逐图接口 → 浏览器兜底）")
    t0 = time.time()
    try:
        pubmed.fetch_figure_images(pmcid, figures)
    except Exception as e:
        print(f"    失败：{e}")
        print(traceback.format_exc()[-500:])
        return
    got = sum(1 for f in figures if f.get("data"))
    shot = sum(1 for f in figures if f.get("is_screenshot"))
    print(f"    成功 {got}/{len(figures)} 张（截图 {shot} 张），耗时 {time.time() - t0:.1f}s")
    print("\n结论：图表解析链路正常" if got else "\n结论：未取到任何图片")


if __name__ == "__main__":
    main()
