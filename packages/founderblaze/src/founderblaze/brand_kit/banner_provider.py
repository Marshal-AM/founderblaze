from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import (
    asset_json,
    bytes_file_asset,
    chosen_logo_assets,
    crop_cover,
    read_asset_bytes,
    wait_between_steps,
)

log = logging.getLogger("founderblaze.brand_kit.banners")

BANNERS: list[dict[str, Any]] = [
    {
        "name": "og-image-1200x630.png",
        "width": 1200,
        "height": 630,
        "aspect_ratio": "16:9",
        "purpose": "Open Graph / social share card",
        "guidance": (
            "Design a complete share-card scene. Include the brand name once as "
            "clean typography. Leave some calm area so the composition still reads "
            "when cropped slightly."
        ),
    },
    {
        "name": "twitter-banner-1500x500.png",
        "width": 1500,
        "height": 500,
        "aspect_ratio": "16:9",
        "purpose": "Twitter / X profile banner",
        "guidance": (
            "Design a wide cinematic profile banner with atmospheric brand visuals "
            "across the full width. Keep important marks away from the extreme edges."
        ),
    },
    {
        "name": "linkedin-banner-1584x396.png",
        "width": 1584,
        "height": 396,
        "aspect_ratio": "16:9",
        "purpose": "LinkedIn company / profile banner",
        "guidance": (
            "Design a professional ultra-wide LinkedIn banner with rich visual "
            "content spanning the entire frame. Keep the composition balanced and "
            "corporate-clean."
        ),
    },
]


class BannerProvider(SyncProvider):
    """Multimodal Gemini image banners using the chosen logo as reference.

    Stock GeminiImageProvider is text-only; this wraps the same google-genai
    client / GEMINI_API_KEY path Genblaze uses.
    """

    name = "brand-kit-banners"

    def __init__(
        self,
        *,
        brand_name: str,
        description: str,
        pick: int = 0,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.brand_name = brand_name
        self.description = description
        self.pick = pick
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE],
            accepts_chain_input=True,
            supported_inputs=["image", "text"],
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)
        if not step.inputs:
            raise RuntimeError("BannerProvider needs logo + palette assets")

        logo_assets = [
            a
            for a in step.inputs
            if (getattr(a, "media_type", "") or "").startswith("image/")
        ]
        palette = {
            "primary": "#111111",
            "secondary": "#666666",
            "accent": "#222222",
            "light": "#F5F5F5",
            "dark": "#0A0A0A",
        }
        typography: dict[str, Any] = {}
        for asset in step.inputs:
            if (getattr(asset, "media_type", "") or "") == "application/json":
                data = asset_json(asset)
                if "palette" in data:
                    palette = data.get("palette") or palette
                    typography = data.get("typography") or typography

        # Prefer chosen_logo from palette step if present, else pick from logos.
        chosen = next(
            (
                a
                for a in logo_assets
                if (getattr(a, "metadata", None) or {}).get("kind") == "chosen_logo"
            ),
            None,
        )
        if chosen is None:
            chosen, _ = chosen_logo_assets(logo_assets, self.pick)
        logo_bytes = read_asset_bytes(chosen)
        mime = getattr(chosen, "media_type", None) or "image/png"

        model = step.model or "gemini-2.5-flash-image"
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-banners-"))
        work.mkdir(parents=True, exist_ok=True)

        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=self.api_key or os.environ.get("GEMINI_API_KEY"))

        for i, banner in enumerate(BANNERS):
            if i > 0:
                wait_between_steps(f"banner {i + 1}")
            prompt = _banner_prompt(
                banner,
                brand_name=self.brand_name,
                description=self.description,
                palette=palette,
                typography=typography,
            )
            log.info("generating banner=%s model=%s", banner["name"], model)
            response = client.models.generate_content(
                model=model,
                contents=[
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part.from_text(text=prompt),
                            genai_types.Part.from_bytes(
                                data=logo_bytes,
                                mime_type=mime,
                            ),
                        ],
                    )
                ],
                config=genai_types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=genai_types.ImageConfig(
                        aspect_ratio=banner["aspect_ratio"]
                    ),
                ),
            )
            raw = _extract_inline_image(response)
            if not raw:
                raise RuntimeError(f"no banner image for {banner['name']}")
            cropped = crop_cover(raw, banner["width"], banner["height"])
            step.assets.append(
                bytes_file_asset(
                    cropped,
                    suffix=".png",
                    media_type="image/png",
                    work_dir=work,
                    name=banner["name"],
                    metadata={"kind": "banner", "zip_path": f"assets/{banner['name']}"},
                )
            )
        return step


def _banner_prompt(
    banner: dict[str, Any],
    *,
    brand_name: str,
    description: str,
    palette: dict[str, str],
    typography: dict[str, Any],
) -> str:
    colors = ", ".join(
        f"{k} {v}"
        for k, v in palette.items()
        if v
    )
    return f"""Create a finished {banner['purpose']} for the brand "{brand_name}".

Brand context: {description}
Mood: {typography.get('mood') or 'modern professional'}
Typography vibe: heading {typography.get('heading') or 'clean sans'}, body {typography.get('body') or 'readable sans'}
Color direction: {colors or 'derive from the attached logo'}

{banner['guidance']}

Hard requirements:
- Fill the ENTIRE frame edge-to-edge with intentional visual content (gradients, abstract geometry, motifs, atmosphere, or brand world-building).
- Do NOT leave large empty grey/white/beige negative space.
- Do NOT place a tiny logo tile in the center of a blank field.
- Use the attached logo as brand identity reference and incorporate its mark tastefully into the composition (as a secondary or mid-ground element, not a lonely centered stamp).
- Make it look like a real marketed social banner, not a logo mockup.
- No watermarks, no UI chrome, no stock photo collage look."""


def _extract_inline_image(response: Any) -> bytes | None:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        data = getattr(inline, "data", None) if inline is not None else None
        if not data:
            continue
        if isinstance(data, str):
            return base64.b64decode(data)
        return bytes(data)
    return None
