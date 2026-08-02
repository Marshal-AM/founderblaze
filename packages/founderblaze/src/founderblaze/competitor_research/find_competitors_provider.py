from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import json_file_asset
from founderblaze.competitor_research.gemini_chat import gemini_json
from founderblaze.competitor_research.page_fetch import fetch_page_jina
from founderblaze.competitor_research.search_client import (
    name_from_url,
    root_domain,
    web_search,
)

log = logging.getLogger("founderblaze.competitor_research.find")

MAX_COMPETITORS = 5

_BLOCKED = re.compile(
    r"(youtube|reddit|wikipedia|linkedin|facebook|x\.com|twitter|g2\.com|"
    r"capterra\.com|getapp\.com)",
    re.I,
)


class FindCompetitorsProvider(SyncProvider):
    """Web search + Gemini ranking → competitors.json."""

    name = "competitor-research-find"

    def __init__(
        self,
        *,
        product_name: str,
        product_url: str | None = None,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.product_url = product_url
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        queries = [
            f"{self.product_name} alternatives",
            f"{self.product_name} vs competitors",
            f"{self.product_name} competitors",
        ]
        hits: list[dict[str, str]] = []
        for q in queries:
            hits.extend(web_search(q, num=8))

        product_text = ""
        product_url_fetch_failed = False
        if self.product_url:
            try:
                page = fetch_page_jina(self.product_url)
                product_text = page["text"][:2500]
                if len(re.sub(r"\s+", " ", product_text).strip()) < 80:
                    product_url_fetch_failed = True
                    product_text = ""
            except Exception:  # noqa: BLE001
                product_url_fetch_failed = True

        product_host = root_domain(self.product_url) if self.product_url else None
        candidates: list[dict[str, str]] = []
        for h in hits:
            host = root_domain(h["url"])
            if not host:
                continue
            if product_host and host == product_host:
                continue
            if _BLOCKED.search(host):
                continue
            candidates.append(h)
            if len(candidates) >= 20:
                break

        if not candidates:
            if self.product_url and product_url_fetch_failed:
                raise RuntimeError(
                    f'[product_url_no_content] Could not research competitors for '
                    f'"{self.product_name}": product URL {self.product_url} yielded no '
                    f"readable content and web search returned no usable candidates."
                )
            raise RuntimeError("findCompetitors: no search candidates found")

        competitors = self._rank_with_gemini(
            model, candidates[:15], product_text
        )
        if not competitors:
            competitors = self._heuristic(candidates)

        if not competitors:
            raise RuntimeError(
                "findCompetitors: unable to derive competitors from search results"
            )

        payload: dict[str, Any] = {
            "product_name": self.product_name,
            "product_url": self.product_url
            or f"https://www.google.com/search?q={quote(self.product_name)}",
            "competitors": competitors[:MAX_COMPETITORS],
        }
        log.info(
            "found %s competitors for %s",
            len(payload["competitors"]),
            self.product_name,
        )
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="competitors",
                metadata={"kind": "competitors"},
            )
        )
        return step

    def _rank_with_gemini(
        self, model: str, candidates: list[dict[str, str]], product_text: str
    ) -> list[dict[str, Any]]:
        try:
            data = gemini_json(
                f"""Product: {self.product_name}
URL: {self.product_url or "n/a"}
Excerpt: {product_text or "(none)"}

Candidates:
{candidates}

Return {{ "competitors": [{{ "name", "url" (homepage), "confidence": 0-1, "category_match"? }}] }}
Rules: 4-{MAX_COMPETITORS} max; vendor homepages only; drop weak matches.""",
                model=model,
                api_key=self.api_key,
                system=(
                    "You are a competitive-intelligence analyst. Return JSON only. "
                    "Pick real direct competitors (same category / ICP), not blogs or directories."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("gemini rank failed: %s", exc)
            return []

        out: list[dict[str, Any]] = []
        for c in data.get("competitors") or []:
            if not c.get("url") or not c.get("name"):
                continue
            conf = float(c.get("confidence") or 0.5)
            out.append(
                {
                    "name": str(c["name"]),
                    "url": str(c["url"]),
                    "confidence": max(0.0, min(1.0, conf)),
                    "sources": ["web_search", "gemini"],
                    "category_match": c.get("category_match"),
                }
            )
        return out

    def _heuristic(self, candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
        by_domain: dict[str, dict[str, Any]] = {}
        for hit in candidates:
            host = root_domain(hit["url"])
            if not host:
                continue
            existing = by_domain.get(host)
            if existing:
                existing["confidence"] = min(1.0, existing["confidence"] + 0.12)
                continue
            by_domain[host] = {
                "name": name_from_url(hit["url"]),
                "url": f"https://{host}",
                "confidence": 0.5,
                "sources": ["web_search"],
                "category_match": "inferred",
            }
        return sorted(
            by_domain.values(), key=lambda c: c["confidence"], reverse=True
        )[:MAX_COMPETITORS]
