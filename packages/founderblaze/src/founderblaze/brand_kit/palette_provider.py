from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import (
    asset_json,
    bytes_file_asset,
    chosen_logo_assets,
    extract_palette,
    json_file_asset,
    read_asset_bytes,
)

log = logging.getLogger("founderblaze.brand_kit.palette")


class PaletteProvider(SyncProvider):
    """Extract hex palette from the chosen logo concept."""

    name = "brand-kit-palette"

    def __init__(self, *, pick: int = 0, work_dir: str | None = None) -> None:
        super().__init__()
        self.pick = pick
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("PaletteProvider needs logo step assets")
        chosen, _ = chosen_logo_assets(list(step.inputs), self.pick)
        logo_bytes = read_asset_bytes(chosen)
        palette = extract_palette(logo_bytes)
        concept_id = (getattr(chosen, "metadata", None) or {}).get("concept_id") or "chosen"

        # Recover typography from logo sidecar JSON if present.
        typography = {"heading": "Space Grotesk", "body": "Inter", "mood": "modern"}
        for asset in step.inputs:
            if (getattr(asset, "media_type", "") or "") == "application/json":
                data = asset_json(asset)
                analysis = data.get("analysis") or data
                if isinstance(analysis.get("typography"), dict):
                    typography = analysis["typography"]
                    break

        payload = {
            "palette": palette,
            "typography": typography,
            "chosen_concept": concept_id,
            "pick": self.pick,
        }
        log.info("palette extracted concept=%s palette=%s", concept_id, palette)
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-palette-"))
        # Keep a copy of the chosen logo for zip/icons/banners metadata path.
        bytes_file_asset(
            logo_bytes,
            suffix=".png",
            media_type="image/png",
            work_dir=work,
            name=f"chosen-{concept_id}.png",
            metadata={"kind": "chosen_logo", "concept_id": concept_id},
        )
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=work,
                name="palette.json",
                metadata={"kind": "palette"},
            )
        )
        # Also emit chosen logo image as an asset for fan-in consumers.
        step.assets.append(
            bytes_file_asset(
                logo_bytes,
                suffix=".png",
                media_type="image/png",
                work_dir=work,
                name=f"chosen-logo.png",
                metadata={"kind": "chosen_logo", "concept_id": concept_id},
            )
        )
        step.metadata = {**(step.metadata or {}), "chosen_concept": concept_id}
        return step
