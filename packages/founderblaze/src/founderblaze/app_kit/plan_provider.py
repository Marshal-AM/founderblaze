from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core import Modality, ProviderCapabilities, SyncProvider
from genblaze_google import chat

from founderblaze.app_kit._assets import json_file_asset

log = logging.getLogger("founderblaze.app_kit.plan")


class PlanScreensProvider(SyncProvider):
    """Gemini TEXT: information architecture + ordered screen list for the app."""

    name = "app-kit-plan"

    def __init__(
        self,
        *,
        product_name: str,
        product_idea: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_name = product_name
        self.product_idea = product_idea
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_modalities=[Modality.TEXT])

    def generate(self, step, config=None):  # noqa: ANN001
        if self.api_key:
            os.environ.setdefault("GEMINI_API_KEY", self.api_key)

        prompt = f"""You are a principal product designer planning a complete mobile + desktop app IA.

Product name: "{self.product_name}"
Product idea:
\"\"\"{self.product_idea}\"\"\"

Design a COMPLETE mini information architecture for this product — not a single generic screen.
Include typically 6–10 screens covering onboarding/auth, core loops, detail views, account/settings,
and at least one empty or error state when it fits the product.

Rules:
- Every screen must be specific to THIS product (names, entities, primary actions).
- id: short kebab-case unique id (e.g. "home", "session-player", "settings").
- title: human label for the screen.
- purpose: one sentence why the screen exists.
- key_ui: 3–6 concrete UI elements/sections that must appear.
- nav: how users reach this screen (e.g. "bottom tab Home", "stack from home card").

Return ONLY JSON:
{{
  "app_type": "short category label",
  "nav_pattern": {{
    "desktop": "e.g. left sidebar + top bar",
    "mobile": "e.g. bottom tabs + stack"
  }},
  "screens": [
    {{
      "id": "home",
      "title": "Home",
      "purpose": "...",
      "key_ui": ["...", "..."],
      "nav": "..."
    }}
  ]
}}"""

        model = step.model or "gemini-2.5-flash"
        log.info("planning app screens model=%s product=%s", model, self.product_name)
        resp = chat(model, prompt=prompt, api_key=self.api_key or None)
        text = getattr(resp, "text", None) or str(resp)
        plan = _parse_plan(text)
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="app-kit-plan-"))
        work.mkdir(parents=True, exist_ok=True)
        step.assets.append(
            json_file_asset(
                plan,
                work_dir=work,
                name="screen-plan.json",
                metadata={"kind": "screen_plan"},
            )
        )
        step.metadata = {
            **(step.metadata or {}),
            "product_name": self.product_name,
            "screen_count": len(plan.get("screens") or []),
        }
        return step


def _parse_plan(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(f"plan step returned non-JSON: {text[:400]}") from None
        data = json.loads(raw[start : end + 1])

    screens = data.get("screens") or []
    if not isinstance(screens, list) or len(screens) < 4:
        raise RuntimeError("plan must include at least 4 screens")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, s in enumerate(screens[:12]):
        if not isinstance(s, dict):
            continue
        sid = re.sub(r"[^a-z0-9-]+", "-", str(s.get("id") or f"screen-{i}").lower()).strip("-")
        if not sid or sid in seen:
            sid = f"screen-{i}"
        seen.add(sid)
        key_ui = s.get("key_ui") or []
        if not isinstance(key_ui, list):
            key_ui = [str(key_ui)]
        cleaned.append(
            {
                "id": sid,
                "title": str(s.get("title") or sid),
                "purpose": str(s.get("purpose") or ""),
                "key_ui": [str(x) for x in key_ui][:8],
                "nav": str(s.get("nav") or ""),
            }
        )
    if len(cleaned) < 4:
        raise RuntimeError("plan produced fewer than 4 valid screens")
    return {
        "app_type": str(data.get("app_type") or "product app"),
        "nav_pattern": data.get("nav_pattern")
        if isinstance(data.get("nav_pattern"), dict)
        else {
            "desktop": "left sidebar + top bar",
            "mobile": "bottom tabs + stack",
        },
        "screens": cleaned,
    }
