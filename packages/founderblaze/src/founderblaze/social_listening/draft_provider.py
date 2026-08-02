from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.social_listening._assets import find_input_json, json_file_asset
from founderblaze.social_listening.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.social_listening.draft")

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
DOMAIN_RE = re.compile(r"\b[\w-]+\.(?:ai|io|com|dev|app)\b", re.I)


class DraftComplianceProvider(SyncProvider):
    """Per-thread draft (Tavily suggested_reply or Gemini) + compliance gate."""

    name = "social-listening-drafts"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        product = find_input_json(inputs, "social_listening_product")
        threads = find_input_json(inputs, "social_listening_threads")
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        max_n = int(product.get("max_posts_per_cycle") or 5)
        events = list(threads.get("events") or [])[:max_n]

        ready: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        candidates_seen = int(threads.get("candidates_seen") or threads.get("hit_count") or len(events))
        funnel = {
            "scanned": max(candidates_seen, len(events)),
            "matching_intent": int(threads.get("hit_count") or len(events)),
            "recency_engagement": 0,
            "compliance": 0,
            "shortlist": 0,
            # legacy keys kept for logs
            "ingested": len(events),
            "dedup": 0,
            "draft": 0,
        }

        for event in events:
            if len(ready) >= max_n:
                break
            ext_id = str(event.get("external_id") or "")
            if ext_id in seen_ids:
                skipped.append(_skip(event, "already_scheduled_or_posted"))
                continue
            seen_ids.add(ext_id)
            funnel["dedup"] += 1
            funnel["recency_engagement"] += 1

            draft_text = str(event.get("suggested_reply") or "").strip()
            draft_rationale = "From Tavily research" if draft_text else ""
            if not draft_text or len(draft_text) < 40:
                try:
                    drafted = _write_draft(event, product, model, self.api_key)
                    draft_text = drafted["draft_text"]
                    draft_rationale = drafted["draft_rationale"]
                except Exception as exc:  # noqa: BLE001
                    log.warning("draft failed id=%s: %s", ext_id, exc)
                    skipped.append(_skip(event, str(exc)))
                    continue
            funnel["draft"] += 1

            compliance = _review_compliance(event, product, draft_text, model, self.api_key)
            if not compliance["ok"]:
                log.warning("compliance failed id=%s: %s", ext_id, compliance["notes"])
                skipped.append(
                    _skip(
                        event,
                        compliance["notes"] or "compliance",
                        draft_text=draft_text,
                        draft_rationale=draft_rationale,
                    )
                )
                continue
            funnel["compliance"] += 1
            ready.append(
                {
                    "targetPermalink": event.get("permalink"),
                    "draftText": draft_text,
                    "draftRationale": draft_rationale,
                    "title": event.get("title") or "",
                    "threadContext": event.get("thread_context") or "",
                    "status": "included",
                    "community": event.get("community"),
                    "event": event,
                }
            )

        if not ready:
            raise RuntimeError(
                f'[reddit_no_drafts] No compliant Reddit drafts for '
                f'"{product.get("product_name")}". Threads were found but none passed '
                f"draft/compliance."
            )

        window = int(product.get("window_hours") or 24)
        interval_label = _format_interval(window, len(ready))
        funnel["shortlist"] = len(ready)
        # Keep funnel monotone decreasing for charts.
        funnel["matching_intent"] = max(funnel["matching_intent"], funnel["recency_engagement"])
        funnel["scanned"] = max(funnel["scanned"], funnel["matching_intent"])
        payload = {
            "model": model,
            "product_name": product.get("product_name"),
            "recommendations": ready,
            "skipped": skipped,
            "funnel": funnel,
            "interval_label": interval_label,
            "subreddits": product.get("subreddits") or [],
            "need_statement": threads.get("need_statement"),
            "events": events,
        }
        log.info("drafts ready included=%s skipped=%s funnel=%s", len(ready), len(skipped), funnel)
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="recommendations",
                metadata={"kind": "social_listening_recommendations"},
            )
        )
        return step


def _skip(
    event: dict[str, Any],
    reason: str,
    *,
    draft_text: str = "",
    draft_rationale: str = "",
) -> dict[str, Any]:
    return {
        "targetPermalink": event.get("permalink"),
        "draftText": draft_text,
        "draftRationale": draft_rationale,
        "title": event.get("title") or "",
        "threadContext": event.get("thread_context") or "",
        "status": "skipped",
        "community": event.get("community"),
        "skipReason": reason,
    }


def _event_text(event: dict[str, Any]) -> str:
    parts = [
        event.get("title") or "",
        event.get("body") or "",
        event.get("thread_context") or "",
    ]
    return "\n\n".join(p for p in parts if p).strip()


def _strip_links(text: str) -> str:
    text = URL_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _write_draft(
    event: dict[str, Any],
    product: dict[str, Any],
    model: str,
    api_key: str,
) -> dict[str, str]:
    name = str(product.get("product_name") or "the product")
    data = gemini_json(
        f"""Product name to mention once: {name}
What it roughly does (do not dump as a pitch): {product.get("one_liner")}
More context (ideas only): {str(product.get("description") or "")[:350]}

Subreddit: {event.get("community") or "-"}

Thread:
{_event_text(event)}

Past reply style examples (tone only):
(none yet)

Return JSON:
{{
  "draft_text": "peer reply that helps first, then casually names {name} once, with no links",
  "draft_rationale": "one line: what ask you answered"
}}""",
        model=model,
        api_key=api_key,
        system=(
            f"You write natural Reddit comments as a helpful peer who happens to know {name}.\n"
            "Hard rules:\n"
            "- Lead with useful advice for THIS thread — be specific to the OP's ask.\n"
            f"- Mention {name} once, casually, as something that fits their situation.\n"
            '- NO URLs, NO domain names (no .ai / .com / .io), NO "check out", NO "sign up", '
            "NO pricing, NO feature laundry lists.\n"
            '- No formal "Disclosure:" line — keep it conversational.\n'
            "- 2–4 short paragraphs. Reddit tone. No hype.\n"
            "Return JSON only."
        ),
    )
    draft = _strip_links(str(data.get("draft_text") or ""))
    if not draft or len(draft) < 40:
        raise RuntimeError("draft_empty_or_too_short")
    if not re.search(re.escape(name), draft, re.I):
        draft = f"{draft}\n\nI've had decent luck with {name} for that kind of setup."
    draft = re.sub(r"\(?\s*disclosure\s*:[^)\n]+\)?", "", draft, flags=re.I)
    draft = DOMAIN_RE.sub("", draft)
    draft = re.sub(r"\n{3,}", "\n\n", draft).strip()
    if len(draft) > 1200:
        draft = re.sub(r"\s+\S*$", "", draft[:1200]).strip()
    return {
        "draft_text": draft,
        "draft_rationale": str(data.get("draft_rationale") or "").strip(),
    }


def _review_compliance(
    event: dict[str, Any],
    product: dict[str, Any],
    draft_text: str,
    model: str,
    api_key: str,
) -> dict[str, Any]:
    name = str(product.get("product_name") or "")
    if len(draft_text) < 40 or len(draft_text) > 1400:
        return {"ok": False, "notes": "length_out_of_bounds"}
    if URL_RE.search(draft_text) or DOMAIN_RE.search(draft_text):
        return {"ok": False, "notes": "contains_link_or_domain"}
    if re.search(r"disclosure\s*:", draft_text, re.I):
        return {"ok": False, "notes": "looks_like_ad_disclosure"}
    if name and not re.search(rf"\b{re.escape(name)}\b", draft_text, re.I):
        return {"ok": False, "notes": "missing_product_name"}
    if re.search(
        r"check (it )?out|sign up|try (our|my)|use my tool|pricing|pay only \$|game[- ]?changer|click here",
        draft_text,
        re.I,
    ):
        return {"ok": False, "notes": "promotional_cta"}

    try:
        data = gemini_json(
            f"""Thread:
{_event_text(event)}

Draft:
{draft_text}

Return JSON: {{ "ok": boolean, "notes": "short reason" }}""",
            model=model,
            api_key=api_key,
            system=(
                f"You gatekeep Reddit replies. PASS if mostly helpful peer advice specific to "
                f"the thread, casually mentions {name} once, and has no links/domains/CTAs. "
                "FAIL if mostly an ad, has URLs/domains, disclosure boilerplate, hard sell, "
                "or ignores the thread. Return JSON only."
            ),
        )
        return {
            "ok": bool(data.get("ok")),
            "notes": str(data.get("notes") or "")[:280],
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("compliance LLM failed — heuristic pass: %s", exc)
        return {"ok": True, "notes": "heuristic_pass"}


def _format_interval(window_hours: int, n: int) -> str:
    if n <= 0:
        return f"0 posts / {window_hours}h"
    return f"~{max(1, round(window_hours / n))}h between posts ({n} over {window_hours}h)"
