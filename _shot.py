"""用 Chrome DevTools Protocol 给运行中的应用拍真实截图（落地页 / README 用）。

为什么不用 `chrome --headless --screenshot`：那条路径 1 秒就退出，只能拍到
Streamlit 的 HTML 骨架（7KB 空白），因为它不等待 WebSocket 渲染完成。
CDP 可以自己控制等待时机，再用 Page.captureScreenshot 抓像素。

用法：
    python _shot.py <输出目录> [端口] [--flow]
    --flow  会自动走一遍「检索 → 详情」，多拍几张
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote
import urllib.request

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333          # 调试端口，避开 9222 以防与用户自己的 Chrome 冲突
PROFILE = None       # 由 _free_port_dir 动态分配


# --------------------------------------------------------------- 端口/目录
def _free_port(start: int) -> int:
    for p in range(start, start + 40):
        with socket.socket() as s:
            s.settimeout(0.3)
            try:
                s.connect(("127.0.0.1", p))
            except Exception:
                return p
    raise RuntimeError("找不到可用调试端口")


def _temp_profile() -> str:
    import tempfile

    d = os.path.join(tempfile.gettempdir(), f"medlit_shot_{os.getpid()}")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------- CDP 会话
class CDP:
    def __init__(self, ws_url: str):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=60)
        self._id = 0

    def send(self, method: str, params: dict | None = None, timeout: float = 60):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(0.5, deadline - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def launch_chrome(port: int, profile: str) -> subprocess.Popen:
    args = [
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        "--disable-features=Translate,BackForwardCache",
        "--force-device-scale-factor=1",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        # 新版 Chrome 默认拒绝来自调试端口的 websocket 握手，必须显式放行
        f"--remote-allow-origins=http://127.0.0.1:{port}",
        "--remote-allow-origins=*",
        "--window-size=1440,940", "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def target_ws(port: int, timeout: float = 30) -> str:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
                data = json.load(r)
            for t in data:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.6)
    raise RuntimeError(f"拿不到调试目标：{last}")


# --------------------------------------------------------------- 拍摄
def wait_for_text(cdp: CDP, needle: str, timeout: float = 40) -> bool:
    """轮询页面文本，等到出现关键内容才算渲染完成。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = cdp.send("Runtime.evaluate",
                         {"expression": "document.body ? document.body.innerText : ''",
                          "returnByValue": True})
            txt = (r.get("result", {}).get("value") or "")
            if needle in txt:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def shoot(cdp: CDP, out_png: str, full: bool = True) -> bool:
    # 截图前先回到页首：Streamlit 是长页面，上一次交互的滚动位置会留在原地，
    # 不归零就会拍到页面中部（甚至只拍到页脚），看着像"页面是空的"。
    try:
        cdp.send("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
        time.sleep(0.4)
    except Exception:
        pass
    params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full)}
    r = cdp.send("Page.captureScreenshot", params, timeout=90)
    data = r.get("data")
    if not data:
        return False
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(data))
    return os.path.getsize(out_png) > 15000


def set_viewport(cdp: CDP, w: int, h: int) -> None:
    cdp.send("Emulation.setDeviceMetricsOverride",
             {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})


_FIND_JS = """
(() => {
  const t = %s;
  const scopes = [
    document.querySelector('[data-testid="stSidebarNav"]'),
    document.querySelector('[data-testid="stMain"]'),
    document.body
  ].filter(Boolean);
  const inScope = (root, exactOnly) => {
    const els = Array.from(root.querySelectorAll('button, a, [role="button"], label, li, div, span'));
    const hit = exactOnly
      ? els.find(e => (e.innerText || '').trim() === t)
      : els.find(e => { const s = (e.innerText || '').trim();
                        return s.includes(t) && s.length < t.length + 12; });
    if (!hit) return null;
    const r = hit.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height};
  };
  for (const root of scopes) { const r = inScope(root, true);  if (r) return r; }
  for (const root of scopes) { const r = inScope(root, false); if (r) return r; }
  return null;
})()
"""


def click_text(cdp: CDP, text: str) -> bool:
    """按可见文本点击。

    注意：Streamlit 内部用 React，`element.click()` 不会触发它的处理器，
    必须用 CDP 的 Input 事件在元素中心发一次真实鼠标点击。
    先在侧边导航（stSidebarNav）里精确匹配，再退到主区域，避免误中同名说明文字。
    """
    r = cdp.send("Runtime.evaluate",
                 {"expression": _FIND_JS % json.dumps(text), "returnByValue": True})
    box = r.get("result", {}).get("value")
    if not box:
        return False
    x, y = float(box["x"]), float(box["y"])
    for _ in range(2):
        cdp.send("Input.dispatchMouseEvent",
                 {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
        cdp.send("Input.dispatchMouseEvent",
                 {"type": "mousePressed", "x": x, "y": y, "button": "left",
                  "clickCount": 1, "buttons": 1})
        cdp.send("Input.dispatchMouseEvent",
                 {"type": "mouseReleased", "x": x, "y": y, "button": "left",
                  "clickCount": 1, "buttons": 0})
        time.sleep(0.25)
    return True


def wait_for_any(cdp: CDP, needles, timeout: float = 40) -> str:
    """等到任意一个关键文本出现，返回命中的那个（都超时则返回空串）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = cdp.send("Runtime.evaluate",
                         {"expression": "document.body ? document.body.innerText : ''",
                          "returnByValue": True})
            txt = (r.get("result", {}).get("value") or "")
            for n in needles:
                if n in txt:
                    return n
        except Exception:
            pass
        time.sleep(1.0)
    return ""


def click_consent(cdp: CDP) -> bool:
    """勾选「我已阅读并同意…」。

    坑：Streamlit 的 checkbox 原生 input 是**隐藏**的（尺寸为 0），
    按它的 boundingRect 中心去点等于点在空白处，什么都不会发生。
    所以要按可见性择一：input 足够大就点它，否则点它的 label 容器。
    """
    js = """(() => {
        const inp = document.querySelector('input[type="checkbox"]');
        const cands = [];
        if (inp) {
            const b = inp.getBoundingClientRect();
            if (b.width > 4 && b.height > 4) cands.push({el: inp, r: b});
            const lab = inp.closest('label') || inp.parentElement;
            if (lab) cands.push({el: lab, r: lab.getBoundingClientRect()});
        }
        const box = document.querySelector('[data-testid="stCheckbox"]');
        if (box) cands.push({el: box, r: box.getBoundingClientRect()});
        for (const c of cands) {
            if (c.r.width > 4 && c.r.height > 4)
                return {x: c.r.x + c.r.width / 2, y: c.r.y + c.r.height / 2};
        }
        if (inp) { inp.click(); return {x: -1, y: -1}; }
        return null;
    })()"""
    r = cdp.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
    box = r.get("result", {}).get("value")
    if not box:
        return False
    x, y = float(box["x"]), float(box["y"])
    if x < 0:          # 已走 JS 兜底点击
        return True
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
    for et, btns in (("mousePressed", 1), ("mouseReleased", 0)):
        cdp.send("Input.dispatchMouseEvent",
                 {"type": et, "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": btns})
        time.sleep(0.08)
    return True


def expand_summary(cdp: CDP, text: str) -> bool:
    """展开折叠区。

    Streamlit 的 expander 是原生 <details><summary>，对 summary 元素直接 .click()
    会走浏览器默认的展开行为；给内部 span 发鼠标事件只会聚焦不会展开。
    """
    r = cdp.send("Runtime.evaluate", {
        "expression": """(() => {
            const t = %s;
            for (const s of document.querySelectorAll('summary')) {
                if ((s.innerText || '').includes(t)) { s.click(); return true; }
            }
            return false;
        })()""" % json.dumps(text), "returnByValue": True})
    return bool(r.get("result", {}).get("value"))


def fill_input(cdp: CDP, selector: str, value: str) -> bool:
    """真实填写输入框：点进去聚焦 → Input.insertText → Tab 失焦提交。

    比 dispatchEvent 可靠：React 受控组件会忽略合成事件，但认 CDP 的真实输入事件。
    """
    r = cdp.send("Runtime.evaluate", {
        "expression": """(() => {
            const el = document.querySelector(%s);
            if (!el) return null;
            const b = el.getBoundingClientRect();
            return {x: b.x + b.width / 2, y: b.y + b.height / 2};
        })()""" % json.dumps(selector), "returnByValue": True})
    box = r.get("result", {}).get("value")
    if not box:
        return False
    x, y = float(box["x"]), float(box["y"])
    cdp.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                          "button": "left", "clickCount": 1, "buttons": 1})
    cdp.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                          "button": "left", "clickCount": 1, "buttons": 0})
    time.sleep(0.4)
    cdp.send("Input.insertText", {"text": value})
    time.sleep(0.6)
    for k in ("Tab",):
        cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": k, "windowsVirtualKeyCode": 9})
        cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": k, "windowsVirtualKeyCode": 9})
    time.sleep(1.2)
    # 回读校验：值真的进了 DOM 吗
    chk = cdp.send("Runtime.evaluate", {
        "expression": "(() => {const e=document.querySelector(%s); return e ? e.value : null;})()"
                      % json.dumps(selector), "returnByValue": True})
    return (chk.get("result", {}).get("value") or "") == value


def type_into(cdp: CDP, selector: str, value: str) -> bool:
    js = """
    (() => {
      const el = document.querySelector(%s);
      if (!el) return false;
      // 注意：必须按标签选原生 setter。textarea 的 value 描述符对 input 不可用，
      // 用错会在严格模式下抛 "incompatible receiver"。
      const proto = (el.tagName === 'TEXTAREA')
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, %s);
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      // Streamlit 的 text_input 靠 blur / Enter 提交值，模拟失焦才能让状态真正落到服务端
      el.dispatchEvent(new Event('blur', {bubbles: true}));
      el.blur();
      return true;
    })()
    """ % (json.dumps(selector), json.dumps(value))
    r = cdp.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
    return bool(r.get("result", {}).get("value"))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    out_dir = args[0] if args else "docs/shots"
    app_port = args[1] if len(args) > 1 else "8501"
    base = f"http://127.0.0.1:{app_port}"

    port = _free_port(PORT)
    profile = _temp_profile()
    proc = launch_chrome(port, profile)
    cdp = None
    ok = True
    try:
        cdp = CDP(target_ws(port))
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        set_viewport(cdp, 1440, 940)

        cdp.send("Page.navigate", {"url": base})
        # 首次进入会先碰到隐私同意门（这时页面里还没有正文标题），两种情况都算渲染完成
        hit = wait_for_any(cdp, ["医学文献智能摘要与检索系统", "使用前请先确认数据处理方式"], timeout=60)
        print(f"[1] 首屏渲染 {'就绪' if hit else '超时（仍继续截图）'}"
              f"{'（同意待确认）' if hit == '使用前请先确认数据处理方式' else ''}")

        shots = [("01_home.png", base)]
        for name, _ in shots:
            p = os.path.join(out_dir, name)
            good = shoot(cdp, p)
            sz = os.path.getsize(p) // 1024 if os.path.exists(p) else 0
            print(f"  {'OK ' if good else 'FAIL'} {name} · {sz}KB")
            ok = ok and good

        if "--flow" in flags:
            # 侧栏「功能导航」是自定义组件（iframe）里的 streamlit_option_menu，
            # 元素点击打不进去；主区域的「去检索 / 去摘要」卡片是真按钮，走它们。
            nav_ok = click_text(cdp, "去检索") or click_text(cdp, "文献检索")
            print(f"[2] 进入检索页：{'成功' if nav_ok else '未找到入口'}")
            wait_for_text(cdp, "主关键词", timeout=40)
            time.sleep(1.5)

            typed = fill_input(cdp, 'input[aria-label="主关键词（必填）"]',
                           "metformin cardiovascular outcomes")
            print(f"[3] 填入检索词：{'成功' if typed else '未找到输入框'}")
            time.sleep(2.5)          # 等 Streamlit 把值提交到会话状态
            click_text(cdp, "开始检索") or click_text(cdp, "检索")
            print("[4] 已提交检索，等待结果…")
            got = wait_for_text(cdp, "PMID", timeout=150) or wait_for_text(cdp, "导出", timeout=30)
            time.sleep(3.0)
            p = os.path.join(out_dir, "02_results.png")
            good = shoot(cdp, p)
            print(f"  {'OK ' if good else 'FAIL'} 02_results.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB"
                  f"{'' if got else '（结果未确认）'}")
            ok = ok and good

            if got and "--detail" in flags:
                # 首条结果的「摘要全文」折叠区里就是中文摘要 + 句子重要性得分，
                # 这是这个产品最有说服力的一屏
                click_text(cdp, "摘要全文") or expand_summary(cdp, "摘要全文")
                wait_for_text(cdp, "重要性", timeout=90)
                time.sleep(4.0)
                p3 = os.path.join(out_dir, "03_summary.png")
                good3 = shoot(cdp, p3)
                print(f"  {'OK ' if good3 else 'FAIL'} 03_summary.png · "
                      f"{os.path.getsize(p3) // 1024 if os.path.exists(p3) else 0}KB")
                ok = ok and good3
        if "--privacy" in flags:
                    # 注意：Page.navigate 是整页刷新，Streamlit 会开新会话，
                    # 所以每个需要进入的页面都要「先落地 → 再勾选同意 → 再截图」。
                    def _consent_and_shoot(needle: str, out_name: str, height: int) -> bool:
                        if not click_consent(cdp):
                            print(f"  FAIL {out_name}：未找到同意勾选框")
                            return False
                        got = wait_for_text(cdp, needle, timeout=90)
                        time.sleep(3.0)
                        set_viewport(cdp, 1400, height)
                        time.sleep(1.2)
                        p = os.path.join(out_dir, out_name)
                        good = shoot(cdp, p, full=False)
                        print(f"  {'OK ' if good else 'FAIL'} {out_name} · "
                              f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB"
                              f"{'' if got else '（目标文本未出现）'}")
                        return good

                    # 1) 首页：先拍同意门，再勾选后拍真实首页
                    wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
                    time.sleep(2.0)
                    shoot(cdp, os.path.join(out_dir, "04_consent.png"))
                    print("[·] 首页同意门已拍")
                    ok = ok and _consent_and_shoot("医学文献智能摘要与检索系统", "01_home.png", 940)

                    # 2) 隐私政策页（新会话，需重新勾选）
                    cdp.send("Page.navigate", {"url": base + "/?page=" + quote("隐私与数据")})
                    wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
                    time.sleep(2.0)
                    ok = ok and _consent_and_shoot("隐私政策与数据处理说明", "05_privacy.png", 2600)

        if "--review" in flags:
            # 综述工作台（v2.9.0）：深链直达 → 勾选同意 → 点「全选」→ 拍对比表与冲突核查
            # 注意：Page.navigate 是整页刷新，Streamlit 会开新会话，所以必须先落地再勾选。
            cdp.send("Page.navigate", {"url": base + "/?page=" + quote("综述工作台")})
            wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
            time.sleep(2.0)
            print(f"[R0] 勾选同意：{'成功' if click_consent(cdp) else '未找到勾选框'}")
            if not wait_for_text(cdp, "确定主题并勾选纳入文献", timeout=90):
                txt = cdp.send("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0, 600) : ''",
                    "returnByValue": True}).get("result", {}).get("value") or ""
                print("  [调试] 当前页面文本：\n" + txt)
            time.sleep(2.5)
            picked = click_text(cdp, "全选")
            print(f"[R1] 点「全选」：{'成功' if picked else '未找到按钮'}")
            ok_tbl = wait_for_text(cdp, "横向对比表", timeout=90)
            if not ok_tbl:
                txt = cdp.send("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0, 2500) : ''",
                    "returnByValue": True}).get("result", {}).get("value") or ""
                with open(os.path.join(out_dir, "review_debug.txt"), "w", encoding="utf-8") as f:
                    f.write(txt)
                print("  [调试] 未出现对比表，页面文本已写入 review_debug.txt")
            time.sleep(3.5)
            set_viewport(cdp, 1440, 2300)
            time.sleep(1.5)
            p = os.path.join(out_dir, "06_review_table.png")
            good = shoot(cdp, p, full=False)
            print(f"  {'OK ' if good else 'FAIL'} 06_review_table.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB")
            ok = ok and good

            def _tab(name: str, wait: str, out_name: str) -> bool:
                click_text(cdp, name)
                wait_for_text(cdp, wait, timeout=60)
                time.sleep(2.5)
                pp = os.path.join(out_dir, out_name)
                good = shoot(cdp, pp, full=False)
                print(f"  {'OK ' if good else 'FAIL'} {out_name} · "
                      f"{os.path.getsize(pp) // 1024 if os.path.exists(pp) else 0}KB")
                return good

            ok = _tab("结论冲突核查", "可信度", "07_review_conflicts.png") and ok
            ok = _tab("筛选记录", "PRISMA 式", "08_review_prisma.png") and ok
            click_text(cdp, "综述初稿骨架")
            wait_for_text(cdp, "生成综述初稿骨架", timeout=60)
            time.sleep(1.5)
            if click_text(cdp, "生成综述初稿骨架"):
                wait_for_text(cdp, "文献综述初稿", timeout=90)
                time.sleep(3.0)
                pp = os.path.join(out_dir, "09_review_draft.png")
                good = shoot(cdp, pp, full=False)
                print(f"  {'OK ' if good else 'FAIL'} 09_review_draft.png · "
                      f"{os.path.getsize(pp) // 1024 if os.path.exists(pp) else 0}KB")
                ok = ok and good

    finally:
        if cdp:
            cdp.close()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
