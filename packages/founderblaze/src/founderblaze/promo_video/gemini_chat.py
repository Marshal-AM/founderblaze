from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from founderblaze.core.gemini_retry import chat_with_retry, generate_content_with_retry

log = logging.getLogger("founderblaze.promo_video.gemini")


def _google_search_tools() -> list[Any]:
    from google.genai import types

    return [types.Tool(google_search=types.GoogleSearch())]


def gemini_text(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    system: str | None = None,
) -> str:
    if api_key:
        os.environ.setdefault("GEMINI_API_KEY", api_key)
    full = prompt
    if system:
        full = f"{system.strip()}\n\n---\n\n{prompt.strip()}"
    log.info("gemini chat model=%s chars=%s", model, len(full))
    resp = chat_with_retry(model, prompt=full, api_key=api_key)
    text = getattr(resp, "text", None) or str(resp)
    return (text or "").strip()


def gemini_json(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    text = gemini_text(prompt, model=model, api_key=api_key, system=system)
    return parse_json_object(text)


def gemini_grounded_text(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    system: str | None = None,
) -> str:
    """Gemini generate_content with Google Search grounding enabled."""
    if api_key:
        os.environ.setdefault("GEMINI_API_KEY", api_key)
    tools = _google_search_tools()
    full = prompt
    if system:
        full = f"{system.strip()}\n\n---\n\n{prompt.strip()}"
    log.info("gemini grounded chat model=%s chars=%s", model, len(full))
    try:
        resp = chat_with_retry(model, prompt=full, api_key=api_key, tools=tools)
        text = getattr(resp, "text", None) or str(resp)
        return (text or "").strip()
    except Exception as exc:  # noqa: BLE001
        # Fall back to direct google-genai Client if chat() rejects Tool objects.
        log.warning("genblaze chat grounding failed (%s); trying google.genai Client", exc)
        return _grounded_via_client(full, model=model, api_key=api_key)


def gemini_grounded_json(
    prompt: str,
    *,
    model: str,
    api_key: str | None = None,
    system: str | None = None,
) -> dict[str, Any]:
    text = gemini_grounded_text(
        prompt, model=model, api_key=api_key, system=system
    )
    return parse_json_object(text)


def _grounded_via_client(prompt: str, *, model: str, api_key: str | None) -> str:
    from google import genai
    from google.genai import types

    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    client = genai.Client(api_key=key) if key else genai.Client()
    try:
        def _once() -> Any:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )

        resp = generate_content_with_retry(_once)
        text = getattr(resp, "text", None) or ""
        return (text or "").strip()
    finally:
        close_fn = getattr(client, "close", None)
        if callable(close_fn):
            close_fn()


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        val = json.loads(text)
        if isinstance(val, dict):
            return val
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        val = json.loads(fence.group(1).strip())
        if isinstance(val, dict):
            return val
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        val = json.loads(text[start : end + 1])
        if isinstance(val, dict):
            return val
    raise ValueError(f"Could not parse JSON object: {text[:240]}")
