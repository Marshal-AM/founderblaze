from __future__ import annotations

from temporalio.client import Client

from founderblaze.core.config import Settings, get_settings

_client: Client | None = None


async def get_temporal_client(settings: Settings | None = None) -> Client:
    global _client
    if _client is not None:
        return _client
    settings = settings or get_settings()
    kwargs: dict = {"namespace": settings.temporal_namespace}
    if settings.temporal_api_key:
        kwargs["api_key"] = settings.temporal_api_key
    if settings.temporal_tls or settings.temporal_api_key:
        kwargs["tls"] = True
    _client = await Client.connect(settings.temporal_address, **kwargs)
    return _client
