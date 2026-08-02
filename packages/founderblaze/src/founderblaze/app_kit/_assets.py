"""Shared asset helpers for app-kit providers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from genblaze_core import Asset


def step_delay_seconds() -> float:
    raw = os.environ.get("APPKIT_STEP_DELAY_MS") or os.environ.get(
        "BRANDKIT_STEP_DELAY_MS", "3000"
    )
    try:
        return max(0.0, float(raw) / 1000.0)
    except ValueError:
        return 3.0


def wait_between_steps(label: str = "") -> None:
    delay = step_delay_seconds()
    if delay > 0:
        time.sleep(delay)


def slugify(value: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return s or "app"


def path_from_asset(asset: Asset) -> Path:
    url = getattr(asset, "url", None)
    url_s = str(getattr(url, "url", None) or url or "")
    if url_s.startswith("file:"):
        parsed = urlparse(url_s)
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)
    raise ValueError(f"Expected file:// asset URL, got: {url_s[:120]}")


def read_asset_bytes(asset: Asset) -> bytes:
    meta = getattr(asset, "metadata", None) or {}
    if isinstance(meta, dict) and isinstance(meta.get("bytes_b64"), str):
        import base64

        return base64.b64decode(meta["bytes_b64"])
    return path_from_asset(asset).read_bytes()


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
        metadata=metadata or {},
    )


def bytes_file_asset(
    data: bytes,
    *,
    suffix: str,
    media_type: str,
    work_dir: Path,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / name
    if not path.suffix:
        path = path.with_suffix(suffix)
    path.write_bytes(data)
    return file_asset(path, media_type=media_type, metadata=metadata)


def json_file_asset(
    data: dict[str, Any],
    *,
    work_dir: Path,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    payload = json.dumps(data, indent=2)
    meta = {
        "text": payload,
        "json": data,
        **(metadata or {}),
    }
    return bytes_file_asset(
        payload.encode("utf-8"),
        suffix=".json",
        media_type="application/json",
        work_dir=work_dir,
        name=name if name.endswith(".json") else f"{name}.json",
        metadata=meta,
    )


def asset_json(asset: Asset) -> dict[str, Any]:
    meta = getattr(asset, "metadata", None) or {}
    if isinstance(meta, dict) and isinstance(meta.get("json"), dict):
        return dict(meta["json"])
    text = ""
    if isinstance(meta, dict) and isinstance(meta.get("text"), str):
        text = meta["text"]
    else:
        try:
            text = read_asset_bytes(asset).decode("utf-8")
        except Exception:  # noqa: BLE001
            text = ""
    return json.loads(text) if text.strip() else {}
