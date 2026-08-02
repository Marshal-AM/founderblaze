from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Callable

from genblaze_core import Modality, Pipeline, StepType

from founderblaze.apd.assemble_provider import AssembleProvider
from founderblaze.apd.plan_provider import PlanProvider
from founderblaze.apd.record_provider import RecordProvider
from founderblaze.core.config import Settings, get_settings
from founderblaze.core.storage.b2 import (
    build_b2_sink,
    pick_final_video_asset,
    resolve_download_url,
)
from founderblaze.core.storage.provenance import (
    finalize_run_provenance,
    merge_provenance,
    pick_primary_local_path,
)

log = logging.getLogger("founderblaze.apd.pipeline")


def run_apd_pipeline(
    *,
    job_id: str,
    website_url: str,
    script: str,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run the full APD Genblaze Pipeline as one DAG.

    Plan → Record → Assemble → ObjectStorageSink (B2).

    When ``upload_to_b2`` is False, skips ObjectStorageSink and returns a
    local ``file://`` video URL (smoke / offline artifact check).
    """
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    settings.require_apd_vendors()

    from founderblaze.apd.ffmpeg_util import resolve_ffmpeg

    resolve_ffmpeg()

    if settings.lmnt_api_key:
        os.environ["LMNT_API_KEY"] = settings.lmnt_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.firecrawl_api_key:
        os.environ["FIRECRAWL_API_KEY"] = settings.firecrawl_api_key

    work = tempfile.mkdtemp(prefix=f"apd-{job_id[:8]}-")
    log.info(
        "apd work_dir=%s job_id=%s upload_to_b2=%s",
        work,
        job_id,
        upload_to_b2,
    )

    sink = (
        build_b2_sink(service="automated-product-demo", settings=settings)
        if upload_to_b2
        else None
    )

    result = (
        Pipeline(
            "apd",
            tenant_id=job_id,
            project_id="automated-product-demo",
        )
        .step(
            PlanProvider(
                website_url=website_url,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=settings.gemini_text_model,
            prompt=script,
            modality=Modality.TEXT,
        )
        .step(
            RecordProvider(
                website_url=website_url,
                api_key=settings.firecrawl_api_key,
                work_dir=work,
            ),
            model="firecrawl-record",
            modality=Modality.VIDEO,
            input_from=[0],
        )
        .step(
            AssembleProvider(
                api_key=settings.lmnt_api_key or None,
                voice=settings.lmnt_voice,
            ),
            model="apd-assemble",
            modality=Modality.VIDEO,
            step_type=StepType.MIX,
            input_from=[1],
        )
        .run(
            sink=sink,
            pipeline_timeout=1800,
            on_step_complete=on_step_complete,
        )
    )
    if getattr(result.run, "status", None) == "failed":
        err = _first_step_error(result) or "apd pipeline failed"
        raise RuntimeError(err)

    url, object_key = pick_final_video_asset(result)
    if upload_to_b2 and object_key:
        url = resolve_download_url(object_key, settings=settings)

    local_video = pick_primary_local_path(result, kind="video")
    prov = finalize_run_provenance(
        result,
        sink=sink,
        primary_local_path=local_video,
        object_key=object_key,
        settings=settings,
        mode="pointer",
        upload_sidecar=upload_to_b2,
    )
    primary = merge_provenance(
        {
            "type": "video",
            "url": url,
            "object_key": object_key,
            "mime_type": "video/mp4",
        },
        prov,
    )
    log.info(
        "apd completed job_id=%s run_id=%s object_key=%s url=%s verified=%s",
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
        "provenance": prov,
    }


def _first_step_error(result: Any) -> str | None:
    run = getattr(result, "run", result)
    for step in getattr(run, "steps", []) or []:
        err = getattr(step, "error", None)
        if err:
            return str(err)
        status = getattr(step, "status", None)
        if str(status).lower() in {"failed", "error"}:
            return f"step failed: {getattr(step, 'provider', step)}"
    return None
