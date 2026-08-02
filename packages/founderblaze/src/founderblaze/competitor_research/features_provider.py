from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import find_input_json, json_file_asset
from founderblaze.competitor_research.gemini_chat import gemini_json
from founderblaze.competitor_research.page_fetch import truncate_for_llm

log = logging.getLogger("founderblaze.competitor_research.features")

Status = Literal["yes", "partial", "no", "unknown"]

GENERIC_FEATURES = [
    "Free plan / trial",
    "Mobile apps (iOS/Android)",
    "API / developer platform",
    "Third-party integrations",
    "SSO / SAML",
    "AI features",
]

FEATURE_ALIASES: dict[str, list[str]] = {
    "free plan": ["free plan", "free forever", "free tier", "free trial", "start for free"],
    "mobile app": ["mobile app", "ios app", "android app", "iphone", "app store", "google play"],
    "api": ["api", "rest api", "graphql", "developer platform", "webhooks", "sdk"],
    "integration": ["integration", "integrations", "zapier", "marketplace", "connect"],
    "sso": ["sso", "single sign", "saml", "okta", "oidc", "scim"],
    "permission": ["role-based", "rbac", "permission", "roles", "access control"],
    "audit": ["audit log", "audit trail", "activity log"],
    "ai": ["ai ", "artificial intelligence", "copilot", "assistant", "gpt"],
}

STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "with", "to", "in", "on",
    "features", "feature", "support", "advanced", "based",
}


def _keywords_for(feature: str) -> list[str]:
    label = feature.lower()
    for key, aliases in FEATURE_ALIASES.items():
        if key in label:
            return aliases
    tokens = [
        w
        for w in re.sub(r"[^a-z0-9 /]", " ", label).split()
        if len(w) > 2 and w not in STOPWORDS
    ]
    return tokens or [label]


def infer_status(text: str, feature: str) -> Status:
    t = text.lower()
    for kw in _keywords_for(feature):
        if kw not in t:
            continue
        if f"no {kw}" in t or f"without {kw}" in t:
            return "no"
        if re.search(r"enterprise[- ]only|add-?on|paid add|higher tiers", t):
            return "partial"
        return "yes"
    return "unknown"


def prune_sparse_features(diff: dict[str, Any]) -> dict[str, Any]:
    features = list(diff.get("features") or [])
    matrix = dict(diff.get("matrix") or {})
    entities = list(matrix.keys())
    if not entities or not features:
        return diff

    scored = []
    for feature in features:
        known = sum(
            1
            for e in entities
            if (matrix.get(e) or {}).get(feature, {}).get("status", "unknown")
            != "unknown"
        )
        scored.append({"feature": feature, "known": known, "ratio": known / len(entities)})

    keep = [s["feature"] for s in scored if s["ratio"] >= 0.5]
    if len(keep) < 4:
        keep = [
            s["feature"]
            for s in sorted(scored, key=lambda x: x["known"], reverse=True)[
                : min(6, len(scored))
            ]
            if s["known"] > 0
        ]
    if not keep:
        keep = features[:4]

    new_matrix: dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    for entity, cells in matrix.items():
        new_matrix[entity] = {}
        for f in keep:
            new_matrix[entity][f] = (cells or {}).get(f) or {
                "status": "unknown",
                "evidence_url": None,
                "scraped_at": now,
            }
    return {"features": keep, "matrix": new_matrix, "conflicts": diff.get("conflicts") or []}


class DiffFeaturesProvider(SyncProvider):
    """Gemini feature dimensions + matrix → features.json."""

    name = "competitor-research-features"

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

        targets = [{"key": product_name}] + [{"key": c["name"]} for c in competitors]
        product_ev = evidence.get(product_name) or {"text": "", "url": "", "fetched_at": ""}
        features = self._select_features(model, product_name, str(product_ev.get("text") or ""))

        matrix: dict[str, Any] = {}
        for t in targets:
            key = t["key"]
            ev = evidence.get(key) or {"text": "", "url": "", "fetched_at": ""}
            cells = self._score_vendor(model, key, str(ev.get("text") or ""), features)
            matrix[key] = {
                f: {
                    "status": cells.get(f, "unknown"),
                    "evidence_url": ev.get("url"),
                    "scraped_at": ev.get("fetched_at"),
                }
                for f in features
            }

        feature_diff = prune_sparse_features(
            {"features": features, "matrix": matrix, "conflicts": []}
        )
        payload = {
            "product_name": product_name,
            "product_url": found.get("product_url"),
            "competitors": competitors,
            "feature_diff": feature_diff,
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="features",
                metadata={"kind": "features"},
            )
        )
        return step

    def _select_features(self, model: str, product_name: str, product_text: str) -> list[str]:
        try:
            data = gemini_json(
                f"""Product: {product_name}

Product page excerpt:
{truncate_for_llm(product_text, 1400)}

Return {{ "category": string, "features": string[] }} with 6-8 features that best differentiate tools in this category.""",
                model=model,
                api_key=self.api_key,
                system=(
                    "You define the buying criteria for a software category. Return 6-8 concrete, "
                    "comparable capabilities that buyers in THIS product's category weigh when "
                    "choosing between tools. Use short noun phrases (2-4 words), category-specific "
                    "where possible, not generic fluff. Return JSON only."
                ),
            )
            features = [
                str(f).strip()
                for f in (data.get("features") or [])
                if 3 <= len(str(f).strip()) <= 40
            ][:8]
            if len(features) >= 4:
                return features
        except Exception as exc:  # noqa: BLE001
            log.warning("feature selection failed: %s", exc)
        return list(GENERIC_FEATURES)

    def _score_vendor(
        self, model: str, name: str, text: str, features: list[str]
    ) -> dict[str, Status]:
        try:
            data = gemini_json(
                f"""Vendor: {name}

Features to assess:
{features}

Page text:
{truncate_for_llm(text, 3600)}

Return {{ "features": {{ "<feature>": "yes|partial|no|unknown", ... }} }} for every feature listed.""",
                model=model,
                api_key=self.api_key,
                system=(
                    "You are a meticulous product analyst. Decide feature support for ONE vendor "
                    "using ONLY the provided page text. Rules: 'yes' = text clearly shows the vendor "
                    "offers it; 'partial' = only on higher/enterprise tiers or as an add-on; "
                    "'no' = ONLY if the text explicitly says it is not available; 'unknown' = the "
                    "text does not mention it. Never guess. When in doubt use 'unknown'. Return JSON only."
                ),
            )
            raw_map = data.get("features") or {}
            cells: dict[str, Status] = {}
            for f in features:
                raw = raw_map.get(f)
                st: Status = (
                    raw if raw in ("yes", "partial", "no") else "unknown"  # type: ignore[assignment]
                )
                if st == "unknown":
                    heur = infer_status(text, f)
                    cells[f] = heur if heur in ("yes", "partial") else "unknown"
                else:
                    cells[f] = st
            return cells
        except Exception as exc:  # noqa: BLE001
            log.warning("vendor feature scoring failed vendor=%s: %s", name, exc)
            return {f: infer_status(text, f) for f in features}
