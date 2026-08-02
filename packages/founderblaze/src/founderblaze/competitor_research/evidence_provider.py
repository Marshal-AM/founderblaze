from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.competitor_research._assets import find_input_json, json_file_asset
from founderblaze.competitor_research.page_fetch import fetch_vendor_evidence

log = logging.getLogger("founderblaze.competitor_research.evidence")


class GatherEvidenceProvider(SyncProvider):
    """Per product+competitor: Jina/HTTP homepage + features + pricing → evidence.json."""

    name = "competitor-research-evidence"

    def __init__(self, *, work_dir: str | None = None) -> None:
        super().__init__()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        found = find_input_json(list(step.inputs or []), "competitors")
        product_name = str(found["product_name"])
        product_url = str(found["product_url"])
        competitors = list(found.get("competitors") or [])[:5]

        targets = [{"key": product_name, "url": product_url}]
        targets.extend({"key": c["name"], "url": c["url"]} for c in competitors)

        evidence: dict[str, Any] = {}
        for t in targets:
            log.info("fetching evidence key=%s url=%s", t["key"], t["url"])
            evidence[t["key"]] = fetch_vendor_evidence(t["url"], max_chars=4200)

        payload = {
            "product_name": product_name,
            "product_url": product_url,
            "competitors": competitors,
            "evidence": evidence,
        }
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=Path(self.work_dir or "."),
                name="evidence",
                metadata={"kind": "evidence"},
            )
        )
        return step
