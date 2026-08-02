from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

log = logging.getLogger("founderblaze.competitor_research.search")

UA = "Mozilla/5.0 (compatible; FounderBlazeBot/1.0)"


def web_search(query: str, *, num: int = 8) -> list[dict[str, str]]:
    """Serper → Brave → DuckDuckGo failover (port of connectors webSearch)."""
    errors: list[str] = []
    if (os.environ.get("SERPER_API_KEY") or "").strip():
        try:
            return _search_serper(query, num)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"serper:{exc}")
            log.warning("serper failed: %s", exc)
    if (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip():
        try:
            return _search_brave(query, num)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"brave:{exc}")
            log.warning("brave failed: %s", exc)
    try:
        return _search_duckduckgo(query, num)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"duckduckgo:{exc}")
    raise RuntimeError(
        f"webSearch failed: {'; '.join(errors) or 'no providers available'}"
    )


def _search_serper(query: str, num: int) -> list[dict[str, str]]:
    key = os.environ["SERPER_API_KEY"].strip()
    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "num": num},
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Serper {res.status_code}")
    data = res.json()
    hits: list[dict[str, str]] = []
    for r in data.get("organic") or []:
        if r.get("link") and r.get("title"):
            hits.append(
                {
                    "title": str(r["title"]),
                    "url": str(r["link"]),
                    "snippet": str(r.get("snippet") or ""),
                }
            )
    return hits[:num]


def _search_brave(query: str, num: int) -> list[dict[str, str]]:
    key = os.environ["BRAVE_SEARCH_API_KEY"].strip()
    with httpx.Client(timeout=30.0) as client:
        res = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": str(num)},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
    if res.status_code >= 400:
        raise RuntimeError(f"Brave {res.status_code}")
    data = res.json()
    hits: list[dict[str, str]] = []
    for r in (data.get("web") or {}).get("results") or []:
        if r.get("url") and r.get("title"):
            hits.append(
                {
                    "title": str(r["title"]),
                    "url": str(r["url"]),
                    "snippet": str(r.get("description") or ""),
                }
            )
    return hits[:num]


def _strip_html(s: str) -> str:
    t = re.sub(r"<[^>]+>", "", s or "")
    return (
        t.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .strip()
    )


def _search_duckduckgo(query: str, num: int) -> list[dict[str, str]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        res = client.post(
            "https://html.duckduckgo.com/html/",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "user-agent": UA,
            },
            data={"q": query},
        )
    if res.status_code >= 400:
        raise RuntimeError(f"DuckDuckGo {res.status_code}")
    html = res.text
    hits: list[dict[str, str]] = []
    re_hit = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>'
        r'[\s\S]*?(?:class="result__snippet"[^>]*>([\s\S]*?)</(?:a|td|div)>)?',
        re.I,
    )
    for match in re_hit.finditer(html):
        if len(hits) >= num:
            break
        href = match.group(1) or ""
        title = _strip_html(match.group(2) or "")
        snippet = _strip_html(match.group(3) or "")
        final_url = href
        try:
            u = urlparse(href)
            if "uddg" in parse_qs(u.query):
                final_url = unquote(parse_qs(u.query)["uddg"][0])
            elif href.startswith("//"):
                final_url = "https:" + href
            elif href.startswith("/"):
                final_url = "https://duckduckgo.com" + href
        except Exception:  # noqa: BLE001
            continue
        if not title or not final_url.startswith("http"):
            continue
        hits.append({"title": title, "url": final_url, "snippet": snippet})
    return hits


def root_domain(url: str) -> str | None:
    try:
        host = urlparse(url).hostname or ""
        return host.replace("www.", "").lower() or None
    except Exception:  # noqa: BLE001
        return None


def name_from_url(url: str) -> str:
    host = root_domain(url) or url
    part = host.split(".")[0] if host else url
    return part[:1].upper() + part[1:] if part else url
