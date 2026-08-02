"""Tavily Reddit research via HTTP (mirrors TS ingest/tavilyReddit.ts)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger("founderblaze.social_listening.tavily")

TAVILY_BASE = "https://api.tavily.com"

REDDIT_THREADS_OUTPUT_SCHEMA = {
    "properties": {
        "threads": {
            "type": "array",
            "description": "Reddit seeker threads only",
            "items": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "Full Reddit thread URL, e.g. "
                            "https://www.reddit.com/r/sub/comments/id/slug/"
                        ),
                    },
                    "title": {"type": "string", "description": "Post title"},
                    "selftext": {
                        "type": "string",
                        "description": "Short excerpt or paraphrase of the OP ask",
                    },
                    "subreddit": {
                        "type": "string",
                        "description": "Subreddit name without r/",
                    },
                    "why": {
                        "type": "string",
                        "description": "Why this post matches the need (one sentence)",
                    },
                    "suggested_comment": {
                        "type": "string",
                        "description": (
                            "Natural Reddit reply for this thread: helpful peer tone, "
                            "no URLs, no CTAs, mention the product by name once if relevant"
                        ),
                    },
                },
                "required": ["url", "title", "selftext", "subreddit"],
            },
        },
    },
    "required": ["threads"],
}


def build_reddit_research_prompt(
    need_statement: str,
    max_threads: int,
    product: dict[str, str] | None = None,
) -> str:
    need = need_statement.strip().strip("{}").strip()
    product_hint = ""
    if product:
        product_hint = (
            f'\n- When writing suggested_comment, the commenter knows about '
            f'"{product["name"]}" ({product["oneLiner"]}). Mention {product["name"]} '
            f"once naturally if relevant. No URLs in comments."
        )
    return f"""Fetch Reddit posts where {{{need}}} I want ONLY reddit posts and NOTHING else.

Rules:
- Search and return ONLY real threads on reddit.com (www.reddit.com or old.reddit.com).
- ONLY seeker posts: people looking for a tool, workaround, recommendation, or help.
- EXCLUDE founder launches / showcases: "I built", "I'm building", "just launched", "feedback on my", product demos, Show HN.
- Each item must include a real /r/.../comments/.../ URL (not a subreddit homepage, user profile, or wiki).
- Return at least 1 and at most {max_threads} threads.
- Do not invent URLs. If unsure a URL is real, omit it.
- Output must match the provided JSON schema (threads array).
- For EVERY thread include suggested_comment: a ready-to-post Reddit reply (2–4 short paragraphs, peer tone, no links).{product_hint}"""


def ensure_reddit_thread_url(raw: str) -> str | None:
    try:
        u = urlparse(raw.strip())
        host = (u.hostname or "").lower()
        if not host.endswith("reddit.com"):
            return None
        m = re.match(
            r"^/r/([^/]+)/comments/([a-z0-9]+)(?:/([^/]*))?",
            u.path or "",
            re.I,
        )
        if not m or m.group(3) == "comment":
            return None
        slug = m.group(3) if m.group(3) and m.group(3) != "comment" else ""
        path = (
            f"/r/{m.group(1)}/comments/{m.group(2)}/{slug}/"
            if slug
            else f"/r/{m.group(1)}/comments/{m.group(2)}/"
        )
        return f"https://www.reddit.com{path}"
    except Exception:  # noqa: BLE001
        return None


def _api_key() -> str:
    key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("TAVILY_API_KEY is required for Reddit thread discovery")
    return key


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key()}",
        "X-Client-Source": "founderblaze-social-listening",
    }


def _extract_threads_array(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    if isinstance(raw.get("threads"), list):
        return raw["threads"]
    for key in ("output", "result", "data", "response"):
        nested = raw.get(key)
        if isinstance(nested, (dict, list)):
            arr = _extract_threads_array(nested)
            if arr:
                return arr
    content = raw.get("content")
    if isinstance(content, str):
        try:
            return _extract_threads_array(json.loads(content))
        except Exception:  # noqa: BLE001
            pass
    return []


def normalize_hits(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _extract_threads_array(raw):
        if not isinstance(row, dict):
            continue
        url = ensure_reddit_thread_url(
            str(row.get("url") or row.get("permalink") or row.get("link") or "")
        )
        if not url or url in seen:
            continue
        seen.add(url)
        sub_from_url = re.search(r"reddit\.com/r/([^/]+)", url, re.I)
        sub = str(row.get("subreddit") or (sub_from_url.group(1) if sub_from_url else ""))
        sub = re.sub(r"^r/", "", sub, flags=re.I).strip() or None
        comment = str(
            row.get("suggested_comment") or row.get("comment") or row.get("draft") or ""
        ).strip()
        out.append(
            {
                "url": url,
                "title": str(row.get("title") or "").strip() or "(untitled)",
                "selftext": str(
                    row.get("selftext")
                    or row.get("excerpt")
                    or row.get("snippet")
                    or row.get("why")
                    or ""
                ).strip(),
                "subreddit": sub,
                "why": str(row["why"]) if row.get("why") else None,
                "suggested_comment": comment or None,
            }
        )
    return out


def harvest_from_sources(content: Any, sources: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(hit: dict[str, Any]) -> None:
        if not hit.get("url") or hit["url"] in seen:
            return
        seen.add(hit["url"])
        out.append(hit)

    if isinstance(sources, list):
        for row in sources:
            if not isinstance(row, dict):
                continue
            url = ensure_reddit_thread_url(str(row.get("url") or row.get("link") or ""))
            if not url:
                continue
            sub = re.search(r"reddit\.com/r/([^/]+)", url, re.I)
            push(
                {
                    "url": url,
                    "title": str(row.get("title") or "").strip() or "(from Tavily sources)",
                    "selftext": str(
                        row.get("content") or row.get("snippet") or row.get("rawContent") or ""
                    ).strip(),
                    "subreddit": sub.group(1) if sub else None,
                    "why": "from Tavily research sources",
                    "suggested_comment": None,
                }
            )

    blob = "\n".join(
        [
            content if isinstance(content, str) else json.dumps(content or ""),
            json.dumps(sources or []),
        ]
    )
    urls = re.findall(
        r"https?://(?:www\.|old\.|np\.)?reddit\.com/r/[^/\s)\"']+/comments/[a-z0-9]+(?:/[^/\s)\"']*)?",
        blob,
        flags=re.I,
    )
    for raw in urls:
        url = ensure_reddit_thread_url(raw)
        if not url:
            continue
        sub = re.search(r"reddit\.com/r/([^/]+)", url, re.I)
        push(
            {
                "url": url,
                "title": "(from Tavily sources)",
                "selftext": "",
                "subreddit": sub.group(1) if sub else None,
                "why": "harvested from Tavily report text",
                "suggested_comment": None,
            }
        )
    return out


def discover_via_search(need_statement: str, max_threads: int) -> dict[str, Any]:
    need = need_statement.strip().strip("{}").strip()
    query = f"reddit.com posts where {need}"
    started = time.time()
    log.info("tavily search start max=%s", max_threads)
    with httpx.Client(timeout=60.0) as client:
        res = client.post(
            f"{TAVILY_BASE}/search",
            headers=_headers(),
            json={
                "query": query,
                "max_results": min(20, max(max_threads * 2, 8)),
                "include_domains": ["reddit.com"],
                "search_depth": "advanced",
                "include_answer": False,
            },
        )
        res.raise_for_status()
        data = res.json()
    results = data.get("results") if isinstance(data, dict) else []
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in results or []:
        if not isinstance(r, dict):
            continue
        url = ensure_reddit_thread_url(str(r.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        sub = re.search(r"reddit\.com/r/([^/]+)", url, re.I)
        hits.append(
            {
                "url": url,
                "title": str(r.get("title") or "").strip() or "(untitled)",
                "selftext": str(r.get("content") or "").strip(),
                "subreddit": sub.group(1) if sub else None,
                "why": "matched Tavily search (reddit.com)",
                "suggested_comment": None,
            }
        )
        if len(hits) >= max_threads:
            break
    return {
        "hits": hits,
        "meta": {
            "requestId": "search",
            "status": "completed",
            "model": "search",
            "prompt": query,
            "elapsedMs": int((time.time() - started) * 1000),
        },
    }


def discover_reddit_threads(
    *,
    need_statement: str,
    max_threads: int | None = None,
    product: dict[str, str] | None = None,
) -> dict[str, Any]:
    max_n = max_threads or int(os.environ.get("TAVILY_REDDIT_LIMIT", "10"))
    model = (os.environ.get("TAVILY_RESEARCH_MODEL") or "mini").strip()
    poll_ms = int(os.environ.get("TAVILY_POLL_MS", "3000"))
    timeout_ms = int(os.environ.get("TAVILY_RESEARCH_TIMEOUT_MS", "180000"))
    mode = (os.environ.get("TAVILY_REDDIT_MODE") or "research").strip().lower()
    if mode != "research":
        raise RuntimeError(
            f"TAVILY_REDDIT_MODE={mode} is not supported. Set TAVILY_REDDIT_MODE=research."
        )

    prompt = build_reddit_research_prompt(need_statement, max_n, product)
    started = time.time()
    log.info("tavily research start model=%s max=%s", model, max_n)

    with httpx.Client(timeout=120.0) as client:
        created = client.post(
            f"{TAVILY_BASE}/research",
            headers=_headers(),
            json={
                "input": prompt,
                "model": model,
                "output_schema": REDDIT_THREADS_OUTPUT_SCHEMA,
            },
        )
        if created.status_code >= 400:
            raise RuntimeError(
                f"Tavily research create failed HTTP {created.status_code}: "
                f"{created.text[:500]}"
            )
        created_body = created.json()
        request_id = (
            created_body.get("requestId")
            or created_body.get("request_id")
            or created_body.get("id")
        )
        if not request_id:
            raise RuntimeError(
                f"Tavily research did not return requestId: {json.dumps(created_body)[:300]}"
            )
        log.info("tavily research task created requestId=%s", request_id)

        last: dict[str, Any] = {"status": "pending"}
        while (time.time() - started) * 1000 < timeout_ms:
            poll = client.get(
                f"{TAVILY_BASE}/research/{request_id}",
                headers=_headers(),
            )
            poll.raise_for_status()
            last = poll.json()
            status = str(last.get("status") or "").lower()
            log.info(
                "tavily research poll status=%s elapsed_ms=%s",
                status,
                int((time.time() - started) * 1000),
            )
            if status == "completed":
                break
            if status == "failed":
                raise RuntimeError(
                    f"Tavily research failed: {last.get('error_message') or last.get('error') or 'unknown'}"
                )
            time.sleep(poll_ms / 1000.0)

    if str(last.get("status") or "").lower() != "completed":
        raise RuntimeError(
            f"Tavily research timed out after {timeout_ms}ms (last status={last.get('status')})"
        )

    content = last.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:  # noqa: BLE001
            pass

    structured = normalize_hits(content)
    harvested = harvest_from_sources(last.get("content"), last.get("sources"))
    all_unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in [*structured, *harvested]:
        if h["url"] in seen:
            continue
        seen.add(h["url"])
        all_unique.append(h)
    hits = all_unique[:max_n]

    # Broader scan count: every reddit thread URL mentioned in the research blob.
    blob = "\n".join(
        [
            content if isinstance(content, str) else json.dumps(content or ""),
            json.dumps(last.get("sources") or []),
        ]
    )
    scanned_urls = {
        u
        for raw in re.findall(
            r"https?://(?:www\.|old\.|np\.)?reddit\.com/r/[^/\s)\"']+/comments/[a-z0-9]+",
            blob,
            flags=re.I,
        )
        if (u := ensure_reddit_thread_url(raw))
    }
    candidates_seen = max(len(all_unique), len(scanned_urls))

    meta = {
        "requestId": request_id,
        "status": str(last.get("status")),
        "model": model,
        "prompt": prompt,
        "elapsedMs": int((time.time() - started) * 1000),
        "candidates_seen": candidates_seen,
        "structured_count": len(structured),
        "harvested_count": len(harvested),
    }
    log.info(
        "tavily research done structured=%s harvested=%s candidates=%s kept=%s",
        len(structured),
        len(harvested),
        candidates_seen,
        len(hits),
    )
    if not hits:
        log.warning("tavily research returned 0 threads — falling back to search")
        return discover_via_search(need_statement, max_n)
    return {"hits": hits, "meta": meta}


def hits_to_events(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for h in hits:
        m = re.search(r"/comments/([a-z0-9]+)", h["url"], re.I)
        post_id = m.group(1) if m else h["url"][:12]
        sub = (h.get("subreddit") or "") or ""
        if not sub:
            sm = re.search(r"/r/([^/]+)", h["url"], re.I)
            sub = sm.group(1) if sm else ""
        sub = re.sub(r"^r/", "", sub, flags=re.I)
        events.append(
            {
                "platform": "reddit",
                "external_id": f"post_{post_id}",
                "community": sub or None,
                "title": h.get("title") or "",
                "body": h.get("selftext") or "",
                "author": "[tavily]",
                "created_utc": 0,
                "permalink": h["url"],
                "thread_context": "\n".join(
                    x for x in ([f"r/{sub}" if sub else "", h.get("why") or ""]) if x
                ),
                "suggested_reply": h.get("suggested_comment"),
            }
        )
    return events
