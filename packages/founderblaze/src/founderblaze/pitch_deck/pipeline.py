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
from founderblaze.pitch_deck.design_provider import DesignLanguageProvider
from founderblaze.pitch_deck.pdf_provider import PdfCompileProvider
from founderblaze.pitch_deck.plan_provider import PlanDeckProvider
from founderblaze.pitch_deck.research_provider import ProductResearchProvider
from founderblaze.pitch_deck.slides_provider import SlidesProvider

log = logging.getLogger("founderblaze.pitch_deck.pipeline")


def run_pitch_deck_pipeline(
    *,
    job_id: str,
    product_url: str,
    funding_ask: str,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run pitch-deck Genblaze Pipeline (research → design → plan → slides → PDF → B2)."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    if not (settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")):
        raise RuntimeError("GEMINI_API_KEY is required for pitch-deck")

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    url = (product_url or "").strip()
    ask = (funding_ask or "").strip()
    if not url:
        raise RuntimeError("product_url is required")
    if not ask:
        raise RuntimeError("funding_ask is required")

    work = tempfile.mkdtemp(prefix=f"pitch-deck-{job_id[:8]}-")
    log.info(
        "pitch-deck work_dir=%s job_id=%s upload_to_b2=%s url=%s",
        work,
        job_id,
        upload_to_b2,
        url,
    )

    sink = build_b2_sink(service="pitch-deck", settings=settings) if upload_to_b2 else None
    text_model = settings.gemini_text_model
    image_model = settings.gemini_image_model

    result = (
        Pipeline(
            "pitch-deck",
            tenant_id=job_id,
            project_id="pitch-deck",
        )
        .step(
            ProductResearchProvider(
                product_url=url,
                funding_ask=ask,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            prompt=url,
            modality=Modality.TEXT,
        )
        .step(
            DesignLanguageProvider(
                product_url=url,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            modality=Modality.TEXT,
            input_from=[0],
        )
        .step(
            PlanDeckProvider(
                product_url=url,
                funding_ask=ask,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            modality=Modality.TEXT,
            input_from=[0, 1],
        )
        .step(
            SlidesProvider(
                product_url=url,
                funding_ask=ask,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[0, 1, 2],
        )
        .step(
            PdfCompileProvider(work_dir=work),
            model="pitch-deck-pdf",
            modality=Modality.TEXT,
            input_from=[2, 3],
        )
        .run(
            sink=sink,
            pipeline_timeout=2400,
            on_step_complete=on_step_complete,
        )
    )

    if getattr(result.run, "status", None) == "failed":
        err = _first_step_error(result) or "pitch-deck pipeline failed"
        raise RuntimeError(err)

    url_out, object_key = pick_final_pdf_asset(result)
    meta = _pdf_meta(result)
    if upload_to_b2 and object_key:
        url_out = resolve_download_url(object_key, settings=settings)

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
            "type": "pitch_deck_pdf",
            "url": url_out,
            "object_key": object_key,
            "mime_type": "application/pdf",
        },
        prov,
    )
    log.info(
        "pitch-deck completed job_id=%s run_id=%s object_key=%s url=%s pages=%s",
        job_id,
        result.run.run_id,
        object_key,
        url_out,
        meta.get("page_count"),
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "artifacts": [primary],
        "product_url": url,
        "funding_ask": ask,
        "page_count": meta.get("page_count"),
        "product_name": meta.get("product_name"),
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": result.run.run_id,
        "work_dir": work,
        "upload_to_b2": upload_to_b2,
        "provenance": prov,
    }


def _pdf_meta(result: Any) -> dict[str, Any]:
    run = getattr(result, "run", result)
    for step in reversed(getattr(run, "steps", []) or []):
        for asset in getattr(step, "assets", None) or []:
            meta = dict(getattr(asset, "metadata", None) or {})
            if meta.get("kind") == "pitch_deck_pdf":
                return meta
        sm = dict(getattr(step, "metadata", None) or {})
        if sm.get("page_count"):
            return sm
    return {}


def pick_final_pitch_pdf_asset(result: Any) -> tuple[str, str | None, dict[str, Any]]:
    """Local helper if needed; prefer shared pick_final_pdf_asset + metadata."""
    url, key = pick_final_pdf_asset(result)
    return url, key, _pdf_meta(result)


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
