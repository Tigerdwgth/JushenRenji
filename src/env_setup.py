import os, socket, logging


def apply_network_workarounds(profile=None):
    """根据 JSR_NETWORK_PROFILE 环境变量配置网络。当前唯一 profile: gsjts。"""
    profile = profile or os.environ.get("JSR_NETWORK_PROFILE", "")
    if profile != "gsjts":
        return False
    os.environ["HTTP_PROXY"] = os.environ.get("HTTP_PROXY") or "http://127.0.0.1:7890"
    os.environ["HTTPS_PROXY"] = os.environ.get("HTTPS_PROXY") or "http://127.0.0.1:7890"
    os.environ["http_proxy"] = os.environ["HTTP_PROXY"]
    os.environ["https_proxy"] = os.environ["HTTPS_PROXY"]
    no_proxy_default = "dashscope.aliyuncs.com,aliyuncs.com,aliyun.com,localhost,127.0.0.1"
    os.environ.setdefault("NO_PROXY", no_proxy_default)
    os.environ.setdefault("no_proxy", no_proxy_default)
    for k in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    _orig = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **kw: [r for r in _orig(*a, **kw) if r[0] == socket.AF_INET]
    logging.info("[env_setup] GSJts profile: clash proxy + NO_PROXY aliyun + IPv4 only")
    return True


def parse_arxiv_link(link):
    """Extract arxiv id from a URL like https://arxiv.org/abs/2410.11758v2 -> 2410.11758."""
    import re
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,6})", link)
    if not m:
        m = re.search(r"([0-9]{4}\.[0-9]{4,6})", link)
    if not m:
        raise ValueError("cannot parse arxiv id from: %s" % link)
    return m.group(1)


def fetch_arxiv_by_id(arxiv_id):
    """Fetch one paper via arxiv API by id. Returns dict with title/submitted_date/pdf_url/etc."""
    import feedparser, re
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
    url = "https://export.arxiv.org/api/query?id_list=%s" % arxiv_id
    feed = feedparser.parse(url)
    if not feed.entries:
        raise RuntimeError("arxiv id not found: %s" % arxiv_id)
    e = feed.entries[0]
    pdf_url = "https://arxiv.org/pdf/%s" % arxiv_id
    for l in getattr(e, "links", []) or []:
        if getattr(l, "type", "") == "application/pdf":
            pdf_url = l.href
            break
    return {
        "title": (e.title or "").replace("\n", " ").strip(),
        "abstract": (e.summary or "").strip(),
        "link": e.link,
        "pdf_url": pdf_url,
        "submitted_date": (e.published or "")[:10],
        "updated_date": (e.updated or "")[:10],
        "arxiv_id": arxiv_id,
    }
