from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Callable

from genblaze_core import Modality, Pipeline

from founderblaze.competitor_research.evidence_provider import GatherEvidenceProvider
from founderblaze.competitor_research.features_provider import DiffFeaturesProvider
from founderblaze.competitor_research.find_competitors_provider import (
    FindCompetitorsProvider,
)
from founderblaze.competitor_research.insights_provider import VisualInsightsProvider
from founderblaze.competitor_research.positioning_provider import BuildPositioningProvider
from founderblaze.competitor_research.pricing_provider import ScrapePricingProvider
from founderblaze.competitor_research.report_provider import CompileReportProvider
from founderblaze.core.config import Settings, get_settings
from founderblaze.core.storage.b2 import (
    build_b2_sink,
    pick_final_pdf_asset,
    resolve_download_url,
)
from founderblaze.core.storage.provenance import (
    finalize_chart_provenance,
    finalize_run_provenance,
    merge_provenance,
    pick_primary_local_path,
)

log = logging.getLogger("founderblaze.competitor_research.pipeline")


def run_competitor_research_pipeline(
    *,
    job_id: str,
    product_name: str,
    product_url: str | None = None,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run competitor-research Genblaze Pipeline and upload the PDF to B2 only."""
    settings = settings or get_settings()
    settings.require_b2()
    settings.require_competitor_research_vendors()

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.jina_api_key:
        os.environ.setdefault("JINA_API_KEY", settings.jina_api_key)
    if settings.serper_api_key:
        os.environ.setdefault("SERPER_API_KEY", settings.serper_api_key)
    if settings.brave_search_api_key:
        os.environ.setdefault("BRAVE_SEARCH_API_KEY", settings.brave_search_api_key)

    work = tempfile.mkdtemp(prefix=f"competitor-{job_id[:8]}-")
    log.info("competitor-research work_dir=%s job_id=%s", work, job_id)

    sink = build_b2_sink(service="competitor-research", settings=settings)
    model = settings.gemini_text_model
    gemini = settings.gemini_api_key
    image_model = (
        getattr(settings, "gemini_image_model", None)
        or os.environ.get("GEMINI_IMAGE_MODEL")
        or "gemini-2.5-flash-image"
    )

    url: str | None = None
    object_key: str | None = None
    prov: dict[str, Any] = {}
    chart_artifacts: list[dict[str, Any]] = []

    try:
        result = (
            Pipeline(
                "competitor-research",
                tenant_id=job_id,
                project_id="competitor-research",
            )
            .step(
                FindCompetitorsProvider(
                    product_name=product_name,
                    product_url=product_url,
                    api_key=gemini,
                    work_dir=work,
                ),
                model=model,
                modality=Modality.TEXT,
            )
            .step(
                GatherEvidenceProvider(work_dir=work),
                model="competitor-research-evidence",
                modality=Modality.TEXT,
                input_from=[0],
            )
            .step(
                DiffFeaturesProvider(api_key=gemini, work_dir=work),
                model=model,
                modality=Modality.TEXT,
                input_from=[0, 1],
            )
            .step(
                ScrapePricingProvider(api_key=gemini, work_dir=work),
                model=model,
                modality=Modality.TEXT,
                input_from=[0, 1],
            )
            .step(
                BuildPositioningProvider(api_key=gemini, work_dir=work),
                model=model,
                modality=Modality.TEXT,
                input_from=[2, 3],
            )
            .step(
                VisualInsightsProvider(
                    api_key=gemini,
                    work_dir=work,
                    image_model=image_model,
                ),
                model=image_model,
                modality=Modality.IMAGE,
                input_from=[1, 4],
            )
            .step(
                CompileReportProvider(work_dir=work),
                model="competitor-research-report",
                modality=Modality.TEXT,
                input_from=[4, 5],
            )
            .run(
                sink=sink,
                pipeline_timeout=3600,
                on_step_complete=on_step_complete,
                raise_on_failure=True,
            )
        )

        url, object_key = pick_final_pdf_asset(result)
        if not object_key:
            raise RuntimeError("B2 upload did not produce an object_key for the PDF")
        url = resolve_download_url(object_key, settings=settings)

        # Provenance must run before work_dir cleanup (PDF + chart files).
        local_pdf = pick_primary_local_path(result, kind="pdf")
        prov = finalize_run_provenance(
            result,
            sink=sink,
            primary_local_path=local_pdf,
            object_key=object_key,
            settings=settings,
            mode="sidecar",
        )
        chart_artifacts = finalize_chart_provenance(
            result, sink=sink, settings=settings, upload=True
        )
    finally:
        # Scratch PDF/JSON are ephemeral — deliverable lives only on B2.
        shutil.rmtree(work, ignore_errors=True)
        log.info("cleaned local work_dir=%s", work)

    primary = merge_provenance(
        {
            "type": "report_pdf",
            "url": url,
            "object_key": object_key,
            "mime_type": "application/pdf",
        },
        prov,
    )
    return {
        "job_id": job_id,
        "product_name": product_name,
        "product_url": product_url,
        "artifacts": [primary, *chart_artifacts],
        "pdf_url": url,
        "object_key": object_key,
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": prov.get("run_id"),
        "provenance": prov,
    }
