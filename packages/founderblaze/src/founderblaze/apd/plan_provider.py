from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Asset, Modality, ProviderCapabilities, SyncProvider
from genblaze_google import chat

log = logging.getLogger("founderblaze.apd.plan")


class PlanProvider(SyncProvider):
    """Gemini planning step as a Genblaze SyncProvider."""

    name = "apd-plan"

    def __init__(
        self,
        *,
        website_url: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.website_url = website_url
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)
        script = step.prompt or ""
        prompt = f"""You are planning a product demo video.

Target website: {self.website_url}
Demo script / instructions from the user:
\"\"\"{script}\"\"\"

Break this into an ordered list of ATOMIC browser steps for Firecrawl's /interact API.

Rules:
- Each step's instruction must be a single clear action (click one thing, fill one field, navigate once, scroll once, etc.).
- Do NOT combine multiple actions in one instruction.
- Instructions should be natural-language prompts a browser agent can follow on the live page.
- narration_draft should be one short conversational sentence (under 12 words) for voiceover of that step.
- Start from the page already being open at the target URL (do not include a separate "open the URL" step unless navigation elsewhere is needed).
- Keep the demo focused; typically 4–12 steps unless the script clearly needs more.
- Number ids starting at 1.

Return JSON matching: {{ "steps": [ {{ "id": number, "instruction": string, "narration_draft": string }} ] }}"""

        model = step.model or "gemini-2.0-flash"
        log.info("planning with Gemini model=%s", model)
        resp = chat(model, prompt=prompt)
        text = getattr(resp, "text", None) or str(resp)
        plan = _parse_plan_json(text)

        # file:// JSON — ObjectStorageSink rejects text: URLs
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="apd-plan-"))
        work.mkdir(parents=True, exist_ok=True)
        plan_path = work / "plan.json"
        payload = json.dumps(plan, indent=2)
        plan_path.write_text(payload, encoding="utf-8")
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        step.assets.append(
            Asset(
                url=plan_path.resolve().as_uri(),
                media_type="application/json",
                sha256=digest,
                metadata={
                    "text": payload,
                    "json": plan,
                    "kind": "apd_plan",
                    "website_url": self.website_url,
                },
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "website_url": self.website_url,
            "step_count": len(plan.get("steps", [])),
        }
        return step


def _parse_plan_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return json.loads(fence.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"Could not parse plan JSON from model output: {text[:200]}")
