"""Segmind Seedance 2.0 — port of services/promo-video-service/src/video.ts."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import file_asset, find_input_json

log = logging.getLogger("founderblaze.promo_video.seedance")

SUBMIT_URL = "https://api.segmind.com/v2/seedance-2.0"
STATUS_URL = "https://api.segmind.com/v2/requests/{request_id}/status"
RESULT_URL = "https://api.segmind.com/v2/requests/{request_id}"

_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
_POLL_INTERVAL_S = 3.0


class SeedanceProvider(SyncProvider):
    """Submit Seedance job → infinite poll → write work/promo.mp4."""

    name = "promo-video-seedance"

    def __init__(
        self,
        *,
        duration: int,
        resolution: str,
        api_key: str | None = None,
        work_dir: str | None = None,
        aspect_ratio: str = "16:9",
        bitrate_mode: str = "standard",
        generate_audio: bool = True,
        seed: int = -1,
        poll_interval: float = _POLL_INTERVAL_S,
    ) -> None:
        super().__init__()
        self.duration = duration
        self.resolution = resolution
        self.api_key = api_key or os.environ.get("SEGMIND_API_KEY", "")
        self.work_dir = work_dir
        self.aspect_ratio = aspect_ratio
        self.bitrate_mode = bitrate_mode
        self.generate_audio = generate_audio
        self.seed = seed
        self.poll_interval = poll_interval

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.VIDEO],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not self.api_key.strip():
            raise RuntimeError("SEGMIND_API_KEY is required for Seedance")

        script = find_input_json(step.inputs, "promo_script")
        prompt = str(
            script.get("seedance_prompt") or script.get("veo_prompt") or ""
        ).strip()
        if len(prompt) < 40:
            raise RuntimeError("script missing seedance_prompt")

        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        output_path = work / "promo.mp4"

        body: dict[str, Any] = {
            "prompt": prompt,
            "duration": int(self.duration),
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
            "bitrate_mode": self.bitrate_mode,
            "generate_audio": bool(self.generate_audio),
            "seed": int(self.seed),
        }

        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            log.info(
                "submitting Seedance 2.0 duration=%s resolution=%s",
                self.duration,
                self.resolution,
            )
            request_id = _submit(client, headers, body)
            log.info("seedance submitted request_id=%s", request_id)
            _poll_until_done(client, headers, request_id, self.poll_interval)
            video_url, local_path = _fetch_and_save(
                client, headers, request_id, output_path
            )

        result_meta = {
            "request_id": request_id,
            "video_url": video_url,
            "local_path": str(local_path),
        }
        (work / "seedance_result.json").write_text(
            json.dumps(result_meta, indent=2),
            encoding="utf-8",
        )
        log.info(
            "seedance ready request_id=%s bytes=%s",
            request_id,
            local_path.stat().st_size,
        )
        step.assets.append(
            file_asset(
                local_path,
                media_type="video/mp4",
                metadata={
                    "kind": "promo_video",
                    "request_id": request_id,
                    "segmind_video_url": video_url,
                },
            )
        )
        return step


def _submit(
    client: httpx.Client, headers: dict[str, str], body: dict[str, Any]
) -> str:
    res = client.post(SUBMIT_URL, headers=headers, json=body)
    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise RuntimeError(
            f"Seedance submit failed ({res.status_code}): {json.dumps(data, indent=2)}"
        )
    request_id = (
        data.get("request_id") or data.get("requestId") or data.get("id")
    )
    if not request_id:
        raise RuntimeError(f"No request_id in submit response: {data}")
    return str(request_id)


def _poll_until_done(
    client: httpx.Client,
    headers: dict[str, str],
    request_id: str,
    poll_interval: float,
) -> None:
    """Poll forever until COMPLETED or FAILED (no timeout)."""
    status = "QUEUED"
    log.info("polling Segmind job request_id=%s", request_id)
    while status in ("QUEUED", "PROCESSING"):
        time.sleep(poll_interval)
        try:
            res = client.get(
                STATUS_URL.format(request_id=request_id),
                headers={"x-api-key": headers["x-api-key"]},
            )
        except httpx.HTTPError as exc:
            log.warning("status poll network blip: %s", exc)
            continue

        data = _json_or_empty(res)
        if res.status_code == 422 or data.get("status") == "FAILED":
            raise RuntimeError(f"Generation FAILED: {json.dumps(data, indent=2)}")
        if res.status_code in _RETRY_STATUS or res.status_code == 404:
            log.warning("status poll transient HTTP %s", res.status_code)
            continue
        if res.status_code >= 400:
            raise RuntimeError(
                f"Status poll error ({res.status_code}): {json.dumps(data)}"
            )
        status = str(data.get("status") or status)
        log.info("seedance status=%s", status)

    if status != "COMPLETED":
        raise RuntimeError(f"Unexpected final status: {status}")


def _fetch_and_save(
    client: httpx.Client,
    headers: dict[str, str],
    request_id: str,
    output_path: Path,
) -> tuple[str | None, Path]:
    res = client.get(
        RESULT_URL.format(request_id=request_id),
        headers={"x-api-key": headers["x-api-key"]},
    )
    content_type = (res.headers.get("content-type") or "").lower()

    if "video/" in content_type or "octet-stream" in content_type:
        output_path.write_bytes(res.content)
        return None, output_path

    data = _json_or_empty(res)
    if res.status_code >= 400:
        raise RuntimeError(
            f"Result fetch failed ({res.status_code}): {json.dumps(data, indent=2)}"
        )

    video_url = _extract_video_url(data)
    if video_url:
        log.info("downloading video from Segmind URL")
        vid = client.get(video_url)
        if vid.status_code >= 400:
            raise RuntimeError(
                f"Video download failed ({vid.status_code}): {video_url}"
            )
        output_path.write_bytes(vid.content)
        return video_url, output_path

    b64 = _extract_base64_video(data)
    if b64:
        output_path.write_bytes(base64.b64decode(b64))
        return None, output_path

    raise RuntimeError(
        "Could not find video in Segmind result. Full body:\n"
        + json.dumps(data, indent=2)
    )


def _json_or_empty(res: httpx.Response) -> dict[str, Any]:
    try:
        val = res.json()
        return val if isinstance(val, dict) else {"raw": val}
    except Exception:  # noqa: BLE001
        text = (res.text or "").strip()
        return {"raw": text} if text else {}


def _extract_video_url(result: dict[str, Any]) -> str | None:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    nested = result.get("result") if isinstance(result.get("result"), dict) else {}
    candidates: list[Any] = [
        result.get("video"),
        result.get("output"),
        result.get("url"),
        result.get("video_url"),
        result.get("videoUrl"),
        data.get("video") if isinstance(data, dict) else None,
        data.get("output") if isinstance(data, dict) else None,
        data.get("url") if isinstance(data, dict) else None,
        nested.get("video") if isinstance(nested, dict) else None,
        nested.get("output") if isinstance(nested, dict) else None,
    ]
    out = result.get("output")
    if isinstance(out, list) and out:
        candidates.append(out[0])
    for c in candidates:
        if isinstance(c, str) and c.startswith(("http://", "https://")):
            return c
        if isinstance(c, dict):
            for key in ("url", "uri"):
                v = c.get(key)
                if isinstance(v, str) and v.startswith(("http://", "https://")):
                    return v
    return None


def _extract_base64_video(result: dict[str, Any]) -> str | None:
    for c in (
        result.get("video"),
        result.get("output"),
        result.get("data"),
        result.get("video_base64"),
    ):
        if isinstance(c, str) and len(c) > 200 and not c.startswith(("http://", "https://")):
            if c.startswith("data:video/"):
                _, _, payload = c.partition(",")
                return payload
            return c
    return None
