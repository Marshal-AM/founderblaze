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

log = logging.getLogger("founderblaze.outreach.portfolio")


class PortfolioBenchmarkProvider(SyncProvider):
    name = "outreach-portfolio"

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
        investors = find_input_json(inputs, "outreach_investors")
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        product = website.get("productSummary") or ""
        performance = revenue.get("performanceSummary") or ""
        investor_summary = investors.get("investorSummary") or ""
        firm_bits = ", ".join(
            (r.get("title") or "")
            for r in (investors.get("sources") or [])[:8]
            if r.get("title")
        )

        plan = gemini_json(
            f"""Create an Exa search plan for pre-investment ARR/MRR / revenue benchmarks of portfolio companies tied to these investors.

Product:
\"\"\"{product}\"\"\"

Performance:
\"\"\"{performance}\"\"\"

Investor shortlist:
\"\"\"{investor_summary}\"\"\"

Investor sources: {firm_bits or "(none)"}

Return JSON:
{{
  "query": "one Exa query for pre-investment revenue / ARR / MRR of portfolio companies",
  "additionalQueries": ["up to 3 alternates"]
}}""",
            model=model,
            api_key=self.api_key,
            system="You write precise Exa queries for VC portfolio revenue benchmarks. JSON only.",
        )
        query = str(plan.get("query") or "").strip()
        if not query:
            raise RuntimeError("Portfolio query planner returned empty query")
        additional = [
            str(q).strip()
            for q in (plan.get("additionalQueries") or [])
            if str(q).strip()
        ][:3]
        log.info("portfolio Exa query=%s", query[:140])

        exa = create_exa_client(self.exa_api_key)
        search = run_exa_search(
            exa,
            query,
            additional_queries=additional,
            output_schema={
                "type": "object",
                "properties": {
                    "benchmarks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "company": {"type": "string"},
                                "investor": {"type": "string"},
                                "round": {"type": "string"},
                                "preInvestmentRevenue": {"type": "string"},
                                "metricType": {"type": "string"},
                                "sourceNote": {"type": "string"},
                            },
                            "required": ["company", "preInvestmentRevenue"],
                        },
                    },
                    "notes": {"type": "string"},
                },
                "required": ["benchmarks"],
            },
        )

        summary = gemini_text(
            f"""Synthesize pre-investment revenue benchmarks from Exa evidence.

Product:
\"\"\"{product}\"\"\"

Performance:
\"\"\"{performance}\"\"\"

Investors:
\"\"\"{investor_summary}\"\"\"

Exa results:
\"\"\"{format_exa_results_for_prompt(search)}\"\"\"

Structured output:
\"\"\"{str(search.get("output") or {})[:2500]}\"\"\"

Return concise bullets: company, investor, metric, round if known, confidence.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You extract pre-investment ARR/MRR benchmarks from search evidence. "
                "Do not invent numbers."
            ),
        )
        if not summary:
            raise RuntimeError("Portfolio synthesis returned empty content")

        payload = {
            "model": model,
            "query": query,
            "additionalQueries": additional,
            "exaResultCount": search["resultCount"],
            "exaResults": search["results"],
            "structuredOutput": search.get("output"),
            "portfolioRevenueSummary": summary,
            "sources": [
                {"title": r.get("title"), "url": r.get("url")}
                for r in search["results"]
            ],
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="portfolio",
                metadata={"kind": "outreach_portfolio"},
            )
        )
        return step
