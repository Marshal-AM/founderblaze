from __future__ import annotations

import logging
import os
import time
from typing import Any

log = logging.getLogger("founderblaze.outreach.exa")


def create_exa_client(api_key: str | None = None) -> Any:
    from exa_py import Exa

    key = (
        api_key
        or os.environ.get("EXA_SEARCH_API_KEY", "")
        or os.environ.get("EXA_API_KEY", "")
    ).strip()
    if not key:
        raise RuntimeError("Missing EXA_SEARCH_API_KEY (or EXA_API_KEY)")
    return Exa(api_key=key)


def fetch_website_context(exa: Any, url: str, *, max_chars: int = 12000) -> dict[str, Any]:
    """Pull page body/highlights for a known URL so Gemini has site context."""
    normalized = normalize_url(url)
    log.info("exa get_contents url=%s", normalized)
    try:
        resp = exa.get_contents([normalized], text=True, highlights=True)
    except TypeError:
        # Older SDK keyword shapes
        resp = exa.get_contents([normalized], text=True)

    results = list(getattr(resp, "results", None) or [])
    if not results and isinstance(resp, dict):
        results = list(resp.get("results") or [])
    if not results:
        raise RuntimeError(f"Exa returned no contents for {normalized}")

    first = results[0]
    title = _attr(first, "title") or ""
    text = str(_attr(first, "text") or "")
    highlights = list(_attr(first, "highlights") or [])
    if not text and highlights:
        text = "\n".join(str(h) for h in highlights)
    text = text.strip()
    if not text:
        raise RuntimeError(f"Exa contents empty for {normalized}")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[truncated]"
    return {
        "url": normalized,
        "title": title,
        "text": text,
        "highlights": [str(h) for h in highlights[:8]],
    }


def run_exa_search(
    exa: Any,
    query: str,
    *,
    additional_queries: list[str] | None = None,
    num_results: int | None = None,
    search_type: str | None = None,
    output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    n = num_results or int(os.environ.get("EXA_NUM_RESULTS", "8"))
    stype = search_type or os.environ.get("EXA_SEARCH_TYPE", "deep")
    kwargs: dict[str, Any] = {
        "num_results": n,
        "type": stype,
        "contents": {"highlights": True},
    }
    extras = [q for q in (additional_queries or []) if q.strip()]
    if extras:
        kwargs["additional_queries"] = extras
    if output_schema is not None:
        # SDK versions differ: output_schema vs outputSchema
        kwargs["output_schema"] = output_schema

    log.info("exa search type=%s n=%s q=%s", stype, n, query[:120])
    try:
        resp = exa.search(query, **kwargs)
    except TypeError:
        kwargs.pop("output_schema", None)
        if output_schema is not None:
            kwargs["outputSchema"] = output_schema
        try:
            resp = exa.search(query, **kwargs)
        except TypeError:
            kwargs.pop("outputSchema", None)
            kwargs.pop("additional_queries", None)
            resp = exa.search(query, **kwargs)

    raw_results = list(getattr(resp, "results", None) or [])
    if not raw_results and isinstance(resp, dict):
        raw_results = list(resp.get("results") or [])
    output = getattr(resp, "output", None)
    if output is None and isinstance(resp, dict):
        output = resp.get("output")
    output = unwrap_exa_output(output)

    results: list[dict[str, Any]] = []
    for r in raw_results:
        results.append(
            {
                "title": str(_attr(r, "title") or ""),
                "url": str(_attr(r, "url") or ""),
                "publishedDate": _attr(r, "published_date")
                or _attr(r, "publishedDate"),
                "author": _attr(r, "author"),
                "highlights": list(_attr(r, "highlights") or [])[:3],
                "text": str(_attr(r, "text") or ""),
            }
        )
    return {
        "query": query,
        "additionalQueries": extras,
        "resultCount": len(results),
        "results": results,
        "output": output,
    }


def unwrap_exa_output(output: Any) -> Any:
    """Normalize Exa structured output (object / content wrapper / JSON string)."""
    if output is None:
        return None
    if not isinstance(output, dict):
        # pydantic / SDK objects
        if hasattr(output, "model_dump"):
            try:
                output = output.model_dump()
            except Exception:  # noqa: BLE001
                pass
        elif hasattr(output, "__dict__") and not isinstance(output, type):
            try:
                output = {
                    k: v
                    for k, v in vars(output).items()
                    if not k.startswith("_")
                }
            except Exception:  # noqa: BLE001
                return output

    if isinstance(output, str):
        text = output.strip()
        try:
            import json

            return json.loads(text)
        except Exception:  # noqa: BLE001
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    import json

                    return json.loads(text[start : end + 1])
                except Exception:  # noqa: BLE001
                    return output
            return output

    if not isinstance(output, dict):
        return output

    content = output.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        nested = unwrap_exa_output(content)
        if isinstance(nested, dict):
            return nested
    return output


def format_exa_results_for_prompt(
    search: dict[str, Any] | None,
    *,
    max_results: int = 6,
    max_highlight_chars: int = 280,
) -> str:
    if not search or not search.get("results"):
        return "(no Exa results)"
    blocks = []
    for i, r in enumerate(search["results"][:max_results], start=1):
        highlights = [
            str(h)[:max_highlight_chars]
            for h in (r.get("highlights") or [])
            if h
        ][:2]
        bits = [
            f"{i}. {r.get('title') or '(untitled)'}",
            f"URL: {r['url']}" if r.get("url") else None,
            f"Date: {r['publishedDate']}" if r.get("publishedDate") else None,
            f"Highlights: {' | '.join(highlights)}" if highlights else None,
        ]
        blocks.append("\n".join(b for b in bits if b))
    return "\n\n".join(blocks)


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Website URL is required")
    if not raw.lower().startswith(("http://", "https://")):
        return f"https://{raw}"
    return raw


def sleep_ms(ms: int) -> None:
    if ms > 0:
        time.sleep(ms / 1000.0)


def _attr(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
