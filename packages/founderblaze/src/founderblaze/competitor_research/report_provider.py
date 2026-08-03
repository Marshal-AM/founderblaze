from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import file_asset, find_input_json, local_path
from founderblaze.competitor_research.insights_provider import CHART_KINDS, CHART_SPECS
from founderblaze.competitor_research.report_html import build_report_html

log = logging.getLogger("founderblaze.competitor_research.report")


class CompileReportProvider(SyncProvider):
    """HTML template + insight charts → Playwright PDF → competitor_research_pdf asset."""

    name = "competitor-research-report"

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
        payload = find_input_json(inputs, "positioning")
        product_name = str(payload.get("product_name") or "product")

        insights: dict[str, Any] = {}
        try:
            insights = find_input_json(inputs, "competitor_research_insights")
        except RuntimeError:
            log.warning("competitor insights missing — PDF without charts")

        charts = _collect_chart_images(inputs, insights)
        data: dict[str, Any] = {
            "product_name": product_name,
            "product_url": payload.get("product_url"),
            "competitors": payload.get("competitors") or [],
            "feature_diff": payload.get("feature_diff") or {},
            "pricing": payload.get("pricing") or {},
            "positioning": payload.get("positioning") or {},
            "insights": insights,
            "charts": charts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        html = build_report_html(data)
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        label = _safe_slug(product_name)
        pdf_path = work / f"{label}-competitors.pdf"
        html_path = work / f"{label}-competitors.html"
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
                    "kind": "competitor_research_pdf",
                    "bytes": bytes_len,
                    "html_path": str(html_path),
                    "product_name": product_name,
                    "charts_embedded": [c.get("id") for c in charts],
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
        uri = _file_to_data_uri(candidate)
        if uri:
            return uri
    return None


def _file_to_data_uri(path: Path | None) -> str | None:
    import base64

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


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-_]+", "-", name.lower()).strip("-")
    return slug or "report"
