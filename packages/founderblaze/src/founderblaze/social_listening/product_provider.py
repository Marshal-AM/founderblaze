from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.social_listening._assets import json_file_asset
from founderblaze.social_listening.gemini_chat import gemini_json
from founderblaze.social_listening.page_fetch import (
    chunk_text,
    fetch_site_corpus,
    normalize_url,
    product_from_name_fallback,
)

log = logging.getLogger("founderblaze.social_listening.product")


class ProductDiscoverProvider(SyncProvider):
    """Fetch product site → Gemini extract ProductConfig JSON."""

    name = "social-listening-product"

    def __init__(
        self,
        *,
        product_url: str,
        product_name: str | None = None,
        max_posts: int | None = None,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_url = product_url
        self.product_name = product_name
        self.max_posts = max_posts
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        url = normalize_url(self.product_url)
        try:
            product = self._discover(url, model)
        except Exception as exc:  # noqa: BLE001
            log.warning("product scrape/LLM failed — fallback: %s", exc)
            product = product_from_name_fallback(url, self.product_name)

        if self.max_posts and self.max_posts > 0:
            product["max_posts_per_cycle"] = int(self.max_posts)
        product.setdefault("website_url", url)
        product.setdefault("max_posts_per_cycle", 5)
        product.setdefault("window_hours", 24)
        product["model"] = model

        log.info(
            "product ready name=%s subs=%s max=%s",
            product.get("product_name"),
            product.get("subreddits"),
            product.get("max_posts_per_cycle"),
        )
        step.assets.append(
            json_file_asset(
                product,
                work_dir=Path(self.work_dir or "."),
                name="product",
                metadata={"kind": "social_listening_product"},
            )
        )
        return step

    def _discover(self, url: str, model: str) -> dict:
        chunk_size = int(os.environ.get("PRODUCT_CHUNK_SIZE", "2800"))
        max_chunks = int(os.environ.get("PRODUCT_MAX_CHUNKS", "6"))
        corpus = fetch_site_corpus(url)
        chunks = chunk_text(corpus["combined"], chunk_size)[:max_chunks]
        log.info("fetched pages=%s chunks=%s", len(corpus["pages"]), len(chunks))

        partials = []
        for i, chunk in enumerate(chunks):
            data = gemini_json(
                f"""Website: {url}
Chunk {i + 1}/{len(chunks)}:

{chunk}

Return JSON:
{{
  "product_name": string | omit,
  "one_liner": string | omit,
  "audience": string | omit,
  "problem": string | omit,
  "capabilities": string[] | omit,
  "keywords": string[] | omit,
  "notes": string | omit
}}""",
                model=model,
                api_key=self.api_key,
                system=(
                    "Extract product facts from ONE website text chunk. Return JSON only. "
                    "Only use facts present in the chunk. Omit unknown fields."
                ),
            )
            partials.append(data)

        research = "\n\n".join(
            f"CHUNK {i + 1}:\n{json.dumps(p, indent=2)}"
            for i, p in enumerate(partials)
        )
        host = (urlparse(url).hostname or "").replace("www.", "")
        merged = gemini_json(
            f"""Website: {url}

Example subreddits (pick relevant ones or better fits):
SaaS, startups, Entrepreneur, productivity, webdev, devops, artificial, MachineLearning, nocode, indiehackers, SideProject, Zapier, automations

Chunk extractions:
{research}

Return JSON:
{{
  "product_name": string,
  "one_liner": string,
  "description": string,
  "disclosure_line": string,
  "keywords": string[],
  "subreddits": string[],
  "max_posts_per_cycle": number,
  "window_hours": number
}}""",
            model=model,
            api_key=self.api_key,
            system=(
                "You merge chunked website extractions into JSON for a Reddit engagement pack. "
                "Return JSON only. Rules:\n"
                "- Prefer consistent facts that appear across chunks\n"
                "- keywords: pain/search phrases — 8–20 items\n"
                "- subreddits: 4–6 real Reddit communities (bare names, no r/)\n"
                f'- disclosure_line: must include the word "disclosure" and domain {host}\n'
                "- max_posts_per_cycle 5–8, window_hours 24"
            ),
        )
        name = str(merged.get("product_name") or "").strip()
        if not name:
            raise RuntimeError("product merge returned empty product_name")
        subs = [
            str(s).replace("r/", "").strip()
            for s in (merged.get("subreddits") or [])
            if str(s).strip()
        ][:6]
        kws = [str(k).strip() for k in (merged.get("keywords") or []) if str(k).strip()]
        return {
            "product_name": name,
            "one_liner": str(merged.get("one_liner") or "").strip(),
            "description": str(merged.get("description") or "").strip(),
            "disclosure_line": str(merged.get("disclosure_line") or f"disclosure: {name} ({host})"),
            "keywords": kws,
            "subreddits": subs or ["SaaS", "startups"],
            "max_posts_per_cycle": int(merged.get("max_posts_per_cycle") or 5),
            "window_hours": int(merged.get("window_hours") or 24),
            "website_url": url,
            "fallback": False,
        }
