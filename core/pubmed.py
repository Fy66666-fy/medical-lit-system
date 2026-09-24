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


def _ncbi_get(path: str, params: dict, timeout: int = 30, retries: int = 2):
    """带重试的 NCBI E-utilities 请求（自动附加 tool 标识，缓解偶发网络抖动/限流）"""
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
                time.sleep(1.0 + attempt)
    raise last_exc


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
        figures.append({"label": label, "caption": caption, "file": href})
    return figures


_FIG_ZIP_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles"
_IMG_EXTS = (".jpg", ".jpeg", ".gif", ".png", ".tif", ".tiff")


def fetch_pmc_fulltext(pmcid: str) -> list[dict]:
    """
    抓取 PMC 开放获取全文，按章节切分（引言/方法/结果/讨论等）。
    返回 [{"title": 章节标题, "text": 章节正文}, ...]；无章节结构时合并为单章。
    """
    pmc_num = pmcid.replace("PMC", "")
    time.sleep(0.4)
    r = _ncbi_get(EFETCH, {"db": "pmc", "id": pmc_num, "retmode": "xml"}, timeout=60)
    root = ET.fromstring(r.content)
    body = root.find(".//body")
    if body is None:
        return []
    sections = []
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
    从 Europe PMC 下载该文献的图片包（zip，本地缓存），
    将每张图表的图片二进制数据填入 figure['data']。

    v1.2.2 修复：
    1. Europe PMC 对非开放获取文章返回 200 + XML 错误体，旧版会把错误体当 zip
       写入缓存并永久报 BadZipFile——现在校验 zip 魔数（PK）后才落盘，并给出可读错误
    2. 已损坏的缓存文件会自动删除并重新下载
    3. 图片文件名匹配改为大小写不敏感 + 归一化模糊匹配（fig1 ↔ F1.jpg 等场景）
    """
    import zipfile

    zip_path = _fig_zip_path(pmcid)
    names = _read_zip_names(zip_path) if os.path.exists(zip_path) else None
    if names is None:
        time.sleep(0.4)
        r = requests.get(_FIG_ZIP_URL.format(pmcid=pmcid), headers=HEADERS, timeout=120)
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()
        if not r.content.startswith(b"PK") or "xml" in ct or "json" in ct:
            body = r.content[:400].decode("utf-8", "ignore")
            m = re.search(r"<errMsg>(.*?)</errMsg>", body)
            raise RuntimeError(
                "Europe PMC 图片包不可用：" + (m.group(1).strip() if m else "接口未返回有效数据")
            )
        with open(zip_path, "wb") as f:
            f.write(r.content)
        names = _read_zip_names(zip_path)
        if names is None:
            raise RuntimeError("下载的图片包不是有效 zip 文件")

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
