from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Callable

from genblaze_core import Modality, Pipeline

from founderblaze.core.config import Settings, get_settings
from founderblaze.core.storage.b2 import (
    build_b2_sink,
    pick_final_pdf_asset,
    resolve_download_url,
)
from founderblaze.core.storage.provenance import (
    finalize_run_provenance,
    merge_provenance,
    pick_primary_local_path,
)
from founderblaze.outreach.enrich_provider import ContactEnrichProvider
from founderblaze.outreach.insights_provider import VisualInsightsProvider
from founderblaze.outreach.investor_provider import InvestorFinderProvider
from founderblaze.outreach.partners_provider import PartnerContactsProvider
from founderblaze.outreach.portfolio_provider import PortfolioBenchmarkProvider
from founderblaze.outreach.report_provider import CompileReportProvider
from founderblaze.outreach.revenue_provider import RevenueAnalyzeProvider
from founderblaze.outreach.sheet_download_provider import SheetDownloadProvider
from founderblaze.outreach.website_provider import WebsiteAnalyzeProvider

log = logging.getLogger("founderblaze.outreach.pipeline")


def run_outreach_pipeline(
    *,
    job_id: str,
    website_url: str,
    sheet_url: str | None = None,
    sheet_path: str | None = None,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run the full outreach Genblaze Pipeline as one DAG + optional B2 sink."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    settings.require_outreach_vendors()

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    exa_key = settings.resolved_exa_api_key
    if exa_key:
        os.environ.setdefault("EXA_API_KEY", exa_key)
        os.environ.setdefault("EXA_SEARCH_API_KEY", exa_key)

    work = tempfile.mkdtemp(prefix=f"outreach-{job_id[:8]}-")
    log.info(
        "outreach work_dir=%s job_id=%s upload_to_b2=%s",
        work,
        job_id,
        upload_to_b2,
    )

    sink = (
        build_b2_sink(service="outreach", settings=settings) if upload_to_b2 else None
    )
    model = settings.gemini_text_model
    image_model = settings.gemini_image_model
    gemini = settings.gemini_api_key

    result = (
        Pipeline(
            "outreach",
            tenant_id=job_id,
            project_id="outreach",
        )
        .step(
            SheetDownloadProvider(
                sheet_url=sheet_url,
                sheet_path=sheet_path,
                work_dir=work,
            ),
            model="outreach-sheet",
            modality=Modality.TEXT,
        )
        .step(
            WebsiteAnalyzeProvider(
                website_url=website_url,
                api_key=gemini,
                exa_api_key=exa_key,
                work_dir=work,
            ),
            model=model,
            modality=Modality.TEXT,
        )
        .step(
            RevenueAnalyzeProvider(api_key=gemini, work_dir=work),
            model=model,
            modality=Modality.TEXT,
            input_from=[0],
        )
        .step(
            InvestorFinderProvider(
                api_key=gemini, exa_api_key=exa_key, work_dir=work
            ),
            model=model,
            modality=Modality.TEXT,
            input_from=[1, 2],
        )
        .step(
            PortfolioBenchmarkProvider(
                api_key=gemini, exa_api_key=exa_key, work_dir=work
            ),
            model=model,
            modality=Modality.TEXT,
            input_from=[1, 2, 3],
        )
        .step(
            PartnerContactsProvider(
                api_key=gemini, exa_api_key=exa_key, work_dir=work
            ),
            model=model,
            modality=Modality.TEXT,
            input_from=[1, 3],
        )
        .step(
            ContactEnrichProvider(exa_api_key=exa_key, work_dir=work),
            model="outreach-enrich",
            modality=Modality.TEXT,
            input_from=[5],
        )
        .step(
            VisualInsightsProvider(
                api_key=gemini,
                work_dir=work,
                image_model=image_model,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[1, 2, 3, 4, 6],
        )
        .step(
            CompileReportProvider(work_dir=work),
            model="outreach-report",
            modality=Modality.TEXT,
            input_from=[1, 2, 3, 4, 6, 7],
        )
        .run(
            sink=sink,
            pipeline_timeout=3600,
            on_step_complete=on_step_complete,
            raise_on_failure=True,
        )
    )

    url, object_key = pick_final_pdf_asset(result)
    if upload_to_b2 and object_key:
        url = resolve_download_url(object_key, settings=settings)

    local_pdf = pick_primary_local_path(result, kind="pdf")
    prov = finalize_run_provenance(
        result,
        sink=sink,
        primary_local_path=local_pdf,
        object_key=object_key,
        settings=settings,
        mode="sidecar",
        upload_sidecar=upload_to_b2,
    )
    primary = merge_provenance(
        {
            "type": "pdf_report",
            "url": url,
            "object_key": object_key,
            "mime_type": "application/pdf",
        },
        prov,
    )
    log.info(
        "outreach completed job_id=%s run_id=%s object_key=%s url=%s verified=%s",
        job_id,
        result.run.run_id,
        object_key,
        url,
        prov.get("provenance_verified"),
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "artifacts": [primary],
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": result.run.run_id,
        "work_dir": work,
        "upload_to_b2": upload_to_b2,
        "pdf_url": url,
        "object_key": object_key,
        "provenance": prov,
    }
