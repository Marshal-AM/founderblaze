from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from genblaze_google import chat

from founderblaze.a2mcp.tools import (
    list_service_tools,
    service_from_tool_name,
    tool_by_name,
    validate_tool_input,
)
from founderblaze.core.config import get_settings
from founderblaze.mcp_server.server import run_tool_call

log = logging.getLogger("founderblaze.agent.runner")

_SYSTEM = """You are the FounderBlaze agent. You help founders by running catalog A2MCP services via tools.

HARD RULES (non-negotiable):
1. NEVER call a tool until the user has explicitly provided EVERY required field for that tool.
2. NEVER invent, guess, autocomplete, or reuse example URLs/names (no example.com, linear.app, "your company", placeholders).
3. If anything required is missing or ambiguous — ASK one short clarifying question and STOP. Do not call tools.
4. Copy URLs and names EXACTLY as the user wrote them. Do not "fix" or substitute another site.
5. Optional fields may use defaults only when the schema defines a default; never invent required values.
6. When listing capabilities, briefly name each tool and its required inputs — do not start jobs.
7. After a real tool result, summarize status and artifact links. Never fake job success.

Outreach example: both website_url AND sheet_url are required. A finance sheet alone is NOT enough — ask for the company website URL first.
"""

_PLACEHOLDER_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "yourcompany.com",
    "company.com",
    "website.com",
    "domain.com",
}


def _sanitize_schema_for_gemini(node: Any) -> Any:
    """Gemini GenerateContentConfig requires enum values to be strings."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "enum" and isinstance(value, list):
                out[key] = [str(v) if not isinstance(v, str) else v for v in value]
            else:
                out[key] = _sanitize_schema_for_gemini(value)
        out.pop("title", None)
        out.pop("$defs", None)
        out.pop("definitions", None)
        return out
    if isinstance(node, list):
        return [_sanitize_schema_for_gemini(v) for v in node]
    return node


def _coerce_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    """Coerce stringified numeric enums back to ints where possible."""
    coerced: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str) and value.isdigit():
            coerced[key] = int(value)
        elif isinstance(value, str) and value.replace(".", "", 1).isdigit():
            try:
                coerced[key] = float(value) if "." in value else int(value)
            except ValueError:
                coerced[key] = value
        else:
            coerced[key] = value
    return coerced


def _gemini_tools() -> list[dict[str, Any]]:
    decls = []
    for t in list_service_tools():
        decls.append(
            {
                "name": t["name"],
                "description": t["description"][:1024],
                "parameters": _sanitize_schema_for_gemini(t["input_schema"]),
            }
        )
    return [{"function_declarations": decls}]


def _extract_function_calls(resp: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for tc in getattr(resp, "tool_calls", None) or []:
        name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None)
        args = getattr(tc, "arguments", None)
        if args is None and isinstance(tc, dict):
            args = tc.get("arguments") or tc.get("args")
        if name:
            calls.append({"name": str(name), "arguments": dict(args or {})})
    if calls:
        return calls

    raw = getattr(resp, "raw", None)
    try:
        candidates = getattr(raw, "candidates", None) or []
        for cand in candidates:
            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is None:
                    continue
                name = getattr(fc, "name", None)
                args = dict(getattr(fc, "args", None) or {})
                if name:
                    calls.append({"name": str(name), "arguments": args})
    except Exception:  # noqa: BLE001
        pass
    return calls


def _user_corpus(message: str, history: list[dict[str, str]] | None) -> str:
    parts: list[str] = []
    for h in history or []:
        if (h.get("role") or "").lower() == "user":
            parts.append(h.get("content") or "")
    parts.append(message or "")
    return "\n".join(parts)


def _normalize_url_variants(url: str) -> list[str]:
    raw = (url or "").strip()
    if not raw:
        return []
    variants = {raw, raw.rstrip("/")}
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        if host:
            variants.add(host)
            variants.add(f"https://{host}{path}".rstrip("/"))
            variants.add(f"http://{host}{path}".rstrip("/"))
            variants.add(f"https://{host}")
            if host.startswith("www."):
                variants.add(host[4:])
            else:
                variants.add(f"www.{host}")
    except Exception:  # noqa: BLE001
        pass
    return [v for v in variants if v]


def _value_grounded_in_corpus(value: Any, corpus: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lower = corpus.lower()
    for variant in _normalize_url_variants(text):
        if variant.lower() in lower:
            return True
    # Non-URL required strings (brand_name, product_name, script snippets)
    if text.lower() in lower:
        return True
    # Allow multi-line script if a substantial unique chunk appears
    if len(text) > 40:
        chunk = text[:40].lower()
        if chunk in lower:
            return True
    return False


def _is_placeholder_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host in _PLACEHOLDER_HOSTS:
            return True
        if host.endswith(".example") or host.endswith(".test"):
            return True
    except Exception:  # noqa: BLE001
        return True
    return False


def _gate_tool_call(
    tool_name: str,
    args: dict[str, Any],
    *,
    corpus: str,
) -> str | None:
    """Return a user-facing rejection reason, or None if the call may proceed."""
    tool = tool_by_name(tool_name)
    if not tool:
        return f"Unknown tool `{tool_name}`."

    required = list(tool.get("required_fields") or [])
    missing = [f for f in required if args.get(f) in (None, "", [])]
    if missing:
        return (
            f"I still need these required field(s) before I can run "
            f"**{tool['title']}**: {', '.join(missing)}. "
            f"Please paste the exact value(s) — I will not guess."
        )

    ungrounded: list[str] = []
    placeholders: list[str] = []
    for field in required:
        value = args.get(field)
        if field.endswith("_url") or field == "website_url":
            if _is_placeholder_url(value):
                placeholders.append(field)
            elif not _value_grounded_in_corpus(value, corpus):
                ungrounded.append(field)
        elif isinstance(value, str) and not _value_grounded_in_corpus(value, corpus):
            # Required free-text must come from the user (prevents invented scripts/names)
            ungrounded.append(field)

    if placeholders:
        return (
            f"I won't use placeholder/example values for: {', '.join(placeholders)}. "
            f"Please send your real URL(s)."
        )
    if ungrounded:
        return (
            f"I won't start **{tool['title']}** yet — these values were not found in "
            f"your messages (I refuse to invent them): {', '.join(ungrounded)}. "
            f"Please provide them explicitly."
        )

    # Schema validation (types / HttpUrl / min lengths)
    try:
        service = service_from_tool_name(tool_name)
        validate_tool_input(service, args)
    except ValueError as exc:
        # Surface first error lines cleanly
        msg = str(exc)
        msg = re.sub(r"\s+", " ", msg)[:500]
        return (
            f"Those inputs aren't valid for **{tool['title']}** yet: {msg}. "
            f"Please correct them before I start the job."
        )
    return None


async def run_agent(
    message: str,
    *,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run one Gemini tool-calling turn (optionally multi-step)."""
    settings = get_settings()
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
    model = settings.resolved_agent_gemini_model
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the agent")

    sid = session_id or str(uuid.uuid4())
    tools = _gemini_tools()
    tool_calls_out: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    corpus = _user_corpus(message, history)

    prompt_bits = []
    for h in history or []:
        role = h.get("role", "user")
        content = h.get("content", "")
        prompt_bits.append(f"{role.upper()}: {content}")
    prompt_bits.append(f"USER: {message}")
    prompt = "\n\n".join(prompt_bits)

    resp = chat(
        model,
        prompt=prompt,
        system=_SYSTEM,
        tools=tools,
        api_key=api_key,
    )
    calls = _extract_function_calls(resp)
    reply_text = (getattr(resp, "text", None) or "").strip()

    if not calls:
        return {
            "session_id": sid,
            "reply": reply_text
            or "I can help you run FounderBlaze services. Ask me what I can do, or say which deliverable you want.",
            "tool_calls": [],
            "jobs": [],
            "artifacts": [],
        }

    tool_results: list[str] = []
    blocked_replies: list[str] = []

    for call in calls:
        name = call["name"]
        args = _coerce_tool_args(dict(call.get("arguments") or {}))
        gate = _gate_tool_call(name, args, corpus=corpus)
        if gate:
            log.warning("agent blocked tool=%s reason=%s", name, gate[:200])
            tool_calls_out.append(
                {
                    "name": name,
                    "arguments": args,
                    "ok": False,
                    "blocked": True,
                    "error": gate,
                }
            )
            blocked_replies.append(gate)
            continue

        log.info("agent calling tool=%s args_keys=%s", name, list(args.keys()))
        try:
            result = await run_tool_call(name, args)
            tool_calls_out.append({"name": name, "arguments": args, "ok": True})
            jobs.append(
                {
                    "job_id": result.get("job_id"),
                    "service": result.get("service"),
                    "status": result.get("status"),
                    "error": result.get("error"),
                }
            )
            for a in result.get("artifacts") or []:
                if isinstance(a, dict):
                    artifacts.append(a)
            tool_results.append(
                f"TOOL {name} RESULT:\n{json.dumps(result, default=str)[:6000]}"
            )
        except Exception as exc:  # noqa: BLE001
            tool_calls_out.append(
                {"name": name, "arguments": args, "ok": False, "error": str(exc)}
            )
            tool_results.append(f"TOOL {name} ERROR: {exc}")

    # If every call was blocked, return the clarifying message — no second model turn.
    if blocked_replies and not tool_results:
        return {
            "session_id": sid,
            "reply": "\n\n".join(blocked_replies),
            "tool_calls": tool_calls_out,
            "jobs": [],
            "artifacts": [],
        }

    follow = (
        prompt
        + "\n\n"
        + "\n\n".join(tool_results + [f"BLOCKED: {b}" for b in blocked_replies])
        + "\n\nASSISTANT: Summarize for the user. If something was blocked, ask only for the missing real inputs. Include artifact URLs if any."
    )
    resp2 = chat(
        model,
        prompt=follow,
        system=_SYSTEM,
        api_key=api_key,
    )
    final = (getattr(resp2, "text", None) or reply_text or "").strip()
    return {
        "session_id": sid,
        "reply": final,
        "tool_calls": tool_calls_out,
        "jobs": jobs,
        "artifacts": artifacts,
    }
