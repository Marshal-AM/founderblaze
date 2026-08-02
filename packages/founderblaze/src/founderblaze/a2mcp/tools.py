from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from founderblaze.core.schemas.models import (
    SERVICE_MANIFESTS,
    ApdInput,
    AppKitInput,
    BrandKitInput,
    CompetitorResearchInput,
    OutreachInput,
    PitchDeckInput,
    PromoVideoInput,
    ServiceName,
    SocialListeningInput,
)

_INPUT_MODELS: dict[ServiceName, type[BaseModel]] = {
    ServiceName.AUTOMATED_PRODUCT_DEMO: ApdInput,
    ServiceName.BRAND_KIT: BrandKitInput,
    ServiceName.OUTREACH: OutreachInput,
    ServiceName.SOCIAL_LISTENING: SocialListeningInput,
    ServiceName.PROMO_VIDEO: PromoVideoInput,
    ServiceName.COMPETITOR_RESEARCH: CompetitorResearchInput,
    ServiceName.APP_KIT: AppKitInput,
    ServiceName.PITCH_DECK: PitchDeckInput,
}


def _schema_for(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    # Prefer JSON Schema draft-friendly shape for MCP / Gemini
    schema.pop("title", None)
    return schema


def required_fields_for(model: type[BaseModel]) -> list[str]:
    schema = model.model_json_schema()
    return list(schema.get("required") or [])


def list_service_tools() -> list[dict[str, Any]]:
    """Tool definitions for MCP + Gemini from SERVICE_MANIFESTS."""
    tools: list[dict[str, Any]] = []
    for name, manifest in SERVICE_MANIFESTS.items():
        model = _INPUT_MODELS[name]
        required = required_fields_for(model)
        req_txt = ", ".join(required) if required else "(none)"
        tools.append(
            {
                "name": name.value.replace("-", "_"),
                "service": name.value,
                "title": manifest["title"],
                "description": (
                    f"{manifest['summary']} "
                    f"REQUIRED fields (must be explicitly provided by the user — "
                    f"never invent or guess): {req_txt}. "
                    f"Also: {manifest['provide']}. "
                    f"Deliverable: {manifest['deliverable']}. "
                    f"Do NOT call this tool until every required field is present "
                    f"in the user's messages."
                ),
                "input_schema": _schema_for(model),
                "required_fields": required,
                "sla_minutes": manifest["sla_minutes"],
                "price_usd": manifest["a2mcp_price_usd"],
            }
        )
    return tools


def tool_by_name(tool_name: str) -> dict[str, Any] | None:
    key = tool_name.replace("-", "_")
    for t in list_service_tools():
        if t["name"] == key or t["service"] == tool_name:
            return t
    return None


def validate_tool_input(service: str, raw: dict[str, Any]) -> dict[str, Any]:
    try:
        enum = ServiceName(service)
    except ValueError as exc:
        raise ValueError(f"Unknown service: {service}") from exc
    model = _INPUT_MODELS[enum]
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    # Serialize HttpUrl etc. to plain JSON-friendly values
    return parsed.model_dump(mode="json")


def service_from_tool_name(tool_name: str) -> str:
    tool = tool_by_name(tool_name)
    if not tool:
        raise ValueError(f"Unknown tool: {tool_name}")
    return str(tool["service"])
