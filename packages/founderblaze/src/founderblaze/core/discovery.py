from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from founderblaze.core.config import get_settings
from founderblaze.core.schemas.models import SERVICE_MANIFESTS, ServiceName


def default_public_base_url() -> str:
    settings = get_settings()
    base = settings.public_api_base_url.strip().rstrip("/")
    if not base:
        return "http://localhost:4021"
    # Force https for non-local public hosts
    if not any(h in base for h in ("localhost", "127.0.0.1")):
        if base.startswith("http://"):
            base = "https://" + base[len("http://") :]
    return base


def build_discovery_document(*, base_url: str | None = None) -> dict[str, Any]:
    base = (base_url or default_public_base_url()).rstrip("/")
    services = []
    for name, manifest in SERVICE_MANIFESTS.items():
        endpoint = manifest["endpoint_path"]
        services.append(
            {
                "name": name.value,
                "title": manifest["title"],
                "paid": False,
                "method": "POST",
                "a2mcp_price_usd": manifest["a2mcp_price_usd"],
                "currency": "USD",
                "endpoint_path": endpoint,
                "endpoint_url": f"{base}{endpoint}",
                "sla_minutes": manifest["sla_minutes"],
                "eta_seconds": manifest["sla_minutes"] * 60,
                "summary": manifest["summary"],
                "provide": manifest["provide"],
                "deliverable": manifest["deliverable"],
                "example_request": manifest.get("example_request")
                or {"input": {}},
                "example_artifacts": manifest.get("example_artifacts") or [],
                "status_url_template": "/v1/jobs/{job_id}",
            }
        )

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "asp": {
            "name": "FounderBlaze",
            "description": (
                "FounderBlaze A2MCP services — async create, free poll, "
                "downloadable artifacts on Backblaze B2."
            ),
        },
        "base_url": base,
        "protocol": {
            "pattern": "A",
            "name": "async_create_free_poll",
            "summary": (
                "POST job create (free). Then GET /v1/jobs/{job_id} until "
                "completed, failed, or cancelled. Download artifacts[].url."
            ),
            "steps": [
                {
                    "step": 1,
                    "action": "Read discovery",
                    "detail": "GET or POST /v1/discovery",
                },
                {
                    "step": 2,
                    "action": "Create job",
                    "detail": 'POST endpoint with {"input":{...}} → HTTP 202',
                },
                {
                    "step": 3,
                    "action": "Poll",
                    "detail": "GET /v1/jobs/{job_id} until terminal status",
                },
                {
                    "step": 4,
                    "action": "Download",
                    "detail": "On completed, use artifacts[].url",
                },
            ],
            "polling": {
                "method": "GET",
                "path_template": "/v1/jobs/{job_id}",
                "free": True,
                "recommended_interval_seconds": 10,
                "terminal_statuses": ["completed", "failed", "cancelled"],
                "success_status": "completed",
                "failure_fields": ["error", "error_code"],
                "result_field": "artifacts",
                "result_url_field": "artifacts[].url",
            },
            "headers": {
                "content_type": "application/json",
                "idempotency": "X-Idempotency-Key",
            },
        },
        "free_endpoints": [
            {
                "method": "GET",
                "path": "/health",
                "path_url": f"{base}/health",
                "paid": False,
                "description": "Liveness",
            },
            {
                "method": "GET",
                "path": "/v1/discovery",
                "path_url": f"{base}/v1/discovery",
                "paid": False,
                "description": "A2MCP discovery document",
            },
            {
                "method": "POST",
                "path": "/v1/discovery",
                "path_url": f"{base}/v1/discovery",
                "paid": False,
                "description": "Same as GET /v1/discovery",
            },
            {
                "method": "GET",
                "path": "/v1/jobs/{job_id}",
                "path_url": f"{base}/v1/jobs/{{job_id}}",
                "paid": False,
                "description": "Poll job status",
            },
        ],
        "services": services,
        "live_services": [
            ServiceName.AUTOMATED_PRODUCT_DEMO.value,
            ServiceName.BRAND_KIT.value,
            ServiceName.OUTREACH.value,
            ServiceName.SOCIAL_LISTENING.value,
            ServiceName.PROMO_VIDEO.value,
            ServiceName.COMPETITOR_RESEARCH.value,
        ],
    }
