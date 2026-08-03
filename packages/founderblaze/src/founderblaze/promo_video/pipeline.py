from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from genblaze_core import Modality, Pipeline

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
from founderblaze.promo_video.emit_provider import EmitFinalVideoProvider
from founderblaze.promo_video.research_provider import ProductResearchProvider
from founderblaze.promo_video.script_provider import ScriptProvider
from founderblaze.promo_video.seedance_provider import SeedanceProvider

log = logging.getLogger("founderblaze.promo_video.pipeline")

# Seedance 2.0 durations (match TS PromoVideoDurationSchema)
_VALID_DURATIONS = frozenset({4, 5, 6, 8, 10, 12, 15})
_VALID_RESOLUTIONS = frozenset({"480p", "720p", "1080p", "4k"})


def run_promo_video_pipeline(
    *,
    job_id: str,
    product_url: str,
    duration: int = 8,
    resolution: str = "720p",
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run promo-video Genblaze Pipeline: research → script → Seedance → B2."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    settings.require_promo_video_vendors()

    duration_i = int(duration)
    if duration_i not in _VALID_DURATIONS:
        raise ValueError(f"duration must be one of {sorted(_VALID_DURATIONS)}")
    resolution_s = (resolution or "720p").strip().lower()
    if resolution_s not in _VALID_RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(_VALID_RESOLUTIONS)}")

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.segmind_api_key:
        os.environ["SEGMIND_API_KEY"] = settings.segmind_api_key

    work = tempfile.mkdtemp(prefix=f"promo-{job_id[:8]}-")
    log.info(
        "promo-video work_dir=%s job_id=%s duration=%ss resolution=%s upload_to_b2=%s",
        work,
        job_id,
        duration_i,
        resolution_s,
        upload_to_b2,
    )

    model = settings.gemini_text_model
    gemini = settings.gemini_api_key
    segmind = settings.segmind_api_key

    sink = (
        build_b2_sink(service="promo-video", settings=settings)
        if upload_to_b2
        else None
    )

    # Genblaze DAG: research → script → Seedance (local MP4). B2 via emit
    # follow-up so we only upload the final file:// asset.
    Pipeline(
        "promo-video",
        tenant_id=job_id,
        project_id="promo-video",
    ).step(
        ProductResearchProvider(
            product_url=product_url,
            api_key=gemini,
            work_dir=work,
        ),
        model=model,
        modality=Modality.TEXT,
    ).step(
        ScriptProvider(
            product_url=product_url,
            duration=duration_i,
            resolution=resolution_s,
            api_key=gemini,
            work_dir=work,
        ),
        model=model,
        modality=Modality.TEXT,
        input_from=[0],
    ).step(
        SeedanceProvider(
            duration=duration_i,
            resolution=resolution_s,
            api_key=segmind,
            work_dir=work,
        ),
        model="segmind-seedance-2.0",
        modality=Modality.VIDEO,
        input_from=[1],
    ).run(
        timeout=float("inf"),
        on_step_complete=on_step_complete,
        raise_on_failure=True,
        max_retries=0,
    )

    if upload_to_b2 and sink is not None:
        result = (
            Pipeline(
                "promo-video-upload",
                tenant_id=job_id,
                project_id="promo-video",
            )
            .step(
                EmitFinalVideoProvider(work_dir=work),
                model="promo-video-emit",
                modality=Modality.VIDEO,
            )
            .run(
                sink=sink,
                on_step_complete=on_step_complete,
                raise_on_failure=True,
            )
        )
    else:
        result = (
            Pipeline(
                "promo-video-local",
                tenant_id=job_id,
                project_id="promo-video",
            )
            .step(
                EmitFinalVideoProvider(work_dir=work),
                model="promo-video-emit",
                modality=Modality.VIDEO,
            )
            .run(
                on_step_complete=on_step_complete,
                raise_on_failure=True,
            )
        )

    url, object_key = pick_final_video_asset(result)
    if upload_to_b2 and object_key:
        url = resolve_download_url(object_key, settings=settings)

    concept = None
    script_path = Path(work) / "script.json"
    if script_path.is_file():
        try:
            raw = json.loads(script_path.read_text(encoding="utf-8")).get("concept")
            concept = str(raw).strip() if raw else None
        except Exception:  # noqa: BLE001
            concept = None

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
        "promo-video completed job_id=%s run_id=%s object_key=%s concept=%s verified=%s",
        job_id,
        result.run.run_id,
        object_key,
        (concept or "")[:80],
        prov.get("provenance_verified"),
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "artifacts": [primary],
        "concept": concept,
        "duration_seconds": duration_i,
        "resolution": resolution_s,
        "cost_breakdown": [
            {"vendor": "gemini", "operation": "research", "amount_usd": 0.02},
            {"vendor": "gemini", "operation": "script", "amount_usd": 0.02},
            {"vendor": "segmind", "operation": "seedance", "amount_usd": 0.40},
        ],
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": result.run.run_id,
        "work_dir": work,
        "upload_to_b2": upload_to_b2,
        "provenance": prov,
    }
