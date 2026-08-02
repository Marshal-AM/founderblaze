from __future__ import annotations

import logging
import os
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.social_listening._assets import find_input_json, json_file_asset
from founderblaze.social_listening.gemini_chat import gemini_json
from founderblaze.social_listening.tavily_client import (
    discover_reddit_threads,
    hits_to_events,
)

log = logging.getLogger("founderblaze.social_listening.threads")


class ThreadDiscoverProvider(SyncProvider):
    """Need statement + Tavily Reddit research → events JSON."""

    name = "social-listening-threads"

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
        product = find_input_json(list(step.inputs or []), "social_listening_product")
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        max_n = int(product.get("max_posts_per_cycle") or 5)
        max_n = min(int(os.environ.get("TAVILY_REDDIT_LIMIT", "10")), max(1, max_n))

        need = _need_statement(product, model, self.api_key)
        log.info("need statement chars=%s: %s", len(need), need[:200])

        try:
            discovered = discover_reddit_threads(
                need_statement=need,
                max_threads=max_n,
                product={
                    "name": str(product.get("product_name") or ""),
                    "oneLiner": str(product.get("one_liner") or ""),
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f'[reddit_ingest_failed] Reddit thread discovery failed for '
                f'"{product.get("product_name")}". {exc}'
            ) from exc

        hits = discovered["hits"]
        events = hits_to_events(hits)[:max_n]
        if not events:
            raise RuntimeError(
                f'[reddit_no_threads] No matching Reddit threads found for '
                f'"{product.get("product_name")}". Product page was readable, but research '
                f"returned zero engagement targets."
            )

        tavily_meta = discovered.get("meta") or {}
        payload = {
            "need_statement": need,
            "model": model,
            "max_threads": max_n,
            "hit_count": len(hits),
            "candidates_seen": int(tavily_meta.get("candidates_seen") or len(hits)),
            "events": events,
            "tavily_meta": tavily_meta,
        }
        log.info(
            "threads ready n=%s with_comments=%s",
            len(events),
            sum(1 for e in events if e.get("suggested_reply")),
        )
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="threads",
                metadata={"kind": "social_listening_threads"},
            )
        )
        return step


def _need_statement(product: dict, model: str, api_key: str) -> str:
    def fallback() -> str:
        kws = ", ".join((product.get("keywords") or [])[:6])
        core = product.get("one_liner") or str(product.get("description") or "")[:160]
        return (
            f"someone who complains about {core}"
            + (f" (related: {kws})" if kws else "")
            + ", and wishes there was a better tool for that problem"
        )

    try:
        data = gemini_json(
            f"""Product one-liner: {product.get("one_liner")}
What it solves: {product.get("description")}
Keywords: {", ".join((product.get("keywords") or [])[:12])}

Return ONLY this JSON shape (no markdown):
{{"need_statement":"someone …"}}""",
            model=model,
            api_key=api_key,
            system=(
                "You write a single Reddit-search need statement for Tavily Research. "
                "Describe the PERSON and their PAIN — not the product brand. "
                'Phrase it like: "someone … complains about … and wishes …" '
                "No product name, no URLs, no marketing. One dense sentence (max ~60 words)."
            ),
        )
        need = str(data.get("need_statement") or "").strip().strip("{}").strip("\"'")
        if not need or len(need) < 20:
            return fallback()
        return need
    except Exception as exc:  # noqa: BLE001
        log.warning("need statement LLM failed — fallback: %s", exc)
        return fallback()
