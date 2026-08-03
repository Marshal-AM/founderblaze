from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import file_asset, find_input_json
from founderblaze.outreach.insights_provider import CHART_KINDS, CHART_SPECS
from founderblaze.outreach.report_html import build_report_html

log = logging.getLogger("founderblaze.outreach.report")


class CompileReportProvider(SyncProvider):
    """Assemble findings JSON + insight charts → HTML → Playwright PDF."""

    name = "outreach-report"

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
        website = find_input_json(inputs, "outreach_website")
        revenue = find_input_json(inputs, "outreach_revenue")
        investors = find_input_json(inputs, "outreach_investors")
        portfolio = find_input_json(inputs, "outreach_portfolio")
        try:
            partners = find_input_json(inputs, "outreach_enriched")
        except RuntimeError:
            partners = find_input_json(inputs, "outreach_partners")

        insights: dict[str, Any] = {}
        try:
            insights = find_input_json(inputs, "outreach_insights")
        except RuntimeError:
            log.warning("outreach insights missing — PDF without charts")

        charts = _collect_chart_images(inputs, insights)

        result: dict[str, Any] = {
            "status": "ok",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "website": website,
            "revenue": revenue,
            "investors": investors,
            "portfolioBenchmarks": portfolio,
            "partnerContacts": partners,
            "insights": insights,
            "charts": charts,
        }
        html = build_report_html(result)
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        label = _safe_slug(_product_label(website))
        pdf_path = work / f"{label}-outreach.pdf"
        html_path = work / f"{label}-outreach.html"
        html_path.write_text(html, encoding="utf-8")

        log.info("rendering PDF via Playwright path=%s charts=%s", pdf_path, len(charts))
        _html_to_pdf(html, pdf_path)
        bytes_len = pdf_path.stat().st_size
        log.info("PDF ready bytes=%s", bytes_len)

        step.assets.append(
            file_asset(
                pdf_path,
                media_type="application/pdf",
                metadata={
                    "kind": "outreach_pdf",
                    "bytes": bytes_len,
                    "html_path": str(html_path),
                    "charts_embedded": [c.get("id") for c in charts],
                    "findings": {
                        "website": website,
                        "revenue": revenue,
                        "investors": {
                            "investorSummary": investors.get("investorSummary"),
                            "exaResultCount": investors.get("exaResultCount"),
                        },
                        "portfolioBenchmarks": {
                            "portfolioRevenueSummary": portfolio.get(
                                "portfolioRevenueSummary"
                            ),
                        },
                        "partnerContacts": {
                            "contactSummary": partners.get("contactSummary"),
                            "contacts": partners.get("contacts"),
                        },
                    },
                },
            )
        )
        return step


def _collect_chart_images(
    inputs: list[Any], insights: dict[str, Any]
) -> list[dict[str, Any]]:
    titles = {cid: title for cid, _, title in CHART_SPECS}
    captions = {
        c.get("id"): c.get("caption")
        for c in (insights.get("charts") or [])
        if isinstance(c, dict)
    }
    by_id: dict[str, dict[str, Any]] = {}

    for asset in inputs or []:
        meta = dict(getattr(asset, "metadata", None) or {})
        kind = meta.get("kind")
        if kind not in CHART_KINDS:
            continue
        chart_id = str(meta.get("chart_id") or "")
        data_uri = _resolve_chart_data_uri(
            data_uri=meta.get("data_uri"),
            path=meta.get("local_path"),
            asset=asset,
        )
        if not chart_id or not data_uri:
            continue
        by_id[chart_id] = {
            "id": chart_id,
            "kind": kind,
            "title": meta.get("title") or titles.get(chart_id, chart_id),
            "caption": captions.get(chart_id) or "",
            "data_uri": data_uri,
        }

    for c in insights.get("charts") or []:
        if not c.get("ok"):
            continue
        chart_id = str(c.get("id") or "")
        if chart_id in by_id:
            continue
        data_uri = _resolve_chart_data_uri(
            data_uri=c.get("data_uri"),
            path=c.get("path"),
        )
        if not chart_id or not data_uri:
            continue
        by_id[chart_id] = {
            "id": chart_id,
            "kind": c.get("kind"),
            "title": c.get("title") or titles.get(chart_id, chart_id),
            "caption": c.get("caption") or "",
            "data_uri": data_uri,
        }

    order = [cid for cid, _, _ in CHART_SPECS]
    return [by_id[k] for k in order if k in by_id]


def _resolve_chart_data_uri(
    *,
    data_uri: Any = None,
    path: Any = None,
    asset: Any = None,
) -> str | None:
    import base64

    from founderblaze.outreach._assets import local_path

    if isinstance(data_uri, str) and data_uri.startswith("data:"):
        return data_uri
    candidates: list[Path] = []
    if path:
        candidates.append(Path(str(path)))
    if asset is not None:
        raw_url = getattr(asset, "url", None)
        url_s = str(getattr(raw_url, "url", None) or raw_url or "")
        lp = local_path(url_s)
        if lp is not None:
            candidates.append(lp)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        raw = candidate.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(candidate.suffix.lower(), "image/png")
        return f"data:{mime};base64,{b64}"
    return None


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


def _product_label(website: dict[str, Any]) -> str:
    summary = str(website.get("productSummary") or "")
    url = str(website.get("url") or "")
    for line in summary.splitlines():
        if ":" in line and "product" in line.lower():
            return line.split(":", 1)[-1].strip()[:48] or "company"
    try:
        host = urlparse(url).hostname or "company"
        return host.replace("www.", "").split(".")[0]
    except Exception:  # noqa: BLE001
        return "company"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-_]+", "-", value.lower()).strip("-")
    return (slug or "company")[:48]
