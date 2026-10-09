"""一键发布（v2.5.0）：跑测试 → 改版本 → 同步部署目录 → 提交打标签 → 推送。

为什么要它：此前发版是手工一串操作（改版本号、复制文件到部署目录、
git add/commit/tag/push），漏任何一步就会出现"线上还是旧代码"或
"页面显示的版本和实际代码不一致"。现在一条命令走完，且每步失败立即停下。

常用命令：
    python release.py --bump patch                 # 常规发版（patch: v2.5.0 → v2.5.1）
    python release.py --bump minor --message "新增综述模式"
    python release.py --set v3.0.0
    python release.py --bump patch --no-push       # 只本地提交，不推远程
    python release.py --deploy-only                # 只同步部署目录，不动版本
    python release.py --bump patch --skip-tests    # 紧急修补（不建议）

推送提示：直连 GitHub 常被重置 / 长时间无响应，可加 --resolve 直连 IP
（注意 curloptResolve 的格式是 主机名:端口:IP，端口不能省）：
    nslookup github.com    # 或用 DoH：https://dns.alidns.com/resolve?name=github.com
    python release.py --bump patch --resolve "github.com:443:20.205.243.166"

凭据：git push 需要 PAT。若提示 "could not read Username"，说明本机没有保存凭据，
可在 ~/.git-credentials 写入一行 `https://<PAT>@github.com` 并执行
`git config --global credential.helper store`，之后即可真正一键发布。
注意：创建或修改 .github/workflows/ 下的文件需要 PAT 具备 **workflow** 权限。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import signal
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEPLOY_DIR = os.path.join(os.path.dirname(ROOT), "medical-lit-deploy")

# 发布时需要同步到部署目录的白名单（部署目录只用于 Streamlit Cloud，
# 不需要测试脚本、打包产物与本地数据）
SYNC_ITEMS = [
    "app.py", "version.py", "launch.py", "requirements.txt",
    "使用说明.md", "ROADMAP.md", "CHANGELOG.md", "README.md",
    "core", ".streamlit",
]
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".DS_Store", "data", "logs", "*.log"
)
# 部署目录里历史遗留的调试残留，同步时清理（只删这几类明确模式）
JUNK_PATTERNS = (re.compile(r"^check.*\.txt$", re.I), re.compile(r"^_.*\.txt$", re.I))

TESTS = ["_test_http.py", "_test_logger.py", "_test_p1.py", "_test_cache.py",
         "_test_ncbi_key.py", "_test_feedback.py", "_test_review.py", "_test_appraisal.py",
         "_test_cite.py", "_test_library.py", "_test_locate.py", "_test_pdfdoc.py",
         "_test_pdfpage.py", "_smoke_app.py"]
UNIT_TESTS = ["_test_translate.py"]


def run(cmd: list[str], cwd: str = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True,
                          encoding="utf-8", errors="replace",
                          capture_output=True)


def step(title: str) -> None:
    print(f"\n=== {title} ===")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


# ---------------- 步骤 1：环境预检 ----------------
def preflight() -> bool:
    step("1/6 环境预检")
    try:
        cp = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=False)
        if cp.returncode != 0:
            fail("当前目录不是 git 仓库")
            return False
        ok(f"git 分支 {cp.stdout.strip()}")
    except FileNotFoundError:
        fail("未找到 git，请先安装并加入 PATH")
        return False

    cp = run(["git", "status", "--porcelain"], check=False)
    dirty = [l for l in (cp.stdout or "").splitlines() if l.strip()]
    if dirty:
        print(f"  [提示] 工作区有 {len(dirty)} 项未提交改动，将一并提交：")
        for l in dirty[:8]:
            print(f"         {l}")
        if len(dirty) > 8:
            print(f"         … 其余 {len(dirty) - 8} 项")
    else:
        ok("工作区干净")
    return True


# ---------------- 步骤 2：跑测试 ----------------
def run_tests(skip: bool) -> bool:
    step("2/6 运行测试")
    if skip:
        print("  [跳过] --skip-tests")
        return True
    py = sys.executable
    bad = False
    for t in TESTS:
        path = os.path.join(ROOT, t)
        if not os.path.exists(path):
            print(f"  [跳过] {t}（不存在）")
            continue
        cp = run([py, t], check=False)
        if cp.returncode == 0:
            ok(f"{t} 通过")
        else:
            bad = True
            fail(f"{t} 失败（退出码 {cp.returncode}）")
            print((cp.stdout or "")[-1500:])
            print((cp.stderr or "")[-800:])
    for t in UNIT_TESTS:
        path = os.path.join(ROOT, t)
        if not os.path.exists(path):
            continue
        cp = run([py, "-m", "unittest", t[:-3], "-v"], check=False)
        if cp.returncode == 0:
            ok(f"{t} 通过（unittest）")
        else:
            bad = True
            fail(f"{t} 失败")
            print((cp.stdout or "")[-1500:])
    if bad:
        print("\n  测试未全部通过，已中止发布。确认无问题可加 --skip-tests 强制发布。")
    return not bad


# ---------------- 步骤 3：版本号 ----------------
def read_version() -> tuple[str, tuple[int, int, int]]:
    ns: dict = {}
    src = open(os.path.join(ROOT, "version.py"), encoding="utf-8").read()
    exec(compile(src, "version.py", "exec"), ns)
    return ns["APP_VERSION"], tuple(ns["VERSION_TUPLE"])


def write_version(new_version: str) -> None:
    major, minor, patch = [int(x) for x in new_version.lstrip("v").split(".")]
    content = f'''"""版本单一来源（{new_version}）。

此前版本号散落在 app.py、使用说明.md、ROADMAP.md、打包脚本等多处，
每次发版靠手工同步，漏改就会出现"页面显示 v2.3.0、实际代码是 v2.4.0"的错位。
现在所有地方统一从这里读取，发版只需 release.py 改这一个数字。
"""
from __future__ import annotations

# 语义化版本（major.minor.patch），带 v 前缀是页面展示用的既有格式
APP_VERSION = "{new_version}"

# 内部比较用的数字元组，CI / 发布脚本判断是否需要 bump 时使用
VERSION_TUPLE = ({major}, {minor}, {patch})


def bump(part: str = "patch") -> str:
    """返回递增后的版本号字符串（不写文件，供 release.py 决定并落盘）。"""
    major, minor, patch = VERSION_TUPLE
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"v{{major}}.{{minor}}.{{patch}}"


if __name__ == "__main__":
    print(APP_VERSION)
'''
    with open(os.path.join(ROOT, "version.py"), "w", encoding="utf-8") as f:
        f.write(content)


def bump_version(bump_part: str | None, set_to: str | None) -> str:
    step("3/6 版本号")
    cur, tup = read_version()
    print(f"  当前版本 {cur}")
    if set_to:
        new = set_to if set_to.startswith("v") else "v" + set_to
    elif bump_part:
        major, minor, patch = tup
        if bump_part == "major":
            new = f"v{major + 1}.0.0"
        elif bump_part == "minor":
            new = f"v{major}.{minor + 1}.0"
        else:
            new = f"v{major}.{minor}.{patch + 1}"
    else:
        print("  [跳过] 未指定 --bump / --set，保持当前版本")
        return cur
    if new == cur:
        print(f"  [提示] 版本号未变化（{cur}）")
        return cur
    write_version(new)
    ok(f"已更新 version.py → {new}")
    return new


# ---------------- 步骤 4：同步部署目录 ----------------
def sync_deploy(deploy_dir: str) -> bool:
    step("4/6 同步部署目录")
    if not os.path.isdir(deploy_dir):
        print(f"  [跳过] 部署目录不存在：{deploy_dir}（可用 --deploy-dir 指定）")
        return True
    ok(f"目标 {deploy_dir}")

    # 清理历史调试残留
    removed = []
    for name in os.listdir(deploy_dir):
        if any(p.match(name) for p in JUNK_PATTERNS):
            try:
                os.remove(os.path.join(deploy_dir, name))
                removed.append(name)
            except OSError:
                pass
    if removed:
        ok(f"清理残留文件 {len(removed)} 个：{', '.join(removed)}")

    for item in SYNC_ITEMS:
        src = os.path.join(ROOT, item)
        if not os.path.exists(src):
            continue
        dst = os.path.join(deploy_dir, item)
        try:
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, ignore=IGNORE)
            else:
                shutil.copy2(src, dst)
            ok(f"同步 {item}")
        except Exception as e:
            fail(f"同步 {item} 失败：{e}")
            return False
    return True


# ---------------- 步骤 5：更新 CHANGELOG.md ----------------
def update_changelog(version: str, message: str) -> None:
    step("5/6 更新 CHANGELOG.md")
    today = dt.date.today().isoformat()
    # 自上一个 tag 以来的提交（无 tag 时取最近 20 条）
    cp = run(["git", "describe", "--tags", "--abbrev=0"], check=False)
    if cp.returncode == 0 and cp.stdout.strip():
        log_cp = run(["git", "log", "--oneline", f"{cp.stdout.strip()}..HEAD"], check=False)
        scope = f"{cp.stdout.strip()}..HEAD"
    else:
        log_cp = run(["git", "log", "--oneline", "-20"], check=False)
        scope = "最近 20 条"
    commits = [l.strip() for l in (log_cp.stdout or "").splitlines() if l.strip()]

    path = os.path.join(ROOT, "CHANGELOG.md")
    old = ""
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
        old = re.sub(r"^# 更新日志\n", "", old)

    section = [f"## {version} · {today}\n"]
    if message:
        section.append(f"{message}\n")
    if commits:
        section.append(f"\n本次包含 {len(commits)} 项提交（{scope}）：\n")
        for c in commits:
            section.append(f"- {c}\n")
    section.append("\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("# 更新日志\n\n" + "\n".join(section) + old)
    ok(f"CHANGELOG.md 已写入 {version}（{len(commits)} 项提交）")


# ---------------- 步骤 6：提交 / 标签 / 推送 ----------------
def commit_and_push(version: str, no_push: bool, tag: bool, resolve: str | None) -> bool:
    step("6/6 提交与推送")
    cp = run(["git", "add", "-A"], check=False)
    if cp.returncode != 0:
        fail(f"git add 失败：{cp.stderr}")
        return False
    ok("git add 完成")

    cp = run(["git", "commit", "-m", f"release: {version}"], check=False)
    if cp.returncode != 0:
        out = (cp.stdout or "") + (cp.stderr or "")
        if "nothing to commit" in out:
            print("  [提示] 没有需要提交的改动")
        else:
            fail(f"git commit 失败：{out}")
            return False
    else:
        ok(f"已提交 release: {version}")

    if tag:
        run(["git", "tag", "-f", version], check=False)
        ok(f"已打标签 {version}")

    if no_push:
        print("  [跳过] --no-push：未推送到远程")
        return True

    return push_all(resolve, tag, version)


# ---- 推送（含本机网络环境的自动兜底） --------------------------------
# 本机到 GitHub 的链路很不稳定：代理会对 CONNECT 回 502、直连会被 reset、
# TLS 偶发 "server closed abruptly"。这里把常见的几种绕法依次尝试，
# 免得每次发版都要手动加 --resolve。
# 顺序按实测可达性排：2026-10-08 同刻对照 5 轮，140.82.114.4 / 140.82.112.4 最快（2.0~2.2s），
# 20.205.243.166 最慢（4.3s）且在坏窗口（12:11）完全超时——所以它排最后，只作轮换兜底。
# 注意：**单个 IP 时通时不通是常态**（GFW 窗口随时变），不要因为一次成功就把它钉死；
# 曾把 20.205.243.166 写进全局 http.curloptResolve，坏窗口里反而让所有 git 操作白等 30 秒。
GITHUB_IPS = ["140.82.114.4", "140.82.112.4", "140.82.113.3", "20.205.243.166"]


def _push_cmd(resolve_pairs: list[str], *args: str, bypass_proxy: bool = True) -> list[str]:
    """组装 push 命令。

    - `bypass_proxy=True` 时显式带 `-c http.proxy= -c https.proxy=`：本机装了白名单代理
      （环境变量 HTTP_PROXY），它对 github.com 的 CONNECT 时而回 502、时而隧道建立后不传数据，
      显式置空最彻底（清环境变量有时不够，git 还可能从别处读到代理）。
    - 始终带 lowSpeedLimit / lowSpeedTime：把「连上但不传数据」的死路在约 10 秒内掐掉。
      兜底还有 `_run_bounded` 的 60 秒**进程树**硬超时，即使 git 完全不守规矩也不会挂死。
    """
    cmd = ["git"]
    if bypass_proxy:
        cmd += ["-c", "http.proxy=", "-c", "https.proxy="]
    cmd += ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=10"]
    for p in resolve_pairs:
        cmd += ["-c", f"http.curloptResolve={p}"]
    cmd.append("push")
    cmd += list(args)
    return cmd


def _run_bounded(cmd: list[str], timeout: float, env: dict | None = None,
                 cwd: str = ROOT) -> tuple[int, str]:
    """带**进程树**硬超时的命令执行，返回 (rc, 合并后的输出)。

    为什么不能直接用 `subprocess.run(timeout=...)`：git push 真正干活的进程是
    它派生的 `git-remote-https`。超时触发时 subprocess 只 kill 直接子进程，
    孙进程仍持有 stdout/stderr 管道，随后的 `communicate()` 会**永久阻塞**——
    2026-10-08 实测让一次发版卡了 2 小时 15 分（父进程 timeout=180 形同虚设）。
    所以这里：Windows 用 `taskkill /F /T` 杀整棵树，POSIX 用 `killpg`。
    """
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    p = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=flags,
        start_new_session=(os.name != "nt"),
    )
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, (out or "")
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                p.kill()
        try:
            out, _ = p.communicate(timeout=15)
        except Exception:
            out = ""
        return -9, (out or "") + f"\n[已按 {timeout:.0f}s 硬超时终止进程树]"


def _try_push(cmd: list[str], label: str, clear_proxy: bool = False) -> tuple[bool, str]:
    env = dict(os.environ)
    # 禁止任何交互式凭据提示：后台运行时没有 tty，一旦 git 想提示用户名就会永久挂住
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    if clear_proxy:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env.pop(k, None)
    rc, msg = _run_bounded(cmd, timeout=60, env=env)
    msg = msg.strip()
    if rc == 0:
        ok(f"已推送到远程（{label}）")
        return True, msg
    print(f"    · {label} 失败：{msg.splitlines()[-1][:120] if msg else '未知错误'}")
    return False, msg


def push_all(resolve: str | None, tag: bool, version: str) -> bool:
    """按「用户指定 → 直推（走系统配置）→ 轮换直连 IP → 清空代理直连」的顺序推送分支与标签。

    计划项 = (标签, curloptResolve 列表, 是否清空代理环境变量, 是否显式绕过代理)。
    """
    plans: list[tuple[str, list[str], bool, bool]] = []
    if resolve:
        pairs = [f"{x.strip()}:443" for x in resolve.split(",") if x.strip()]
        plans.append((f"指定直连 {resolve}", [f"http.curloptResolve={p}" for p in pairs], False, True))
    # 第一条先试「不加任何覆盖」的普通推送：网络好时最快（实测 1.4~9.8s），
    # 坏时也能靠 lowSpeedTime 在约 10s 内快速失败，不至于拖住整个轮换。
    plans.append(("直接推送（走系统配置）", [], False, False))
    for ip in GITHUB_IPS:
        plans.append((f"直连 {ip}", [f"http.curloptResolve=github.com:443:{ip}"], False, True))
    plans.append(("清空代理后直连", [f"http.curloptResolve=github.com:443:{GITHUB_IPS[0]}"], True, True))

    done = False
    used_idx = -1
    for i, (label, pairs, clear, bypass) in enumerate(plans):
        done, msg = _try_push(_push_cmd(pairs, "-u", "origin", "HEAD", bypass_proxy=bypass),
                              label, clear)
        if done:
            used_idx = i
            break
    if not done:
        fail("git push 全部尝试均失败")
        print(f"    最后一次错误：{msg[-300:]}")
        print('  补救：确认网络后执行  git push -u origin HEAD  再执行  git push origin <tag>')
        print('       或到 https://github.com/Fy66666-fy/medical-lit-system 手动上传')
        return False

    # 标签单独推：`git push --follow-tags` 只跟随**附注标签**（annotated tag），
    # 而 `git tag vX.Y.Z` 建的是轻量标签，会被静默漏掉——发布看起来成功，远端却没有 tag。
    if not tag:
        return True
    label, pairs, clear, bypass = plans[used_idx]
    tcp_ok, tmsg = _try_push(_push_cmd(pairs, "origin", version, bypass_proxy=bypass),
                             f"标签 {version} · {label}", clear)
    if tcp_ok:
        ok(f"标签 {version} 已推送")
        return True
    fail(f"标签推送失败：{tmsg[-200:]}")
    print(f"  补救：git push origin {version}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="医学文献智能摘要系统 · 一键发布")
    ap.add_argument("--bump", choices=["patch", "minor", "major"], help="版本号递增")
    ap.add_argument("--set", dest="set_to", help="直接指定版本，如 v3.0.0")
    ap.add_argument("--message", default="", help="写进 CHANGELOG 的发布说明")
    ap.add_argument("--deploy-dir", default=DEFAULT_DEPLOY_DIR, help="部署目录路径")
    ap.add_argument("--deploy-only", action="store_true", help="只同步部署目录")
    ap.add_argument("--skip-tests", action="store_true", help="跳过测试（不建议）")
    ap.add_argument("--no-push", action="store_true", help="只本地提交，不推远程")
    ap.add_argument("--no-tag", action="store_true", help="不打 git 标签")
    ap.add_argument("--resolve", help="git push 直连，如 \"github.com:140.82.113.3\"")
    args = ap.parse_args()

    print("=" * 60)
    print("  医学文献智能摘要系统 · 一键发布")
    print("=" * 60)

    if args.deploy_only:
        return 0 if sync_deploy(args.deploy_dir) else 1

    if not preflight():
        return 1
    if not run_tests(args.skip_tests):
        return 1
    version = bump_version(args.bump, args.set_to)
    if not sync_deploy(args.deploy_dir):
        return 1
    if args.bump or args.set_to:
        update_changelog(version, args.message)
    if not commit_and_push(version, args.no_push, not args.no_tag, args.resolve):
        return 1

    print(f"\n发布完成：{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
