from __future__ import annotations

import base64
import json
import logging
import os
import re
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

from founderblaze.competitor_research._assets import (
    file_asset,
    find_input_json,
    json_file_asset,
    local_path,
)
from founderblaze.competitor_research.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.competitor_research.insights")

CHART_SPECS: list[tuple[str, str, str]] = [
    ("steal_share", "competitor_steal_share_image", "Steal-Share Priority Scatter"),
    ("icp_heat", "competitor_icp_heat_image", "ICP × Workflow Heat Grid"),
    ("icp_venn", "competitor_icp_venn_image", "ICP Overlap Venn"),
    ("threat_portfolio", "competitor_threat_portfolio_image", "Threat / Opportunity Portfolio"),
    ("lock_in", "competitor_lock_in_image", "Lock-in Force Diagram"),
]

CHART_KINDS = tuple(kind for _, kind, _ in CHART_SPECS)

_LOCKIN_HINTS = re.compile(
    r"\b(sso|saml|scim|okta|azure ad|active directory|salesforce|hubspot|"
    r"slack|jira|github|gitlab|zapier|api\b|webhook|sdk|export|csv|migration|"
    r"annual contract|multi[- ]year|enterprise agreement|seat minimum|"
    r"data residency|on[- ]prem|self[- ]host|lock[- ]in|vendor lock)\b",
    re.I,
)


class VisualInsightsProvider(SyncProvider):
    """Synthesize competitive attack chart payloads → Gemini images for the PDF."""

    name = "competitor-research-insights"

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
        positioning = find_input_json(inputs, "positioning")
        try:
            evidence_payload = find_input_json(inputs, "evidence")
        except RuntimeError:
            evidence_payload = {}

        text_model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        image_model = self.image_model or step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or ".")
        img_dir = work / "insight-charts"
        img_dir.mkdir(parents=True, exist_ok=True)

        chart_data = _synthesize_chart_data(
            positioning, evidence_payload, text_model, self.api_key
        )
        product_label = str(
            chart_data.get("product_label")
            or positioning.get("product_name")
            or "Product"
        )

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
            # Skip lock-in image when there is truly no public signal.
            if chart_id == "lock_in" and not payload.get("has_signal"):
                log.info("skipping lock_in chart — no public lock-in signals")
                charts_meta.append(
                    {
                        "id": chart_id,
                        "kind": kind,
                        "title": title,
                        "ok": False,
                        "skipped": True,
                        "error": "insufficient_public_lock_in_signal",
                        "caption": _caption_for(chart_id),
                    }
                )
                continue

            prompt = _prompt_for(chart_id, product_label, payload, chart_data)
            log.info("generating competitor chart=%s model=%s", chart_id, image_model)
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
                log.warning("competitor chart failed id=%s: %s", chart_id, exc)
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
                metadata={"kind": "competitor_research_insights"},
            )
        )
        ok_n = sum(1 for c in charts_meta if c.get("ok"))
        log.info("competitor insights charts_ok=%s/%s", ok_n, len(charts_meta))
        if ok_n == 0:
            raise RuntimeError(
                "[competitor_insight_images_failed] Gemini produced no competitor charts"
            )
        return step


def _synthesize_chart_data(
    positioning: dict[str, Any],
    evidence_payload: dict[str, Any],
    model: str,
    api_key: str,
) -> dict[str, Any]:
    product_name = str(positioning.get("product_name") or "Product")
    feature_diff = dict(positioning.get("feature_diff") or {})
    pricing = dict(positioning.get("pricing") or {})
    pos = dict(positioning.get("positioning") or {})
    competitors = list(positioning.get("competitors") or [])
    evidence = dict(evidence_payload.get("evidence") or {})

    lock_hints = _extract_lockin_hints(evidence)
    compact = {
        "product_name": product_name,
        "product_url": positioning.get("product_url"),
        "competitors": [
            {
                "name": c.get("name"),
                "url": c.get("url"),
                "confidence": c.get("confidence"),
            }
            for c in competitors[:5]
        ],
        "features": list(feature_diff.get("features") or [])[:16],
        "matrix_compact": _compact_matrix(feature_diff),
        "pricing_compact": _compact_pricing(product_name, pricing),
        "positioning_map": pos.get("positioning_map"),
        "swot": pos.get("swot"),
        "recommended_positioning": (pos.get("recommended_positioning") or [])[:4],
        "lock_in_hints": lock_hints,
        "evidence_snippets": {
            k: str((v or {}).get("text") or "")[:900]
            for k, v in list(evidence.items())[:6]
        },
    }
    try:
        data = gemini_json(
            f"""You are building STRUCTURED chart payloads for a competitive intelligence PDF.
Use ONLY evidence in the JSON below. Never invent competitor names.
For lock_in: ONLY include forces backed by lock_in_hints or evidence_snippets;
set has_signal=false if nothing concrete about integrations, SSO, contracts, or migration.

Evidence:
{json.dumps(compact, default=str)[:14000]}

Return JSON with this exact shape:
{{
  "product_label": "{product_name}",
  "headline": "one sentence: who to steal from first + category posture",
  "steal_share": {{
    "points": [
      {{
        "competitor": "",
        "icp_overlap": 0-100,
        "switching_pain": 0-100,
        "bubble": 1-5,
        "monday_action": "one short action",
        "is_you": false
      }}
    ],
    "x_axis": "ICP overlap with you (stealability)",
    "y_axis": "Switching pain (low = easier displace)",
    "callout": "who to steal from Monday morning"
  }},
  "icp_heat": {{
    "segments": ["SMB", "Mid-market", "Enterprise"],
    "workflows": ["workflow A", "workflow B", "..."],
    "cells": [
      {{
        "segment": "SMB",
        "workflow": "workflow A",
        "owner": "Competitor or You or Contested or Whitespace",
        "intensity": 0-3,
        "is_wedge": false
      }}
    ],
    "wedge_note": "why your outlined cells are the wedge"
  }},
  "icp_venn": {{
    "sets": [
      {{"label": "You", "segments": ["SMB","Mid-market"], "workflows": ["..."], "is_you": true}},
      {{"label": "Rival", "segments": ["Enterprise"], "workflows": ["..."], "is_you": false}}
    ],
    "wedge": "one sentence: where you uniquely sit",
    "steal_first": "competitor name to attack first"
  }},
  "threat_portfolio": {{
    "points": [
      {{
        "name": "",
        "threat": 0-100,
        "readiness": 0-100,
        "quadrant": "ignore|watch|attack|defend",
        "is_you": false
      }}
    ],
    "x_axis": "Peer market threat",
    "y_axis": "Your readiness to compete",
    "board_read": "one sentence board-deck takeaway"
  }},
  "lock_in": {{
    "has_signal": true,
    "nodes": [
      {{"id": "data|integrations|admin|contracts|habits", "label": "", "force": 0-100}}
    ],
    "edges": [
      {{
        "competitor": "",
        "to": "integrations",
        "strength": 0-100,
        "evidence": "short quote or page signal"
      }}
    ],
    "caveat": "public-web only; validate in sales diligence"
  }}
}}

Rules:
- steal_share: include every competitor; optionally include You with is_you=true at a reference point. Prefer high icp_overlap + low switching_pain as steal-first.
- icp_heat: 3 segments × 4-6 workflows; mark is_wedge=true only on cells you uniquely own or can credibly claim.
- icp_venn: You + up to 3 competitors (not all 5 overlapping — pick clearest sets).
- threat_portfolio: You may appear as readiness reference; peers plotted by threat vs how ready you are against them.
- lock_in edges MUST cite evidence strings from lock_in_hints or snippets; else has_signal=false and empty edges.
- Do not invent pricing numbers; scores are relative judgments grounded in matrix/pricing/evidence.""",
            model=model,
            api_key=api_key,
            system=(
                "You are a competitive strategy analyst converting feature/pricing evidence "
                "into exact chart-ready JSON. Prefer null/empty and has_signal=false over fiction. JSON only."
            ),
        )
        if isinstance(data, dict) and data.get("steal_share"):
            # Merge lock-in hints if model dropped them.
            lock = dict(data.get("lock_in") or {})
            if not lock.get("has_signal") and lock_hints:
                data["lock_in"] = _lockin_from_hints(product_name, lock_hints)
            elif lock.get("has_signal") and not lock.get("edges"):
                lock["has_signal"] = False
                data["lock_in"] = lock
            data.setdefault("product_label", product_name)
            return data
    except Exception as exc:  # noqa: BLE001
        log.warning("competitor chart synthesis failed: %s", exc)

    return _fallback_chart_data(product_name, competitors, feature_diff, pricing, lock_hints)


def _compact_matrix(feature_diff: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    features = list(feature_diff.get("features") or [])[:14]
    for entity, row in (feature_diff.get("matrix") or {}).items():
        out[str(entity)] = {
            f: str((row or {}).get(f, {}).get("status") or "unknown") for f in features
        }
    return out


def _compact_pricing(product_name: str, pricing: dict[str, Any]) -> dict[str, Any]:
    def tiers(items: list[dict[str, Any]]) -> list[str]:
        labels = []
        for t in items[:4]:
            price = t.get("price")
            name = t.get("name") or "Plan"
            if isinstance(price, (int, float)):
                labels.append(f"{name} ${price}")
            else:
                labels.append(f"{name} (custom/undisclosed)")
        return labels

    return {
        "product": tiers(list((pricing.get("product_pricing") or {}).get("tiers") or [])),
        "competitors": [
            {
                "name": c.get("competitor"),
                "model": c.get("pricing_model"),
                "tiers": tiers(list(c.get("tiers") or [])),
            }
            for c in (pricing.get("competitor_pricing") or [])[:5]
        ],
    }


def _extract_lockin_hints(evidence: dict[str, Any]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for name, blob in evidence.items():
        text = str((blob or {}).get("text") or "")
        url = str((blob or {}).get("url") or (blob or {}).get("pricingUrl") or "")
        for m in _LOCKIN_HINTS.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 60)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            hints.append(
                {
                    "entity": str(name),
                    "signal": m.group(0).lower(),
                    "snippet": snippet[:160],
                    "url": url,
                }
            )
            if len(hints) >= 24:
                return hints
    return hints


def _lockin_from_hints(
    product_name: str, hints: list[dict[str, str]]
) -> dict[str, Any]:
    force_map = {
        "integrations": (
            "salesforce",
            "hubspot",
            "slack",
            "jira",
            "github",
            "gitlab",
            "zapier",
            "api",
            "webhook",
            "sdk",
        ),
        "data": ("export", "csv", "migration", "data residency", "on-prem", "self-host"),
        "admin": ("sso", "saml", "scim", "okta", "azure ad", "active directory"),
        "contracts": (
            "annual contract",
            "multi-year",
            "enterprise agreement",
            "seat minimum",
        ),
        "habits": ("lock-in", "vendor lock"),
    }
    nodes = [
        {"id": k, "label": k.replace("_", " ").title(), "force": 35}
        for k in force_map
    ]
    edges: list[dict[str, Any]] = []
    force_scores: dict[str, int] = {k: 20 for k in force_map}
    for h in hints:
        sig = h.get("signal") or ""
        node_id = None
        for nid, keys in force_map.items():
            if any(k in sig for k in keys):
                node_id = nid
                break
        if not node_id:
            continue
        entity = h.get("entity") or "Unknown"
        if entity == product_name:
            continue
        force_scores[node_id] = min(100, force_scores[node_id] + 12)
        edges.append(
            {
                "competitor": entity,
                "to": node_id,
                "strength": 55,
                "evidence": h.get("snippet") or sig,
            }
        )
    for n in nodes:
        n["force"] = force_scores.get(n["id"], 20)
    # Deduplicate edges by competitor+to
    seen: set[str] = set()
    uniq = []
    for e in edges:
        key = f"{e['competitor']}|{e['to']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return {
        "has_signal": bool(uniq),
        "nodes": nodes,
        "edges": uniq[:16],
        "caveat": "Public-page signals only — validate contracts and admin lock-in in diligence.",
    }


def _parity_debt_from_matrix(
    product_name: str, feature_diff: dict[str, Any]
) -> dict[str, Any]:
    features = list(feature_diff.get("features") or [])
    matrix = dict(feature_diff.get("matrix") or {})
    product_row = matrix.get(product_name) or {}
    rivals = [k for k in matrix if k != product_name]
    bars: list[dict[str, Any]] = []
    for rival in rivals:
        row = matrix.get(rival) or {}
        gaps: list[str] = []
        for f in features:
            rival_st = (row.get(f) or {}).get("status", "unknown")
            prod_st = (product_row.get(f) or {}).get("status", "unknown")
            if rival_st == "yes" and prod_st in ("no", "unknown", "partial"):
                gaps.append(f)
        bars.append(
            {
                "competitor": rival,
                "debt_count": len(gaps),
                "gaps": gaps[:8],
                "label": f"{len(gaps)} gaps to close",
            }
        )
    bars.sort(key=lambda b: (-int(b["debt_count"]), str(b["competitor"])))
    return {
        "bars": bars,
        "unit": "features they evidence that you lack or only partially cover",
        "note": "Computed directly from the yes/partial/no feature matrix — no invented gaps.",
    }


def _fallback_chart_data(
    product_name: str,
    competitors: list[dict[str, Any]],
    feature_diff: dict[str, Any],
    pricing: dict[str, Any],
    lock_hints: list[dict[str, str]],
) -> dict[str, Any]:
    names = [str(c.get("name") or "Peer") for c in competitors[:5]]
    matrix = dict(feature_diff.get("matrix") or {})
    features = list(feature_diff.get("features") or [])
    workflows = (features[:5] or ["Core workflow", "Collaboration", "Reporting", "Admin"])[
        :5
    ]
    segments = ["SMB", "Mid-market", "Enterprise"]

    steal_points = []
    for i, name in enumerate(names):
        conf = float((competitors[i] or {}).get("confidence") or 0.6)
        breadth = _breadth(matrix.get(name), features)
        steal_points.append(
            {
                "competitor": name,
                "icp_overlap": int(round(conf * 100)),
                "switching_pain": int(round(breadth * 100)),
                "bubble": max(1, 5 - i),
                "monday_action": f"Probe displace path vs {name}",
                "is_you": False,
            }
        )
    steal_points.sort(key=lambda p: (-p["icp_overlap"], p["switching_pain"]))

    cells = []
    for wi, wf in enumerate(workflows):
        for si, seg in enumerate(segments):
            owner = names[(wi + si) % len(names)] if names else "Whitespace"
            is_wedge = wi == 0 and si == 0
            if is_wedge:
                owner = product_name
            cells.append(
                {
                    "segment": seg,
                    "workflow": wf,
                    "owner": owner,
                    "intensity": 2 if not is_wedge else 3,
                    "is_wedge": is_wedge,
                }
            )

    threat_points = []
    for i, name in enumerate(names):
        debt = _parity_debt_from_matrix(product_name, feature_diff)
        debt_n = next(
            (b["debt_count"] for b in debt["bars"] if b["competitor"] == name), 0
        )
        readiness = max(10, 90 - int(debt_n) * 12)
        threat = int(round(float((competitors[i] or {}).get("confidence") or 0.5) * 100))
        if readiness >= 55 and threat >= 55:
            quad = "attack"
        elif readiness < 55 and threat >= 55:
            quad = "defend"
        elif readiness >= 55 and threat < 55:
            quad = "watch"
        else:
            quad = "ignore"
        threat_points.append(
            {
                "name": name,
                "threat": threat,
                "readiness": readiness,
                "quadrant": quad,
                "is_you": False,
            }
        )

    lock_in = _lockin_from_hints(product_name, lock_hints)
    first = steal_points[0]["competitor"] if steal_points else "top peer"
    return {
        "product_label": product_name,
        "headline": f"Monday move: pressure {first} where ICP overlap is high and switching pain is lower.",
        "steal_share": {
            "points": steal_points,
            "x_axis": "ICP overlap with you (stealability)",
            "y_axis": "Switching pain (low = easier displace)",
            "callout": f"Steal first from {first}" if steal_points else "Validate peers",
        },
        "icp_heat": {
            "segments": segments,
            "workflows": workflows,
            "cells": cells,
            "wedge_note": f"Outlined cells are {product_name}'s claimed wedge from public evidence.",
        },
        "icp_venn": {
            "sets": [
                {
                    "label": product_name,
                    "segments": ["SMB", "Mid-market"],
                    "workflows": workflows[:2],
                    "is_you": True,
                },
                *[
                    {
                        "label": n,
                        "segments": [segments[i % 3]],
                        "workflows": [workflows[i % len(workflows)]],
                        "is_you": False,
                    }
                    for i, n in enumerate(names[:3])
                ],
            ],
            "wedge": f"{product_name} as the SMB/mid wedge against enterprise-heavy peers",
            "steal_first": first,
        },
        "threat_portfolio": {
            "points": threat_points,
            "x_axis": "Peer market threat",
            "y_axis": "Your readiness to compete",
            "board_read": "Attack high-threat peers only where readiness clears the bar.",
        },
        "lock_in": lock_in,
    }


def _breadth(row: dict[str, Any] | None, features: list[str]) -> float:
    if not features:
        return 0.5
    yes = sum(
        1
        for f in features
        if (row or {}).get(f, {}).get("status") in ("yes", "partial")
    )
    return yes / len(features)


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
        "steal_share": "Who to steal from Monday morning — high ICP overlap, lower switching pain.",
        "icp_heat": "Who owns each segment × workflow cell; your wedge cells are outlined.",
        "icp_venn": "Segment/workflow ownership overlap with you as the wedge.",
        "threat_portfolio": "Board altitude: ignore / watch / attack / defend across the category.",
        "lock_in": "Why a feature win ≠ a deal win — lock-in forces from public page signals only.",
    }.get(chart_id, "")


_STYLE = """You are generating ONE editorial data visualization for a founder-facing
Competitive Intelligence PDF (FounderBlaze Feature 5).

HARD VISUAL RULES:
- Clean modern strategy / board-memo infographic. NOT photorealistic, NOT 3D CGI, NOT cartoon.
- White / soft rose-tint background. Ink #241a1c. Accent crimson #c1202a. Teal #1c7a4a for opportunity.
- Space Grotesk / geometric sans titles + clean sans body. Generous margins. No watermarks, no fake UI chrome.
- Every label MUST match the provided data. Do not invent extra competitors.
- Landscape 16:9, print-ready for A4 embedding.
- No real product logos. Title + short subtitle only.
"""


def _prompt_for(
    chart_id: str,
    product_label: str,
    payload: dict[str, Any],
    all_data: dict[str, Any],
) -> str:
    data_blob = json.dumps(payload, indent=2, default=str)[:4500]
    makers = {
        "steal_share": f"""{_STYLE}
CHART: Steal-Share Priority Scatter.
PRODUCT: {product_label}
HEADLINE: {all_data.get("headline") or ""}
DATA:
{data_blob}
DESIGN:
- X = ICP overlap (stealability); Y = switching pain (LOW at bottom = easier displace).
- Plot each competitor as a bubble sized by bubble field; label names.
- Highlight the top-left / high-overlap + low-pain quadrant as "STEAL FIRST".
- One callout box with monday_action for the top target.
- Title: "Steal-share priority — what to do Monday".""",
        "icp_heat": f"""{_STYLE}
CHART: ICP × Workflow Heat Grid.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Rows = workflows; columns = SMB / Mid-market / Enterprise.
- Cell color by intensity; put owner name in each cell.
- Outline YOUR wedge cells (is_wedge=true) with a thick dark border — the strategic claim.
- Small note for wedge_note. Title: "Who owns which buyer × workflow".""",
        "icp_venn": f"""{_STYLE}
CHART: ICP Overlap — simplified set diagram (NOT a messy 5-circle Venn).
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Show You as a distinct wedge/set overlapping 2–3 rival sets (segments + workflows labeled).
- Call out steal_first and the wedge sentence.
- Keep readable — use overlapping rounded regions or a clear Euler-style layout, not spaghetti.
- Title: "Where you sit vs who to steal from".""",
        "threat_portfolio": f"""{_STYLE}
CHART: Threat / Opportunity Portfolio — classic 2×2.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- X = peer market threat; Y = your readiness to compete.
- Quadrant labels: IGNORE / WATCH / ATTACK / DEFEND.
- Plot each peer; annotate board_read as a footer callout.
- Title: "Category posture for the board".""",
        "lock_in": f"""{_STYLE}
CHART: Lock-in Force Diagram — node + edge force map.
PRODUCT: {product_label}
DATA:
{data_blob}
DESIGN:
- Center nodes for lock-in forces (data, integrations, admin, contracts, habits) sized by force.
- Edges from competitors into those nodes, thickness by strength; tiny evidence quote on 2–3 key edges.
- Banner caveat: public-web signals only.
- Title: "Why feature wins ≠ deal wins".""",
    }
    return makers[chart_id]
