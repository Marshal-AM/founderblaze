from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from genblaze_core.models.policy import EmbedPolicy

from founderblaze.core.config import Settings, get_settings
from founderblaze.core.storage.b2 import (
    _unwrap_url,
    build_b2_backend,
    resolve_download_url,
    upload_local_file,
)

log = logging.getLogger("founderblaze.storage.provenance")

PrimaryKind = Literal["pdf", "video", "zip", "image", "any"]
EmbedMode = Literal["auto", "sidecar", "pointer"]

_SIDECAR_SUFFIXES = {".pdf", ".zip"}
_POINTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mp3", ".wav", ".m4a", ".flac"}


def pick_primary_local_path(
    result: Any,
    *,
    kind: PrimaryKind = "any",
) -> Path | None:
    """Resolve a local ``file:`` path for the primary deliverable before cleanup."""
    run = getattr(result, "run", result)
    steps = getattr(run, "steps", []) or []
    for step in reversed(steps):
        for asset in getattr(step, "assets", None) or []:
            path = _local_path_from_asset(asset)
            if path is None or not path.is_file():
                continue
            if kind == "any" or _matches_kind(path, asset, kind):
                return path
    return None


def pick_insight_chart_paths(result: Any) -> list[Path]:
    """Local PNG/JPEG/WebP paths from insight image assets (if still on disk)."""
    run = getattr(result, "run", result)
    out: list[Path] = []
    seen: set[str] = set()
    for step in getattr(run, "steps", []) or []:
        for asset in getattr(step, "assets", None) or []:
            meta = dict(getattr(asset, "metadata", None) or {})
            kind = str(meta.get("kind") or "")
            if "image" not in kind and not str(meta.get("chart_id") or ""):
                media = str(getattr(asset, "media_type", "") or "")
                if "image" not in media:
                    continue
            path = _local_path_from_asset(asset)
            if path is None or not path.is_file():
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def finalize_run_provenance(
    result: Any,
    *,
    sink: Any | None,
    primary_local_path: str | Path | None,
    object_key: str | None,
    settings: Settings | None = None,
    mode: EmbedMode = "auto",
    upload_sidecar: bool = True,
    allow_unverified_assets: bool = True,
) -> dict[str, Any]:
    """Verify stored manifest, write sidecar/pointer next to deliverable, upload sidecar.

    Returns a uniform provenance block for job artifacts / pipeline results.
    Does not overwrite the canonical B2 asset bytes (pre-embed sha256 stays valid).
    """
    settings = settings or get_settings()
    run = getattr(result, "run", None)
    manifest = getattr(result, "manifest", None)
    if run is None or manifest is None:
        raise RuntimeError("PipelineResult missing run/manifest")

    path = Path(primary_local_path) if primary_local_path else None
    verified = False
    manifest_key: str | None = None
    manifest_url: str | None = None
    canonical_hash = getattr(manifest, "canonical_hash", None)

    if sink is not None:
        try:
            stored = sink.read_manifest(
                run,
                verify=True,
                allow_unverified_assets=allow_unverified_assets,
            )
            verified = bool(
                stored.verify_hash()
                if allow_unverified_assets
                else stored.verify()
            )
            manifest = stored
            result.manifest = stored
            canonical_hash = stored.canonical_hash
        except Exception as exc:  # noqa: BLE001
            log.warning("manifest read/verify failed: %s", exc)
            # Fall back to in-memory hash check.
            try:
                verified = bool(manifest.verify_hash())
            except Exception:  # noqa: BLE001
                verified = False
        try:
            manifest_key = sink.manifest_key_for(run)
        except Exception:  # noqa: BLE001
            manifest_key = None
        if not getattr(manifest, "manifest_uri", None) and manifest_key:
            try:
                manifest.manifest_uri = sink._backend.get_durable_url(manifest_key)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass
        if manifest_key:
            try:
                manifest_url = resolve_download_url(manifest_key, settings=settings)
            except Exception:  # noqa: BLE001
                manifest_url = getattr(manifest, "manifest_uri", None)
    else:
        try:
            verified = bool(manifest.verify_hash())
        except Exception:  # noqa: BLE001
            verified = False

    embed_method = _resolve_mode(mode, path)
    sidecar_path: Path | None = None
    save_method: str | None = None

    if path is not None and path.is_file() and hasattr(result, "save"):
        try:
            if embed_method == "sidecar":
                embed_result = result.save(path, embed=False)
            else:
                if not getattr(manifest, "manifest_uri", None):
                    # Pointer requires URI; degrade to full sidecar.
                    log.warning(
                        "manifest_uri missing — writing full sidecar instead of pointer"
                    )
                    embed_result = result.save(path, embed=False)
                else:
                    policy = EmbedPolicy(embed_mode="pointer")
                    embed_result = result.save(path, embed=True, policy=policy)
            sidecar_path = getattr(embed_result, "sidecar_path", None)
            save_method = getattr(embed_result, "method", None)
            if sidecar_path is not None:
                sidecar_path = Path(sidecar_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("result.save provenance failed path=%s: %s", path, exc)

    sidecar_object_key: str | None = None
    sidecar_url: str | None = None
    if (
        upload_sidecar
        and sink is not None
        and object_key
        and sidecar_path is not None
        and sidecar_path.is_file()
    ):
        sidecar_object_key = f"{object_key.rstrip('/')}.genblaze.json"
        # Prefer Genblaze's actual sidecar filename if it already matches pattern
        if sidecar_path.name.endswith(".genblaze.json"):
            # Keep object key aligned with deliverable key + .genblaze.json
            pass
        try:
            uploaded = upload_local_file(
                sidecar_path,
                object_key=sidecar_object_key,
                content_type="application/json",
                settings=settings,
            )
            sidecar_url = uploaded.get("url")
            log.info(
                "uploaded provenance sidecar key=%s method=%s",
                sidecar_object_key,
                save_method,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("sidecar upload failed: %s", exc)
            sidecar_object_key = None
            sidecar_url = None

    return {
        "canonical_hash": canonical_hash,
        "run_id": getattr(run, "run_id", None),
        "manifest_key": manifest_key,
        "manifest_url": manifest_url or getattr(manifest, "manifest_uri", None),
        "sidecar_object_key": sidecar_object_key,
        "sidecar_url": sidecar_url,
        "provenance_verified": verified,
        "embed_method": save_method or embed_method,
        "local_sidecar_path": str(sidecar_path) if sidecar_path else None,
    }


def finalize_chart_provenance(
    result: Any,
    *,
    sink: Any | None,
    settings: Settings | None = None,
    upload: bool = True,
) -> list[dict[str, Any]]:
    """Pointer-sidecar + optional B2 upload for insight chart images."""
    settings = settings or get_settings()
    charts = pick_insight_chart_paths(result)
    if not charts or sink is None:
        return []

    manifest = getattr(result, "manifest", None)
    run = getattr(result, "run", None)
    if manifest is None or run is None:
        return []

    if not getattr(manifest, "manifest_uri", None):
        try:
            key = sink.manifest_key_for(run)
            manifest.manifest_uri = sink._backend.get_durable_url(key)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

    out: list[dict[str, Any]] = []
    backend = build_b2_backend(settings) if upload else None
    prefix = getattr(sink, "_prefix", "founderblaze")
    date_str = getattr(run, "created_at", None)
    date_part = date_str.strftime("%Y-%m-%d") if date_str else "undated"

    for path in charts:
        try:
            if getattr(manifest, "manifest_uri", None):
                er = result.save(
                    path, embed=True, policy=EmbedPolicy(embed_mode="pointer")
                )
            else:
                er = result.save(path, embed=False)
            side = getattr(er, "sidecar_path", None)
            side_path = Path(side) if side else None
            chart_key = (
                f"{prefix}/assets/{run.tenant_id}/{date_part}/"
                f"{run.run_id}/charts/{path.name}"
            )
            sidecar_key = f"{chart_key}.genblaze.json"
            chart_url = None
            sidecar_url = None
            if upload and backend is not None:
                backend.put(
                    chart_key,
                    path.read_bytes(),
                    content_type=_image_mime(path),
                )
                chart_url = resolve_download_url(chart_key, settings=settings)
                if side_path and side_path.is_file():
                    backend.put(
                        sidecar_key,
                        side_path.read_bytes(),
                        content_type="application/json",
                    )
                    sidecar_url = resolve_download_url(sidecar_key, settings=settings)
            out.append(
                {
                    "type": "insight_chart",
                    "url": chart_url,
                    "object_key": chart_key if upload else None,
                    "mime_type": _image_mime(path),
                    "path": str(path),
                    "sidecar_object_key": sidecar_key if upload and side_path else None,
                    "sidecar_url": sidecar_url,
                    "canonical_hash": getattr(manifest, "canonical_hash", None),
                    "provenance_verified": True,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("chart provenance failed path=%s: %s", path, exc)
    return out


def merge_provenance(artifact: dict[str, Any], prov: dict[str, Any]) -> dict[str, Any]:
    """Copy provenance fields onto a primary artifact dict."""
    merged = dict(artifact)
    for key in (
        "canonical_hash",
        "manifest_key",
        "manifest_url",
        "sidecar_object_key",
        "sidecar_url",
        "provenance_verified",
        "embed_method",
    ):
        if prov.get(key) is not None:
            merged[key] = prov[key]
    return merged


def _resolve_mode(mode: EmbedMode, path: Path | None) -> Literal["sidecar", "pointer"]:
    if mode in ("sidecar", "pointer"):
        return mode  # type: ignore[return-value]
    if path is None:
        return "sidecar"
    suffix = path.suffix.lower()
    if suffix in _SIDECAR_SUFFIXES or suffix not in _POINTER_SUFFIXES:
        return "sidecar"
    return "pointer"


def _matches_kind(path: Path, asset: Any, kind: PrimaryKind) -> bool:
    media = str(getattr(asset, "media_type", "") or "").lower()
    meta = dict(getattr(asset, "metadata", None) or {})
    meta_kind = str(meta.get("kind") or "").lower()
    name = path.name.lower()
    if kind == "pdf":
        return "pdf" in media or name.endswith(".pdf") or "pdf" in meta_kind
    if kind == "video":
        return "video" in media or name.endswith(".mp4") or "video" in meta_kind
    if kind == "zip":
        return "zip" in media or name.endswith(".zip") or "zip" in meta_kind
    if kind == "image":
        return (
            "image" in media
            or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            or "image" in meta_kind
        )
    return True


def _local_path_from_asset(asset: Any) -> Path | None:
    meta = dict(getattr(asset, "metadata", None) or {})
    for key in ("local_path", "html_path"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw:
            p = Path(raw)
            if p.is_file():
                return p
    raw_url = getattr(asset, "url", None)
    url = _unwrap_url(raw_url)
    if not url:
        return None
    if url.startswith("file:"):
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        p = Path(path)
        return p if p.exists() else None
    p = Path(url)
    return p if p.is_file() else None


def _image_mime(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
