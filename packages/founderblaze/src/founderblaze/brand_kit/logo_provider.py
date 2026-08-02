from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from genblaze_google import GeminiImageProvider

from founderblaze.brand_kit._imaging import asset_json, json_file_asset, wait_between_steps

log = logging.getLogger("founderblaze.brand_kit.logos")


class LogoConceptsProvider(SyncProvider):
    """Generate N logo concepts via Genblaze GeminiImageProvider."""

    name = "brand-kit-logos"

    def __init__(
        self,
        *,
        brand_name: str,
        description: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.brand_name = brand_name
        self.description = description
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)
        if not step.inputs:
            raise RuntimeError("LogoConceptsProvider needs analyze step assets")
        analysis = asset_json(step.inputs[0])
        angles = list(analysis.get("concepts") or [])
        if not angles:
            raise RuntimeError("analysis has no concepts")

        model = step.model or "gemini-2.5-flash-image"
        out_dir = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-logos-"))
        out_dir.mkdir(parents=True, exist_ok=True)
        image_provider = GeminiImageProvider(
            api_key=self.api_key or None,
            output_dir=out_dir,
        )

        concept_meta: list[dict[str, Any]] = []
        for i, angle in enumerate(angles):
            if i > 0:
                wait_between_steps(f"logo concept {i + 1}")
            prompt = _logo_prompt(angle, self.brand_name, self.description)
            log.info("generating logo concept=%s model=%s", angle.get("id"), model)
            # Build a temporary step shape GeminiImageProvider expects.
            from genblaze_core.models.step import Step

            tmp = Step(
                step_id=f"{step.step_id}-logo-{i}",
                provider=image_provider.name,
                model=model,
                modality=Modality.IMAGE,
                prompt=prompt,
            )
            image_provider.generate(tmp, config)
            if not tmp.assets:
                raise RuntimeError(f"no image for logo concept {angle.get('id')}")
            asset = tmp.assets[0]
            meta = dict(getattr(asset, "metadata", None) or {})
            meta.update(
                {
                    "kind": "logo_concept",
                    "concept_id": angle.get("id"),
                    "needsText": bool(angle.get("needsText")),
                    "style": angle.get("style"),
                    "prompt": prompt,
                }
            )
            step.assets.append(asset.model_copy(update={"metadata": meta}))
            concept_meta.append(
                {
                    "id": angle.get("id"),
                    "needsText": bool(angle.get("needsText")),
                    "style": angle.get("style"),
                }
            )

        # Sidecar JSON so downstream steps can recover analysis + concept list.
        sidecar = {
            "analysis": analysis,
            "concepts": concept_meta,
            "brand_name": self.brand_name,
            "description": self.description,
        }
        step.assets.append(
            json_file_asset(
                sidecar,
                work_dir=out_dir,
                name="logos-sidecar.json",
                metadata={"kind": "logos_sidecar"},
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "concept_count": len(concept_meta),
        }
        return step


def _logo_prompt(angle: dict[str, Any], brand_name: str, description: str) -> str:
    style = str(angle.get("style") or "").strip()
    if angle.get("needsText"):
        return (
            f"Create a professional logo based on this direction: {style}\n"
            f'The brand name must appear exactly as "{brand_name}" with legible, '
            "correctly spelled lettering.\n"
            f"Brand context: {description}.\n"
            "Use a square composition, flat vector aesthetic, high contrast, "
            "and a plain white background.\n"
            "Do not add mockups, photography, 3D effects, watermarks, signatures, "
            "or extra text."
        )
    return (
        f"Create a professional icon-only logo based on this direction: {style}\n"
        f"Brand context: {description}.\n"
        "Use a square composition, flat vector aesthetic, high contrast, "
        "and a plain white background.\n"
        "Do not include any letters, words, mockups, photography, 3D effects, "
        "watermarks, or signatures."
    )
