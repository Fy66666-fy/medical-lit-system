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


def fetch_articles(pmids: list[str]) -> list[dict]:
    """批量拉取文献详情（标题/作者/期刊/日期/摘要）"""
    if not pmids:
        return []
    time.sleep(0.4)  # 尊重 NCBI 限速
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    r = requests.get(EFETCH, params=params, headers=HEADERS, timeout=30)
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
    params = {"db": "pmc", "id": pmc_num, "retmode": "xml"}
    r = requests.get(EFETCH, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
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


def _fig_zip_path(pmcid: str) -> str:
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "fig_cache")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, f"{pmcid}.zip")


def fetch_figure_images(pmcid: str, figures: list[dict]) -> None:
    """
    从 Europe PMC 下载该文献的图片包（zip，本地缓存），
    将每张图表的图片二进制数据填入 figure['data']。
    """
    import io
    import zipfile

    zip_path = _fig_zip_path(pmcid)
    if not os.path.exists(zip_path):
        time.sleep(0.4)
        r = requests.get(_FIG_ZIP_URL.format(pmcid=pmcid), headers=HEADERS, timeout=120)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(r.content)

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        for fig in figures:
            base = fig["file"]
            stem = re.sub(r"\.(jpg|jpeg|gif|png|tif|tiff)$", "", base, flags=re.I)
            candidates = [base] + [stem + e for e in _IMG_EXTS]
            data = None
            for cand in candidates:
                if cand in names:
                    data = z.read(cand)
                    break
            if data is None:
                # 兜底：按文件名片段模糊匹配
                for n in names:
                    if stem in n and n.lower().endswith(_IMG_EXTS):
                        data = z.read(n)
                        break
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
