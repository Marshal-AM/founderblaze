from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from founderblaze.core.config import get_settings
from founderblaze.core.discovery import build_discovery_document
from founderblaze.core.jobs.migrate import migrate
from founderblaze.core.jobs.store import close_pool, create_pool, get_job_store
from founderblaze.core.logging import setup_logging
from founderblaze.core.schemas.models import (
    SERVICE_MANIFESTS,
    ApdInput,
    AppKitInput,
    BrandKitInput,
    CreateJobRequest,
    JobStatus,
    CompetitorResearchInput,
    OutreachInput,
    PromoVideoInput,
    ServiceName,
    SocialListeningInput,
)
from founderblaze.core.storage.b2 import resolve_download_url
from founderblaze_api.temporal_client import get_temporal_client

log = logging.getLogger("founderblaze.api")

_WORKFLOWS: dict[ServiceName, tuple[str, str]] = {
    ServiceName.AUTOMATED_PRODUCT_DEMO: ("ApdWorkflow", "apd"),
    ServiceName.BRAND_KIT: ("BrandKitWorkflow", "brand-kit"),
    ServiceName.OUTREACH: ("OutreachWorkflow", "outreach"),
    ServiceName.SOCIAL_LISTENING: ("SocialListeningWorkflow", "social-listening"),
    ServiceName.PROMO_VIDEO: ("PromoVideoWorkflow", "promo-video"),
    ServiceName.COMPETITOR_RESEARCH: (
        "CompetitorResearchWorkflow",
        "competitor-research",
    ),
    ServiceName.APP_KIT: ("AppKitWorkflow", "app-kit"),
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    await migrate(pool)
    log.info("FounderBlaze API ready port=%s", settings.port)
    yield
    await close_pool()


app = FastAPI(title="FounderBlaze A2MCP", version="0.1.0", lifespan=lifespan)


def _poll_hints(job_id: str) -> dict[str, Any]:
    return {
        "poll": {
            "method": "GET",
            "path": f"/v1/jobs/{job_id}",
            "recommended_interval_seconds": 10,
            "terminal_statuses": ["completed", "failed", "cancelled"],
        }
    }


def _job_public(job) -> dict[str, Any]:  # noqa: ANN001
    artifacts = []
    for a in job.artifacts:
        item = a.model_dump()
        if item.get("object_key") and not item.get("url"):
            try:
                item["url"] = resolve_download_url(item["object_key"])
            except Exception as exc:  # noqa: BLE001
                log.warning("resolve artifact url failed: %s", exc)
        artifacts.append(item)
    return {
        "id": job.id,
        "service": job.service.value,
        "status": job.status.value,
        "artifacts": artifacts,
        "cost_breakdown": [c.model_dump() for c in job.cost_breakdown],
        "list_price_usd": job.list_price_usd,
        "error": job.error,
        "workflow_id": job.workflow_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "eta_seconds": job.eta_seconds,
        "step": job.step,
        **_poll_hints(job.id),
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    store = await get_job_store()
    queue_age = await store.oldest_queued_age_seconds()
    return {
        "ok": True,
        "service": "founderblaze-api",
        "queue_oldest_age_seconds": queue_age,
    }


@app.get("/v1/discovery")
@app.post("/v1/discovery")
@app.get("/v1/services")
@app.post("/v1/services")
async def discovery(request: Request) -> dict[str, Any]:
    settings = get_settings()
    if settings.public_api_base_url.strip():
        return build_discovery_document()
    return build_discovery_document(base_url=str(request.base_url).rstrip("/"))


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    store = await get_job_store()
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _job_public(job)


@app.post("/v1/services/{service}/jobs", status_code=202)
async def create_job(
    service: str,
    body: dict[str, Any],
    x_idempotency_key: str | None = Header(default=None),
) -> JSONResponse:
    try:
        service_name = ServiceName(service)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "unknown_service", "service": service}
        ) from exc

    if "input" not in body:
        body = {"input": body}
    try:
        req = CreateJobRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "invalid_body", "details": exc.errors()}
        ) from exc

    try:
        if service_name == ServiceName.AUTOMATED_PRODUCT_DEMO:
            ApdInput.model_validate(req.input)
        elif service_name == ServiceName.BRAND_KIT:
            BrandKitInput.model_validate(req.input)
        elif service_name == ServiceName.OUTREACH:
            OutreachInput.model_validate(req.input)
        elif service_name == ServiceName.SOCIAL_LISTENING:
            SocialListeningInput.model_validate(req.input)
        elif service_name == ServiceName.PROMO_VIDEO:
            PromoVideoInput.model_validate(req.input)
        elif service_name == ServiceName.COMPETITOR_RESEARCH:
            CompetitorResearchInput.model_validate(req.input)
        elif service_name == ServiceName.APP_KIT:
            AppKitInput.model_validate(req.input)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_input", "details": exc.errors()},
        ) from exc

    store = await get_job_store()
    job = await store.create(service_name, req, idempotency_key=x_idempotency_key)

    settings = get_settings()
    if job.status == JobStatus.QUEUED and not job.workflow_id:
        workflow_name, id_prefix = _WORKFLOWS[service_name]
        workflow_id = f"{id_prefix}-{job.id}"
        try:
            client = await get_temporal_client(settings)
            await client.start_workflow(
                workflow_name,
                job.id,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )
            job = await store.mark_dispatched(job.id, workflow_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("temporal dispatch failed job_id=%s", job.id)
            job = await store.mark_dispatch_failed(job.id, str(exc))

    manifest = SERVICE_MANIFESTS[service_name]
    payload = {
        "job_id": job.id,
        "list_price_usd": job.list_price_usd,
        "eta_seconds": job.eta_seconds
        or int(manifest["sla_minutes"]) * 60,
        "status_url": f"/v1/jobs/{job.id}",
        "status": job.status.value,
        **_poll_hints(job.id),
    }
    if job.workflow_id:
        payload["workflow_id"] = job.workflow_id
    if job.error:
        payload["error"] = job.error
    return JSONResponse(status_code=202, content=payload)


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "founderblaze_api.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
