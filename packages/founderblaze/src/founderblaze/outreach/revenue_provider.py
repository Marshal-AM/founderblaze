from __future__ import annotations

import logging
import os
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import json_file_asset, local_path
from founderblaze.outreach.gemini_chat import gemini_text
from founderblaze.outreach.sheet_loader import load_workbook

log = logging.getLogger("founderblaze.outreach.revenue")


class RevenueAnalyzeProvider(SyncProvider):
    """Gemini performance summary over the downloaded workbook."""

    name = "outreach-revenue"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        inputs = list(step.inputs or [])
        if not inputs:
            raise RuntimeError("RevenueAnalyzeProvider needs the sheet Asset")
        meta = dict(getattr(inputs[0], "metadata", None) or {})
        path = Path(meta.get("sheet_path") or "")
        if not path.is_file():
            path = local_path(getattr(inputs[0], "url", "") or "") or path
        if not path or not path.is_file():
            raise RuntimeError("Sheet file missing for revenue analysis")

        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        workbook = load_workbook(path)
        sheet_list = "\n".join(
            f'{i + 1}. "{s["sheetName"]}" — {s["rowCount"]} rows — columns: '
            f'{", ".join(s["headers"]) or "(none)"}'
            for i, s in enumerate(workbook["sheets"])
        )
        log.info(
            "analyzing workbook file=%s sheets=%s",
            workbook["fileName"],
            len(workbook["sheets"]),
        )
        summary = gemini_text(
            f"""Analyze this company revenue workbook. It contains multiple sheets — you must use ALL of them.

File: {workbook["fileName"]}
Sheets ({len(workbook["sheets"])}):
{sheet_list}

Full workbook content:
```
{workbook["text"]}
```

Return only:
1) Revenue overview (ARR/MRR/other metrics across sheets)
2) Trajectory (growth, decline, flat — with evidence)
3) Cross-sheet insights (how sheets relate; e.g. customers vs MRR vs churn)
4) Notable patterns (seasonality, concentration, segment mix if present)
5) Risks / gaps / inconsistencies across sheets
Keep it short and specific.""",
            model=model,
            api_key=self.api_key,
            system=(
                "You are a finance-minded company performance analyst. Read every "
                "sheet, cross-check related metrics, and produce one clear "
                "performance summary. Be factual. Do not invent numbers."
            ),
        )
        if not summary:
            raise RuntimeError("Sheet model returned an empty performance summary")

        payload = {
            "model": model,
            "sheet": {
                "fileName": workbook["fileName"],
                "sheetCount": len(workbook["sheets"]),
                "sheets": [
                    {
                        "sheetName": s["sheetName"],
                        "rowCount": s["rowCount"],
                        "headers": s["headers"],
                    }
                    for s in workbook["sheets"]
                ],
            },
            "performanceSummary": summary,
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="revenue",
                metadata={"kind": "outreach_revenue"},
            )
        )
        return step
