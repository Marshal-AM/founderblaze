from __future__ import annotations

import base64
import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from genblaze_core.models.step import Step
from founderblaze.core.gemini_retry import (
    call_with_transient_retry,
    gemini_image_retry_policy,
)
from genblaze_google import GeminiImageProvider

from founderblaze.social_listening._assets import (
    file_asset,
    find_input_json,
    json_file_asset,
    local_path,
)
from founderblaze.social_listening.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.social_listening.insights")

CHART_KINDS = (
    "social_listening_funnel_image",
    "social_listening_territory_image",
    "social_listening_cluster_image",
)


class VisualInsightsProvider(SyncProvider):
    """Synthesize funnel / territory / pain clusters → Gemini image charts."""

    name = "social-listening-insights"

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
        product = find_input_json(inputs, "social_listening_product")
        threads = find_input_json(inputs, "social_listening_threads")
        recs = find_input_json(inputs, "social_listening_recommendations")
        text_model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        image_model = self.image_model or step.model or "gemini-2.5-flash-image"

        work = Path(self.work_dir or ".")
        img_dir = work / "insight-charts"
        img_dir.mkdir(parents=True, exist_ok=True)

        funnel_stages = _build_funnel_stages(threads, recs)
        territory = _build_territory(threads, recs)
        clusters = _cluster_pain_points(
            product, threads, recs, text_model, self.api_key
        )

        charts_meta: list[dict[str, Any]] = []
        image_provider = GeminiImageProvider(
            api_key=self.api_key or None,
            output_dir=img_dir,
            retry_policy=gemini_image_retry_policy(),
        )

        specs = [
            (
                "funnel",
                CHART_KINDS[0],
                _funnel_image_prompt(product, funnel_stages),
            ),
            (
                "territory",
                CHART_KINDS[1],
                _territory_image_prompt(product, territory),
            ),
            (
                "cluster",
                CHART_KINDS[2],
                _cluster_image_prompt(product, clusters),
            ),
        ]

        for i, (chart_id, kind, prompt) in enumerate(specs):
            if i > 0:
                time.sleep(1.5)
            log.info("generating insight chart=%s model=%s", chart_id, image_model)
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
                log.warning("insight image failed chart=%s: %s", chart_id, exc)
                charts_meta.append(
                    {
                        "id": chart_id,
                        "kind": kind,
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
                        "ok": False,
                        "error": "no_image_asset",
                        "prompt": prompt,
                    }
                )
                continue
            asset = tmp.assets[0]
            path = local_path(str(getattr(getattr(asset, "url", None), "url", None) or asset.url or ""))
            data_uri = _file_to_data_uri(path) if path else None
            meta = dict(getattr(asset, "metadata", None) or {})
            meta.update(
                {
                    "kind": kind,
                    "chart_id": chart_id,
                    "prompt": prompt,
                    "data_uri": data_uri,
                    "local_path": str(path) if path else None,
                }
            )
            step.assets.append(asset.model_copy(update={"metadata": meta}))
            # Also emit a durable local copy asset for PDF embedding reliability
            if path and path.is_file():
                step.assets.append(
                    file_asset(
                        path,
                        media_type=getattr(asset, "media_type", None) or "image/png",
                        metadata={
                            "kind": kind,
                            "chart_id": chart_id,
                            "data_uri": data_uri,
                            "embed": True,
                        },
                    )
                )
            charts_meta.append(
                {
                    "id": chart_id,
                    "kind": kind,
                    "ok": True,
                    "path": str(path) if path else None,
                    "data_uri": data_uri,
                    "prompt": prompt,
                }
            )

        insights = {
            "product_name": product.get("product_name"),
            "funnel_stages": funnel_stages,
            "territory": territory,
            "clusters": clusters,
            "charts": charts_meta,
            "headline": _headline(product, funnel_stages, clusters),
        }
        step.assets.append(
            json_file_asset(
                insights,
                work_dir=work,
                name="insights",
                metadata={"kind": "social_listening_insights"},
            )
        )
        ok_n = sum(1 for c in charts_meta if c.get("ok"))
        log.info("insights ready charts_ok=%s/%s", ok_n, len(charts_meta))
        if ok_n == 0:
            raise RuntimeError(
                "[insight_images_failed] Gemini image generation produced no charts"
            )
        return step


def _build_funnel_stages(threads: dict[str, Any], recs: dict[str, Any]) -> list[dict[str, Any]]:
    funnel = dict(recs.get("funnel") or {})
    scanned = int(funnel.get("scanned") or threads.get("candidates_seen") or 0)
    matching = int(funnel.get("matching_intent") or threads.get("hit_count") or 0)
    engagement = int(funnel.get("recency_engagement") or matching)
    compliance = int(funnel.get("compliance") or 0)
    shortlist = int(funnel.get("shortlist") or len(recs.get("recommendations") or []))
    stages = [
        {"key": "scanned", "label": "Threads scanned", "count": scanned},
        {"key": "matching", "label": "Matching intent", "count": matching},
        {
            "key": "engagement",
            "label": "Recency / engagement filter",
            "count": engagement,
        },
        {"key": "compliance", "label": "Passed compliance", "count": compliance},
        {"key": "shortlist", "label": "Final shortlist delivered", "count": shortlist},
    ]
    # Enforce non-increasing counts for a readable funnel.
    prev = stages[0]["count"]
    for s in stages:
        s["count"] = min(int(s["count"]), prev)
        prev = s["count"]
        s["count"] = max(0, int(s["count"]))
    return stages


def _build_territory(threads: dict[str, Any], recs: dict[str, Any]) -> list[dict[str, Any]]:
    events = list(threads.get("events") or [])
    ready = list(recs.get("recommendations") or [])
    skipped = list(recs.get("skipped") or [])
    by_sub: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"thread_count": 0, "shortlisted": 0, "skipped": 0, "titles": []}
    )
    for e in events:
        sub = _sub(e.get("community"))
        by_sub[sub]["thread_count"] += 1
        if e.get("title"):
            by_sub[sub]["titles"].append(str(e["title"])[:80])
    for r in ready:
        sub = _sub(r.get("community") or (r.get("event") or {}).get("community"))
        by_sub[sub]["shortlisted"] += 1
        by_sub[sub]["thread_count"] = max(by_sub[sub]["thread_count"], 1)
    for s in skipped:
        sub = _sub(s.get("community"))
        by_sub[sub]["skipped"] += 1
        by_sub[sub]["thread_count"] = max(by_sub[sub]["thread_count"], 1)

    out = []
    for sub, stats in by_sub.items():
        total = max(1, stats["shortlisted"] + stats["skipped"])
        # Higher receptiveness when more threads made the shortlist.
        receptiveness = round(stats["shortlisted"] / total, 2)
        risk = round(1.0 - receptiveness, 2)
        out.append(
            {
                "subreddit": sub,
                "thread_count": int(stats["thread_count"]),
                "shortlisted": int(stats["shortlisted"]),
                "skipped": int(stats["skipped"]),
                "receptiveness": receptiveness,
                "compliance_risk": risk,
                "sample_titles": stats["titles"][:3],
            }
        )
    out.sort(key=lambda x: (-x["thread_count"], x["subreddit"]))
    return out[:12]


def _cluster_pain_points(
    product: dict[str, Any],
    threads: dict[str, Any],
    recs: dict[str, Any],
    model: str,
    api_key: str,
) -> list[dict[str, Any]]:
    corpus = []
    for e in threads.get("events") or []:
        corpus.append(
            {
                "subreddit": _sub(e.get("community")),
                "title": e.get("title"),
                "body": str(e.get("body") or "")[:400],
                "why": e.get("thread_context"),
            }
        )
    for r in recs.get("recommendations") or []:
        corpus.append(
            {
                "subreddit": _sub(r.get("community")),
                "title": r.get("title"),
                "body": str(r.get("threadContext") or "")[:400],
                "why": "shortlisted",
            }
        )
    if not corpus:
        return []

    try:
        data = gemini_json(
            f"""Product: {product.get("product_name")}
One-liner: {product.get("one_liner")}

Threads (JSON):
{corpus[:20]}

Cluster these Reddit threads by the underlying buyer pain / unmet need
(not by subreddit name). Prefer short noun phrases founders would recognize
(e.g. "manual reconciliation", "no API", "too expensive", "onboarding friction").

Return JSON only:
{{
  "clusters": [
    {{
      "label": "2-5 word pain name",
      "summary": "one sentence of demand shape",
      "size": 1,
      "example_titles": ["..."],
      "subreddits": ["r/..."]
    }}
  ]
}}
Rules: 3-6 clusters; size = thread count in cluster; no brand pitches.""",
            model=model,
            api_key=api_key,
            system=(
                "You are a product research synthesizer. You turn messy Reddit "
                "seeker threads into a compact demand topology. Be concrete, "
                "skeptical of fluff, and never invent threads. Return JSON only."
            ),
        )
        clusters = data.get("clusters") or []
        cleaned = []
        for c in clusters[:6]:
            label = str(c.get("label") or "").strip()
            if not label:
                continue
            cleaned.append(
                {
                    "label": label[:60],
                    "summary": str(c.get("summary") or "")[:220],
                    "size": max(1, int(c.get("size") or 1)),
                    "example_titles": list(c.get("example_titles") or [])[:3],
                    "subreddits": list(c.get("subreddits") or [])[:5],
                }
            )
        if cleaned:
            return cleaned
    except Exception as exc:  # noqa: BLE001
        log.warning("pain clustering LLM failed: %s", exc)

    # Heuristic fallback: one cluster per subreddit with titles.
    territory = _build_territory(threads, recs)
    return [
        {
            "label": f"{t['subreddit']} asks",
            "summary": f"Demand signals concentrated in {t['subreddit']}",
            "size": t["thread_count"],
            "example_titles": t.get("sample_titles") or [],
            "subreddits": [t["subreddit"]],
        }
        for t in territory[:5]
    ]


def _headline(
    product: dict[str, Any],
    stages: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> str:
    scanned = next((s["count"] for s in stages if s["key"] == "scanned"), 0)
    shortlist = next((s["count"] for s in stages if s["key"] == "shortlist"), 0)
    top = clusters[0]["label"] if clusters else "buyer pain"
    name = product.get("product_name") or "your product"
    return (
        f"We scanned {scanned} threads to deliver {shortlist} ready replies for {name} "
        f"— demand shape led by “{top}”."
    )


def _sub(community: Any) -> str:
    s = str(community or "reddit").strip()
    if not s:
        return "r/unknown"
    return s if s.startswith("r/") else f"r/{s}"


def _file_to_data_uri(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# Image prompts — designed for Gemini image models (chart/infographic style)
# ---------------------------------------------------------------------------

_STYLE_SYSTEM = """You are generating a SINGLE editorial data visualization for a founder-facing
Reddit engagement intelligence PDF (FounderBlaze).

HARD VISUAL RULES:
- Clean modern infographic / analytics dashboard aesthetic (NOT photorealistic, NOT 3D CGI, NOT cartoon mascot).
- White or very light warm-gray background. Dark charcoal text (#1a1f24). Accent color Reddit-orange (#FF4500) sparingly.
- Generous margins, crisp typography (Inter / Geist / Helvetica-like), no watermarks, no UI chrome, no phone mockups.
- Every number shown MUST match the data provided exactly — do not invent extra metrics.
- Landscape 16:9 composition suitable for embedding full-width in an A4 PDF.
- No logos of Reddit or third parties. No stock-photo people. No fake browser windows.
- Title at top; small caption/footer with the product name only.
"""


def _funnel_image_prompt(product: dict[str, Any], stages: list[dict[str, Any]]) -> str:
    name = product.get("product_name") or "Product"
    lines = "\n".join(f"- {s['label']}: {s['count']}" for s in stages)
    scanned = stages[0]["count"] if stages else 0
    shortlist = stages[-1]["count"] if stages else 0
    return f"""{_STYLE_SYSTEM}

CHART TYPE: Thread Discovery Funnel (vertical funnel / stacked trapezoids narrowing downward).

PRODUCT: {name}

FUNNEL STAGES (top → bottom, exact counts):
{lines}

DESIGN INTENT:
- This chart sells the "community manager labor" behind the report: volume of work vs curated output.
- Emphasize the drop from {scanned} scanned → {shortlist} delivered with a bold callout:
  "Scanned {scanned} threads to find your {shortlist}."
- Stage labels left or inside each band; counts large and tabular.
- Soft orange fill at the top band fading cooler/neutral toward the bottom shortlist band.
- Subtitle: "Discovery → intent match → engagement filter → compliance → shortlist"

OUTPUT: one polished funnel infographic image, no surrounding explanation text outside the chart."""


def _territory_image_prompt(product: dict[str, Any], territory: list[dict[str, Any]]) -> str:
    name = product.get("product_name") or "Product"
    if not territory:
        territory = [{"subreddit": "r/unknown", "thread_count": 1, "receptiveness": 0.5, "compliance_risk": 0.5}]
    lines = "\n".join(
        (
            f"- {t['subreddit']}: threads={t['thread_count']}, "
            f"receptiveness={t['receptiveness']}, compliance_risk={t['compliance_risk']}"
        )
        for t in territory
    )
    return f"""{_STYLE_SYSTEM}

CHART TYPE: Subreddit Territory Map (bubble chart).

PRODUCT: {name}

BUBBLES (exact data):
{lines}

DESIGN INTENT:
- Each bubble = one subreddit. Bubble AREA proportional to thread_count.
- Color encodes reply-receptiveness (green = high receptiveness / low compliance risk) → amber → red (higher compliance risk).
- Include a small legend: size = thread volume; color = receptiveness vs compliance risk.
- Title: "Where your audience actually asks"
- Subtitle: "Territory map — durable community intelligence beyond this week's shortlist"
- Labels should use r/name next to or inside bubbles without overlap.

OUTPUT: one polished bubble-map infographic, white background, print-ready."""


def _cluster_image_prompt(product: dict[str, Any], clusters: list[dict[str, Any]]) -> str:
    name = product.get("product_name") or "Product"
    if not clusters:
        clusters = [
            {
                "label": "Unmet workflow pain",
                "summary": "Seekers asking for a better tool",
                "size": 1,
            }
        ]
    lines = "\n".join(
        (
            f"- {c['label']} (size={c['size']}): {c.get('summary') or ''} "
            f"| examples: {', '.join(c.get('example_titles') or [])}"
        )
        for c in clusters
    )
    return f"""{_STYLE_SYSTEM}

CHART TYPE: Pain-Point Cluster Diagram (node / bubble clusters).

PRODUCT: {name}

CLUSTERS (exact data):
{lines}

DESIGN INTENT:
- Reframe Reddit noise into the shape of demand — synthesis a founder cannot get by scrolling.
- Soft clustered blobs / nodes grouped by theme; larger nodes for larger size values.
- Each cluster labeled with its pain-point name; tiny supporting caption from summary.
- Title: "Shape of demand"
- Subtitle: "NLP clusters of the complaints and needs behind this week's threads"
- Use muted teal/slate nodes with orange highlights on the largest cluster only.

OUTPUT: one polished cluster diagram infographic, editorial and boardroom-safe."""
