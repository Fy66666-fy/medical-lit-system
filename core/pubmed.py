"""PubMed E-utilities API 封装（免费，无需 API Key，限速 3 req/s）"""
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
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip()
        articles.append(
            {
                "pmid": pmid,
                "title": title,
                "journal": journal,
                "year": year,
                "authors": authors,
                "abstract": abstract,
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            }
        )
    return articles


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
