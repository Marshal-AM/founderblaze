"""Curated Google Fonts allowlist for brand kits (ported from TS)."""

from __future__ import annotations

HEADING_FONTS: tuple[str, ...] = (
    "Fraunces",
    "Playfair Display",
    "Libre Baskerville",
    "Lora",
    "Merriweather",
    "Source Serif 4",
    "Cormorant Garamond",
    "DM Serif Display",
    "Space Grotesk",
    "Outfit",
    "Sora",
    "Manrope",
    "Poppins",
    "Montserrat",
    "Raleway",
    "Syne",
    "Archivo",
    "Bebas Neue",
    "Oswald",
    "Anton",
    "JetBrains Mono",
    "IBM Plex Mono",
)

BODY_FONTS: tuple[str, ...] = (
    "Inter",
    "Source Sans 3",
    "Nunito Sans",
    "DM Sans",
    "IBM Plex Sans",
    "Work Sans",
    "Karla",
    "Lato",
    "Open Sans",
    "Roboto",
    "Noto Sans",
    "Mulish",
    "Figtree",
    "Plus Jakarta Sans",
    "Lexend",
    "Literata",
    "Source Serif 4",
    "Lora",
    "IBM Plex Mono",
    "JetBrains Mono",
)

_HEADING_SET = {f.lower() for f in HEADING_FONTS}
_BODY_SET = {f.lower() for f in BODY_FONTS}


def _find_canonical(name: str | None, list_: tuple[str, ...], set_: set[str]) -> str | None:
    raw = (name or "").strip()
    if not raw:
        return None
    if raw.lower() in set_:
        return next(f for f in list_ if f.lower() == raw.lower())
    compact = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
    for f in list_:
        if f.lower().replace(" ", "").replace("-", "").replace("_", "") == compact:
            return f
    return None


def canonicalize_heading_font(name: str | None) -> str:
    return _find_canonical(name, HEADING_FONTS, _HEADING_SET) or HEADING_FONTS[8]


def canonicalize_body_font(name: str | None) -> str:
    return _find_canonical(name, BODY_FONTS, _BODY_SET) or BODY_FONTS[0]
