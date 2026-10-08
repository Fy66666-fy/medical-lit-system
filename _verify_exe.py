"""验证桌面版 exe：静态检查打包内容 → 冻结环境内跑 PDF 自检 → server 模式起服务。

用法：python _verify_exe.py [dist目录名] [端口]

为什么不止「看文件在不在」：PyInstaller 最典型的失败是**纯 Python 模块打进去了、
数据文件却没带上**。pdfminer 要 `cmap/` 下的 CMap 数据、pypdfium2 要 `pdfium.dll`
原生库，这两样「文件在磁盘上」与「运行时真能加载」完全是两回事。所以这里：
  1) 先静态核对关键文件与依赖资源是否落盘；
  2) 再让 exe 自己以 `selftest` 模式**真解析一份 PDF 并渲染首页**（这一步才会
     真正触发 CMap 读取与 pdfium.dll 加载），结论以退出码为准；
  3) 最后以 `server` 模式起服务，验健康检查与首页。
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
dist = sys.argv[1] if len(sys.argv) > 1 else "dist_v17"
port = sys.argv[2] if len(sys.argv) > 2 else "8599"

APP_DIR = os.path.join(ROOT, dist, "医学文献智能摘要")
exe = os.path.join(APP_DIR, "医学文献智能摘要.exe")
internal = os.path.join(APP_DIR, "_internal")

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'OK ' if cond else 'NG '} {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)
    return bool(cond)


print(f"exe: {exe}")
print(f"exists: {os.path.exists(exe)}")
if not os.path.exists(exe):
    sys.exit(1)


# ---------------- 1. 静态检查：源码与依赖资源 ----------------
print("\n【1】打包内容静态检查")
# v2.5.0 起 app.py 依赖 version.py，漏打会直接起不来；
# v3.0.1 起 import core.cite，v3.1.0 起 core.library，v3.2.0 起 core.pdfdoc
for f in ("app.py", "version.py", "使用说明.md",
          os.path.join("core", "http.py"), os.path.join("core", "cite.py"),
          os.path.join("core", "review.py"), os.path.join("core", "library.py"),
          os.path.join("core", "pdfdoc.py")):
    check(f"内含 {f}", os.path.exists(os.path.join(internal, f)))

# pdfminer 的 CMap 数据：中文/日文等 CID 字体的文本抽取要靠它
cmap_dir = os.path.join(internal, "pdfminer", "cmap")
n_cmap = len(os.listdir(cmap_dir)) if os.path.isdir(cmap_dir) else 0
check("pdfminer/cmap 数据文件已带上", n_cmap > 100, f"{n_cmap} 个")

# pypdfium2 的原生库：页面渲染（图表解析的取图路径）依赖它
pdfium = os.path.join(internal, "pypdfium2_raw", "pdfium.dll")
check("pypdfium2_raw/pdfium.dll 已带上", os.path.exists(pdfium),
      f"{os.path.getsize(pdfium) / 1048576:.1f} MB" if os.path.exists(pdfium) else "")

# 运行时用 importlib.metadata 查版本，缺 dist-info 会报 PackageNotFoundError
meta_names = [n for n in os.listdir(internal) if n.endswith(".dist-info")]
for pkg in ("pdfplumber", "pdfminer", "pypdfium2"):
    hit = [n for n in meta_names if n.startswith(pkg)]
    check(f"{pkg} 的 dist-info 已带上", bool(hit), hit[0] if hit else "")


# ---------------- 2. 冻结环境内跑 PDF 自检 ----------------
print("\n【2】冻结环境内 PDF 解析自检（CMap + pdfium 真实加载）")
try:
    sys.path.insert(0, ROOT)
    from _test_pdfdoc import make_pdf, sample_pages, table_page_content

    tmpdir = tempfile.mkdtemp(prefix="medlit_exe_")
    sample = os.path.join(tmpdir, "sample.pdf")
    with open(sample, "wb") as fh:
        fh.write(make_pdf(sample_pages() + [table_page_content()]))
    out = os.path.join(tmpdir, "selftest.txt")
    print(f"  样本 {os.path.getsize(sample):,} bytes → {sample}")

    proc = subprocess.run([exe, "selftest", sample, out],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)
    lines = []
    if os.path.exists(out):
        lines = open(out, encoding="utf-8").read().splitlines()
    else:
        lines = [l for l in (proc.stdout or "").splitlines() if "[selftest]" in l]
    for l in lines:
        print("   ", l)
    ok = proc.returncode == 0 and any("结论: PASS" in l for l in lines)
    check("exe 内 PDF 解析与渲染自检通过", ok, f"退出码 {proc.returncode}")
    if not ok:
        for l in (proc.stdout or "").splitlines()[-15:]:
            print("    stdout:", l)
        for l in (proc.stderr or "").splitlines()[-15:]:
            print("    stderr:", l)
except Exception as e:  # noqa: BLE001
    check("冻结环境内 PDF 自检", False, f"{type(e).__name__}: {e}")


# ---------------- 3. server 模式：健康检查 + 首页 ----------------
print("\n【3】server 模式启动验证")
proc = subprocess.Popen([exe, "server", port],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")
ready = False
t0 = time.time()
try:
    while time.time() - t0 < 150:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=3) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(1)
    check("健康检查 /_stcore/health", ready, f"{time.time() - t0:.1f}s")
    if ready:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            body = r.read()
        check("首页可访问", r.status == 200 and len(body) > 0, f"{len(body)} bytes")
        appdata = os.path.join(os.environ.get("APPDATA", ""), "MedLitSummary")
        check("用户数据目录已建立", os.path.isdir(appdata), appdata)
        logs = os.path.join(appdata, "logs")
        if os.path.isdir(logs):
            print(f"    日志文件: {sorted(os.listdir(logs))[-3:]}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

print("\n" + "=" * 56)
if FAILS:
    print(f"验证未通过，{len(FAILS)} 项失败：")
    for f in FAILS:
        print("  -", f)
else:
    print("验证全部通过。")
print("=" * 56)
sys.exit(1 if FAILS else 0)
