from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import (
    asset_json,
    bytes_file_asset,
    read_asset_bytes,
    slugify,
)
from founderblaze.brand_kit.fonts_provider import build_typography_html

log = logging.getLogger("founderblaze.brand_kit.zip")


class ZipProvider(SyncProvider):
    """Assemble the brand-kit zip from prior Pipeline step assets."""

    name = "brand-kit-zip"

    def __init__(
        self,
        *,
        brand_name: str,
        description: str,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.brand_name = brand_name
        self.description = description
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("ZipProvider needs prior brand-kit assets")

        entries: list[tuple[str, bytes]] = []
        analysis: dict[str, Any] = {}
        palette: dict[str, str] = {}
        typography: dict[str, Any] = {}
        fonts_summary: dict[str, Any] = {}
        chosen_concept = "chosen"
        concepts_meta: list[dict[str, Any]] = []

        for asset in step.inputs:
            mt = getattr(asset, "media_type", "") or ""
            meta = dict(getattr(asset, "metadata", None) or {})
            kind = meta.get("kind")

            if mt == "application/json":
                data = asset_json(asset)
                if "concepts" in data and "typography" in data and "palette" not in data:
                    # raw analysis
                    if "analysis" in data:
                        analysis = data.get("analysis") or analysis
                        concepts_meta = data.get("concepts") or concepts_meta
                    else:
                        analysis = data
                if "palette" in data:
                    palette = data.get("palette") or palette
                    typography = data.get("typography") or typography
                    chosen_concept = str(
                        data.get("chosen_concept") or chosen_concept
                    )
                if "css_url" in data or "css" in data:
                    fonts_summary = data
                    typography = data.get("typography") or typography
                continue

            zip_path = meta.get("zip_path")
            if zip_path:
                entries.append((str(zip_path), read_asset_bytes(asset)))
                continue

            if kind == "logo_concept":
                cid = meta.get("concept_id") or "concept"
                entries.append((f"concepts/{cid}.png", read_asset_bytes(asset)))
                continue

            if kind == "chosen_logo":
                # Also ensure concepts include chosen if missing — skip duplicate zip root
                continue

        # Typography CSS / HTML
        css = fonts_summary.get("css") or ""
        css_url = fonts_summary.get("css_url")
        if css:
            entries.append(("typography.css", css.encode("utf-8")))
        entries.append(
            (
                "typography.html",
                build_typography_html(
                    self.brand_name,
                    typography,
                    css_url,
                    bool((fonts_summary.get("heading") or {}).get("available")),
                    bool((fonts_summary.get("body") or {}).get("available")),
                ).encode("utf-8"),
            )
        )

        if not analysis and concepts_meta:
            analysis = {"concepts": concepts_meta, "typography": typography}

        brand_guide = {
            "brandName": self.brand_name,
            "description": self.description,
            "chosenConcept": chosen_concept,
            "concepts": (analysis.get("concepts") if analysis else concepts_meta) or [],
            "palette": palette,
            "typography": {
                **typography,
                "googleFontsStylesheet": css_url,
                "heading": {
                    "family": typography.get("heading"),
                    "onGoogleFonts": bool(
                        (fonts_summary.get("heading") or {}).get("available")
                    ),
                    "files": [
                        f"fonts/heading-{n}"
                        for n in (fonts_summary.get("heading") or {}).get("files") or []
                    ],
                },
                "body": {
                    "family": typography.get("body"),
                    "onGoogleFonts": bool(
                        (fonts_summary.get("body") or {}).get("available")
                    ),
                    "files": [
                        f"fonts/body-{n}"
                        for n in (fonts_summary.get("body") or {}).get("files") or []
                    ],
                },
            },
        }
        entries.append(
            ("brand-guide.json", json.dumps(brand_guide, indent=2).encode("utf-8"))
        )
        if analysis:
            entries.append(
                ("analysis.json", json.dumps(analysis, indent=2).encode("utf-8"))
            )

        # Deduplicate by zip path (last wins)
        by_path: dict[str, bytes] = {}
        for path, data in entries:
            by_path[path] = data

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-zip-"))
        work.mkdir(parents=True, exist_ok=True)
        slug = slugify(self.brand_name)
        zip_path = work / f"{slug}-brand-kit.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path, data in sorted(by_path.items()):
                zf.writestr(path, data)

        step.assets.append(
            bytes_file_asset(
                zip_path.read_bytes(),
                suffix=".zip",
                media_type="application/zip",
                work_dir=work,
                name=zip_path.name,
                metadata={
                    "kind": "brand_kit_zip",
                    "brand_name": self.brand_name,
                    "chosen_concept": chosen_concept,
                    "palette": palette,
                    "typography": brand_guide["typography"],
                    "entry_count": len(by_path),
                },
            )
        )
        log.info(
            "zip ready path=%s entries=%s",
            zip_path,
            len(by_path),
        )
        step.metadata = {
            **(step.metadata or {}),
            "chosen_concept": chosen_concept,
            "palette": palette,
            "typography": brand_guide["typography"],
        }
        return step
