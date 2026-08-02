from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("founderblaze.temporal_bridge")


def make_on_step_complete(
    *,
    set_step: Callable[[str], Any] | None = None,
    heartbeat: Callable[[str], Any] | None = None,
) -> Callable[[Any], None]:
    """Map Genblaze StepCompleteEvent → job step + Temporal heartbeat."""

    def _handler(event: Any) -> None:
        step = getattr(event, "step", event)
        name = (
            getattr(step, "provider", None)
            or getattr(step, "model", None)
            or getattr(step, "id", None)
            or "step"
        )
        status = getattr(step, "status", "")
        label = f"{name}:{status}" if status else str(name)
        log.info("genblaze step complete: %s", label)
        if set_step is not None:
            try:
                set_step(str(name))
            except Exception as exc:  # noqa: BLE001
                log.warning("set_step failed: %s", exc)
        if heartbeat is not None:
            try:
                heartbeat(label)
            except Exception as exc:  # noqa: BLE001
                log.warning("heartbeat failed: %s", exc)

    return _handler
