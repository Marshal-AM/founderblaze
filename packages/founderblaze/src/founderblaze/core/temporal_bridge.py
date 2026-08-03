from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

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


def make_threadsafe_heartbeat(
    heartbeat: Callable[..., Any],
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    timeout: float = 10.0,
) -> Callable[[str], None]:
    """Wrap ``activity.heartbeat`` so it is safe from ``asyncio.to_thread`` workers.

    Async Temporal activities install a heartbeat that uses ``asyncio.create_task``.
    Calling it directly from a worker thread raises ``RuntimeError: no running event
    loop`` and Temporal never receives the heartbeat (activity timeout → retry).
    """
    loop = loop or asyncio.get_running_loop()
    # Capture activity ContextVars while still on the activity task.
    ctx = contextvars.copy_context()

    def _safe_heartbeat(label: str) -> None:
        def _call() -> None:
            heartbeat(label)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            ctx.run(_call)
            return

        async def _run() -> None:
            ctx.run(_call)

        fut = asyncio.run_coroutine_threadsafe(_run(), loop)
        try:
            fut.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("heartbeat failed: %s", exc)

    return _safe_heartbeat


@contextmanager
def heartbeat_keepalive(
    heartbeat: Callable[[str], Any],
    *,
    interval: float = 30.0,
    label: str = "keepalive",
) -> Iterator[None]:
    """Emit periodic heartbeats while a long pipeline step has no completions."""
    stop = threading.Event()

    def _run() -> None:
        while not stop.wait(interval):
            try:
                heartbeat(label)
            except Exception as exc:  # noqa: BLE001
                log.warning("keepalive heartbeat failed: %s", exc)

    thread = threading.Thread(
        target=_run,
        name="temporal-heartbeat-keepalive",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=max(5.0, interval + 1.0))
