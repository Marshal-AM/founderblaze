from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from genblaze_core import KeyStrategy, ObjectStorageSink
from genblaze_s3 import S3StorageBackend

from founderblaze.core.config import Settings, get_settings

log = logging.getLogger("founderblaze.storage.b2")


def build_b2_backend(settings: Settings | None = None) -> S3StorageBackend:
    settings = settings or get_settings()
    settings.require_b2()
    public = settings.b2_public_url_base.strip() or None
    return S3StorageBackend.for_backblaze(
        settings.b2_bucket.strip(),
        region=settings.b2_region.strip() or "us-west-004",
        public_url_base=public,
        key_id=settings.b2_key_id.strip() or None,
        app_key=settings.b2_app_key.strip() or None,
    )


def build_b2_sink(
    *,
    service: str = "automated-product-demo",
    settings: Settings | None = None,
) -> ObjectStorageSink:
    settings = settings or get_settings()
    backend = build_b2_backend(settings)
    prefix = f"founderblaze/{service}"
    return ObjectStorageSink(
        backend,
        prefix=prefix,
        key_strategy=KeyStrategy.HIERARCHICAL,
    )


def _unwrap_url(value: Any) -> str:
    """Genblaze ``PresignedURL`` redacts in ``str()`` — use ``.url`` explicitly."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = getattr(value, "url", None)
    if isinstance(raw, str) and raw.startswith(("http://", "https://")):
        return raw
    return str(value)


def resolve_download_url(
    object_key: str,
    *,
    settings: Settings | None = None,
    expires_in: int | None = None,
) -> str:
    """Resolve a client-facing URL from a durable object key."""
    settings = settings or get_settings()
    backend = build_b2_backend(settings)
    ttl = expires_in if expires_in is not None else settings.b2_url_ttl_seconds
    if settings.b2_public_url_base.strip() and ttl <= 0:
        base = settings.b2_public_url_base.rstrip("/")
        return f"{base}/{object_key.lstrip('/')}"
    # Prefer helpers that already return a plain string URL when available.
    if hasattr(backend, "presigned_get_url"):
        return _unwrap_url(
            backend.presigned_get_url(object_key, expires_in=max(ttl, 60))
        )
    if hasattr(backend, "presigned_get"):
        return _unwrap_url(backend.presigned_get(object_key, expires_in=max(ttl, 60)))
    if hasattr(backend, "get_url"):
        return _unwrap_url(backend.get_url(object_key))
    raise RuntimeError("B2 backend cannot resolve download URLs")


def upload_local_file(
    local_path: str | Path,
    *,
    object_key: str,
    content_type: str = "video/mp4",
    settings: Settings | None = None,
) -> dict[str, str]:
    """Direct PutObject upload (for AssembleProvider fallback)."""
    settings = settings or get_settings()
    backend = build_b2_backend(settings)
    path = Path(local_path)
    data = path.read_bytes()
    backend.put(object_key, data, content_type=content_type)
    url = resolve_download_url(object_key, settings=settings)
    log.info("uploaded artifact", extra={"object_key": object_key})
    return {"object_key": object_key, "url": url}


def object_key_from_asset_url(url: str, *, prefix_hint: str = "founderblaze/") -> str | None:
    """Best-effort extract object key from a Genblaze/B2 asset URL."""
    if not url:
        return None
    if url.startswith("file:"):
        return None
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    # Friendly: /file/<bucket>/<key>
    if "/file/" in path:
        parts = path.split("/file/", 1)[-1].split("/", 1)
        if len(parts) == 2:
            return parts[1]
    if prefix_hint in path:
        idx = path.find(prefix_hint)
        return path[idx:]
    # S3 virtual-hosted: bucket.s3.region/.../<key>
    if ".backblazeb2.com" in (parsed.netloc or ""):
        return path
    return path or None


def pick_final_video_asset(result: Any) -> tuple[str, str | None]:
    """Return (url, object_key) from a PipelineResult."""
    run = getattr(result, "run", result)
    steps = getattr(run, "steps", []) or []
    for step in reversed(steps):
        assets = getattr(step, "assets", None) or []
        for asset in assets:
            raw_url = getattr(asset, "url", None) or ""
            url = _unwrap_url(raw_url)
            media = getattr(asset, "media_type", "") or ""
            meta = getattr(asset, "metadata", None) or {}
            kind = meta.get("kind") if isinstance(meta, dict) else None
            if (
                "video" in media
                or url.endswith(".mp4")
                or ".mp4?" in url
                or kind == "promo_video"
            ):
                key = None
                if isinstance(meta, dict) and meta.get("object_key"):
                    key = str(meta["object_key"])
                if not key:
                    key = getattr(raw_url, "key", None) or object_key_from_asset_url(url)
                return url, key
    raise RuntimeError("No video asset found in Genblaze pipeline result")


def pick_final_pdf_asset(result: Any) -> tuple[str, str | None]:
    """Return (url, object_key) for the outreach PDF Asset."""
    run = getattr(result, "run", result)
    steps = getattr(run, "steps", []) or []
    for step in reversed(steps):
        assets = getattr(step, "assets", None) or []
        for asset in assets:
            raw_url = getattr(asset, "url", None) or ""
            url = _unwrap_url(raw_url)
            media = getattr(asset, "media_type", "") or ""
            meta = getattr(asset, "metadata", None) or {}
            kind = meta.get("kind") if isinstance(meta, dict) else None
            if (
                "pdf" in media
                or url.endswith(".pdf")
                or ".pdf?" in url
                or                 kind
                in (
                    "outreach_pdf",
                    "social_listening_pdf",
                    "competitor_research_pdf",
                    "pitch_deck_pdf",
                )
            ):
                key = None
                if isinstance(meta, dict) and meta.get("object_key"):
                    key = str(meta["object_key"])
                if not key:
                    key = getattr(raw_url, "key", None) or object_key_from_asset_url(url)
                return url, key
    raise RuntimeError("No PDF asset found in Genblaze pipeline result")
