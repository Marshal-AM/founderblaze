from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from PIL import Image

from founderblaze.pitch_deck._assets import (
    assert_slide_count,
    bytes_file_asset,
    read_asset_bytes,
    slugify,
)

log = logging.getLogger("founderblaze.pitch_deck.pdf")


class PdfCompileProvider(SyncProvider):
    """Compile ordered pitch_slide PNGs into a multipage PDF (6–8 pages)."""

    name = "pitch-deck-pdf"

    def __init__(
        self,
        *,
        product_name: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
            supported_inputs=["image", "text"],
        )

    def generate(self, step, config=None):  # noqa: ANN001
        slides: list[tuple[int, bytes]] = []
        product_name = self.product_name or "Product"

        for asset in step.inputs or []:
            mt = getattr(asset, "media_type", "") or ""
            meta = dict(getattr(asset, "metadata", None) or {})
            if meta.get("kind") == "pitch_plan" or (
                mt == "application/json" and "slides" in (meta.get("json") or {})
            ):
                data = meta.get("json") if isinstance(meta.get("json"), dict) else {}
                if data.get("product_name"):
                    product_name = str(data["product_name"])
            if mt.startswith("image/") and meta.get("kind") == "pitch_slide":
                order = int(meta.get("order") if meta.get("order") is not None else 999)
                slides.append((order, read_asset_bytes(asset)))

        slides.sort(key=lambda x: x[0])
        assert_slide_count(len(slides), where="pitch PDF compile")

        pil_images: list[Image.Image] = []
        for _, data in slides:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            pil_images.append(img)

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="pitch-deck-pdf-"))
        work.mkdir(parents=True, exist_ok=True)
        out = work / f"{slugify(product_name)}-pitch-deck.pdf"

        first, rest = pil_images[0], pil_images[1:]
        first.save(
            out,
            "PDF",
            save_all=True,
            append_images=rest,
            resolution=150.0,
        )
        for im in pil_images:
            im.close()

        pdf_bytes = out.read_bytes()
        page_count = len(slides)
        assert_slide_count(page_count, where="pitch PDF pages")

        step.assets.append(
            bytes_file_asset(
                pdf_bytes,
                suffix=".pdf",
                media_type="application/pdf",
                work_dir=work,
                name=out.name,
                metadata={
                    "kind": "pitch_deck_pdf",
                    "page_count": page_count,
                    "product_name": product_name,
                    "slide_count": page_count,
                },
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "page_count": page_count,
            "product_name": product_name,
        }
        log.info("compiled pitch deck PDF pages=%s path=%s", page_count, out)
        return step
