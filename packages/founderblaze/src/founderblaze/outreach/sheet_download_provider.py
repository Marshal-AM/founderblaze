from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

import httpx
from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import file_asset

log = logging.getLogger("founderblaze.outreach.sheet")


class SheetDownloadProvider(SyncProvider):
    """Download (or copy) the revenue workbook into the work dir."""

    name = "outreach-sheet"

    def __init__(
        self,
        *,
        sheet_url: str | None = None,
        sheet_path: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.sheet_url = (sheet_url or "").strip()
        self.sheet_path = (sheet_path or "").strip()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        work = Path(self.work_dir or ".")
        work.mkdir(parents=True, exist_ok=True)
        if self.sheet_path:
            src = Path(self.sheet_path).expanduser().resolve()
            if not src.is_file():
                raise RuntimeError(f"sheet_path not found: {src}")
            dest = work / src.name
            if src != dest.resolve():
                shutil.copy2(src, dest)
            path = dest
            source = "path"
        elif self.sheet_url:
            path = _download(self.sheet_url, work)
            source = "url"
        else:
            raise RuntimeError("Provide sheet_url or sheet_path")

        log.info("sheet ready path=%s source=%s", path, source)
        step.assets.append(
            file_asset(
                path,
                media_type=_mime_for(path),
                metadata={
                    "kind": "outreach_sheet",
                    "sheet_path": str(path),
                    "source": source,
                    "sheet_url": self.sheet_url or None,
                },
            )
        )
        return step


def _download(url: str, work: Path) -> Path:
    parsed = urlparse(url)
    name = Path(parsed.path).name or "revenue.xlsx"
    if "." not in name:
        name = f"{name}.xlsx"
    dest = work / name
    log.info("downloading sheet %s", url)
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def _mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".csv":
        return "text/csv"
    if ext in {".xlsx", ".xlsm"}:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == ".xls":
        return "application/vnd.ms-excel"
    return "application/octet-stream"
