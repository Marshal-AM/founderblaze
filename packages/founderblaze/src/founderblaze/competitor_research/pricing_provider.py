from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import find_input_json, json_file_asset
from founderblaze.competitor_research.gemini_chat import gemini_json
from founderblaze.competitor_research.page_fetch import truncate_for_llm

log = logging.getLogger("founderblaze.competitor_research.pricing")


def extract_prices(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    re_price = re.compile(
        r"(?:starting at|from|only)?\s*\$\s*([\d,]+(?:\.\d+)?)\s*"
        r"(?:/\s*|per\s+)?(user/mo|seat/mo|mo|month|/mo|yr|year|/yr|user|seat)?",
        re.I,
    )
    for match in re_price.finditer(text or ""):
        if len(results) >= 8:
            break
        raw = (match.group(1) or "").replace(",", "")
        try:
            price = float(raw)
        except ValueError:
            continue
        period_raw = (match.group(2) or "").lower()
        period = None
        if re.search(r"yr|year", period_raw):
            period = "year"
        elif re.search(r"mo|month|user|seat", period_raw):
            period = "month"
        results.append({"price": price, "period": period})
    return results


def extract_tiers_heuristic(text: str, label: str) -> list[dict[str, Any]]:
    prices = extract_prices(text)
    plan_names = [
        m.group(1)
        for m in re.finditer(
            r"\b(Free|Starter|Basic|Plus|Pro|Professional|Team|Business|"
            r"Enterprise|Unlimited|Standard|Premium|Growth)\b",
            text or "",
            re.I,
        )
    ]
    unique: list[str] = []
    for p in plan_names:
        name = p[:1].upper() + p[1:]
        if name not in unique:
            unique.append(name)
    unique = unique[:5]

    if unique and prices:
        out = []
        for i, name in enumerate(unique):
            p = prices[min(i, len(prices) - 1)]
            is_free = re.match(r"^free$", name, re.I)
            out.append(
                {
                    "name": name,
                    "price": 0 if is_free else p["price"],
                    "currency": "USD",
                    "period": None if is_free else (p.get("period") or "month"),
                }
            )
        return out

    if prices:
        return [
            {
                "name": "Listed plan" if i == 0 else f"Plan {i + 1}",
                "price": p["price"],
                "currency": "USD",
                "period": p.get("period") or "month",
                "notes": f"Extracted from {label} public page",
            }
            for i, p in enumerate(prices[:4])
        ]

    if re.search(
        r"contact (sales|us)|custom pricing|talk to sales|request a quote",
        text or "",
        re.I,
    ):
        return [
            {
                "name": "Enterprise",
                "currency": "USD",
                "notes": "Contact sales / custom (public page)",
            }
        ]

    return [
        {
            "name": "Not disclosed",
            "currency": "USD",
            "notes": "No public list price found",
        }
    ]


def infer_pricing_model(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"contact (sales|us)|custom pricing|talk to sales", t) and not re.search(
        r"\$\d", t
    ):
        return "contact-sales"
    if re.search(r"free (forever|plan|tier)|freemium", t) or (
        re.search(r"\bfree\b", t) and re.search(r"\$\d", t)
    ):
        return "freemium"
    if re.search(r"per (user|seat)|/user|/seat", t):
        return "per-seat"
    if re.search(r"usage[- ]based|pay as you go|credits", t):
        return "usage-based"
    if re.search(r"flat[- ]rate|fixed price|per (workspace|org|team)", t):
        return "flat-rate"
    if re.search(r"\$\d", t):
        return "per-seat"
    return "contact-sales"


def pricing_signals(text: str) -> str:
    prices = extract_prices(text)
    price_part = (
        "prices: "
        + ", ".join(
            f"${p['price']}{('/' + p['period']) if p.get('period') else ''}"
            for p in prices
        )
        if prices
        else "prices: none"
    )
    return f"{price_part}; model hint: {infer_pricing_model(text)}"


class ScrapePricingProvider(SyncProvider):
    """Gemini pricing tiers from evidence → pricing.json."""

    name = "competitor-research-pricing"

    def __init__(
        self, *, api_key: str | None = None, work_dir: str | None = None
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
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        inputs = list(step.inputs or [])
        found = find_input_json(inputs, "competitors")
        evidence_payload = find_input_json(inputs, "evidence")
        product_name = str(found["product_name"])
        competitors = list(found.get("competitors") or [])[:5]
        evidence = dict(evidence_payload.get("evidence") or {})

        product_page = evidence.get(product_name) or {
            "pricingText": "",
            "pricingUrl": "",
        }
        competitor_pages = []
        for c in competitors:
            page = evidence.get(c["name"]) or {"pricingText": "", "pricingUrl": ""}
            competitor_pages.append(
                {
                    "name": c["name"],
                    "text": page.get("pricingText") or "",
                    "url": page.get("pricingUrl") or "",
                }
            )

        pricing = self._llm_pricing(
            model, product_name, product_page, competitor_pages
        ) or self._heuristic_pricing(product_name, product_page, competitor_pages)

        payload = {
            "product_name": product_name,
            "product_url": found.get("product_url"),
            "competitors": competitors,
            "pricing": pricing,
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="pricing",
                metadata={"kind": "pricing"},
            )
        )
        return step

    def _llm_pricing(
        self,
        model: str,
        product_name: str,
        product_page: dict[str, Any],
        competitor_pages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        try:
            compact = "\n\n".join(
                f"### {c['name']}\n{pricing_signals(c['text'])}\n"
                f"{truncate_for_llm(c['text'], 700)}"
                for c in competitor_pages
            )
            data = gemini_json(
                f"""Product: {product_name}

Product ({product_page.get('pricingUrl')}):
{pricing_signals(str(product_page.get('pricingText') or ''))}
{truncate_for_llm(str(product_page.get('pricingText') or ''), 1200)}

Competitors:
{compact}

Return:
{{
  "product_pricing": {{ "tiers": [{{ "name", "price"?, "currency":"USD", "period"?, "notes"? }}] }},
  "competitor_pricing": [{{ "competitor", "tiers": [...], "pricing_model", "enterprise_custom"? }}],
  "price_history_signals": []
}}""",
                model=model,
                api_key=self.api_key,
                system=(
                    "Extract public SaaS pricing tiers from vendor markdown. pricing_model must be "
                    "one of: per-seat, flat-rate, usage-based, freemium, contact-sales. Do not invent "
                    "prices. Return JSON only."
                ),
            )
            if not (data.get("product_pricing") or {}).get("tiers"):
                return None
            competitor_pricing = []
            for c in data.get("competitor_pricing") or []:
                page_text = next(
                    (p["text"] for p in competitor_pages if p["name"] == c.get("competitor")),
                    "",
                )
                model_name = c.get("pricing_model")
                if not model_name or model_name == "unknown":
                    model_name = infer_pricing_model(page_text)
                tiers = c.get("tiers") or []
                if not tiers:
                    tiers = extract_tiers_heuristic(page_text, str(c.get("competitor")))
                competitor_pricing.append(
                    {
                        **c,
                        "pricing_model": model_name,
                        "tiers": tiers,
                    }
                )
            return {
                "product_pricing": data["product_pricing"],
                "competitor_pricing": competitor_pricing,
                "price_history_signals": data.get("price_history_signals") or [],
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("pricing LLM failed: %s", exc)
            return None

    def _heuristic_pricing(
        self,
        product_name: str,
        product_page: dict[str, Any],
        competitor_pages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "product_pricing": {
                "tiers": extract_tiers_heuristic(
                    str(product_page.get("pricingText") or ""), product_name
                )
            },
            "competitor_pricing": [
                {
                    "competitor": c["name"],
                    "tiers": extract_tiers_heuristic(c["text"], c["name"]),
                    "pricing_model": infer_pricing_model(c["text"]),
                    "enterprise_custom": bool(
                        re.search(r"contact|sales|custom|enterprise", c["text"], re.I)
                    ),
                }
                for c in competitor_pages
            ],
            "price_history_signals": [],
        }
