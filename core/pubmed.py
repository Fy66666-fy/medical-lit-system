"""PubMed E-utilities API 封装（免费，无需 API Key，限速 3 req/s）"""
import os
import re
import time
import requests
import xml.etree.ElementTree as ET

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

HEADERS = {"User-Agent": "MedLitSummary/1.0 (Streamlit demo)"}


def build_query(keyword: str, author: str = "", start_date: str = "", end_date: str = "") -> str:
    q = keyword.strip()
    if author.strip():
        q += f" AND {author.strip()}[Author]"
    if start_date and end_date:
        q += f" AND {start_date}:{end_date}[Date - Publication]"
    return q


def search(query: str, retmax: int = 20, sort: str = "relevance") -> list[str]:
    """返回 PMID 列表"""
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": retmax,
        "sort": sort,
        "retmode": "json",
        "usehistory": "n",
    }
    r = requests.get(ESEARCH, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", [])


def _merge_text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _ncbi_get(path: str, params: dict, timeout: int = 30, retries: int = 3):
    """带重试的 NCBI E-utilities 请求（自动附加 tool 标识，缓解偶发网络抖动/限流/DNS 污染）"""
    p = dict(params)
    p.setdefault("tool", "med-lit-summarizer")
    last_exc = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(path, params=p, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_exc = e
            if attempt < retries:
                # 指数退避：DNS 污染/代理切换等瞬时故障通常几秒内自愈
                time.sleep(2.0 * (attempt + 1))
    raise last_exc


def friendly_error(e: Exception) -> str:
    """把网络类异常翻译成可操作的中文提示；非网络类异常原样返回"""
    import requests as _rq

    msg = str(e)
    if "SSLCertVerificationError" in msg or "CERTIFICATE_VERIFY_FAILED" in msg:
        return (
            "网络 SSL 证书校验失败——与 PubMed 之间的 HTTPS 连接被中间层截拦"
            "（常见原因：访问 NCBI 时的瞬时 DNS 污染，或代理/VPN 节点切换，"
            "属于网络环境问题而非系统故障）。通常稍等几分钟重试即可恢复；"
            "若持续出现，请检查本机代理/杀软的 HTTPS 扫描设置。"
        )
    if "Max retries exceeded" in msg or "ConnectionError" in msg or "Connection aborted" in msg:
        return "无法连接 PubMed（NCBI）服务器——请检查本机网络连通性后重试。"
    if "ReadTimeout" in msg or "ConnectTimeout" in msg or "timed out" in msg.lower():
        return "连接 PubMed 超时——网络较慢或不稳定，请稍后重试。"
    if isinstance(e, _rq.RequestException):
        return f"网络请求失败：{msg[:200]}"
    return msg


def fetch_articles(pmids: list[str]) -> list[dict]:
    """批量拉取文献详情（标题/作者/期刊/日期/摘要）"""
    if not pmids:
        return []
    time.sleep(0.4)  # 尊重 NCBI 限速
    r = _ncbi_get(EFETCH, {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"}, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    articles = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _merge_text(art.find(".//MedlineCitation/PMID"))
        title_node = art.find(".//Article/ArticleTitle")
        title = _merge_text(title_node)
        journal = _merge_text(art.find(".//Article/Journal/Title"))
        year_node = art.find(".//Article/Journal/JournalIssue/PubDate/Year")
        year = _merge_text(year_node) or _merge_text(art.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate"))
        authors = [
            f"{a.findtext('LastName', '')} {a.findtext('Initials', '')}".strip()
            for a in art.findall(".//AuthorList/Author") if a.find("LastName") is not None
        ]
        # 结构化摘要拼接
        abstract_parts = []
        for at in art.findall(".//Abstract/AbstractText"):
            label = at.get("Label")
            text = _merge_text(at)
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = "\n".join(abstract_parts)
        doi = ""
        pmcid = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
            elif aid.get("IdType") == "pmc":
                pmcid = (aid.text or "").strip()
        articles.append(
            {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "year": year,
                "authors": authors,
                "abstract": abstract,
                "doi": doi,
                "pmcid": pmcid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            }
        )
    return articles


def get_pdf_links(article: dict) -> list[tuple[str, str]]:
    """构造文献全文/文档链接：优先 PMC PDF，其次 DOI，最后 PubMed 页面"""
    links = []
    pmcid = article.get("pmcid") or ""
    if pmcid:
        links.append(("📄 PDF 全文 (PMC)", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"))
    doi = article.get("doi") or ""
    if doi:
        links.append(("🔗 DOI 原文", f"https://doi.org/{doi}"))
    if article.get("url"):
        links.append(("🔎 PubMed 页面", article["url"]))
    return links


def fetch_pmc_figures(pmcid: str) -> list[dict]:
    """抓取 PMC 开放获取全文中的图表元数据（标签 + 说明文字 + 文件名）"""
    pmc_num = pmcid.replace("PMC", "")
    time.sleep(0.4)
    r = _ncbi_get(EFETCH, {"db": "pmc", "id": pmc_num, "retmode": "xml"}, timeout=30)
    root = ET.fromstring(r.content)
    xlink = "{http://www.w3.org/1999/xlink}"
    figures = []
    for fig in root.findall(".//fig"):
        label = (fig.findtext("label") or "").strip()
        caption = _merge_text(fig.find("caption"))
        graphic = fig.find(".//graphic")
        if graphic is None:
            continue
        href = graphic.get(f"{xlink}href") or graphic.get("id") or ""
        if not href:
            continue
        figures.append({
            "label": label,
            "caption": caption,
            "file": href,
            "fig_id": fig.get("id") or "",
        })
    return figures


_FIG_ZIP_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles"
_IMG_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/image/{name}"
_IMG_EXTS = (".jpg", ".jpeg", ".gif", ".png", ".tif", ".tiff")


# ---------------------------------------------------------------- 浏览器兜底 --
def _find_browser() -> str | None:
    """查找本机可用的 Edge / Chrome 可执行文件（无头截图兜底需要）"""
    import shutil

    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    cands += [os.path.expandvars(p) for p in (
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    )]
    for name in ("chromium-browser", "chromium", "google-chrome", "msedge"):
        which = shutil.which(name)
        if which:
            cands.append(which)
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


def _cdp_call(ws, method: str, params: dict | None = None, _id: list = None) -> dict:
    """发送一条 CDP 命令并等待其响应"""
    import json as _json

    _id[0] += 1
    ws.send(_json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    deadline = time.time() + 60
    while time.time() < deadline:
        msg = _json.loads(ws.recv())
        if msg.get("id") == _id[0]:
            if "error" in msg:
                raise RuntimeError(f"CDP {method}: {msg['error']}")
            return msg.get("result", {})
    raise RuntimeError(f"CDP {method} 超时")


def _browser_fetch_images(pmcid: str, missing: list[dict]) -> bool:
    """
    用无头浏览器打开 PMC 文章页，从页面 <img> 元素抓取原图二进制。
    浏览器指纹可通过 NCBI 反爬（requests 会被 403）。成功返回 True。
    """
    import base64
    import json as _json
    import socket
    import subprocess
    import tempfile
    from urllib.parse import quote

    import websocket

    browser = _find_browser()
    if browser is None:
        return False

    stems = {}
    for fig in missing:
        stem = re.sub(r"\.(jpg|jpeg|gif|png|tif|tiff)$", "", fig["file"], flags=re.I)
        stems.setdefault(_norm_figname(stem), stem)
    if not stems:
        return True

    port = None
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    finally:
        sock.close()

    profile = tempfile.mkdtemp(prefix="medlit_cdp_")
    proc = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--no-first-run",
         "--disable-extensions", "--remote-allow-origins=*",
         f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    try:
        # 等调试端口就绪
        import urllib.request
        deadline = time.time() + 20
        targets = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3) as resp:
                    targets = _json.loads(resp.read().decode("utf-8"))
                if any(t.get("type") == "page" for t in targets):
                    break
            except Exception:
                time.sleep(0.5)
        page = next((t for t in (targets or []) if t.get("type") == "page"), None)
        if page is None:
            return False
        ws = websocket.create_connection(
            page["webSocketDebuggerUrl"], timeout=60, suppress_origin=True
        )
        _id = [0]
        _cdp_call(ws, "Page.enable", {}, _id)

        url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        _cdp_call(ws, "Page.navigate", {"url": url}, _id)

        # 等页面加载出与目标文件名匹配的图表 <img>（PMC 文章页图片懒加载，仅等 readyState 不够）
        check_js = (
            "(document.readyState === 'complete' && ["
            + ",".join("'" + s.replace("'", "") + "'" for s in stems.values())
            + "].some(s => Array.from(document.querySelectorAll('img[src]'))"
            + ".some(i => i.src.toLowerCase().replace(/[^a-z0-9]/g, '').includes("
            + "s.toLowerCase().replace(/[^a-z0-9]/g, '')))))"
        )
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                res = _cdp_call(ws, "Runtime.evaluate", {
                    "expression": check_js, "returnByValue": True,
                }, _id)
                if res.get("result", {}).get("value"):
                    break
            except Exception:
                pass
            time.sleep(1.5)

        stem_list = _json.dumps(list(stems.values()))
        js = (
            "(async () => {"
            f"  const stems = {stem_list};"
            "  const out = {};"
            "  const imgs = Array.from(document.querySelectorAll('img[src]'));"
            "  const norm = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');"
            "  for (const stem of stems) {"
            "    const img = imgs.find(i => norm(i.src).includes(norm(stem)));"
            "    if (!img) continue;"
            "    try {"
            "      const resp = await fetch(img.src);"
            "      const blob = await resp.blob();"
            "      const buf = new Uint8Array(await blob.arrayBuffer());"
            "      let bin = '';"
            "      for (let i = 0; i < buf.length; i += 0x8000) {"
            "        bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));"
            "      }"
            "      out[stem] = 'data:' + (blob.type || 'image/jpeg') + ';base64,' + btoa(bin);"
            "    } catch (e) {}"
            "  }"
            "  return JSON.stringify(out);"
            "})()"
        )
        res = _cdp_call(ws, "Runtime.evaluate", {
            "expression": js, "awaitPromise": True, "returnByValue": True,
        }, _id)
        got = _json.loads(res.get("result", {}).get("value") or "{}")
        if not got:
            # 图片可能仍在懒加载，稍候重试一次
            time.sleep(6)
            res = _cdp_call(ws, "Runtime.evaluate", {
                "expression": js, "awaitPromise": True, "returnByValue": True,
            }, _id)
            got = _json.loads(res.get("result", {}).get("value") or "{}")
        for fig in missing:
            stem = re.sub(r"\.(jpg|jpeg|gif|png|tif|tiff)$", "", fig["file"], flags=re.I)
            data_url = got.get(_norm_figname(stem)) or got.get(stem)
            if data_url and ";base64," in data_url:
                fig["data"] = base64.b64decode(data_url.split(";base64,", 1)[1])
        return True
    except Exception:
        return False
    finally:
        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass


def _screenshot_figures(pmcid: str, missing: list[dict]) -> None:
    """
    最后手段：无头浏览器对图表详情页整页截图（含少量页面元素但图表完整可读）。
    截图缓存到 data/fig_cache/，并设置 fig['data'] 与 fig['is_screenshot']=True。
    """
    import subprocess

    browser = _find_browser()
    if browser is None:
        return
    cache_dir = os.path.dirname(_fig_zip_path(pmcid))
    for fig in missing[:8]:  # 与 LLM 视觉分析上限一致，避免耗时过长
        fig_id = fig.get("fig_id") or ""
        if not fig_id:
            continue
        cache_path = os.path.join(cache_dir, f"{pmcid}_{_norm_figname(fig_id)}.png")
        # 最多尝试 2 次（页面懒加载偶发截到空页，小文件视为失败重试）
        for attempt in range(2):
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 30000:
                break
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except OSError:
                    pass
            url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/figure/{fig_id}/"
            cmd = [
                browser, "--headless=new", "--disable-gpu", "--no-first-run",
                "--disable-extensions", f"--screenshot={cache_path}",
                "--window-size=900,1400", "--virtual-time-budget=25000", url,
            ]
            try:
                subprocess.run(cmd, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                continue
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 30000:
            with open(cache_path, "rb") as f:
                fig["data"] = f.read()
            fig["is_screenshot"] = True


def _parse_jats_sections(xml_bytes: bytes) -> list[dict]:
    """
    解析 JATS 全文 XML 为章节列表。两个数据源（NCBI efetch / Europe PMC）
    的 XML 结构一致，共用本解析。解析不出正文返回 []，由调用方走兜底。
    """
    root = ET.fromstring(xml_bytes)
    body = root.find(".//body")
    if body is None:
        return []
    sections = []
    # body 直挂的开篇段落（首个 sec 之前）——旧版会静默丢弃这部分正文
    lead = []
    for child in body:
        if child.tag == "sec":
            break
        if child.tag == "p":
            t = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
            if t:
                lead.append(t)
    if lead:
        sections.append({"title": "引言", "text": " ".join(lead)})
    for sec in body.findall("sec"):
        title = _merge_text(sec.find("title"))
        paras = [" ".join(p.itertext()).strip() for p in sec.iter("p")]
        text = " ".join(x for x in paras if x)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            sections.append({"title": title or "正文", "text": text})
    if not sections:
        text = re.sub(r"\s+", " ", " ".join(
            " ".join(p.itertext()).strip() for p in body.iter("p")
        )).strip()
        if text:
            sections.append({"title": "正文", "text": text})
    return sections


_EPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def fetch_pmc_fulltext(pmcid: str) -> list[dict]:
    """
    抓取 PMC 开放获取全文，按章节切分（引言/方法/结果/讨论等）。
    返回 [{"title": 章节标题, "text": 章节正文}, ...]。

    双通道兜底（v1.4.1 修复偶发解析不出全文）：
    1. NCBI efetch db=pmc —— 主通道；对非 OA 文献会返回「200 + 无正文的错误 XML」
    2. Europe PMC fullTextXML —— 覆盖面更广的 OA 全文源，与主通道互补
    两路都拿不到正文时抛出带原因的 RuntimeError，不再静默返回空列表。
    """
    pmc_num = pmcid.replace("PMC", "")
    errors = []

    # ---- 通道 1：NCBI efetch ----
    try:
        time.sleep(0.4)
        r = _ncbi_get(EFETCH, {"db": "pmc", "id": pmc_num, "retmode": "xml"}, timeout=60)
        try:
            sections = _parse_jats_sections(r.content)
        except ET.ParseError as pe:
            sections = []
            errors.append(f"NCBI 返回内容不是有效 XML（{pe}）")
        if sections:
            return sections
        if not errors:
            err_text = ""
            try:
                err_text = (ET.fromstring(r.content).findtext(".//ERROR") or "").strip()
            except ET.ParseError:
                pass
            errors.append(
                "NCBI efetch 未返回正文" + (f"（{err_text[:80]}）" if err_text else "")
            )
    except requests.RequestException as e:
        errors.append(f"NCBI 请求失败（{e.__class__.__name__}）")

    # ---- 通道 2：Europe PMC fullTextXML ----
    try:
        time.sleep(0.4)
        r2 = requests.get(
            _EPMC_FULLTEXT_URL.format(pmcid=pmcid), headers=HEADERS, timeout=60
        )
        if r2.status_code == 200:
            try:
                sections = _parse_jats_sections(r2.content)
            except ET.ParseError as pe:
                sections = []
                errors.append(f"Europe PMC 返回内容不是有效 XML（{pe}）")
            if sections:
                return sections
            if not any("Europe PMC" in x for x in errors):
                errors.append("Europe PMC 全文 XML 无正文")
        else:
            errors.append(f"Europe PMC 返回 HTTP {r2.status_code}")
    except requests.RequestException as e:
        errors.append(f"Europe PMC 请求失败（{e.__class__.__name__}）")

    raise RuntimeError(
        "未能获取该文献的 PMC 开放全文（" + "；".join(errors[:2]) +
        "）。该文献可能不属于 PMC 开放获取子集（如作者手稿 / 付费文献），"
        "可通过上方「PDF 全文 (PMC)」或 DOI 链接直接阅读原文。"
    )


def _fig_zip_path(pmcid: str) -> str:
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fig_cache")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, f"{pmcid}.zip")


def _norm_figname(s: str) -> str:
    """文件名归一化：仅保留小写字母数字，用于模糊匹配"""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _read_zip_names(zip_path: str):
    """读取 zip 的文件列表；文件损坏返回 None 并删除坏缓存以便重新下载"""
    import zipfile
    try:
        with zipfile.ZipFile(zip_path) as z:
            return z.namelist()
    except zipfile.BadZipFile:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return None


def fetch_figure_images(pmcid: str, figures: list[dict]) -> None:
    """
    将每张图表的图片二进制数据填入 figure['data']，按以下兜底链依次尝试：

    1. Europe PMC 图片包（zip，本地缓存）——完全开放获取文献的主通道
    2. Europe PMC 逐图接口 /image/{name} —— zip 命名对不上时的补充
    3. 无头浏览器访问 PMC 页面抓取原图（浏览器指纹可过 NCBI 反爬）——
       非 OA / 作者手稿文章的救底通道，需本机有 Edge / Chrome
    4. 无头浏览器对图表页整页截图（最后手段）

    v1.3.3 变化：非开放获取文献不再直接抛错——实测其 XML 中能解析出图表
    列表，只是图片包下载受限；改走浏览器兜底后即可取到图片。
    """
    import zipfile

    zip_err = ""
    zip_path = _fig_zip_path(pmcid)
    names = _read_zip_names(zip_path) if os.path.exists(zip_path) else None
    if names is None:
        try:
            time.sleep(0.4)
            r = requests.get(_FIG_ZIP_URL.format(pmcid=pmcid), headers=HEADERS, timeout=120)
            r.raise_for_status()
            ct = (r.headers.get("Content-Type") or "").lower()
            if not r.content.startswith(b"PK") or "xml" in ct or "json" in ct:
                body = r.content[:400].decode("utf-8", "ignore")
                m = re.search(r"<errMsg>(.*?)</errMsg>", body)
                zip_err = m.group(1).strip() if m else "接口未返回有效数据"
                names = None
            else:
                with open(zip_path, "wb") as f:
                    f.write(r.content)
                names = _read_zip_names(zip_path)
                if names is None:
                    zip_err = "下载的图片包不是有效 zip 文件"
        except Exception as e:
            zip_err = str(e)[:120]
            names = None

    # ---- 通道 1：zip 匹配 ----
    if names:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            lower_map = {n.lower(): n for n in names}
            norm_map = {_norm_figname(n): n for n in names}
            for fig in figures:
                base = fig["file"]
                stem = re.sub(r"\.(jpg|jpeg|gif|png|tif|tiff)$", "", base, flags=re.I)
                data = None
                # 1) 精确 / 扩展名补全（大小写不敏感）
                candidates = [base] + [stem + e for e in _IMG_EXTS]
                for cand in candidates:
                    real = lower_map.get(cand.lower())
                    if real is not None:
                        data = z.read(real)
                        break
                # 2) 归一化等值匹配（去掉 - _ . 空格后相等）
                if data is None:
                    real = norm_map.get(_norm_figname(stem))
                    if real is not None and real.lower().endswith(_IMG_EXTS):
                        data = z.read(real)
                # 3) 模糊包含匹配
                if data is None:
                    ns, nn = _norm_figname(stem), None
                    if len(ns) >= 4:
                        for n in names:
                            if nn is None and ns in _norm_figname(n) and n.lower().endswith(_IMG_EXTS):
                                nn = n
                                break
                    if nn is not None:
                        data = z.read(nn)
                if data is not None:
                    fig["data"] = data

    missing = [f for f in figures if not f.get("data")]
    if not missing:
        return

    # ---- 通道 2：Europe PMC 逐图接口 ----
    for fig in missing:
        base = fig["file"]
        stem = re.sub(r"\.(jpg|jpeg|gif|png|tif|tiff)$", "", base, flags=re.I)
        for cand in [base] + [stem + e for e in _IMG_EXTS]:
            try:
                r = requests.get(
                    _IMG_URL.format(pmcid=pmcid, name=cand), headers=HEADERS, timeout=30
                )
                ct = (r.headers.get("Content-Type") or "").lower()
                if r.status_code == 200 and "image" in ct and len(r.content) > 500:
                    fig["data"] = r.content
                    break
            except Exception:
                break
    missing = [f for f in figures if not f.get("data")]
    if not missing:
        return

    # ---- 通道 3/4：无头浏览器（抓原图 / 整页截图） ----
    got_browser = _browser_fetch_images(pmcid, missing)
    missing = [f for f in figures if not f.get("data")]

    if missing and got_browser:
        _screenshot_figures(pmcid, missing)

    if all(not f.get("data") for f in figures) and figures:
        hint = f"该文献为非完全开放获取，Europe PMC 图片包不可用（{zip_err}）" if zip_err else "未能获取任何图表图片"
        raise RuntimeError(
            hint + "；已尝试浏览器截图兜底但仍失败（可能本机无 Edge/Chrome 浏览器）"
        )


def search_and_fetch(query: str, retmax: int = 20, sort: str = "relevance") -> list[dict]:
    pmids = search(query, retmax=retmax, sort=sort)
    return fetch_articles(pmids)


def mesh_suggest(term: str) -> list[str]:
    """简单的 MeSH 词表提示（基于 PubMed 拼写建议接口，可选）"""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/espell.fcgi"
    try:
        r = requests.get(url, params={"db": "pubmed", "term": term}, headers=HEADERS, timeout=10)
        corrected = ET.fromstring(r.content).findtext(".//CorrectedQuery")
        return [corrected] if corrected and corrected.lower() != term.lower() else []
    except Exception:
        return []
