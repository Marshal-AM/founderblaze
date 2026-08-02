from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.social_listening._assets import file_asset, find_input_json
from founderblaze.social_listening.insights_provider import CHART_KINDS
from founderblaze.social_listening.report_html import build_report_html

log = logging.getLogger("founderblaze.social_listening.report")


class CompileReportProvider(SyncProvider):
    """Product + recommendations + insight charts → HTML → Playwright PDF."""

    name = "social-listening-report"

    def __init__(self, *, work_dir: str | None = None) -> None:
        super().__init__()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        product = find_input_json(inputs, "social_listening_product")
        recs_payload = find_input_json(inputs, "social_listening_recommendations")
        recommendations = list(recs_payload.get("recommendations") or [])
        if not recommendations:
            raise RuntimeError(
                f'[reddit_no_drafts] No recommendations to compile for '
                f'"{product.get("product_name")}"'
            )

        insights: dict[str, Any] = {}
        try:
            insights = find_input_json(inputs, "social_listening_insights")
        except RuntimeError:
            log.warning("insights asset missing — PDF without charts")

        chart_images = _collect_chart_images(inputs, insights)

        data: dict[str, Any] = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "websiteUrl": product.get("website_url") or "",
            "product": product,
            "subreddits": recs_payload.get("subreddits") or product.get("subreddits") or [],
            "recommendations": recommendations,
            "intervalLabel": recs_payload.get("interval_label"),
            "funnel": recs_payload.get("funnel") or insights.get("funnel_stages"),
            "insights": insights,
            "charts": chart_images,
        }
        html = build_report_html(data)
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        label = _safe_slug(str(product.get("product_name") or "product"))
        pdf_path = work / f"{label}-reddit.pdf"
        html_path = work / f"{label}-reddit.html"
        html_path.write_text(html, encoding="utf-8")

        log.info("rendering PDF via Playwright path=%s charts=%s", pdf_path, len(chart_images))
        _html_to_pdf(html, pdf_path)
        bytes_len = pdf_path.stat().st_size
        log.info("PDF ready bytes=%s", bytes_len)

        step.assets.append(
            file_asset(
                pdf_path,
                media_type="application/pdf",
                metadata={
                    "kind": "social_listening_pdf",
                    "bytes": bytes_len,
                    "html_path": str(html_path),
                    "recommendations_count": len(recommendations),
                    "charts_embedded": [c.get("id") for c in chart_images],
                    "thread_urls": [
                        r.get("targetPermalink")
                        for r in recommendations
                        if r.get("targetPermalink")
                    ],
                },
            )
        )
        return step


def _collect_chart_images(
    inputs: list[Any], insights: dict[str, Any]
) -> list[dict[str, Any]]:
    """Prefer data URIs from insight assets; fall back to insights.charts JSON."""
    by_id: dict[str, dict[str, Any]] = {}
    titles = {
        "funnel": (
            "Thread discovery funnel",
            "Community-manager labor: scanned → shortlisted.",
        ),
        "territory": (
            "Subreddit territory map",
            "Where relevant threads appeared — size by volume, color by receptiveness.",
        ),
        "cluster": (
            "Pain-point clusters",
            "Shape of demand: complaints and needs behind the threads.",
        ),
    }

    for asset in inputs or []:
        meta = dict(getattr(asset, "metadata", None) or {})
        kind = meta.get("kind")
        if kind not in CHART_KINDS:
            continue
        chart_id = str(meta.get("chart_id") or "")
        data_uri = meta.get("data_uri")
        if not data_uri:
            continue
        title, caption = titles.get(chart_id, (chart_id, ""))
        by_id[chart_id] = {
            "id": chart_id,
            "kind": kind,
            "title": title,
            "caption": caption,
            "data_uri": data_uri,
        }

    for c in insights.get("charts") or []:
        if not c.get("ok"):
            continue
        chart_id = str(c.get("id") or "")
        if chart_id in by_id:
            continue
        data_uri = c.get("data_uri")
        if not data_uri:
            continue
        title, caption = titles.get(chart_id, (chart_id, ""))
        by_id[chart_id] = {
            "id": chart_id,
            "kind": c.get("kind"),
            "title": title,
            "caption": caption,
            "data_uri": data_uri,
        }

    order = ["funnel", "territory", "cluster"]
    return [by_id[k] for k in order if k in by_id]


def _html_to_pdf(html: str, out: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.pdf(
                path=str(out),
                format="A4",
                print_background=True,
                margin={
                    "top": "12mm",
                    "right": "10mm",
                    "bottom": "12mm",
                    "left": "10mm",
                },
            )
        finally:
            browser.close()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-_]+", "-", value.lower()).strip("-")
    return (slug or "product")[:48]
