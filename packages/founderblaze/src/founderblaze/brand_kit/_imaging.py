"""Shared imaging / asset helpers used inside SyncProviders."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from genblaze_core import Asset
from PIL import Image, ImageDraw, ImageFont


def step_delay_seconds() -> float:
    raw = os.environ.get("BRANDKIT_STEP_DELAY_MS") or os.environ.get(
        "VERTEX_STEP_DELAY_MS", "3000"
    )
    try:
        return max(0.0, float(raw) / 1000.0)
    except ValueError:
        return 3.0


def wait_between_steps(label: str = "") -> None:
    delay = step_delay_seconds()
    if delay > 0:
        time.sleep(delay)


def path_from_asset(asset: Asset) -> Path:
    url = getattr(asset, "url", None)
    url_s = str(getattr(url, "url", None) or url or "")
    if url_s.startswith("file:"):
        parsed = urlparse(url_s)
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)
    raise ValueError(f"Expected file:// asset URL, got: {url_s[:120]}")


def read_asset_bytes(asset: Asset) -> bytes:
    meta = getattr(asset, "metadata", None) or {}
    if isinstance(meta, dict) and isinstance(meta.get("bytes_b64"), str):
        import base64

        return base64.b64decode(meta["bytes_b64"])
    return path_from_asset(asset).read_bytes()


def json_file_asset(
    data: dict[str, Any],
    *,
    work_dir: Path,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    """Write JSON to disk — ObjectStorageSink rejects ``text:`` URLs."""
    payload = json.dumps(data, indent=2)
    meta = {
        "text": payload,
        "json": data,
        **(metadata or {}),
    }
    return bytes_file_asset(
        payload.encode("utf-8"),
        suffix=".json",
        media_type="application/json",
        work_dir=work_dir,
        name=name if name.endswith(".json") else f"{name}.json",
        metadata=meta,
    )


def file_asset(
    path: Path,
    *,
    media_type: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return Asset(
        url=path.resolve().as_uri(),
        media_type=media_type,
        sha256=digest,
        metadata=metadata or {},
    )


def bytes_file_asset(
    data: bytes,
    *,
    suffix: str,
    media_type: str,
    work_dir: Path,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> Asset:
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / name
    if not path.suffix:
        path = path.with_suffix(suffix)
    path.write_bytes(data)
    return file_asset(path, media_type=media_type, metadata=metadata)


def asset_json(asset: Asset) -> dict[str, Any]:
    meta = getattr(asset, "metadata", None) or {}
    if isinstance(meta, dict) and isinstance(meta.get("json"), dict):
        return dict(meta["json"])
    text = ""
    if isinstance(meta, dict) and isinstance(meta.get("text"), str):
        text = meta["text"]
    else:
        try:
            text = read_asset_bytes(asset).decode("utf-8")
        except Exception:  # noqa: BLE001
            text = ""
    return json.loads(text) if text.strip() else {}


def extract_palette(logo_bytes: bytes) -> dict[str, str]:
    """Approximate Vibrant-style palette from logo bytes via Pillow."""
    img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    # Flatten onto white so transparent logos still yield colors.
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3] if "A" in img.getbands() else None)
    small = bg.resize((80, 80), Image.Resampling.LANCZOS)
    pixels = [p for p in small.getdata() if not _near_white(p) and not _near_black(p)]
    if not pixels:
        pixels = list(small.getdata())
    counts = Counter(pixels).most_common(12)
    colors = [c[0] for c in counts]

    def hex_of(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

    def pick(n: int, fallback: str) -> str:
        return hex_of(colors[n]) if len(colors) > n else fallback

    vibrant = max(colors, key=lambda c: _saturation(c), default=(17, 17, 17))
    muted = min(colors, key=lambda c: _saturation(c), default=(102, 102, 102))
    dark = min(colors, key=lambda c: _luma(c), default=(10, 10, 10))
    light = max(colors, key=lambda c: _luma(c), default=(245, 245, 245))
    return {
        "primary": hex_of(vibrant),
        "secondary": hex_of(muted) if muted != vibrant else pick(1, "#666666"),
        "accent": pick(2, hex_of(dark)),
        "light": hex_of(light) if _luma(light) > 180 else "#F5F5F5",
        "dark": hex_of(dark) if _luma(dark) < 80 else "#0A0A0A",
    }


def _near_white(rgb: tuple[int, int, int], thresh: int = 245) -> bool:
    return rgb[0] >= thresh and rgb[1] >= thresh and rgb[2] >= thresh


def _near_black(rgb: tuple[int, int, int], thresh: int = 12) -> bool:
    return rgb[0] <= thresh and rgb[1] <= thresh and rgb[2] <= thresh


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(rgb: tuple[int, int, int]) -> float:
    r, g, b = [x / 255 for x in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == 0:
        return 0.0
    return (mx - mn) / mx


def normalize_hex(hex_s: str | None) -> str | None:
    h = (hex_s or "").strip()
    if not h:
        return None
    if not h.startswith("#"):
        h = f"#{h}"
    if re.fullmatch(r"#[0-9a-fA-F]{3}", h):
        h = "#" + "".join(c * 2 for c in h[1:])
    if re.fullmatch(r"#[0-9a-fA-F]{6}", h):
        return h.upper()
    return None


def readable_text_color(hex_s: str) -> str:
    h = normalize_hex(hex_s) or "#111111"
    r = int(h[1:3], 16) / 255
    g = int(h[3:5], 16) / 255
    b = int(h[5:7], 16) / 255

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return "#111111" if L > 0.5 else "#FFFFFF"


def render_palette_png(
    palette: dict[str, str],
    *,
    brand_name: str = "",
    width: int = 1600,
    height: int = 520,
) -> bytes:
    order = ["primary", "secondary", "accent", "dark", "light"]
    entries: list[tuple[str, str]] = []
    for role in order:
        hx = normalize_hex(palette.get(role))
        if hx:
            entries.append((role, hx))
    for role, val in palette.items():
        if role in order:
            continue
        hx = normalize_hex(val)
        if hx:
            entries.append((role, hx))
    if not entries:
        entries = [("primary", "#111111")]

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    block_w = width / len(entries)
    try:
        font_role = ImageFont.truetype("arial.ttf", 20)
        font_hex = ImageFont.truetype("arial.ttf", 34)
        font_title = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font_role = font_hex = font_title = ImageFont.load_default()

    for i, (role, hx) in enumerate(entries):
        x0 = int(i * block_w)
        x1 = int((i + 1) * block_w) + 1
        draw.rectangle([x0, 0, x1, height], fill=hx)
        tc = readable_text_color(hx)
        draw.text((x0 + 34, height - 110), role.upper(), fill=tc, font=font_role)
        draw.text((x0 + 34, height - 70), hx, fill=tc, font=font_hex)

    if brand_name:
        draw.text((34, 24), f"{brand_name} — Color palette", fill="#111111", font=font_title)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_typography_png(
    *,
    typography: dict[str, Any],
    brand_name: str = "",
    heading_font_bytes: bytes | None = None,
    body_font_bytes: bytes | None = None,
    work_dir: Path | None = None,
) -> bytes:
    width, height = 1600, 900
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    heading = str(typography.get("heading") or "System Sans")
    body = str(typography.get("body") or "System Sans")

    heading_font = _load_font_bytes(heading_font_bytes, size=64, work_dir=work_dir, tag="h")
    body_font = _load_font_bytes(body_font_bytes, size=28, work_dir=work_dir, tag="b")
    try:
        label_font = ImageFont.truetype("arial.ttf", 18)
        name_font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        label_font = name_font = ImageFont.load_default()

    y = 48
    if brand_name:
        draw.text((48, y), f"{brand_name} — Typography", fill="#111111", font=name_font)
        y += 56
    draw.text((48, y), "HEADING", fill="#888888", font=label_font)
    y += 28
    draw.text((48, y), heading, fill="#444444", font=name_font)
    y += 40
    draw.text((48, y), brand_name or "Brand Name", fill="#111111", font=heading_font)
    y += 90
    draw.text((48, y), "Bold headlines that set the tone", fill="#222222", font=heading_font)
    y += 110
    draw.text((48, y), "BODY", fill="#888888", font=label_font)
    y += 28
    draw.text((48, y), body, fill="#444444", font=name_font)
    y += 40
    sample = (
        "The quick brown fox jumps over the lazy dog. "
        "Pack my box with five dozen liquor jugs."
    )
    draw.text((48, y), sample, fill="#222222", font=body_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_font_bytes(
    data: bytes | None,
    *,
    size: int,
    work_dir: Path | None,
    tag: str,
) -> ImageFont.ImageFont:
    if data and work_dir is not None:
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / f"_font_{tag}.ttf"
        path.write_bytes(data)
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("arial.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def resize_logo_png(logo_bytes: bytes, size: int) -> bytes:
    img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    ox = (size - img.width) // 2
    oy = (size - img.height) // 2
    canvas.paste(img, (ox, oy), img)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def make_favicon_ico(png_sizes: dict[int, bytes]) -> bytes:
    images = []
    for size in (16, 32, 48):
        data = png_sizes.get(size)
        if not data:
            continue
        images.append(Image.open(io.BytesIO(data)).convert("RGBA"))
    if not images:
        raise RuntimeError("no icon sizes for favicon.ico")
    buf = io.BytesIO()
    images[0].save(
        buf,
        format="ICO",
        sizes=[(im.width, im.height) for im in images],
        append_images=images[1:],
    )
    return buf.getvalue()


def crop_cover(png_bytes: bytes, width: int, height: int) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    src_w, src_h = img.size
    scale = max(width / src_w, height / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    img = img.crop((left, top, left + width, top + height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def slugify(value: str) -> str:
    s = value.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    return s or "brand"


def chosen_logo_assets(logo_assets: list[Asset], pick: int) -> tuple[Asset, list[Asset]]:
    concepts = [
        a
        for a in logo_assets
        if (getattr(a, "media_type", "") or "").startswith("image/")
        and isinstance(getattr(a, "metadata", None), dict)
        and (a.metadata or {}).get("kind") == "logo_concept"
    ]
    if not concepts:
        concepts = [
            a
            for a in logo_assets
            if (getattr(a, "media_type", "") or "").startswith("image/")
        ]
    if not concepts:
        raise RuntimeError("no logo concept assets")
    idx = pick if 0 <= pick < len(concepts) else 0
    return concepts[idx], concepts
