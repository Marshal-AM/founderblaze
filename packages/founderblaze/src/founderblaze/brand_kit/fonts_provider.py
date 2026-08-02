from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.brand_kit._imaging import asset_json, bytes_file_asset, json_file_asset

log = logging.getLogger("founderblaze.brand_kit.fonts")

CSS_BASE = "https://fonts.googleapis.com/css"


class FontsProvider(SyncProvider):
    """Resolve + download Google Fonts TTFs from analyst typography."""

    name = "brand-kit-fonts"

    def __init__(self, *, work_dir: str | None = None) -> None:
        super().__init__()
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        if not step.inputs:
            raise RuntimeError("FontsProvider needs analyze step assets")
        analysis = asset_json(step.inputs[0])
        typography = analysis.get("typography") or {}
        work = Path(self.work_dir or tempfile.mkdtemp(prefix="brand-kit-fonts-"))
        work.mkdir(parents=True, exist_ok=True)

        heading = resolve_google_font(str(typography.get("heading") or ""), weights=[600, 700])
        body = resolve_google_font(str(typography.get("body") or ""), weights=[400, 700])
        css_url = google_fonts_css_url(
            [typography.get("heading"), typography.get("body")]
        )

        for role, resolved in (("heading", heading), ("body", body)):
            for f in resolved.get("files") or []:
                step.assets.append(
                    bytes_file_asset(
                        f["buffer"],
                        suffix=".ttf",
                        media_type="font/ttf",
                        work_dir=work,
                        name=f"{role}-{f['filename']}",
                        metadata={
                            "kind": "font_file",
                            "role": role,
                            "family": resolved.get("family"),
                            "filename": f["filename"],
                            "zip_path": f"fonts/{role}-{f['filename']}",
                        },
                    )
                )

        summary: dict[str, Any] = {
            "typography": typography,
            "css_url": css_url,
            "heading": {
                "family": heading.get("family"),
                "available": heading.get("available"),
                "files": [f["filename"] for f in heading.get("files") or []],
            },
            "body": {
                "family": body.get("family"),
                "available": body.get("available"),
                "files": [f["filename"] for f in body.get("files") or []],
            },
            "css": build_typography_css(typography, css_url, heading, body),
        }
        for role, resolved in (("heading", heading), ("body", body)):
            regular = resolved.get("regular")
            if regular:
                path = work / f"{role}-regular.ttf"
                path.write_bytes(regular)
                summary[f"{role}_regular_path"] = str(path)

        step.assets.append(
            json_file_asset(
                summary,
                work_dir=work,
                name="fonts-summary.json",
                metadata={"kind": "fonts_summary"},
            )
        )
        log.info(
            "fonts heading=%s body=%s css=%s",
            heading.get("family"),
            body.get("family"),
            css_url,
        )
        return step


def family_to_param(family: str) -> str:
    return re.sub(r"\s+", "+", (family or "").strip())


def is_generic_family(family: str) -> bool:
    return bool(
        re.match(
            r"^(sans-serif|serif|monospace|cursive|system-ui|ui-.*)$",
            (family or "").strip(),
            re.I,
        )
    )


def google_fonts_css_url(
    families: list[Any],
    *,
    weights: list[int] | None = None,
    display: str = "swap",
) -> str | None:
    weights = weights or [400, 600, 700]
    list_: list[str] = []
    for f in families:
        if isinstance(f, str) and f.strip() and not is_generic_family(f):
            list_.append(f.strip())
    list_ = list(dict.fromkeys(list_))
    if not list_:
        return None
    parts = [f"{family_to_param(f)}:{','.join(str(w) for w in weights)}" for f in list_]
    return f"{CSS_BASE}?family={'|'.join(parts)}&display={display}"


def resolve_google_font(
    family: str,
    *,
    weights: list[int] | None = None,
) -> dict[str, Any]:
    weights = weights or [400, 700]
    clean = (family or "").strip()
    base: dict[str, Any] = {
        "family": clean,
        "available": False,
        "cssUrl": google_fonts_css_url([clean], weights=weights),
        "files": [],
        "regular": None,
    }
    if not clean or is_generic_family(clean):
        return base
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            url = f"{CSS_BASE}?family={family_to_param(clean)}:{','.join(map(str, weights))}"
            res = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code >= 400:
                res = client.get(
                    f"{CSS_BASE}?family={family_to_param(clean)}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if res.status_code >= 400:
                return {**base, "error": "not_found_on_google_fonts"}
            faces = _parse_font_faces(res.text)
            faces = [f for f in faces if f["style"] == "normal"]
            if not faces:
                return {**base, "error": "no_ttf_sources"}
            by_weight: dict[int, dict[str, Any]] = {}
            for face in faces:
                by_weight.setdefault(face["weight"], face)
            wanted = set(weights) | {400}
            chosen = [
                f for w, f in by_weight.items() if w in wanted or len(by_weight) <= 2
            ]
            use = chosen or list(by_weight.values())
            slug = re.sub(r"[^a-z0-9]+", "-", clean, flags=re.I).strip("-")
            files = []
            for face in use:
                fr = client.get(face["url"])
                if fr.status_code >= 400:
                    continue
                buf = fr.content
                files.append(
                    {
                        "weight": face["weight"],
                        "style": face["style"],
                        "ext": "ttf",
                        "filename": f"{slug}-{face['weight']}.ttf",
                        "buffer": buf,
                    }
                )
            if not files:
                return {**base, "error": "download_failed"}
            regular = next(
                (f["buffer"] for f in files if f["weight"] == 400),
                files[0]["buffer"],
            )
            return {
                "family": clean,
                "available": True,
                "cssUrl": base["cssUrl"],
                "files": files,
                "regular": regular,
            }
    except Exception as exc:  # noqa: BLE001
        return {**base, "error": str(exc)}


def _parse_font_faces(css: str) -> list[dict[str, Any]]:
    faces: list[dict[str, Any]] = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css):
        wm = re.search(r"font-weight:\s*(\d+)", block)
        sm = re.search(r"font-style:\s*([a-z]+)", block)
        um = re.search(r"src:\s*url\(([^)]+)\)", block)
        if not um:
            continue
        url = um.group(1).strip().strip("'\"")
        if not re.search(r"\.ttf(\?|$)", url, re.I):
            continue
        faces.append(
            {
                "weight": int(wm.group(1)) if wm else 400,
                "style": sm.group(1) if sm else "normal",
                "url": url,
            }
        )
    return faces


def build_typography_css(
    typography: dict[str, Any],
    css_url: str | None,
    heading: dict[str, Any],
    body: dict[str, Any],
) -> str:
    mood = typography.get("mood") or ""
    h_note = (
        "" if heading.get("available") else "  /* not on Google Fonts — bundled in /fonts */\n"
    )
    b_note = (
        "" if body.get("available") else "  /* not on Google Fonts — bundled in /fonts */\n"
    )
    link = (
        f'/* <link rel="stylesheet" href="{css_url}"> */'
        if css_url
        else "/* (fonts bundled locally in /fonts) */"
    )
    return f"""/* Brand typography{f' — {mood}' if mood else ''} */
/* 1) Load the fonts (hosted). Add this to your <head>: */
{link}

:root {{
{h_note}  --font-heading: {_css_quote(typography.get('heading'))}, system-ui, sans-serif;
{b_note}  --font-body: {_css_quote(typography.get('body'))}, system-ui, sans-serif;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: var(--font-heading);
  font-weight: 700;
}}

body, p, li, a, button, input {{
  font-family: var(--font-body);
  font-weight: 400;
}}
"""


def build_typography_html(
    brand_name: str,
    typography: dict[str, Any],
    css_url: str | None,
    heading_available: bool,
    body_available: bool,
) -> str:
    heading = typography.get("heading") or "system-ui"
    body = typography.get("body") or "system-ui"
    mood = typography.get("mood") or ""
    h_badge = "Google Fonts ✓" if heading_available else "bundled in /fonts"
    b_badge = "Google Fonts ✓" if body_available else "bundled in /fonts"
    link = f'<link rel="stylesheet" href="{_esc(css_url)}" />' if css_url else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{_esc(brand_name)} — Typography</title>
{link}
<style>
  body {{ margin: 0; padding: 48px; background: #fafafa; color: #111; }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  h1.sample {{ font-family: {_css_quote(heading)}, system-ui, sans-serif; font-weight: 700; font-size: 54px; }}
  p.sample {{ font-family: {_css_quote(body)}, system-ui, sans-serif; font-size: 18px; line-height: 1.6; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1 class="sample">{_esc(brand_name)}</h1>
    <p>{_esc(mood)} · heading {_esc(heading)} ({h_badge}) · body {_esc(body)} ({b_badge})</p>
    <p class="sample">The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.</p>
  </div>
</body>
</html>"""


def _css_quote(family: Any) -> str:
    clean = str(family or "").strip().replace("'", "")
    return f"'{clean}'" if clean else "'system-ui'"


def _esc(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
