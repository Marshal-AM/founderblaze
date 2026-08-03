from __future__ import annotations

import asyncio
import logging
from typing import Any

from temporalio import activity

from founderblaze.apd import run_apd_pipeline
from founderblaze.app_kit import run_app_kit_pipeline
from founderblaze.brand_kit import run_brand_kit_pipeline
from founderblaze.core.config import get_settings
from founderblaze.core.jobs.store import get_job_store
from founderblaze.core.schemas.models import Artifact, JobStatus
from founderblaze.core.temporal_bridge import make_on_step_complete
from founderblaze.outreach import run_outreach_pipeline
from founderblaze.competitor_research import run_competitor_research_pipeline
from founderblaze.pitch_deck import run_pitch_deck_pipeline
from founderblaze.promo_video import run_promo_video_pipeline
from founderblaze.social_listening import run_social_listening_pipeline

log = logging.getLogger("founderblaze.worker")


@activity.defn(name="run_apd_activity")
async def run_apd_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    website_url = str(job.input.get("website_url") or "")
    script = str(job.input.get("script") or "")
    if not website_url or not script:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing website_url or script"
        )
        raise RuntimeError("invalid APD input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_apd_pipeline,
            job_id=job_id,
            website_url=website_url,
            script=script,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("apd pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_brand_kit_activity")
async def run_brand_kit_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    brand_name = str(job.input.get("brand_name") or "").strip()
    description = str(job.input.get("description") or "").strip()
    try:
        pick = int(job.input.get("pick") or 0)
    except (TypeError, ValueError):
        pick = 0
    if not brand_name or not description:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing brand_name or description"
        )
        raise RuntimeError("invalid brand-kit input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_brand_kit_pipeline,
            job_id=job_id,
            brand_name=brand_name,
            description=description,
            pick=pick,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("brand-kit pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_app_kit_activity")
async def run_app_kit_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    product_name = str(job.input.get("product_name") or "").strip()
    product_idea = str(job.input.get("product_idea") or "").strip()
    brand_kit_url = job.input.get("brand_kit_url")
    brand_kit_url_s = str(brand_kit_url).strip() if brand_kit_url else None
    if not product_name or not product_idea:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing product_name or product_idea"
        )
        raise RuntimeError("invalid app-kit input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_app_kit_pipeline,
            job_id=job_id,
            product_name=product_name,
            product_idea=product_idea,
            brand_kit_url=brand_kit_url_s,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("app-kit pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_pitch_deck_activity")
async def run_pitch_deck_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    product_url = str(job.input.get("product_url") or "").strip()
    funding_ask = str(job.input.get("funding_ask") or "").strip()
    if not product_url or not funding_ask:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing product_url or funding_ask"
        )
        raise RuntimeError("invalid pitch-deck input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_pitch_deck_pipeline,
            job_id=job_id,
            product_url=product_url,
            funding_ask=funding_ask,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("pitch-deck pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_outreach_activity")
async def run_outreach_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    website_url = str(job.input.get("website_url") or "")
    sheet_url = str(job.input.get("sheet_url") or "")
    if not website_url or not sheet_url:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing website_url or sheet_url"
        )
        raise RuntimeError("invalid outreach input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_outreach_pipeline,
            job_id=job_id,
            website_url=website_url,
            sheet_url=sheet_url,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("outreach pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_social_listening_activity")
async def run_social_listening_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    product_url = str(job.input.get("product_url") or "")
    product_name = job.input.get("product_name")
    product_name = str(product_name).strip() if product_name else None
    max_posts = job.input.get("max_posts")
    try:
        max_posts_i = int(max_posts) if max_posts is not None else None
    except (TypeError, ValueError):
        max_posts_i = None
    if not product_url:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing product_url"
        )
        raise RuntimeError("invalid social-listening input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_social_listening_pipeline,
            job_id=job_id,
            product_url=product_url,
            product_name=product_name,
            max_posts=max_posts_i,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("social-listening pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_promo_video_activity")
async def run_promo_video_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    product_url = str(job.input.get("product_url") or "")
    duration = job.input.get("duration", 8)
    resolution = str(job.input.get("resolution") or "720p")
    try:
        duration_i = int(duration)
    except (TypeError, ValueError):
        duration_i = 8
    if not product_url:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing product_url"
        )
        raise RuntimeError("invalid promo-video input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_promo_video_pipeline,
            job_id=job_id,
            product_url=product_url,
            duration=duration_i,
            resolution=resolution,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("promo-video pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result


@activity.defn(name="run_competitor_research_activity")
async def run_competitor_research_activity(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise RuntimeError(f"job not found: {job_id}")

    await store.set_status(job_id, JobStatus.RUNNING, error=None)
    await store.set_step(job_id, "starting")

    product_name = str(job.input.get("product_name") or "").strip()
    product_url_raw = job.input.get("product_url")
    product_url = str(product_url_raw).strip() if product_url_raw else None
    if not product_name:
        await store.set_status(
            job_id, JobStatus.FAILED, error="missing product_name"
        )
        raise RuntimeError("invalid competitor-research input")

    loop = asyncio.get_running_loop()

    def set_step(name: str) -> None:
        fut = asyncio.run_coroutine_threadsafe(store.set_step(job_id, name), loop)
        try:
            fut.result(timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_step failed: %s", exc)

    on_step = make_on_step_complete(
        set_step=set_step,
        heartbeat=lambda label: activity.heartbeat(label),
    )

    try:
        result = await asyncio.to_thread(
            run_competitor_research_pipeline,
            job_id=job_id,
            product_name=product_name,
            product_url=product_url,
            on_step_complete=on_step,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("competitor-research pipeline failed job_id=%s", job_id)
        await store.set_status(job_id, JobStatus.FAILED, error=str(exc)[:2000])
        raise

    artifacts = [Artifact.model_validate(a) for a in result.get("artifacts") or []]
    await store.update(
        job_id,
        status=JobStatus.COMPLETED,
        artifacts=artifacts,
        error=None,
        step="completed",
    )
    return result
