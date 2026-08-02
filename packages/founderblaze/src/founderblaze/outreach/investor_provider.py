from __future__ import annotations

import logging
import os
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import find_input_json, json_file_asset
from founderblaze.outreach.exa_client import (
    create_exa_client,
    format_exa_results_for_prompt,
    run_exa_search,
)
from founderblaze.outreach.gemini_chat import gemini_json, gemini_text

log = logging.getLogger("founderblaze.outreach.investors")


class InvestorFinderProvider(SyncProvider):
    name = "outreach-investors"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        exa_api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.exa_api_key = exa_api_key
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        website = find_input_json(inputs, "outreach_website")
        revenue = find_input_json(inputs, "outreach_revenue")
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        product = website.get("productSummary") or ""
        performance = revenue.get("performanceSummary") or ""

        plan = gemini_json(
            f"""Create an Exa search plan to find investors and investing firms that would care about this product and stage.

Product summary:
\"\"\"{product}\"\"\"

Company performance summary:
\"\"\"{performance}\"\"\"

Return JSON:
{{
  "query": "one rich natural-language Exa query asking for investors/firms that invest in this product category and similar ARR/MRR stages",
  "additionalQueries": ["up to 3 alternate deep-search queries"]
}}

Rules:
- Focus on investor thesis fit (category, B2B/B2C, stage, geography if implied).
- Mention the product category explicitly (not the company brand alone).
- Prefer queries that surface firm names, check sizes, and portfolio examples.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You write high-precision Exa search queries to find VCs, angels, "
                "and investment firms. Return JSON only."
            ),
        )
        query = str(plan.get("query") or "").strip()
        if not query:
            raise RuntimeError("Investor query planner returned an empty query")
        additional = [
            str(q).strip()
            for q in (plan.get("additionalQueries") or [])
            if str(q).strip()
        ][:3]
        log.info("investor Exa query=%s", query[:140])

        exa = create_exa_client(self.exa_api_key)
        search = run_exa_search(
            exa,
            query,
            additional_queries=additional,
            output_schema={
                "type": "object",
                "properties": {
                    "investors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "thesis": {"type": "string"},
                                "whyRelevant": {"type": "string"},
                                "examplePortfolioCompanies": {"type": "string"},
                            },
                            "required": ["name", "whyRelevant"],
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["investors"],
            },
        )

        summary = gemini_text(
            f"""Using the Exa results, identify investors / investing firms relevant to this product.

Product:
\"\"\"{product}\"\"\"

Performance:
\"\"\"{performance}\"\"\"

Exa query used:
\"\"\"{query}\"\"\"

Exa results:
\"\"\"{format_exa_results_for_prompt(search)}\"\"\"

Exa structured output (if any):
\"\"\"{str(search.get("output") or {})[:2500]}\"\"\"

Return:
1) Top relevant investors/firms (name + why they fit)
2) Their apparent focus / thesis
3) Example portfolio companies mentioned in the results (if any)
4) Gaps / low-confidence items
Keep it concise.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You shortlist investors from search evidence. Be concrete. "
                "Prefer named firms. Do not invent portfolio facts."
            ),
        )
        if not summary:
            raise RuntimeError("Investor synthesis returned empty content")

        payload = {
            "model": model,
            "query": query,
            "additionalQueries": additional,
            "exaResultCount": search["resultCount"],
            "exaResults": search["results"],
            "structuredOutput": search.get("output"),
            "investorSummary": summary,
            "sources": [
                {"title": r.get("title"), "url": r.get("url")}
                for r in search["results"]
            ],
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="investors",
                metadata={"kind": "outreach_investors"},
            )
        )
        return step
