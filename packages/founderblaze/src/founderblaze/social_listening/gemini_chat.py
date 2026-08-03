from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from founderblaze.core.gemini_retry import chat_with_retry

log = logging.getLogger("founderblaze.social_listening.gemini")


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
