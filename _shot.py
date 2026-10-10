"""用 Chrome DevTools Protocol 给运行中的应用拍真实截图（落地页 / README 用）。

为什么不用 `chrome --headless --screenshot`：那条路径 1 秒就退出，只能拍到
Streamlit 的 HTML 骨架（7KB 空白），因为它不等待 WebSocket 渲染完成。
CDP 可以自己控制等待时机，再用 Page.captureScreenshot 抓像素。

用法：
    python _shot.py <输出目录> [端口] [--flow|--privacy|--review|--cite|--lib|--pdf|--c4]
    --flow     自动走一遍「检索 → 详情」，多拍几张
    --pdf      深链到「PDF 全文分析」→ 勾选版权门 → 注入样本 PDF → 拍解析结果（13_pdf.png）
               样本可用环境变量 MEDLIT_SHOT_PDF 指定，不给则用 _test_pdfdoc 现造一份
    --c4       深链到「综述工作台」→ 全选 → 切「证据与适用性」标签 → 拍结构化评价工具与
               GRADE 自查入口（14_appraisal.png / 15_grade.png）
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

def _find_chrome() -> str:
    """找一个可用的 Chromium 系浏览器（跨平台）。

    优先级：环境变量 CHROME_PATH → 各平台常见安装路径 → PATH 上的命令名。
    找不到返回空串，launch_chrome() 会给出明确报错而不是让 subprocess 抛 FileNotFoundError。
    """
    env = os.environ.get("CHROME_PATH", "").strip()
    if env and os.path.exists(env):
        return env

    cands = [
        # Windows
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        # Linux / WSL
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        which = shutil.which(name)
        if which:
            cands.append(which)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return ""


CHROME = _find_chrome()
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
    if not CHROME:
        raise RuntimeError(
            "没找到 Chromium 系浏览器。\n"
            "  Linux / WSL： sudo apt install -y chromium-browser （或 google-chrome）\n"
            "  指定路径：   export CHROME_PATH=/path/to/chrome\n"
            "  Windows：    默认查 C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        )
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
    # root 身份下 Chrome 拒绝启用沙箱（常见于 WSL / 容器），此时必须显式关掉
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.insert(1, "--no-sandbox")
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


def scroll_to_text(cdp: CDP, text: str, offset: int = -90) -> tuple[bool, int]:
    """把含指定文案的**最小**元素滚到主内容区顶部附近，返回 (是否找到, 滚动后的 scrollTop)。

    三个坑（都实测踩过）：
    1. **`window.scrollTo` 在 Streamlit 上无效** —— 页面不是在 window 上滚，
       而是在主内容容器（`[data-testid="stMain"]` 那一层）上滚，`window.scrollY`
       永远是 0。必须找到"真正能滚的祖先"再设它的 `scrollTop`。
    2. 不能只取"第一个命中"——`div` 的 innerText 天然包含全部后代文字，文档顺序里
       第一个命中的往往是整页容器，滚过去等于滚回页首。所以取 bounding box 面积最小的那个。
    3. 只在主内容区里找，别把左侧栏的同名文字（如导航项）当锚点。
    """
    r = cdp.send("Runtime.evaluate", {
        "expression": """(() => {
            const t = %s, off = %d;
            const root = document.querySelector('[data-testid="stMain"], section.main, [data-testid="stAppViewContainer"]') || document.body;
            let best = null, bestArea = Infinity;
            for (const el of root.querySelectorAll('h1,h2,h3,h4,h5,p,span,label,div')) {
                if (!(el.innerText || '').trim().includes(t)) continue;
                const b = el.getBoundingClientRect();
                const area = b.width * b.height;
                if (area > 0 && area < bestArea) { bestArea = area; best = el; }
            }
            if (!best) return -1;
            // 向上找真正可滚的祖先
            let sc = best.parentElement;
            while (sc && sc !== document.body) {
                const oy = getComputedStyle(sc).overflowY;
                if (/(auto|scroll)/.test(oy) && sc.scrollHeight > sc.clientHeight + 4) break;
                sc = sc.parentElement;
            }
            if (!sc || sc === document.body) sc = document.scrollingElement || document.documentElement;
            const y = best.getBoundingClientRect().top - sc.getBoundingClientRect().top
                      + sc.scrollTop + off;
            sc.scrollTop = Math.max(0, y);
            return Math.round(sc.scrollTop);
        })()""" % (json.dumps(text), offset), "returnByValue": True})
    time.sleep(0.8)
    y = r.get("result", {}).get("value")
    return (isinstance(y, int) and y > 0), (y if isinstance(y, int) else -1)


def scroll_into_view(cdp: CDP, text: str, block: str = "start") -> bool:
    """用元素自身的 ``scrollIntoView`` 把含指定文案的最小元素滚到视口。

    为什么不能只用 ``scroll_to_text``：它手工向上找"可滚祖先"再设 ``scrollTop``，
    猜错元素时**赋值会被静默忽略**（非滚动元素上设 scrollTop 不生效，读回来仍是 0），
    表现为"找到了但没滚动"。``scrollIntoView`` 由浏览器处理嵌套滚动容器，稳得多。
    这里仍要自己挑"面积最小的命中元素"，否则会选中包住整页文字的容器、等于没滚。
    """
    r = cdp.send("Runtime.evaluate", {
        "expression": """(() => {
            const t = %s, blk = %s;
            const root = document.querySelector('[data-testid="stMain"], section.main, [data-testid="stAppViewContainer"]') || document.body;
            let best = null, bestArea = Infinity;
            for (const el of root.querySelectorAll('h1,h2,h3,h4,h5,p,span,label,div')) {
                if (!(el.innerText || '').trim().includes(t)) continue;
                const b = el.getBoundingClientRect();
                const area = b.width * b.height;
                if (area > 0 && area < bestArea) { bestArea = area; best = el; }
            }
            if (!best) return false;
            best.scrollIntoView({block: blk, inline: 'nearest'});
            return true;
        })()""" % (json.dumps(text), json.dumps(block)), "returnByValue": True})
    time.sleep(0.9)
    return bool(r.get("result", {}).get("value"))


def quiesce(cdp: CDP) -> None:
    """关掉页面所有 CSS 动画 / 过渡，再等半拍。

    为什么需要：Streamlit 重渲染会给元素挂 fade-in 动画，如果截图瞬间动画
    还没播完，整页就像蒙了一层雾（14_appraisal 首版整页发虚就是这么来的）。
    动画一旦被移除，元素会立即落到最终态（opacity 回到静态样式值），
    不需要猜哪个元素正在动画。样式幂等，可反复调用。
    """
    try:
        cdp.send("Runtime.evaluate", {"expression": """
            (() => {
                let st = document.getElementById('__shot_quiesce');
                if (!st) {
                    st = document.createElement('style');
                    st.id = '__shot_quiesce';
                    document.head.appendChild(st);
                }
                st.textContent = '*, *::before, *::after {'
                    + 'animation: none !important; transition: none !important;';
            })()
        """})
    except Exception:
        pass
    time.sleep(0.5)


def _capture(cdp: CDP, full: bool) -> bytes | None:
    params = {"format": "png", "fromSurface": True, "captureBeyondViewport": bool(full)}
    r = cdp.send("Page.captureScreenshot", params, timeout=90)
    data = r.get("data")
    return base64.b64decode(data) if data else None


def shoot(cdp: CDP, out_png: str, full: bool = True, keep_scroll: bool = False,
          stable: bool = False, tries: int = 4, gap: float = 1.2) -> bool:
    # 截图前先回到页首：Streamlit 是长页面，上一次交互的滚动位置会留在原地，
    # 不归零就会拍到页面中部（甚至只拍到页脚），看着像"页面是空的"。
    # keep_scroll=True 时保留调用方刚设置的滚动位置（配合 scroll_to_text 用）。
    if not keep_scroll:
        try:
            cdp.send("Runtime.evaluate", {"expression": "window.scrollTo(0, 0)"})
            time.sleep(0.4)
        except Exception:
            pass
    if stable:
        # "页面稳定时截取"：先关动画，再连续截帧，直到相邻两帧字节一致
        # （页面静止时 Chrome 渲染是确定性的，逐字节相同才算真稳定）。
        # 最多 tries 帧，始终兜底用最后一帧，保证函数总能给出产出。
        quiesce(cdp)
        prev: bytes | None = None
        for _ in range(max(1, tries)):
            cur = _capture(cdp, full)
            if cur is None:
                return False
            if prev is not None and cur == prev:
                break
            prev = cur
            time.sleep(gap)
        data = prev
    else:
        data = _capture(cdp, full)
    if not data:
        return False
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    with open(out_png, "wb") as f:
        f.write(data)
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


def click_checkbox_near(cdp: CDP, text: str) -> bool:
    """点击「与给定文字同属一个容器」的那个勾选框。

    页面可能有多个 checkbox，直接取第一个会点错（例如首页的同意门）。
    这里先找 `[data-testid="stCheckbox"]` 里 innerText 含目标文字的，
    再退到 label，命中后点容器左侧 —— 避开可能存在的左侧 padding。
    """
    js = """(() => {
        const t = %s;
        const pick = (el) => {
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) return null;
            return {x: r.x + 16, y: r.y + r.height / 2};
        };
        for (const b of document.querySelectorAll('[data-testid="stCheckbox"]')) {
            if ((b.innerText || '').includes(t)) { const r = pick(b); if (r) return r; }
        }
        for (const l of document.querySelectorAll('label')) {
            if ((l.innerText || '').includes(t)) { const r = pick(l); if (r) return r; }
        }
        return null;
    })()"""
    r = cdp.send("Runtime.evaluate",
                 {"expression": js % json.dumps(text), "returnByValue": True})
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


def set_checkbox(cdp: CDP, text: str, want: bool = True) -> str:
    """把「文字匹配的那个」checkbox 设为指定状态，返回 already / clicked / notfound。

    为什么不用鼠标点击：点的是 `[data-testid="stCheckbox"]` 容器左侧，
    容器有 padding 时可能落在空白处，什么都不会发生（实测「版权与合规确认」
    就是这么没勾上的）。这里直接对原生 `<input type="checkbox">` 调 `click()`：
    它是幂等的（先读 `checked`，已是目标态就不动），且浏览器会派发 change 事件，
    React 的受控组件才收得到。
    """
    js = """(() => {
        const t = __TEXT__, want = __WANT__;
        const find = () => {
            for (const b of document.querySelectorAll('[data-testid="stCheckbox"]')) {
                if ((b.innerText || '').includes(t)) {
                    const i = b.querySelector('input[type="checkbox"]');
                    if (i) return i;
                }
            }
            for (const l of document.querySelectorAll('label')) {
                if ((l.innerText || '').includes(t)) {
                    const i = l.querySelector('input[type="checkbox"]');
                    if (i) return i;
                }
            }
            return null;
        };
        const inp = find();
        if (!inp) return 'notfound';
        if (!!inp.checked === want) return 'already';
        inp.click();
        return 'clicked';
    })()"""
    expr = js.replace("__TEXT__", json.dumps(text)).replace(
        "__WANT__", "true" if want else "false")
    r = cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return str(r.get("result", {}).get("value") or "notfound")


def upload_file(cdp: CDP, selector: str, path: str) -> bool:
    """把本地文件塞进页面的 `<input type="file">`。

    为什么不能直接 `input.files = ...` / `input.value = ...`：浏览器出于安全考虑
    禁止脚本设置 file input 的值（赋了也会被清成空）。唯一可行的是 CDP 的
    `DOM.setFileInputFiles` —— 它由浏览器进程直接写入，并**自动派发 change 事件**，
    Streamlit 的 React 组件才收得到，进而触发一次 rerun。
    """
    try:
        cdp.send("DOM.enable")
        doc = cdp.send("DOM.getDocument", {"depth": -1})
        root = doc.get("root", {}).get("nodeId")
        if not root:
            print("    DOM.getDocument 未返回 root")
            return False
        node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": selector})
        nid = node.get("nodeId")
        if not nid:
            print(f"    选择器未命中：{selector}")
            return False
        cdp.send("DOM.setFileInputFiles", {"files": [path], "nodeId": nid})
        return True
    except Exception as e:  # noqa: BLE001
        print("    upload_file 异常:", type(e).__name__, e)
        return False


def sample_pdf() -> str:
    """现造一份 4 页样本 PDF（含表格）供截图用。

    复用 `_test_pdfdoc.py` 里的极简 PDF 生成器 —— 它手写对象与 xref，
    不引入额外依赖，也保证截图内容与测试用例一致。
    """
    import tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from _test_pdfdoc import make_pdf, sample_pages, table_page_content
    out = os.path.join(tempfile.mkdtemp(prefix="medlit_shot_"), "sample.pdf")
    with open(out, "wb") as fh:
        fh.write(make_pdf(sample_pages() + [table_page_content()]))
    return out


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

            # v3.0.0：证据与适用性（表 2 较长，单独放大视口再回落）
            click_text(cdp, "证据与适用性")
            wait_for_text(cdp, "证据特征与偏倚提示总览", timeout=60)
            time.sleep(2.5)
            set_viewport(cdp, 1440, 2700)
            time.sleep(1.5)
            pp = os.path.join(out_dir, "10_review_evidence.png")
            good_ev = shoot(cdp, pp, full=False)
            print(f"  {'OK ' if good_ev else 'FAIL'} 10_review_evidence.png · "
                  f"{os.path.getsize(pp) // 1024 if os.path.exists(pp) else 0}KB")
            ok = ok and good_ev
            set_viewport(cdp, 1440, 2300)

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

        if "--cite" in flags:
            # 引用导出（v3.0.1，P3-C2）：深链到「我的收藏」→ 勾选同意 → 拍导出区
            cdp.send("Page.navigate", {"url": base + "/?page=" + quote("我的收藏")})
            wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
            time.sleep(2.0)
            print(f"[C0] 勾选同意：{'成功' if click_consent(cdp) else '未找到勾选框'}")
            hit = wait_for_text(cdp, "引用导出", timeout=90)
            print(f"[C1] 进入收藏页：{'成功' if hit else '超时（仍继续截图）'}")
            time.sleep(3.0)
            set_viewport(cdp, 1440, 1600)
            time.sleep(1.5)
            p = os.path.join(out_dir, "11_cite_export.png")
            good = shoot(cdp, p, full=False)
            print(f"  {'OK ' if good else 'FAIL'} 11_cite_export.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB")
            ok = ok and good

        if "--lib" in flags:
            # 文献库管理（v3.1.0，P3-C1）：深链到「我的文献库」→ 勾选同意 → 拍整页
            cdp.send("Page.navigate", {"url": base + "/?page=" + quote("我的文献库")})
            wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
            time.sleep(2.0)
            print(f"[L0] 勾选同意：{'成功' if click_consent(cdp) else '未找到勾选框'}")
            hit = wait_for_text(cdp, "文献列表", timeout=90)
            print(f"[L1] 进入文献库页：{'成功' if hit else '超时（仍继续截图）'}")
            time.sleep(3.0)
            set_viewport(cdp, 1440, 1500)
            time.sleep(1.5)
            p = os.path.join(out_dir, "12_library.png")
            good = shoot(cdp, p, full=False)
            print(f"  {'OK ' if good else 'FAIL'} 12_library.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB")
            ok = ok and good

            # 第二张：展开首篇卡片的「🏷️ 分组 / 标签 / 笔记」再滚过去 —— 落地页讲「标签 + 笔记」
            # 时，只拍到页首的统计卡说服力不够，要看到卡片上真实的标签与笔记文本。
            exp = expand_summary(cdp, "分组 / 标签 / 笔记")
            print(f"[L2] 展开首篇卡片标注：{'成功' if exp else '未找到折叠区'}")
            time.sleep(2.5)
            set_viewport(cdp, 1440, 1250)
            time.sleep(1.2)
            scr, sy = scroll_to_text(cdp, "文献列表", offset=-80)
            print(f"[L3] 滚动到卡片区：{'成功' if scr else '未找到锚点'}（scrollY={sy}）")
            time.sleep(1.0)
            p2 = os.path.join(out_dir, "12b_library_cards.png")
            good2 = shoot(cdp, p2, full=False, keep_scroll=True)
            print(f"  {'OK ' if good2 else 'FAIL'} 12b_library_cards.png · "
                  f"{os.path.getsize(p2) // 1024 if os.path.exists(p2) else 0}KB")
            ok = ok and good2

        if "--pdf" in flags:
            # PDF 全文分析（v3.2.0，P3-C3）：深链 → 数据处理同意 → 版权确认 → 上传样本 → 拍解析结果。
            # 注意：Page.navigate 是整页刷新，Streamlit 会开新会话，所以同意门每次都得重勾。
            cdp.send("Page.navigate", {"url": base + "/?page=" + quote("PDF 全文分析")})
            wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
            time.sleep(2.0)
            print(f"[P0] 勾选数据处理同意：{'成功' if click_consent(cdp) else '未找到勾选框'}")

            hit = wait_for_text(cdp, "版权与合规确认", timeout=90)
            print(f"[P1] 进入 PDF 页：{'成功' if hit else '超时（仍继续）'}")
            time.sleep(2.5)

            # 版权确认门：页面里可能不止一个 checkbox，必须点名设它
            res = set_checkbox(cdp, "版权与合规确认", True)
            print(f"[P2] 勾选版权确认：{res}")
            time.sleep(3.5)
            print(f"[P2b] 复核：{set_checkbox(cdp, '版权与合规确认', True)}")
            ready = wait_for_text(cdp, "自动开始解析", timeout=90)
            print(f"[P3] 上传区已开放：{'是' if ready else '未确认'}")
            if not ready:
                txt = cdp.send("Runtime.evaluate", {
                    "expression": "document.body ? document.body.innerText.slice(0, 900) : ''",
                    "returnByValue": True}).get("result", {}).get("value") or ""
                print("  [调试] 页面文本：\n" + txt)

            pdf = os.environ.get("MEDLIT_SHOT_PDF", "").strip() or sample_pdf()
            print(f"[P4] 样本 PDF：{pdf}（{os.path.getsize(pdf)} bytes）")
            up = upload_file(cdp, 'input[type="file"]', pdf)
            print(f"[P5] 注入文件：{'成功' if up else '未找到 file input'}")

            got = wait_for_text(cdp, "解析概览", timeout=180)
            print(f"[P6] 解析完成：{'是' if got else '超时'}")
            time.sleep(4.5)
            set_viewport(cdp, 1440, 2200)
            time.sleep(1.5)
            p = os.path.join(out_dir, "13_pdf.png")
            good = shoot(cdp, p, full=False)
            print(f"  {'OK ' if good else 'FAIL'} 13_pdf.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB")
            ok = ok and good

        if "--c4" in flags:
            # 结构化评价工具 + GRADE 自查（v3.3.0，P3-C4）：深链到综述工作台 → 勾同意 →
            # 全选纳入 → 切到「证据与适用性」标签 → 滚到两个新区块分别拍摄。
            # 注意：这两个区块在**标签页内部**，未选中的标签面板是 hidden 的，
            # 元素 bounding box 为 0，scroll_to_text 的 area>0 过滤会直接跳过它们——
            # 所以必须先真的点一下标签把它激活。
            cdp.send("Page.navigate", {"url": base + "/?page=" + quote("综述工作台")})
            wait_for_text(cdp, "使用前请先确认数据处理方式", timeout=60)
            time.sleep(2.0)
            print(f"[C4-0] 勾选同意：{'成功' if click_consent(cdp) else '未找到勾选框'}")
            wait_for_text(cdp, "确定主题并勾选纳入文献", timeout=90)
            time.sleep(2.5)
            picked = click_text(cdp, "全选")
            print(f"[C4-1] 点「全选」：{'成功' if picked else '未找到按钮'}")
            wait_for_text(cdp, "横向对比表", timeout=90)
            time.sleep(2.5)
            click_text(cdp, "证据与适用性")
            wait_for_text(cdp, "证据特征与偏倚提示总览", timeout=60)
            time.sleep(3.0)

            set_viewport(cdp, 1440, 1900)
            time.sleep(1.8)
            scrolled = scroll_into_view(cdp, "结构化评价工具")
            print(f"[C4-2] 滚动到结构化评价工具：{'成功' if scrolled else '未找到锚点'}")
            time.sleep(1.2)
            p = os.path.join(out_dir, "14_appraisal.png")
            # stable=True：切标签后 Streamlit 会对新面板做 fade-in，动画没播完就拍
            # 会整页发虚（14_appraisal 首版踩过）——关动画 + 双帧一致才落盘。
            good = shoot(cdp, p, full=False, keep_scroll=True, stable=True)
            print(f"  {'OK ' if good else 'FAIL'} 14_appraisal.png · "
                  f"{os.path.getsize(p) // 1024 if os.path.exists(p) else 0}KB")
            ok = ok and good

            set_viewport(cdp, 1440, 1900)
            time.sleep(1.5)
            scrolled2 = scroll_into_view(cdp, "GRADE 证据分级自查入口")
            print(f"[C4-3] 滚动到 GRADE 入口：{'成功' if scrolled2 else '未找到锚点'}")
            time.sleep(1.2)
            p2 = os.path.join(out_dir, "15_grade.png")
            good2 = shoot(cdp, p2, full=False, keep_scroll=True, stable=True)
            print(f"  {'OK ' if good2 else 'FAIL'} 15_grade.png · "
                  f"{os.path.getsize(p2) // 1024 if os.path.exists(p2) else 0}KB")
            ok = ok and good2

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
