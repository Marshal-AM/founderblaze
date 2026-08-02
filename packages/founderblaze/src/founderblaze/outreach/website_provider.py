from __future__ import annotations

import logging
import os
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.outreach._assets import json_file_asset
from founderblaze.outreach.exa_client import create_exa_client, fetch_website_context
from founderblaze.outreach.gemini_chat import gemini_text

log = logging.getLogger("founderblaze.outreach.website")


class WebsiteAnalyzeProvider(SyncProvider):
    """Exa page contents → Gemini product summary."""

    name = "outreach-website"

    def __init__(
        self,
        *,
        website_url: str,
        api_key: str | None = None,
        exa_api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.website_url = website_url
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.exa_api_key = exa_api_key
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.0-flash")
        exa = create_exa_client(self.exa_api_key)
        ctx = fetch_website_context(exa, self.website_url)
        log.info("website context chars=%s title=%s", len(ctx["text"]), ctx.get("title"))

        summary = gemini_text(
            f"""Company URL: {ctx["url"]}
Page title: {ctx.get("title") or "(unknown)"}

Website content from Exa:
\"\"\"{ctx["text"]}\"\"\"

Return only:
1) Product name (if clear)
2) What it does (1–2 sentences)
3) Who it is for
4) Notable product capabilities (bullets, max 4)

If the content is empty or unusable, reply exactly: UNREACHABLE_SITE""",
            model=model,
            api_key=self.api_key,
            system=(
                "You are a concise product analyst. Use the provided website "
                "content (fetched via Exa) to summarize what the company sells. "
                "Prefer primary site content. Keep the summary to 3–5 sentences "
                "plus short bullets. No fluff."
            ),
        )
        if not summary or "UNREACHABLE_SITE" in summary.upper():
            raise RuntimeError(
                f"Could not extract product content from {ctx['url']}. "
                "Provide a publicly reachable company website."
            )

        payload = {
            "url": ctx["url"],
            "model": model,
            "toolsUsed": ["exa_get_contents"],
            "productSummary": summary,
            "exaTitle": ctx.get("title"),
            "exaHighlightCount": len(ctx.get("highlights") or []),
        }
        work = Path(self.work_dir or ".")
        step.assets.append(
            json_file_asset(
                payload,
                work_dir=work,
                name="website",
                metadata={"kind": "outreach_website"},
            )
        )
        return step
