from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import asyncpg

from founderblaze.core.config import get_settings
from founderblaze.core.schemas.models import (
    SERVICE_MANIFESTS,
    Artifact,
    CostLine,
    CreateJobRequest,
    JobRecord,
    JobStatus,
    ServiceName,
)

log = logging.getLogger("founderblaze.jobs")

_pool: asyncpg.Pool | None = None
_store: JobStore | None = None


async def create_pool(dsn: str | None = None) -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    dsn = dsn or get_settings().database_url
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool, _store
    if _pool is not None:
        await _pool.close()
        _pool = None
    _store = None


def _row_to_job(row: asyncpg.Record) -> JobRecord:
    artifacts_raw = row["artifacts"]
    costs_raw = row["cost_breakdown"]
    if isinstance(artifacts_raw, str):
        artifacts_raw = json.loads(artifacts_raw)
    if isinstance(costs_raw, str):
        costs_raw = json.loads(costs_raw)
    input_raw = row["input"]
    if isinstance(input_raw, str):
        input_raw = json.loads(input_raw)
    return JobRecord(
        id=str(row["id"]),
        service=ServiceName(row["service"]),
        status=JobStatus(row["status"]),
        input=input_raw or {},
        artifacts=[Artifact.model_validate(a) for a in (artifacts_raw or [])],
        cost_breakdown=[CostLine.model_validate(c) for c in (costs_raw or [])],
        list_price_usd=float(row["list_price_usd"]),
        error=row["error"],
        callback_url=row["callback_url"],
        idempotency_key=row["idempotency_key"],
        workflow_id=row["workflow_id"],
        dispatched_at=row["dispatched_at"],
        dispatch_error=row["dispatch_error"],
        eta_seconds=row["eta_seconds"],
        step=row["step"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class JobStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create(
        self,
        service: ServiceName,
        req: CreateJobRequest,
        idempotency_key: str | None = None,
    ) -> JobRecord:
        if idempotency_key:
            existing = await self.pool.fetchrow(
                """
                SELECT * FROM jobs
                WHERE service = $1 AND idempotency_key = $2
                LIMIT 1
                """,
                service.value,
                idempotency_key,
            )
            if existing:
                return _row_to_job(existing)

        manifest = SERVICE_MANIFESTS[service]
        job_id = uuid4()
        row = await self.pool.fetchrow(
            """
            INSERT INTO jobs (
              id, service, status, input, artifacts, cost_breakdown,
              list_price_usd, callback_url, idempotency_key, eta_seconds
            ) VALUES (
              $1, $2, 'queued', $3::jsonb, '[]'::jsonb, '[]'::jsonb,
              $4, $5, $6, $7
            )
            RETURNING *
            """,
            job_id,
            service.value,
            json.dumps(req.input),
            float(manifest["a2mcp_price_usd"]),
            str(req.callback_url) if req.callback_url else None,
            idempotency_key,
            int(manifest["sla_minutes"]) * 60,
        )
        assert row is not None
        return _row_to_job(row)

    async def get(self, job_id: str) -> JobRecord | None:
        row = await self.pool.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        return _row_to_job(row) if row else None

    async def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        artifacts: list[Artifact] | None = None,
        cost_breakdown: list[CostLine] | None = None,
        error: str | None | object = ...,
        step: str | None | object = ...,
        workflow_id: str | None = None,
        dispatched_at: datetime | None | object = ...,
        dispatch_error: str | None | object = ...,
    ) -> JobRecord:
        current = await self.get(job_id)
        if not current:
            raise KeyError(f"job not found: {job_id}")

        next_status = status or current.status
        next_artifacts = artifacts if artifacts is not None else current.artifacts
        next_costs = (
            cost_breakdown if cost_breakdown is not None else current.cost_breakdown
        )
        next_error = current.error if error is ... else error
        next_step = current.step if step is ... else step
        next_workflow = (
            workflow_id if workflow_id is not None else current.workflow_id
        )
        next_dispatched = (
            current.dispatched_at if dispatched_at is ... else dispatched_at
        )
        next_dispatch_err = (
            current.dispatch_error if dispatch_error is ... else dispatch_error
        )

        row = await self.pool.fetchrow(
            """
            UPDATE jobs SET
              status = $2,
              artifacts = $3::jsonb,
              cost_breakdown = $4::jsonb,
              error = $5,
              step = $6,
              workflow_id = $7,
              dispatched_at = $8,
              dispatch_error = $9,
              updated_at = NOW()
            WHERE id = $1
            RETURNING *
            """,
            job_id,
            next_status.value,
            json.dumps([a.model_dump() for a in next_artifacts]),
            json.dumps([c.model_dump() for c in next_costs]),
            next_error,
            next_step,
            next_workflow,
            next_dispatched,
            next_dispatch_err,
        )
        assert row is not None
        return _row_to_job(row)

    async def set_status(
        self, job_id: str, status: JobStatus, error: str | None = None
    ) -> JobRecord:
        return await self.update(job_id, status=status, error=error)

    async def set_step(self, job_id: str, step: str) -> JobRecord:
        return await self.update(job_id, step=step)

    async def mark_dispatched(self, job_id: str, workflow_id: str) -> JobRecord:
        return await self.update(
            job_id,
            workflow_id=workflow_id,
            dispatched_at=datetime.now(timezone.utc),
            dispatch_error=None,
        )

    async def mark_dispatch_failed(self, job_id: str, error: str) -> JobRecord:
        return await self.update(
            job_id,
            status=JobStatus.FAILED,
            error=f"temporal_enqueue_failed:{error}",
            dispatch_error=error,
        )

    async def oldest_queued_age_seconds(self) -> float | None:
        val = await self.pool.fetchval(
            """
            SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at)))
            FROM jobs WHERE status = 'queued'
            """
        )
        if val is None:
            return None
        return max(0.0, float(val))


async def get_job_store() -> JobStore:
    global _store
    if _store is None:
        pool = await create_pool()
        _store = JobStore(pool)
    return _store
