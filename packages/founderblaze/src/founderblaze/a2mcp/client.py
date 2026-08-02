from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("founderblaze.a2mcp.client")


class A2MCPClient:
    """HTTP client for the FounderBlaze A2MCP gateway."""

    def __init__(
        self,
        base_url: str = "http://localhost:4021",
        *,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def fetch_discovery(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(f"{self.base_url}/v1/discovery")
            r.raise_for_status()
            return r.json()

    async def create_job(
        self, service: str, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.base_url}/v1/services/{service}/jobs",
                json={"input": input_data},
            )
            if r.status_code >= 400:
                detail = r.text[:800]
                raise RuntimeError(
                    f"create_job failed service={service} status={r.status_code}: {detail}"
                )
            return r.json()

    async def get_job(self, job_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(f"{self.base_url}/v1/jobs/{job_id}")
            r.raise_for_status()
            return r.json()

    async def poll_job(
        self,
        job_id: str,
        *,
        interval_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        terminal = {"completed", "failed", "cancelled"}
        while time.monotonic() < deadline:
            job = await self.get_job(job_id)
            status = str(job.get("status") or "")
            if status in terminal:
                return job
            await asyncio.sleep(interval_seconds)
        raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds}s")

    async def run_service(
        self,
        service: str,
        input_data: dict[str, Any],
        *,
        poll: bool = True,
        timeout_seconds: float = 1800.0,
    ) -> dict[str, Any]:
        created = await self.create_job(service, input_data)
        job_id = str(created.get("job_id") or created.get("id") or "")
        if not job_id:
            raise RuntimeError(f"create_job missing job_id: {created}")
        if not poll:
            return {"created": created, "job_id": job_id}
        final = await self.poll_job(job_id, timeout_seconds=timeout_seconds)
        return {"created": created, "job": final, "job_id": job_id}
