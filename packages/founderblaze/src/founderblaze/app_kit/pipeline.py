from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Callable

from genblaze_core import Modality, Pipeline

from founderblaze.app_kit.brand_context_provider import BrandContextProvider
from founderblaze.app_kit.plan_provider import PlanScreensProvider
from founderblaze.app_kit.screens_provider import ScreensProvider
from founderblaze.app_kit.zip_provider import ZipProvider
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

log = logging.getLogger("founderblaze.app_kit.pipeline")


def run_app_kit_pipeline(
    *,
    job_id: str,
    product_name: str,
    product_idea: str,
    brand_kit_url: str | None = None,
    on_step_complete: Callable[[Any], None] | None = None,
    settings: Settings | None = None,
    upload_to_b2: bool = True,
) -> dict[str, Any]:
    """Run the app-kit Genblaze Pipeline (plan → brand → screens → zip → B2)."""
    settings = settings or get_settings()
    if upload_to_b2:
        settings.require_b2()
    if not (settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")):
        raise RuntimeError("GEMINI_API_KEY is required for app-kit")

    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

    work = tempfile.mkdtemp(prefix=f"app-kit-{job_id[:8]}-")
    log.info(
        "app-kit work_dir=%s job_id=%s upload_to_b2=%s brand_kit=%s",
        work,
        job_id,
        upload_to_b2,
        bool(brand_kit_url),
    )

    sink = build_b2_sink(service="app-kit", settings=settings) if upload_to_b2 else None
    text_model = settings.gemini_text_model
    image_model = settings.gemini_image_model

    result = (
        Pipeline(
            "app-kit",
            tenant_id=job_id,
            project_id="app-kit",
        )
        .step(
            PlanScreensProvider(
                product_name=product_name,
                product_idea=product_idea,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            prompt=product_idea,
            modality=Modality.TEXT,
        )
        .step(
            BrandContextProvider(
                product_name=product_name,
                product_idea=product_idea,
                brand_kit_url=brand_kit_url,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=text_model,
            modality=Modality.TEXT,
            input_from=[0],
        )
        .step(
            ScreensProvider(
                product_name=product_name,
                product_idea=product_idea,
                api_key=settings.gemini_api_key,
                work_dir=work,
            ),
            model=image_model,
            modality=Modality.IMAGE,
            input_from=[0, 1],
        )
        .step(
            ZipProvider(
                product_name=product_name,
                product_idea=product_idea,
                work_dir=work,
            ),
            model="app-kit-zip",
            modality=Modality.TEXT,
            input_from=[0, 1, 2],
        )
        .run(
            sink=sink,
            pipeline_timeout=2400,
            on_step_complete=on_step_complete,
        )
    )

    if getattr(result.run, "status", None) == "failed":
        err = _first_step_error(result) or "app-kit pipeline failed"
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
            "type": "app_kit_zip",
            "url": url,
            "object_key": object_key,
            "mime_type": "application/zip",
        },
        prov,
    )
    log.info(
        "app-kit completed job_id=%s run_id=%s object_key=%s url=%s verified=%s",
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
        "product_name": product_name,
        "mock_count": (meta or {}).get("mock_count"),
        "screen_count": (meta or {}).get("screen_count"),
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
                or meta.get("kind") == "app_kit_zip"
                or str(url).endswith(".zip")
                or ".zip?" in str(url)
            ):
                key = meta.get("object_key")
                if not key:
                    key = getattr(raw_url, "key", None) or object_key_from_asset_url(
                        str(url)
                    )
                return str(url), str(key) if key else None, meta
    raise RuntimeError("No app_kit_zip asset found in Genblaze pipeline result")


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
