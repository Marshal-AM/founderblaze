from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

log = logging.getLogger("founderblaze.social_listening.fetch")

MIN_PAGE_CHARS = 200
UA = "FounderBlazeSocialListening/0.1 (+https://github.com/local; product research)"


def normalize_url(input_url: str) -> str:
    trimmed = (input_url or "").strip()
    if not trimmed:
        raise RuntimeError("[product_url_invalid] Website URL is required")
    with_proto = (
        trimmed if re.match(r"^https?://", trimmed, re.I) else f"https://{trimmed}"
    )
    try:
        u = urlparse(with_proto)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"[product_url_invalid] Invalid website URL: {input_url}") from exc
    if u.scheme not in ("http", "https"):
        raise RuntimeError(
            f"[product_url_invalid] Invalid website URL protocol: {input_url}"
        )
    return with_proto


def html_to_text(html: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<noscript[\s\S]*?</noscript>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = re.sub(r"</div>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def chunk_text(text: str, chunk_size: int = 2800, overlap: int = 200) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    if len(clean) <= chunk_size:
        return [clean]
    chunks: list[str] = []
    i = 0
    while i < len(clean):
        end = min(i + chunk_size, len(clean))
        chunks.append(clean[i:end])
        if end >= len(clean):
            break
        i = end - overlap
    return chunks


def fetch_page_text(url: str, timeout_ms: int = 25_000) -> dict[str, Any]:
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout_ms / 1000.0,
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
        ) as client:
            res = client.get(url)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"[product_url_unreachable] Failed to fetch {url}: {exc}"
        ) from exc
    if res.status_code >= 400:
        raise RuntimeError(
            f"[product_url_http_error] Failed to fetch {url}: HTTP {res.status_code}"
        )
    html = res.text
    return {
        "url": str(res.url),
        "text": html_to_text(html),
        "bytes": len(html.encode("utf-8", errors="ignore")),
    }


def fetch_jina_text(url: str) -> str:
    key = (os.environ.get("JINA_API_KEY") or "").strip()
    if not key:
        return ""
    jina_url = f"https://r.jina.ai/{url}"
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=40.0,
            headers={"Authorization": f"Bearer {key}", "Accept": "text/plain"},
        ) as client:
            res = client.get(jina_url)
        if res.status_code >= 400:
            return ""
        return re.sub(r"\s+", " ", res.text).strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("jina fetch failed: %s", exc)
        return ""


def fetch_site_corpus(home_url: str) -> dict[str, Any]:
    home = urlparse(home_url)
    base = f"{home.scheme}://{home.netloc}"
    candidates = [
        home_url,
        urljoin(base + "/", "about"),
        urljoin(base + "/", "product"),
        urljoin(base + "/", "pricing"),
    ]
    pages: list[dict[str, str]] = []
    seen: set[str] = set()
    for u in candidates:
        key = u.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        try:
            page = fetch_page_text(u)
            if len(page["text"]) < MIN_PAGE_CHARS:
                continue
            pages.append({"url": page["url"], "text": page["text"][:40_000]})
            time.sleep(0.3)
        except Exception as exc:  # noqa: BLE001
            log.info("skip path %s: %s", u, exc)
        if len(pages) >= 3:
            break

    if not pages:
        jina = fetch_jina_text(home_url)
        if len(jina) >= MIN_PAGE_CHARS:
            pages.append({"url": home_url, "text": jina[:40_000]})

    if not pages:
        raise RuntimeError(
            f"[product_url_empty] Could not extract readable content from {home_url}"
        )

    combined = "\n\n".join(p["text"] for p in pages)
    return {"pages": pages, "combined": combined}


def product_from_name_fallback(product_url: str, product_name: str | None) -> dict[str, Any]:
    host = urlparse(normalize_url(product_url)).hostname or "product"
    host = host.replace("www.", "")
    name = (product_name or "").strip()
    if not name:
        # tasknest.app → Tasknest
        label = host.split(".")[0].replace("-", " ").replace("_", " ").strip()
        name = label.title() if label else "Product"
    return {
        "product_name": name,
        "one_liner": f"{name} — product site at {host}",
        "description": f"{name} (discovered from {host}; page scrape unavailable).",
        "disclosure_line": f"disclosure: I use {name} ({host})",
        "keywords": [name.lower(), host],
        "subreddits": ["SaaS", "startups", "Entrepreneur", "productivity"],
        "max_posts_per_cycle": 5,
        "window_hours": 24,
        "website_url": normalize_url(product_url),
        "fallback": True,
    }
