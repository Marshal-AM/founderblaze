from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from PIL import Image

from founderblaze.app_kit._assets import asset_json, file_asset, json_file_asset
from founderblaze.core.gemini_retry import chat_with_retry

log = logging.getLogger("founderblaze.app_kit.brand_context")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class BrandContextProvider(SyncProvider):
    """Resolve brand direction from optional brand-kit ZIP URL, or invent one."""

    name = "app-kit-brand-context"

    def __init__(
        self,
        *,
        product_name: str,
        product_idea: str,
        brand_kit_url: str | None = None,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.product_idea = product_idea
        self.brand_kit_url = (brand_kit_url or "").strip() or None
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="app-kit-brand-"))
        work.mkdir(parents=True, exist_ok=True)
        brand_dir = work / "brand_refs"
        brand_dir.mkdir(parents=True, exist_ok=True)

        plan: dict[str, Any] = {}
        for asset in step.inputs or []:
            if (getattr(asset, "media_type", "") or "") == "application/json":
                data = asset_json(asset)
                if "screens" in data:
                    plan = data
                    break

        if self.brand_kit_url:
            context = self._from_brand_kit_url(brand_dir)
            source = "brand_kit_url"
        else:
            context = self._invent_brand(step.model or "gemini-2.5-flash")
            source = "invented"

        context["source"] = source
        context["product_name"] = self.product_name
        context["product_idea"] = self.product_idea
        context["app_type"] = plan.get("app_type") or context.get("app_type")
        context["nav_pattern"] = plan.get("nav_pattern") or context.get("nav_pattern")

        step.assets.append(
            json_file_asset(
                context,
                work_dir=work,
                name="brand-context.json",
                metadata={"kind": "brand_context"},
            )
        )
        for ref in context.get("reference_images") or []:
            path = Path(str(ref.get("path") or ""))
            if path.is_file():
                step.assets.append(
                    file_asset(
                        path,
                        media_type=_mime_for(path),
                        metadata={
                            "kind": "brand_reference",
                            "label": ref.get("label") or path.name,
                            "zip_path": f"brand/{path.name}",
                        },
                    )
                )
        step.metadata = {
            **(step.metadata or {}),
            "brand_source": source,
            "reference_count": len(context.get("reference_images") or []),
        }
        return step

    def _from_brand_kit_url(self, brand_dir: Path) -> dict[str, Any]:
        assert self.brand_kit_url
        log.info("downloading brand kit url=%s", self.brand_kit_url[:120])
        try:
            with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                resp = client.get(self.brand_kit_url)
                resp.raise_for_status()
                payload = resp.content
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to download brand_kit_url: {exc}"
            ) from exc

        if len(payload) < 64:
            raise RuntimeError("brand_kit_url returned empty or tiny payload")

        zip_path = brand_dir / "brand-kit-source.zip"
        zip_path.write_bytes(payload)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names = zf.namelist()
                extracted: list[dict[str, Any]] = []
                palette: dict[str, str] = {}
                for name in names:
                    if name.endswith("/") or ".." in name:
                        continue
                    base = Path(name).name
                    lower = base.lower()
                    data = zf.read(name)
                    if lower.endswith(".json") and (
                        "palette" in lower or "brand-guide" in lower or "guide" in lower
                    ):
                        try:
                            parsed = json.loads(data.decode("utf-8"))
                            if isinstance(parsed.get("palette"), dict):
                                palette = {
                                    str(k): str(v)
                                    for k, v in parsed["palette"].items()
                                }
                        except Exception:  # noqa: BLE001
                            pass
                    suffix = Path(base).suffix.lower()
                    if suffix not in _IMAGE_SUFFIXES:
                        continue
                    # Prefer logos / marks; skip huge banners if we already have several
                    out = brand_dir / base
                    if out.exists():
                        out = brand_dir / f"{len(extracted)}-{base}"
                    out.write_bytes(data)
                    try:
                        with Image.open(out) as im:
                            w, h = im.size
                        if max(w, h) > 2400:
                            continue
                    except Exception:  # noqa: BLE001
                        continue
                    label = "logo" if "logo" in lower or "mark" in lower else "asset"
                    extracted.append(
                        {"path": str(out.resolve()), "label": label, "name": out.name}
                    )
                    if len(extracted) >= 8:
                        break
        except zipfile.BadZipFile as exc:
            raise RuntimeError(
                "brand_kit_url did not contain a valid ZIP archive"
            ) from exc

        if not extracted and not palette:
            raise RuntimeError(
                "brand kit ZIP had no usable images or palette — cannot style UI"
            )

        if not palette:
            palette = {
                "primary": "#111827",
                "secondary": "#6B7280",
                "accent": "#0F766E",
                "light": "#F9FAFB",
                "dark": "#030712",
            }

        return {
            "palette": palette,
            "typography": {
                "heading": "System UI",
                "body": "System UI",
                "mood": "from-brand-kit",
            },
            "voice": f"Match the provided {self.product_name} brand kit visuals.",
            "reference_images": extracted,
        }

    def _invent_brand(self, model: str) -> dict[str, Any]:
        prompt = f"""You are a brand + product designer inventing a cohesive visual system for UI mockups.

Product name: "{self.product_name}"
Product idea:
\"\"\"{self.product_idea}\"\"\"

Return ONLY JSON (no example.com placeholder brands):
{{
  "palette": {{
    "primary": "#RRGGBB",
    "secondary": "#RRGGBB",
    "accent": "#RRGGBB",
    "light": "#RRGGBB",
    "dark": "#RRGGBB"
  }},
  "typography": {{
    "heading": "font family name",
    "body": "font family name",
    "mood": "kebab-mood"
  }},
  "voice": "one sentence visual/product tone for UI screens"
}}"""
        log.info("inventing brand context model=%s", model)
        resp = chat_with_retry(model, prompt=prompt, api_key=self.api_key or None)
        text = getattr(resp, "text", None) or str(resp)
        data = _parse_json_object(text)
        palette = data.get("palette") if isinstance(data.get("palette"), dict) else {}
        typography = (
            data.get("typography") if isinstance(data.get("typography"), dict) else {}
        )
        return {
            "palette": {
                "primary": str(palette.get("primary") or "#111827"),
                "secondary": str(palette.get("secondary") or "#6B7280"),
                "accent": str(palette.get("accent") or "#2563EB"),
                "light": str(palette.get("light") or "#F9FAFB"),
                "dark": str(palette.get("dark") or "#030712"),
            },
            "typography": {
                "heading": str(typography.get("heading") or "Inter"),
                "body": str(typography.get("body") or "Inter"),
                "mood": str(typography.get("mood") or "modern"),
            },
            "voice": str(data.get("voice") or "Clean, modern product UI."),
            "reference_images": [],
        }


def _mime_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")


def _parse_json_object(text: str) -> dict[str, Any]:
    import re

    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {}
        data = json.loads(raw[start : end + 1])
    return data if isinstance(data, dict) else {}
