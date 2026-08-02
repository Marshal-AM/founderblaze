from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import find_input_json, json_file_asset
from founderblaze.competitor_research.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.competitor_research.positioning")


def lowest_price(tiers: list[dict[str, Any]]) -> float | None:
    prices = [
        t["price"]
        for t in tiers
        if isinstance(t.get("price"), (int, float))
    ]
    return min(prices) if prices else None


def feature_breadth(
    matrix_row: dict[str, Any] | None, features: list[str]
) -> float:
    if not features:
        return 0.5
    score = 0.0
    for f in features:
        st = (matrix_row or {}).get(f, {}).get("status", "unknown")
        if st == "yes":
            score += 1
        elif st == "partial":
            score += 0.5
    return score / len(features)


def build_deterministic_map(
    product_name: str,
    feature_diff: dict[str, Any],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    features = list(feature_diff.get("features") or [])
    matrix = dict(feature_diff.get("matrix") or {})
    points_raw: list[dict[str, Any]] = [
        {
            "name": product_name,
            "price": lowest_price(
                list((pricing.get("product_pricing") or {}).get("tiers") or [])
            ),
            "breadth": feature_breadth(matrix.get(product_name), features),
        }
    ]
    for c in pricing.get("competitor_pricing") or []:
        points_raw.append(
            {
                "name": c.get("competitor"),
                "price": lowest_price(list(c.get("tiers") or [])),
                "breadth": feature_breadth(matrix.get(c.get("competitor")), features),
            }
        )

    known = [p["price"] for p in points_raw if isinstance(p.get("price"), (int, float))]
    min_p = min(known) if known else 0.0
    max_p = max(known) if known else 1.0
    span = max(1.0, max_p - min_p)
    undisclosed = [p for p in points_raw if not isinstance(p.get("price"), (int, float))]
    undisclosed_index = {p["name"]: i for i, p in enumerate(undisclosed)}

    out_points = []
    for p in points_raw:
        if isinstance(p.get("price"), (int, float)):
            x = 0.08 + ((p["price"] - min_p) / span) * 0.62 if span > 0 else 0.2
        else:
            i = undisclosed_index.get(p["name"], 0)
            n = max(1, len(undisclosed))
            x = 0.82 + ((i / (n - 1)) * 0.1 - 0.05 if n > 1 else 0)
        out_points.append(
            {
                "name": p["name"],
                "x": max(0.06, min(0.94, x)),
                "y": max(0.08, min(0.94, float(p["breadth"]))),
            }
        )
    return {
        "axes": ["monthly price (public list)", "feature breadth (evidenced)"],
        "points": out_points,
    }


def compact_evidence(
    product_name: str, feature_diff: dict[str, Any], pricing: dict[str, Any]
) -> str:
    feature_lines = []
    for f in feature_diff.get("features") or []:
        cells = ", ".join(
            f"{entity}:{(row or {}).get(f, {}).get('status', '?')}"
            for entity, row in (feature_diff.get("matrix") or {}).items()
        )
        feature_lines.append(f"{f} → {cells}")
    price_lines = [
        f"{product_name}: "
        + "; ".join(
            f"{t.get('name')}{(' $' + str(t['price'])) if t.get('price') is not None else ''}"
            for t in (pricing.get("product_pricing") or {}).get("tiers") or []
        )
    ]
    for c in pricing.get("competitor_pricing") or []:
        tiers = "; ".join(
            f"{t.get('name', '?')}{(' $' + str(t['price'])) if t.get('price') is not None else ''}"
            for t in (c.get("tiers") or [])
        )
        price_lines.append(
            f"{c.get('competitor')} ({c.get('pricing_model') or '?'}): {tiers}"
        )
    return (
        "Features:\n"
        + "\n".join(feature_lines)
        + "\n\nPricing:\n"
        + "\n".join(price_lines)
    )


class BuildPositioningProvider(SyncProvider):
    """Gemini SWOT/recs + deterministic price×feature map → positioning.json."""

    name = "competitor-research-positioning"

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
        features_payload = find_input_json(inputs, "features")
        pricing_payload = find_input_json(inputs, "pricing")
        product_name = str(
            features_payload.get("product_name")
            or pricing_payload.get("product_name")
        )
        feature_diff = dict(features_payload.get("feature_diff") or {})
        pricing = dict(pricing_payload.get("pricing") or {})
        competitors = list(
            features_payload.get("competitors")
            or pricing_payload.get("competitors")
            or []
        )

        pos_map = build_deterministic_map(product_name, feature_diff, pricing)
        positioning = self._llm_positioning(
            model, product_name, feature_diff, pricing, pos_map
        )

        payload = {
            "product_name": product_name,
            "product_url": None,
            "competitors": competitors,
            "feature_diff": feature_diff,
            "pricing": pricing,
            "positioning": positioning,
        }
        # Carry product_url if present on earlier payloads
        for src in (features_payload, pricing_payload):
            if src.get("product_url"):
                payload["product_url"] = src["product_url"]
                break

        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="positioning",
                metadata={"kind": "positioning"},
            )
        )
        return step

    def _llm_positioning(
        self,
        model: str,
        product_name: str,
        feature_diff: dict[str, Any],
        pricing: dict[str, Any],
        pos_map: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            data = gemini_json(
                f"""Product: {product_name}

{compact_evidence(product_name, feature_diff, pricing)}

Return:
{{
  "swot": {{ "strengths": string[], "weaknesses": string[], "opportunities": string[], "threats": string[] }},
  "recommended_positioning": [{{ "angle": string, "supporting_facts": string[] }}],
  "risks": string[]
}}
Rules: 3-4 recommendations; each must name a peer and a concrete evidence point.""",
                model=model,
                api_key=self.api_key,
                system=(
                    "Competitive strategist. Cite concrete prices/features only. "
                    "No slogans. Return JSON only."
                ),
            )
            return {
                "swot": data.get("swot")
                or {
                    "strengths": [],
                    "weaknesses": [],
                    "opportunities": [],
                    "threats": [],
                },
                "positioning_map": pos_map,
                "recommended_positioning": data.get("recommended_positioning") or [],
                "risks": data.get("risks") or [],
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("positioning LLM failed: %s", exc)
            peers = [c.get("competitor") for c in pricing.get("competitor_pricing") or []]
            return {
                "swot": {
                    "strengths": [
                        f"{product_name} public feature coverage scored against "
                        f"{len(peers)} peers"
                    ],
                    "weaknesses": ["Some vendors disclose limited public pricing"],
                    "opportunities": ["Differentiate on evidenced feature gaps"],
                    "threats": [p for p in peers[:3] if p],
                },
                "positioning_map": pos_map,
                "recommended_positioning": [
                    {
                        "angle": "Compete on evidenced capability density",
                        "supporting_facts": [
                            "Positioning map derived from public list prices and feature evidence"
                        ],
                    }
                ],
                "risks": [
                    "Synthesis fallback used after LLM error — map/pricing still from public pages"
                ],
            }
