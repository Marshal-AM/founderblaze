from __future__ import annotations

import hashlib

from genblaze_core import Asset


def text_asset(text: str, *, media_type: str = "text/plain") -> Asset:
    """Genblaze text Asset recipe (llm-calls.md ChatStep pattern)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return Asset(
        url=f"text:{digest}",
        media_type=media_type,
        sha256=digest,
        metadata={"text": text},
    )
