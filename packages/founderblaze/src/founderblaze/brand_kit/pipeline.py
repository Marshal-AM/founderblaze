from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Callable

from genblaze_core import Modality, Pipeline

from founderblaze.brand_kit.analyze_provider import AnalyzeProvider
from founderblaze.brand_kit.banner_provider import BannerProvider
from founderblaze.brand_kit.fonts_provider import FontsProvider
from founderblaze.brand_kit.icons_provider import IconsProvider
from founderblaze.brand_kit.logo_provider import LogoConceptsProvider
from founderblaze.brand_kit.palette_provider import PaletteProvider
from founderblaze.brand_kit.visuals_provider import VisualsProvider
from founderblaze.brand_kit.zip_provider import ZipProvider
from founderblaze.core.config import Settings, get_settings
from founderblaze.core.storage.b2 import (
    build_b2_sink,
    object_key_from_asset_url,
    resolve_download_url,
)
from founderblaze.core.storage.provenance import (
    finalize_run_provenance,
    merge_provenance,
    pick_primary_local_path,
)

log = logging.getLogger("founderblaze.brand_kit.pipeline")


def run_brand_kit_pipeline(
    *,
    job_id: str,
    brand_name: str,
    description: str,
    pick: int = 0,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run the full brand-kit Genblaze Pipeline (single DAG + optional B2 sink)."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    settings.require_brand_kit_vendors()

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    work = tempfile.mkdtemp(prefix=f"brand-kit-{job_id[:8]}-")
    log.info(
        "brand-kit work_dir=%s job_id=%s upload_to_b2=%s",
        work,
        job_id,
        upload_to_b2,
    )

    sink = (
        build_b2_sink(service="brand-kit", settings=settings) if upload_to_b2 else None
    )
    text_model = settings.gemini_text_model
    image_model = settings.gemini_image_model

    result = (
        Pipeline(
            "brand-kit",
            tenant_id=job_id,
            project_id="brand-kit",
        )
        .step(
            AnalyzeProvider(
                brand_name=brand_name,
                concept_count=3,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            prompt=description,
            modality=Modality.TEXT,
        )
        .step(
            LogoConceptsProvider(
                brand_name=brand_name,
                description=description,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[0],
        )
        .step(
            PaletteProvider(pick=pick, work_dir=work),
            model="brand-kit-palette",
            modality=Modality.TEXT,
            input_from=[1],
        )
        .step(
            FontsProvider(work_dir=work),
            model="brand-kit-fonts",
            modality=Modality.TEXT,
            input_from=[0],
        )
        .step(
            VisualsProvider(brand_name=brand_name, work_dir=work),
            model="brand-kit-visuals",
            modality=Modality.IMAGE,
            input_from=[2, 3],
        )
        .step(
            IconsProvider(pick=pick, work_dir=work),
            model="brand-kit-icons",
            modality=Modality.IMAGE,
            input_from=[1],
        )
        .step(
            BannerProvider(
                brand_name=brand_name,
                description=description,
                pick=pick,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[1, 2],
        )
        .step(
            ZipProvider(
                brand_name=brand_name,
                description=description,
                work_dir=work,
            ),
            model="brand-kit-zip",
            modality=Modality.TEXT,
            input_from=[1, 2, 3, 4, 5, 6],
        )
        .run(
            sink=sink,
            pipeline_timeout=1800,
            on_step_complete=on_step_complete,
        )
    )

    if getattr(result.run, "status", None) == "failed":
        err = _first_step_error(result) or "brand-kit pipeline failed"
        raise RuntimeError(err)

    url, object_key, meta = pick_final_zip_asset(result)
    if upload_to_b2 and object_key:
        url = resolve_download_url(object_key, settings=settings)

    local_zip = pick_primary_local_path(result, kind="zip")
    prov = finalize_run_provenance(
        result,
        sink=sink,
        primary_local_path=local_zip,
        object_key=object_key,
        settings=settings,
        mode="sidecar",
        upload_sidecar=upload_to_b2,
    )
    primary = merge_provenance(
        {
            "type": "brand_kit_zip",
            "url": url,
            "object_key": object_key,
            "mime_type": "application/zip",
        },
        prov,
    )
    log.info(
        "brand-kit completed job_id=%s run_id=%s object_key=%s url=%s verified=%s",
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
        "brand_name": brand_name,
        "chosen_concept": (meta or {}).get("chosen_concept"),
        "palette": (meta or {}).get("palette") or {},
        "typography": (meta or {}).get("typography") or {},
        "manifest_hash": prov.get("canonical_hash"),
        "run_id": result.run.run_id,
        "work_dir": work,
        "upload_to_b2": upload_to_b2,
        "provenance": prov,
    }


def pick_final_zip_asset(result: Any) -> tuple[str, str | None, dict[str, Any]]:
    run = getattr(result, "run", result)
    steps = getattr(run, "steps", []) or []
    for step in reversed(steps):
        for asset in getattr(step, "assets", None) or []:
            media = getattr(asset, "media_type", "") or ""
            raw_url = getattr(asset, "url", None) or ""
            url = getattr(raw_url, "url", None) or str(raw_url or "")
            meta = dict(getattr(asset, "metadata", None) or {})
            if (
                media == "application/zip"
                or meta.get("kind") == "brand_kit_zip"
                or str(url).endswith(".zip")
                or ".zip?" in str(url)
            ):
                key = meta.get("object_key")
                if not key:
                    key = getattr(raw_url, "key", None) or object_key_from_asset_url(
                        str(url)
                    )
                return str(url), str(key) if key else None, meta
    raise RuntimeError("No brand_kit_zip asset found in Genblaze pipeline result")


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
