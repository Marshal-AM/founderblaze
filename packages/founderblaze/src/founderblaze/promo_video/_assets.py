from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from genblaze_core import Asset


def json_file_asset(
    data: dict[str, Any],
    *,
    work_dir: Path,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    work_dir.mkdir(parents=True, exist_ok=True)
    filename = name if name.endswith(".json") else f"{name}.json"
    path = work_dir / filename
    payload = json.dumps(data, indent=2, default=str)
    path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    meta = {"text": payload, "json": data, **(metadata or {})}
    return Asset(
        url=path.resolve().as_uri(),
        media_type="application/json",
        sha256=digest,
        metadata=meta,
    )


def file_asset(
    path: Path,
    *,
    media_type: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return Asset(
        url=path.resolve().as_uri(),
        media_type=media_type,
        sha256=digest,
        metadata=dict(metadata or {}),
    )


def asset_json(asset: Any) -> dict[str, Any]:
    meta = dict(getattr(asset, "metadata", None) or {})
    raw = meta.get("json")
    if isinstance(raw, dict):
        return dict(raw)
    text = meta.get("text")
    if isinstance(text, str) and text.strip():
        return json.loads(text)
    path = local_path(getattr(asset, "url", "") or "")
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("Asset has no JSON payload")


def local_path(url: str) -> Path | None:
    if not url:
        return None
    if url.startswith("file:"):
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return Path(path)
    p = Path(url)
    return p if p.exists() else None


def find_input_json(inputs: list[Any], kind: str) -> dict[str, Any]:
    for asset in inputs or []:
        meta = dict(getattr(asset, "metadata", None) or {})
        if meta.get("kind") == kind:
            return asset_json(asset)
    raise RuntimeError(f"Missing chained asset kind={kind}")


def unwrap_url(raw: Any) -> str:
    if raw is None:
        return ""
    return getattr(raw, "url", None) or str(raw)
