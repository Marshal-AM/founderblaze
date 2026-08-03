from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from genblaze_core.models.step import Step
from founderblaze.core.gemini_retry import (
    call_with_transient_retry,
    gemini_image_retry_policy,
)
from genblaze_google import GeminiImageProvider

from founderblaze.outreach._assets import (
    file_asset,
    find_input_json,
    json_file_asset,
    local_path,
)
from founderblaze.outreach.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.outreach.insights")

CHART_SPECS: list[tuple[str, str, str]] = [
    ("revenue_benchmark", "outreach_revenue_benchmark_image", "Revenue Benchmark Positioning"),
    ("fit_matrix", "outreach_fit_matrix_image", "Investor Fit Matrix"),
    ("conflict_web", "outreach_conflict_web_image", "Portfolio Overlap / Conflict Web"),
    ("priority_ladder", "outreach_priority_ladder_image", "Partner Outreach Priority Ladder"),
    ("cadence_tracker", "outreach_cadence_tracker_image", "Round Timing / Cadence Tracker"),
    ("check_size", "outreach_check_size_image", "Check-Size Range Chart"),
    ("thesis_cards", "outreach_thesis_cards_image", "Why You Thesis-Match Cards"),
]

CHART_KINDS = tuple(kind for _, kind, _ in CHART_SPECS)


class VisualInsightsProvider(SyncProvider):
    """Synthesize outreach chart payloads → Gemini image visuals for the PDF."""

    name = "outreach-insights"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        work_dir: str | None = None,
        image_model: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir
        self.image_model = image_model or os.environ.get(
            "GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE, Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)

        inputs = list(step.inputs or [])
        website = find_input_json(inputs, "outreach_website")
        revenue = find_input_json(inputs, "outreach_revenue")
        investors = find_input_json(inputs, "outreach_investors")
        portfolio = find_input_json(inputs, "outreach_portfolio")
        try:
            partners = find_input_json(inputs, "outreach_enriched")
        except RuntimeError:
            partners = find_input_json(inputs, "outreach_partners")

        text_model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        image_model = self.image_model or step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or ".")
        img_dir = work / "insight-charts"
        img_dir.mkdir(parents=True, exist_ok=True)

        chart_data = _synthesize_chart_data(
            website, revenue, investors, portfolio, partners, text_model, self.api_key
        )
        product_label = str(chart_data.get("product_label") or "Company")

        image_provider = GeminiImageProvider(
            api_key=self.api_key or None,
            output_dir=img_dir,
            retry_policy=gemini_image_retry_policy(),
        )
        charts_meta: list[dict[str, Any]] = []

        for i, (chart_id, kind, title) in enumerate(CHART_SPECS):
            if i > 0:
                time.sleep(1.8)
            payload = chart_data.get(chart_id) or {}
            prompt = _prompt_for(chart_id, product_label, payload, chart_data)
            log.info("generating outreach chart=%s model=%s", chart_id, image_model)
            tmp = Step(
                step_id=f"{step.step_id}-{chart_id}",
                provider=image_provider.name,
                model=image_model,
                modality=Modality.IMAGE,
                prompt=prompt,
            )
            try:
                call_with_transient_retry(
                    lambda tmp=tmp, cfg=config: image_provider.generate(tmp, cfg)
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("outreach chart failed id=%s: %s", chart_id, exc)
                charts_meta.append(
                    {
                        "id": chart_id,
                        "kind": kind,
                        "title": title,
                        "ok": False,
                        "error": str(exc)[:240],
                        "prompt": prompt,
                    }
                )
                continue
            if not tmp.assets:
                charts_meta.append(
                    {
                        "id": chart_id,
                        "kind": kind,
                        "title": title,
                        "ok": False,
                        "error": "no_image_asset",
                        "prompt": prompt,
                    }
                )
                continue

            asset = tmp.assets[0]
            raw_url = getattr(asset, "url", None)
            url_s = str(getattr(raw_url, "url", None) or raw_url or "")
            path = local_path(url_s)
            data_uri = _file_to_data_uri(path) if path else None
            meta = dict(getattr(asset, "metadata", None) or {})
            meta.update(
                {
                    "kind": kind,
                    "chart_id": chart_id,
                    "title": title,
                    "prompt": prompt,
                    "data_uri": data_uri,
                    "local_path": str(path) if path else None,
                }
            )
            step.assets.append(asset.model_copy(update={"metadata": meta}))
            if path and path.is_file():
                step.assets.append(
                    file_asset(
                        path,
                        media_type=getattr(asset, "media_type", None) or "image/png",
                        metadata={
                            "kind": kind,
                            "chart_id": chart_id,
                            "title": title,
                            "data_uri": data_uri,
                            "embed": True,
                        },
                    )
                )
            charts_meta.append(
                {
                    "id": chart_id,
                    "kind": kind,
                    "title": title,
                    "ok": True,
                    "path": str(path) if path else None,
                    "data_uri": data_uri,
                    "caption": _caption_for(chart_id),
                    "prompt": prompt,
                }
            )

        insights = {
            "product_label": product_label,
            "chart_data": chart_data,
            "charts": charts_meta,
            "headline": str(chart_data.get("headline") or ""),
        }
        step.assets.append(
            json_file_asset(
                insights,
                work_dir=work,
                name="insights",
                metadata={"kind": "outreach_insights"},
            )
        )
        ok_n = sum(1 for c in charts_meta if c.get("ok"))
        log.info("outreach insights charts_ok=%s/%s", ok_n, len(charts_meta))
        if ok_n == 0:
            raise RuntimeError(
                "[outreach_insight_images_failed] Gemini produced no outreach charts"
            )
        return step


def _synthesize_chart_data(
    website: dict[str, Any],
    revenue: dict[str, Any],
    investors: dict[str, Any],
    portfolio: dict[str, Any],
    partners: dict[str, Any],
    model: str,
    api_key: str,
) -> dict[str, Any]:
    compact = {
        "productSummary": str(website.get("productSummary") or "")[:2200],
        "websiteUrl": website.get("url"),
        "performanceSummary": str(revenue.get("performanceSummary") or "")[:2200],
        "investorSummary": str(investors.get("investorSummary") or "")[:2500],
        "investorStructured": investors.get("structuredOutput"),
        "portfolioSummary": str(portfolio.get("portfolioRevenueSummary") or "")[:2500],
        "portfolioStructured": portfolio.get("structuredOutput"),
        "firms": partners.get("firms") or [],
        "contacts": (partners.get("contacts") or [])[:25],
        "contactSummary": str(partners.get("contactSummary") or "")[:1500],
    }
    try:
        data = gemini_json(
            f"""You are building STRUCTURED chart payloads for an investor outreach intelligence PDF.
Use ONLY evidence in the JSON below. Prefer approximate numeric values when text implies them;
use null when unknown. Never invent firm names that are not mentioned.

Evidence:
{json.dumps(compact, default=str)[:14000]}

Return JSON with this exact shape:
{{
  "product_label": "company name",
  "founder_metrics": {{
    "revenue_usd": number|null,
    "revenue_label": "e.g. $40k MRR",
    "stage": "e.g. Seed",
    "ask_usd": number|null,
    "ask_label": "e.g. raising $1.5M"
  }},
  "headline": "one sentence: are we too early? + outreach posture",
  "revenue_benchmark": {{
    "points": [
      {{"company":"", "investor":"", "revenue_usd":0, "revenue_label":"", "round":"", "round_size_usd":null, "is_founder":false}}
    ],
    "x_axis": "Revenue at time of investment",
    "y_axis": "Round / stage size"
  }},
  "fit_matrix": {{
    "investors": ["firm..."],
    "dimensions": ["stage match","category match","check-size match","portfolio overlap/conflict"],
    "scores": {{"Firm": {{"stage match": 0-3, "category match": 0-3, "check-size match": 0-3, "portfolio overlap/conflict": 0-3}}}}
  }},
  "conflict_web": {{
    "nodes": [{{"id":"", "label":"", "type":"founder|investor|portfolio|competitor"}}],
    "edges": [{{"from":"", "to":"", "relation":"funded|competes|adjacent"}}],
    "warning": "one sentence risk if any"
  }},
  "priority_ladder": {{
    "people": [{{"name":"", "firm":"", "role":"", "warm_score":0-100, "why":""}}]
  }},
  "cadence_tracker": {{
    "funds": [{{"firm":"", "deals_per_quarter":number|null, "last_deal":"YYYY-MM or unknown", "category":"", "active":true}}]
  }},
  "check_size": {{
    "funds": [{{"firm":"", "min_usd":number|null, "max_usd":number|null, "label":""}}],
    "ask_usd": number|null,
    "ask_label": ""
  }},
  "thesis_cards": {{
    "cards": [{{"firm":"", "thesis_quote":"", "founder_metric_match":"", "email_language":""}}]
  }}
}}

Rules:
- Include the founder as is_founder=true on revenue_benchmark.points.
- Fit scores 0=poor, 1=weak, 2=good, 3=strong. portfolio overlap/conflict: 3=safe/no conflict, 0=direct rival conflict.
- priority_ladder: top 5-8 people only, ranked by warm_score desc.
- thesis_cards: top 3 firms only.
- Keep arrays compact (max ~12 investors / benchmarks).""",
            model=model,
            api_key=api_key,
            system=(
                "You are a venture outreach analyst converting messy diligence notes into "
                "exact chart-ready JSON. Be skeptical; prefer null over fiction. JSON only."
            ),
        )
        if isinstance(data, dict) and data.get("revenue_benchmark"):
            return data
    except Exception as exc:  # noqa: BLE001
        log.warning("chart data synthesis failed: %s", exc)

    return _fallback_chart_data(website, revenue, investors, portfolio, partners)


def _fallback_chart_data(
    website: dict[str, Any],
    revenue: dict[str, Any],
    investors: dict[str, Any],
    portfolio: dict[str, Any],
    partners: dict[str, Any],
) -> dict[str, Any]:
    label = "Company"
    summary = str(website.get("productSummary") or "")
    for line in summary.splitlines():
        if "product" in line.lower() and ":" in line:
            label = line.split(":", 1)[-1].strip()[:40] or label
            break
    firms = list(partners.get("firms") or [])[:8]
    if not firms:
        for r in (investors.get("sources") or [])[:6]:
            if r.get("title"):
                firms.append(str(r["title"])[:40])
    contacts = list(partners.get("contacts") or [])[:8]
    people = []
    for i, c in enumerate(contacts):
        people.append(
            {
                "name": c.get("name") or "Partner",
                "firm": c.get("firm") or "",
                "role": c.get("role") or "Partner",
                "warm_score": max(40, 90 - i * 7),
                "why": "Public profile / firm page signal",
            }
        )
    structured_bench = []
    out = portfolio.get("structuredOutput")
    if isinstance(out, dict):
        structured_bench = list(out.get("benchmarks") or [])[:10]
    points = [
        {
            "company": label,
            "investor": "(you)",
            "revenue_usd": None,
            "revenue_label": "Your traction",
            "round": "Now",
            "round_size_usd": None,
            "is_founder": True,
        }
    ]
    for b in structured_bench:
        points.append(
            {
                "company": b.get("company") or "Portfolio co",
                "investor": b.get("investor") or "",
                "revenue_usd": None,
                "revenue_label": b.get("preInvestmentRevenue") or "n/a",
                "round": b.get("round") or "",
                "round_size_usd": None,
                "is_founder": False,
            }
        )
    dims = [
        "stage match",
        "category match",
        "check-size match",
        "portfolio overlap/conflict",
    ]
    scores = {f: {d: 2 for d in dims} for f in firms[:8]}
    return {
        "product_label": label,
        "founder_metrics": {
            "revenue_usd": None,
            "revenue_label": "See performance section",
            "stage": "Seed",
            "ask_usd": None,
            "ask_label": "Ask TBD",
        },
        "headline": f"Visual diligence pack for {label} — benchmarks, fit, conflicts, and who to email first.",
        "revenue_benchmark": {
            "points": points,
            "x_axis": "Revenue at time of investment",
            "y_axis": "Round / stage size",
        },
        "fit_matrix": {"investors": firms[:8], "dimensions": dims, "scores": scores},
        "conflict_web": {
            "nodes": [
                {"id": "founder", "label": label, "type": "founder"},
                *[
                    {"id": f"inv-{i}", "label": f, "type": "investor"}
                    for i, f in enumerate(firms[:5])
                ],
            ],
            "edges": [
                {"from": f"inv-{i}", "to": "founder", "relation": "evaluating"}
                for i in range(min(5, len(firms)))
            ],
            "warning": "Validate portfolio conflicts manually before pitching.",
        },
        "priority_ladder": {"people": people},
        "cadence_tracker": {
            "funds": [
                {
                    "firm": f,
                    "deals_per_quarter": None,
                    "last_deal": "unknown",
                    "category": "general",
                    "active": True,
                }
                for f in firms[:8]
            ]
        },
        "check_size": {
            "funds": [
                {"firm": f, "min_usd": None, "max_usd": None, "label": "typical check unknown"}
                for f in firms[:8]
            ],
            "ask_usd": None,
            "ask_label": "Ask TBD",
        },
        "thesis_cards": {
            "cards": [
                {
                    "firm": f,
                    "thesis_quote": "Thesis details in investor shortlist prose",
                    "founder_metric_match": str(revenue.get("performanceSummary") or "")[:120],
                    "email_language": f"Opening line tying {label} traction to {f}'s focus",
                }
                for f in firms[:3]
            ]
        },
    }


def _file_to_data_uri(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64,{b64}"


def _caption_for(chart_id: str) -> str:
    return {
        "revenue_benchmark": "Are we too early? Your company (highlighted) vs portfolio comps at entry.",
        "fit_matrix": "Scan stage / category / check-size / conflict fit across shortlisted VCs.",
        "conflict_web": "Who already funded rivals or adjacent competitors — avoid awkward pitches.",
        "priority_ladder": "Start with these partners — ranked by warm-path likelihood.",
        "cadence_tracker": "Who is actively deploying now vs stale checkbooks.",
        "check_size": "Typical check ranges vs your ask (vertical marker).",
        "thesis_cards": "Thesis language paired with your matching traction for cold emails.",
    }.get(chart_id, "")


_STYLE = """You are generating ONE editorial data visualization for a founder-facing
Investor Outreach Intelligence PDF (FounderBlaze).

HARD VISUAL RULES:
- Clean modern analytics / board-memo infographic. NOT photorealistic, NOT 3D CGI, NOT cartoon.
- White / soft teal-tint background. Ink #122028. Accent teal #0c7268. Sparse coral for warnings.
- Fraunces/serif titles + sans body vibe. Generous margins. No watermarks, no fake UI chrome.
- Every number/label MUST match the provided data. Do not invent extra firms.
- Landscape 16:9, print-ready for A4 embedding.
- No real VC logos. No stock photos of people. Title + short subtitle only.
"""


def _prompt_for(
    chart_id: str,
    product_label: str,
    payload: dict[str, Any],
    all_data: dict[str, Any],
) -> str:
    data_blob = json.dumps(payload, indent=2, default=str)[:4500]
    founder = all_data.get("founder_metrics") or {}
    makers = {
        "revenue_benchmark": f"""{_STYLE}
CHART: Revenue Benchmark Positioning — scatter plot.
PRODUCT: {product_label}
FOUNDER METRICS: {json.dumps(founder, default=str)}
DATA:
{data_blob}
DESIGN:
- X = revenue at investment time; Y = round/stage size (use ordinal if USD missing).
- Plot each portfolio point as a teal dot; founder point LARGER, dark/coral, labeled "YOU".
- Callout: "Are we too early?" with a one-line read of founder vs cloud.
- Axes labeled exactly as in data. Legend for founder vs comps.""",
        "fit_matrix": f"""{_STYLE}
CHART: Investor Fit Matrix — heatmap grid.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Rows = investors; columns = fit dimensions.
- Cell color intensity by score 0–3 (pale = weak, deep teal = strong). For portfolio overlap/conflict, deep teal = safe, red tint = conflict.
- Numeric score inside each cell. Title: "Investor fit at a glance".""",
        "conflict_web": f"""{_STYLE}
CHART: Portfolio Overlap / Conflict Web — node-link diagram.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Center or highlight the founder node; investors and portfolio/competitor companies around it.
- Edge styles: funded (solid teal), competes (red), adjacent (dashed).
- Warning banner if conflict risk exists. Title: "Conflict web — look before you pitch".""",
        "priority_ladder": f"""{_STYLE}
CHART: Partner Outreach Priority Ladder — vertical ranked leaderboard.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Ranked bars/cards top→bottom by warm_score.
- Show name, firm, role, score, one-line why.
- Emphasize top 5. Title: "Who to email first".""",
        "cadence_tracker": f"""{_STYLE}
CHART: Round Timing / Cadence Tracker — horizontal timeline / activity strip.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- One row per fund: last deal date marker + deals/quarter spark.
- Active funds in teal; stale (inactive / old last_deal) muted gray.
- Title: "Who is deploying right now".""",
        "check_size": f"""{_STYLE}
CHART: Check-Size Range Chart — horizontal range bars.
PRODUCT: {product_label}
FOUNDER ASK: {json.dumps({k: founder.get(k) for k in ("ask_usd", "ask_label")}, default=str)}
DATA:
{data_blob}
DESIGN:
- One bar per fund from min→max check size; label ranges.
- Vertical line for founder ask across the chart.
- Title: "Check size vs your ask".""",
        "thesis_cards": f"""{_STYLE}
CHART: "Why You" Thesis-Match Cards — 3 side-by-side cards (top investors only).
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Each card: firm name, short thesis quote/theme, founder metric that matches, suggested cold-email language snippet.
- Prove synthesis is real — specific, not generic slogans.
- Title: "Language that matches their thesis".""",
    }
    return makers[chart_id]
