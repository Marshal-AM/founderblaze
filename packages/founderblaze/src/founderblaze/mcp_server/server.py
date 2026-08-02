from __future__ import annotations

import json
import logging
import os
from typing import Any

import mcp_types as types
from mcp.server.lowlevel import Server

from founderblaze.a2mcp.client import A2MCPClient
from founderblaze.a2mcp.tools import (
    list_service_tools,
    service_from_tool_name,
    validate_tool_input,
)

log = logging.getLogger("founderblaze.mcp_server")


def _client() -> A2MCPClient:
    base = os.environ.get("FOUNDERBLAZE_A2MCP_BASE_URL", "http://localhost:4021")
    return A2MCPClient(base)


async def run_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    poll: bool = True,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Shared execution path for MCP + Gemini agent."""
    service = service_from_tool_name(tool_name)
    raw = dict(arguments or {})
    validated = validate_tool_input(service, raw)
    timeout = timeout_seconds
    if timeout is None:
        timeout = float(os.environ.get("AGENT_JOB_TIMEOUT_SECONDS", "1800"))
    client = _client()
    result = await client.run_service(
        service, validated, poll=poll, timeout_seconds=timeout
    )
    job = result.get("job") or {}
    return {
        "service": service,
        "job_id": result.get("job_id"),
        "status": job.get("status") or "queued",
        "artifacts": job.get("artifacts") or [],
        "error": job.get("error"),
        "created": result.get("created"),
    }


def create_mcp_server() -> Server[Any]:
    """Low-level MCP Server with one tool per A2MCP catalog service."""

    async def on_list_tools(
        _ctx: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools = [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in list_service_tools()
        ]
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(
        _ctx: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        try:
            payload = await run_tool_call(params.name, params.arguments or {})
            text = json.dumps(payload, indent=2, default=str)
            is_error = str(payload.get("status") or "") == "failed"
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)],
                isError=is_error,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("MCP tool call failed name=%s", params.name)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Error: {exc}")],
                isError=True,
            )

    return Server(
        "founderblaze",
        version="0.1.0",
        instructions=(
            "FounderBlaze A2MCP tools. Each tool creates an async job on the "
            "FounderBlaze gateway, polls until complete, and returns artifacts."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )
