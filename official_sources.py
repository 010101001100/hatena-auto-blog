import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS


VENDORS = [
    {
        "keywords": ["chrome", "google chrome", "cookie", "キャッシュ", "gmail", "google drive", "googleドライブ", "android", "googleフォト"],
        "domains": ["support.google.com", "developers.google.com"],
    },
    {
        "keywords": ["windows", "onedrive", "edge", "microsoft", "office", "excel", "word", "outlook"],
        "domains": ["support.microsoft.com", "learn.microsoft.com"],
    },
    {
        "keywords": ["iphone", "ipad", "ios", "mac", "macos", "safari", "icloud", "apple"],
        "domains": ["support.apple.com"],
    },
    {
        "keywords": ["firefox", "mozilla"],
        "domains": ["support.mozilla.org"],
    },
    {
        "keywords": ["github", "git"],
        "domains": ["docs.github.com"],
    },
    {
        "keywords": ["chatgpt", "openai", "api"],
        "domains": ["help.openai.com", "developers.openai.com", "platform.openai.com"],
    },
    {
        "keywords": ["はてな", "hatena", "はてなブログ"],
        "domains": ["help.hatenablog.com", "developer.hatena.ne.jp"],
    },
]

DEFAULT_DOMAINS = [
    "support.google.com",
    "support.microsoft.com",
    "support.apple.com",
    "support.mozilla.org",
    "docs.github.com",
    "help.openai.com",
]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36"
)


def official_domains_for(topic: str) -> list[str]:
    t = topic.lower()
    out = []
    for vendor in VENDORS:
        if any(k.lower() in t for k in vendor["keywords"]):
            out.extend(vendor["domains"])
    if not out:
        out = DEFAULT_DOMAINS[:]
    return list(dict.fromkeys(out))[:4]


def is_official_url(url: str, allowed_domains: list[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def fetch_page_text(url: str, timeout: int = 20) -> str:
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": UA, "Accept-Language": "ja,en-US;q=0.8,en;q=0.6"},
        )
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" not in ctype:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        text = clean_text(main.get_text(" ", strip=True))
        return text[:14000]
    except requests.RequestException:
        return ""


def search_official(topic: str, max_sources: int = 4) -> list[dict]:
    domains = official_domains_for(topic)
    candidates = []
    seen = set()

    for domain in domains:
        query = f'site:{domain} "{topic}"'
        for attempt in range(2):
            try:
                results = DDGS(timeout=12).text(
                    query,
                    region="jp-jp",
                    safesearch="moderate",
                    max_results=6,
                )
                break
            except Exception as e:
                if attempt:
                    print(f"WARNING: 公式検索失敗 {domain}: {e}")
                    results = []
                else:
                    time.sleep(2)

        for item in results or []:
            url = (item.get("href") or item.get("url") or "").strip()
            if not url or url in seen or not is_official_url(url, domains):
                continue
            seen.add(url)
            candidates.append({
                "title": clean_text(item.get("title") or url),
                "url": url,
                "snippet": clean_text(item.get("body") or item.get("snippet") or ""),
                "domain": (urlparse(url).hostname or "").lower(),
            })

    sources = []
    for item in candidates[:10]:
        page_text = fetch_page_text(item["url"])
        evidence = page_text if len(page_text) >= 500 else item["snippet"]
        if len(evidence) < 120:
            continue
        item["evidence"] = evidence[:9000]
        sources.append(item)
        if len(sources) >= max_sources:
            break

    return sources


def source_summary_for_prompt(sources: list[dict]) -> str:
    blocks = []
    for i, src in enumerate(sources, 1):
        blocks.append(
            f"[公式資料{i}]\n"
            f"タイトル: {src['title']}\n"
            f"URL: {src['url']}\n"
            f"抜粋: {src['evidence'][:6500]}"
        )
    return "\n\n".join(blocks)
