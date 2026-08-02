from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("founderblaze.competitor_research.fetch")

UA = "FounderBlazeCompetitorResearch/0.1 (+https://github.com/local; product research)"

BOILERPLATE = re.compile(
    r"(cookie|consent|privacy policy|terms of service|subscribe to|newsletter|"
    r"sign in|log in|©|all rights reserved|follow us|back to top|"
    r"skip to (main )?content|we use cookies|accept all)",
    re.I,
)


def truncate_for_llm(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n…[truncated]"


def is_junk(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 100:
        return True
    if re.match(r"^loading", t, re.I):
        return True
    if re.search(
        r"please enable js|disable any ad blocker|enable javascript", t, re.I
    ):
        return True
    return False


def is_bogus_jina(markdown: str) -> bool:
    t = (markdown or "").strip()
    if len(t) < 80:
        return True
    if re.match(r"^loading[.…]*$", t, re.I):
        return True
    if re.search(
        r"please enable js|disable any ad blocker|enable javascript", t, re.I
    ):
        return True
    if re.match(r"^just a moment", t, re.I):
        return True
    if re.search(r"cf-browser-rendering|access denied|captcha", t, re.I) and len(t) < 200:
        return True
    return False


def clean_markdown(md: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw in md.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line).strip()
        if not line:
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line).strip()
        if BOILERPLATE.search(line):
            continue
        if len(re.findall(r"[|·•]", line)) >= 3 and len(line) < 120:
            continue
        key = line.lower()
        if key in seen and len(line) < 80:
            continue
        seen.add(key)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    s = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (
        s.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return re.sub(r"\s+", " ", s).strip()


def fetch_http_page(url: str, timeout_s: float = 25.0) -> dict[str, Any]:
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout_s,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
    ) as client:
        res = client.get(url)
    if res.status_code >= 400:
        raise RuntimeError(f"HTTP {res.status_code} for {url}")
    text = html_to_text(res.text)
    return {
        "url": str(res.url),
        "title": url,
        "text": text[:40_000],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _call_jina(url: str, *, engine: str, timeout_sec: int, no_cache: bool = False) -> dict[str, Any]:
    api_key = (os.environ.get("JINA_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("JINA_API_KEY missing")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Return-Format": "markdown",
        "X-Engine": engine,
        "X-Timeout": str(timeout_sec),
        "X-Retain-Images": "none",
    }
    if no_cache:
        headers["X-No-Cache"] = "true"
    with httpx.Client(follow_redirects=True, timeout=timeout_sec + 20) as client:
        res = client.post("https://r.jina.ai/", headers=headers, json={"url": url})
    raw = res.text
    if res.status_code >= 400:
        snippet = re.sub(r"\s+", " ", raw[:240])
        raise RuntimeError(f"jina {res.status_code}: {snippet}")
    markdown = ""
    title = url
    try:
        data = res.json()
        payload = data.get("data") or {}
        if isinstance(payload, str):
            markdown = payload.strip()
        else:
            markdown = (payload.get("content") or payload.get("text") or "").strip()
            title = (payload.get("title") or "").strip() or title
            desc = payload.get("description") or ""
            if is_bogus_jina(markdown) and isinstance(desc, str) and len(desc) > 80:
                markdown = f"# {title}\n\n{desc}\n\n{markdown}".strip()
    except Exception:  # noqa: BLE001
        markdown = raw.strip()
    if is_bogus_jina(markdown):
        raise RuntimeError("jina empty/short content")
    return {
        "url": url,
        "title": title,
        "text": markdown[:40_000],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_page_jina(url: str) -> dict[str, Any]:
    """Jina Reader with HTTP fallback (port of connectors fetchPageJina)."""
    if not (os.environ.get("JINA_API_KEY") or "").strip():
        log.warning("JINA_API_KEY missing; using http-fetch fallback url=%s", url)
        return fetch_http_page(url)

    attempts = [
        {"engine": "browser", "timeout_sec": 40, "no_cache": False},
        {"engine": "browser", "timeout_sec": 50, "no_cache": True},
        {"engine": "direct", "timeout_sec": 25, "no_cache": True},
    ]
    errors: list[str] = []
    for attempt in attempts:
        try:
            return _call_jina(url, **attempt)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            errors.append(f"{attempt['engine']}:{msg}")
            if re.search(r"jina 401|jina 403|CAPTCHA|captcha", msg, re.I):
                break
    log.warning("jina failed; http fallback url=%s err=%s", url, " | ".join(errors))
    return fetch_http_page(url)


def fetch_vendor_evidence(base_url: str, *, max_chars: int = 4200) -> dict[str, Any]:
    base = base_url.rstrip("/")
    feature_paths = [base, f"{base}/features", f"{base}/product"]
    pricing_paths = [f"{base}/pricing", f"{base}/plans"]

    feature_text = ""
    feature_url = base
    fetched_at = datetime.now(timezone.utc).isoformat()
    for url in feature_paths:
        try:
            page = fetch_page_jina(url)
            if is_junk(page["text"]):
                continue
            feature_text = clean_markdown(page["text"])
            feature_url = page["url"]
            fetched_at = page["fetched_at"]
            break
        except Exception as exc:  # noqa: BLE001
            log.info("feature fetch skip %s: %s", url, exc)

    pricing_text = ""
    pricing_url = feature_url
    for url in pricing_paths:
        try:
            page = fetch_page_jina(url)
            if is_junk(page["text"]):
                continue
            pricing_text = clean_markdown(page["text"])
            pricing_url = page["url"]
            if re.search(r"\$\d|/user|/seat|per (month|user|seat)|free", pricing_text, re.I):
                break
        except Exception as exc:  # noqa: BLE001
            log.info("pricing fetch skip %s: %s", url, exc)

    combined = "\n\n".join(
        p
        for p in (
            f"# Overview ({feature_url})\n{feature_text}" if feature_text else "",
            f"# Pricing ({pricing_url})\n{pricing_text}" if pricing_text else "",
        )
        if p
    )[:max_chars]

    return {
        "text": combined or f"(no public content for {base_url})",
        "pricingText": (pricing_text or feature_text)[:max_chars],
        "url": feature_url,
        "pricingUrl": pricing_url,
        "fetched_at": fetched_at,
    }
