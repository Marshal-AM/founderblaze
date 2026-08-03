from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.app_kit._assets import (
    asset_json,
    bytes_file_asset,
    read_asset_bytes,
    slugify,
)

log = logging.getLogger("founderblaze.app_kit.zip")


class ZipProvider(SyncProvider):
    """Pack mobile/ + desktop/ UI kit boards (+ brand refs) into app_kit_zip."""

    name = "app-kit-zip"

    def __init__(
        self,
        *,
        product_name: str,
        product_idea: str,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.product_idea = product_idea
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("ZipProvider needs prior app-kit assets")

        plan: dict[str, Any] = {}
        brand: dict[str, Any] = {}
        entries: list[tuple[str, bytes]] = []
        mocks: list[dict[str, Any]] = []

        for asset in step.inputs:
            mt = getattr(asset, "media_type", "") or ""
            meta = dict(getattr(asset, "metadata", None) or {})
            kind = meta.get("kind")

            if mt == "application/json":
                data = asset_json(asset)
                if "screens" in data and "palette" not in data:
                    plan = data
                if "palette" in data or kind == "brand_context":
                    brand = data
                continue

            zip_path = meta.get("zip_path")
            if zip_path and (mt.startswith("image/") or kind in {"ui_mock", "brand_reference"}):
                entries.append((str(zip_path), read_asset_bytes(asset)))
                if kind == "ui_mock":
                    mocks.append(
                        {
                            "viewport": meta.get("viewport"),
                            "title": meta.get("title"),
                            "path": zip_path,
                            "screen_ids": meta.get("screen_ids"),
                            "screen_count": meta.get("screen_count"),
                        }
                    )

        if not mocks:
            raise RuntimeError("no UI mock images to zip")

        manifest = {
            "product_name": self.product_name,
            "product_idea": self.product_idea,
            "app_type": plan.get("app_type"),
            "nav_pattern": plan.get("nav_pattern"),
            "screens": plan.get("screens") or [],
            "brand": {
                "source": brand.get("source"),
                "palette": brand.get("palette") or {},
                "typography": brand.get("typography") or {},
                "voice": brand.get("voice"),
            },
            "mocks": mocks,
        }
        entries.append(
            ("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        )
        entries.append(
            (
                "README.txt",
                (
                    f"App Kit UI boards for {self.product_name}\n\n"
                    f"mobile/ui-kit-board.png  — all phone screens on one board\n"
                    f"desktop/ui-kit-board.png — all desktop screens on one board\n"
                    f"brand/                  — brand references used (when provided)\n"
                    f"manifest.json           — screen plan + file index\n"
                ).encode("utf-8"),
            )
        )

        by_path: dict[str, bytes] = {}
        for path, data in entries:
            by_path[path] = data

        work = Path(self.work_dir or tempfile.mkdtemp(prefix="app-kit-zip-"))
        work.mkdir(parents=True, exist_ok=True)
        slug = slugify(self.product_name)
        zip_path = work / f"{slug}-app-kit.zip"
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
                    "kind": "app_kit_zip",
                    "product_name": self.product_name,
                    "mock_count": len(mocks),
                    "screen_count": len(plan.get("screens") or []),
                    "entry_count": len(by_path),
                },
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "mock_count": len(mocks),
            "screen_count": len(plan.get("screens") or []),
        }
        log.info("app-kit zip ready path=%s mocks=%s", zip_path, len(mocks))
        return step
