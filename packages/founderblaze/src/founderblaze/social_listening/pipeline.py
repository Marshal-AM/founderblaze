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
    finalize_chart_provenance,
    finalize_run_provenance,
    merge_provenance,
    pick_primary_local_path,
)
from founderblaze.social_listening.draft_provider import DraftComplianceProvider
from founderblaze.social_listening.insights_provider import VisualInsightsProvider
from founderblaze.social_listening.product_provider import ProductDiscoverProvider
from founderblaze.social_listening.report_provider import CompileReportProvider
from founderblaze.social_listening.threads_provider import ThreadDiscoverProvider

log = logging.getLogger("founderblaze.social_listening.pipeline")


def run_social_listening_pipeline(
    *,
    job_id: str,
    product_url: str,
    product_name: str | None = None,
    max_posts: int | None = None,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run the full social-listening Genblaze Pipeline + optional B2 sink."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    settings.require_social_listening_vendors()

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.tavily_api_key:
        os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)
    if settings.jina_api_key:
        os.environ.setdefault("JINA_API_KEY", settings.jina_api_key)

    work = tempfile.mkdtemp(prefix=f"social-{job_id[:8]}-")
    log.info(
        "social-listening work_dir=%s job_id=%s upload_to_b2=%s",
        work,
        job_id,
        upload_to_b2,
    )

    sink = (
        build_b2_sink(service="social-listening", settings=settings)
        if upload_to_b2
        else None
    )
    model = settings.gemini_text_model
    image_model = settings.gemini_image_model
    gemini = settings.gemini_api_key

    result = (
        Pipeline(
            "social-listening",
            tenant_id=job_id,
            project_id="social-listening",
        )
        .step(
            ProductDiscoverProvider(
                product_url=product_url,
                product_name=product_name,
                max_posts=max_posts,
                api_key=gemini,
                work_dir=work,
            ),
            model=model,
            modality=Modality.TEXT,
        )
        .step(
            ThreadDiscoverProvider(api_key=gemini, work_dir=work),
            model=model,
            modality=Modality.TEXT,
            input_from=[0],
        )
        .step(
            DraftComplianceProvider(api_key=gemini, work_dir=work),
            model=model,
            modality=Modality.TEXT,
            input_from=[0, 1],
        )
        .step(
            VisualInsightsProvider(
                api_key=gemini,
                work_dir=work,
                image_model=image_model,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[0, 1, 2],
        )
        .step(
            CompileReportProvider(work_dir=work),
            model="social-listening-report",
            modality=Modality.TEXT,
            input_from=[0, 2, 3],
        )
        .run(
            sink=sink,
            pipeline_timeout=2400,
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
    chart_artifacts = (
        finalize_chart_provenance(result, sink=sink, settings=settings, upload=True)
        if upload_to_b2 and sink is not None
        else []
    )

    thread_urls = _thread_urls_from_result(result)
    artifacts: list[dict[str, Any]] = [
        merge_provenance(
            {
                "type": "pdf_report",
                "url": url,
                "object_key": object_key,
                "mime_type": "application/pdf",
            },
            prov,
        ),
        *chart_artifacts,
    ]
    for turl in thread_urls:
        artifacts.append(
            {
                "type": "reddit_thread",
                "url": turl,
                "mime_type": "text/uri-list",
            }
        )

    log.info(
        "social-listening completed job_id=%s run_id=%s object_key=%s threads=%s verified=%s",
        job_id,
        result.run.run_id,
        object_key,
        len(thread_urls),
        prov.get("provenance_verified"),
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "artifacts": artifacts,
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": result.run.run_id,
        "work_dir": work,
        "upload_to_b2": upload_to_b2,
        "recommendations_count": len(thread_urls),
        "pdf_url": url,
        "object_key": object_key,
        "provenance": prov,
    }


def _thread_urls_from_result(result: Any) -> list[str]:
    run = getattr(result, "run", result)
    for step in reversed(getattr(run, "steps", []) or []):
        for asset in getattr(step, "assets", None) or []:
            meta = getattr(asset, "metadata", None) or {}
            if not isinstance(meta, dict):
                continue
            if meta.get("kind") == "social_listening_pdf":
                urls = meta.get("thread_urls") or []
                return [str(u) for u in urls if u]
            if meta.get("kind") == "social_listening_recommendations":
                data = meta.get("json") or {}
                return [
                    str(r.get("targetPermalink"))
                    for r in (data.get("recommendations") or [])
                    if r.get("targetPermalink")
                ]
    return []
