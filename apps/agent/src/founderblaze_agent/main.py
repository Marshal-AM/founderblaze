from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from founderblaze.a2mcp.client import A2MCPClient
from founderblaze.a2mcp.tools import list_service_tools
from founderblaze.agent.runner import run_agent
from founderblaze.core.config import get_settings
from founderblaze.core.logging import setup_logging
from founderblaze.mcp_server.server import create_mcp_server

log = logging.getLogger("founderblaze.agent.api")

_SESSIONS: dict[str, list[dict[str, str]]] = {}
_LAST: dict[str, dict[str, Any]] = {}


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    # Chat UI sets False so it can poll live job steps via /v1/agent/jobs/{id}.
    wait_for_jobs: bool = True


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    settings = get_settings()
    if settings.gemini_api_key:
        os.environ.setdefault("GEMINI_API_KEY", settings.gemini_api_key)
    os.environ.setdefault("GEMINI_TEXT_MODEL", settings.gemini_text_model)
    os.environ.setdefault(
        "AGENT_GEMINI_MODEL", settings.resolved_agent_gemini_model
    )
    os.environ.setdefault(
        "FOUNDERBLAZE_A2MCP_BASE_URL", settings.founderblaze_a2mcp_base_url
    )
    os.environ.setdefault(
        "AGENT_JOB_TIMEOUT_SECONDS", str(settings.agent_job_timeout_seconds)
    )
    log.info(
        "FounderBlaze agent ready port=%s a2mcp=%s model=%s cors=%s",
        settings.agent_port,
        settings.founderblaze_a2mcp_base_url,
        settings.resolved_agent_gemini_model,
        settings.agent_cors_origins,
    )
    yield


app = FastAPI(title="FounderBlaze Agent", version="0.1.0", lifespan=lifespan)

# Load from Settings (.env), not bare os.environ — otherwise chat origin is missing.
_cors_origins = [
    o.strip()
    for o in get_settings().agent_cors_origins.split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "founderblaze-agent"}


@app.get("/v1/tools")
async def tools() -> dict[str, Any]:
    return {"tools": list_service_tools()}


@app.post("/v1/agent/run")
async def agent_run(body: AgentRunRequest) -> dict[str, Any]:
    history = _SESSIONS.get(body.session_id or "", [])
    try:
        result = await run_agent(
            body.message,
            session_id=body.session_id,
            history=history,
            wait_for_jobs=body.wait_for_jobs,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run failed")
        raise HTTPException(status_code=500, detail=str(exc)[:2000]) from exc

    sid = str(result["session_id"])
    hist = list(_SESSIONS.get(sid, []))
    hist.append({"role": "user", "content": body.message})
    hist.append({"role": "assistant", "content": str(result.get("reply") or "")})
    _SESSIONS[sid] = hist[-20:]
    _LAST[sid] = result
    return result


@app.get("/v1/agent/jobs/{job_id}")
async def agent_job(job_id: str) -> dict[str, Any]:
    """CORS-friendly proxy to A2MCP GET /v1/jobs/{id} for the chat UI."""
    settings = get_settings()
    client = A2MCPClient(settings.founderblaze_a2mcp_base_url)
    try:
        return await client.get_job(job_id)
    except Exception as exc:  # noqa: BLE001
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=exc.response.text[:800],
            ) from exc
        log.warning("job proxy failed id=%s err=%s", job_id, exc)
        raise HTTPException(status_code=502, detail=str(exc)[:800]) from exc


@app.get("/v1/agent/sessions/{session_id}")
async def agent_session(session_id: str) -> dict[str, Any]:
    if session_id not in _LAST:
        raise HTTPException(status_code=404, detail="session not found")
    return _LAST[session_id]


# Real MCP over streamable HTTP (alongside Postman JSON API)
try:
    app.mount("/mcp", create_mcp_server().streamable_http_app())
except Exception as _mcp_exc:  # noqa: BLE001
    log.warning("MCP HTTP mount skipped: %s", _mcp_exc)


def run() -> None:
    setup_logging()
    settings = get_settings()
    # Railway injects PORT; prefer AGENT_PORT when set, else PORT, else default.
    if os.environ.get("AGENT_PORT"):
        port = settings.agent_port
    else:
        port = int(os.environ.get("PORT", settings.agent_port))
    uvicorn.run(
        "founderblaze_agent.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    run()
