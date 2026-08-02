from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("founderblaze.apd.browser")

WARMUP_PROMPT = (
    "Confirm the page has fully loaded and is interactive. "
    "Do not click, type, scroll, or navigate. Reply briefly when ready."
)

# Firecrawl interact timeout (seconds). SDK default is 30; demos need more headroom.
INTERACT_TIMEOUT_S = 90


def _is_transient(err: BaseException) -> bool:
    msg = str(err)
    status = getattr(err, "status_code", None) or getattr(err, "status", None)
    if status in (404, 409):
        return True
    resp = getattr(err, "response", None)
    if resp is not None and getattr(resp, "status_code", None) in (404, 409):
        return True
    return bool(
        re.search(
            r"job not found|not found|replay context unavailable|try again",
            msg,
            re.I,
        )
    )


class ScreencastRecorder:
    """CDP screencast that can be fully detached around Firecrawl interact calls.

    Holding ``Page.startScreencast`` / an active Playwright CDP session while
    calling ``interact(prompt=...)`` starves Firecrawl's browser agent — the
    live view sits idle and the HTTP call hangs. We disconnect before each
    interact and reconnect after so the agent can drive the page.
    """

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []
        self.browser = None
        self.cdp = None
        self.page = None
        self.running = False
        self._pw = None
        self._cdp_url: str | None = None

    async def start(self, cdp_url: str) -> None:
        from playwright.async_api import async_playwright

        self._cdp_url = cdp_url
        if self._pw is None:
            self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.connect_over_cdp(cdp_url)
        context = self.browser.contexts[0]
        self.page = context.pages[0]
        self.cdp = await context.new_cdp_session(self.page)
        self.running = True

        async def on_frame(params: dict[str, Any]) -> None:
            if not self.running:
                return
            try:
                data = base64.b64decode(params["data"])
                self.frames.append({"ts": int(time.time() * 1000), "data": data})
                sid = params.get("sessionId")
                if sid is not None and self.cdp:
                    await self.cdp.send("Page.screencastFrameAck", {"sessionId": sid})
            except Exception as exc:  # noqa: BLE001
                log.warning("screencast frame error: %s", exc)

        self.cdp.on("Page.screencastFrame", on_frame)
        await self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 85, "everyNthFrame": 2},
        )
        log.info("CDP screencast attached frames=%s", len(self.frames))

    async def detach(self) -> None:
        """Release CDP so Firecrawl's interact agent can own the browser."""
        self.running = False
        try:
            if self.cdp:
                try:
                    await self.cdp.send("Page.stopScreencast")
                except Exception as exc:  # noqa: BLE001
                    log.warning("stopScreencast: %s", exc)
        finally:
            try:
                if self.browser:
                    await self.browser.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("browser.close: %s", exc)
            self.cdp = None
            self.browser = None
            self.page = None
        log.info("CDP detached for interact (kept frames=%s)", len(self.frames))

    async def stop(self) -> list[dict[str, Any]]:
        await self.detach()
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self._pw = None
        log.info("screencast stopped frames=%s", len(self.frames))
        return self.frames

    async def snapshot(self) -> None:
        """Grab one JPEG while attached (bridges gaps around interact)."""
        if not self.page:
            return
        try:
            data = await self.page.screenshot(type="jpeg", quality=85)
            self.frames.append({"ts": int(time.time() * 1000), "data": data})
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot failed: %s", exc)


class BrowserExecutor:
    """Sync façade around Firecrawl + async Playwright screencast.

    Playwright runs on a dedicated background event loop. CDP is detached for
    every ``interact`` call so Firecrawl's agent receives the instruction.
    """

    def __init__(self, api_key: str) -> None:
        from firecrawl import Firecrawl

        self.client = Firecrawl(api_key=api_key)
        self.scrape_id: str | None = None
        self.recorder = ScreencastRecorder()
        self._frames: list[dict[str, Any]] = []
        self._step_results: list[dict[str, Any]] = []
        self._interaction_stopped = False
        self._cdp_url: str | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name="apd-playwright-loop",
            daemon=True,
        )
        self._thread.start()

    def _run(self, coro, *, timeout: float = 120.0):  # noqa: ANN001
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    def scrape(self, url: str) -> None:
        log.info("firecrawl scrape %s", url)
        if hasattr(self.client, "scrape"):
            result = self.client.scrape(url, formats=["markdown"])
        else:
            result = self.client.scrape_url(url)
        scrape_id = _pick_scrape_id(result)
        if not scrape_id:
            raise RuntimeError(f"Firecrawl scrape did not return scrapeId: {result!r}")
        self.scrape_id = str(scrape_id)
        self._interaction_stopped = False
        log.info("scrape_id=%s", self.scrape_id)
        time.sleep(2.0)

    def warmup(self) -> str:
        last_err: Exception | None = None
        for attempt in range(1, 7):
            try:
                if attempt > 1:
                    time.sleep(min(8.0, 1.0 * (2 ** (attempt - 2))))
                res = self._interact(WARMUP_PROMPT)
                cdp = _extract_cdp(res)
                live = _extract_live(res)
                if live:
                    log.info("live_view=%s", live)
                if cdp:
                    self._cdp_url = cdp
                    log.info("warmup OK cdp=%s", cdp[:90])
                    return cdp
                raise RuntimeError(f"No cdpUrl in interact response: {res!r}")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if not _is_transient(exc) and attempt > 2:
                    raise
                log.warning("warmup attempt %s: %s", attempt, exc)
        raise RuntimeError(f"warmup failed: {last_err}")

    def start_recording(self, cdp_url: str) -> None:
        self._cdp_url = cdp_url
        self._run(self.recorder.start(cdp_url), timeout=60.0)
        self._run(self.recorder.snapshot(), timeout=15.0)
        time.sleep(0.3)

    def run_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for step in steps:
            sid = int(step["id"])
            instruction = str(step["instruction"])
            log.info("step %s interact: %s", sid, instruction[:160])
            start = int(time.time() * 1000)
            err: str | None = None
            output = ""
            success = False
            live = None
            try:
                # CRITICAL: release CDP before interact or the Firecrawl agent
                # never receives the prompt (live view stays idle, HTTP hangs).
                if self.recorder.browser or self.recorder.running:
                    try:
                        self._run(self.recorder.snapshot(), timeout=15.0)
                    except Exception:  # noqa: BLE001
                        pass
                    self._run(self.recorder.detach(), timeout=30.0)

                res = self._interact_with_retry(instruction, attempts=3)
                output = str(_pick(res, "output") or "")[:4000]
                success = _pick(res, "success") is not False
                live = _extract_live(res)
                cdp = _extract_cdp(res) or self._cdp_url
                if _pick(res, "error"):
                    err = str(_pick(res, "error"))
                    success = False
                if live:
                    log.info("step %s live_view=%s", sid, live)

                # Re-attach screencast after the agent finishes this step.
                if cdp and (success or not err):
                    self._cdp_url = cdp
                    self._run(self.recorder.start(cdp), timeout=60.0)
                    self._run(self.recorder.snapshot(), timeout=15.0)

                log.info(
                    "step %s done success=%s frames=%s output=%s",
                    sid,
                    success and not err,
                    len(self.recorder.frames),
                    (output[:80] + "…") if len(output) > 80 else output,
                )
            except Exception as exc:  # noqa: BLE001
                err = str(exc)
                log.warning("step %s failed: %s", sid, err)
                # Best-effort reattach so later steps / teardown still work.
                if self._cdp_url and not self.recorder.browser:
                    try:
                        self._run(self.recorder.start(self._cdp_url), timeout=60.0)
                    except Exception as re_exc:  # noqa: BLE001
                        log.warning("reattach after fail: %s", re_exc)
            end = int(time.time() * 1000)
            results.append(
                {
                    "id": sid,
                    "instruction": instruction,
                    "start": start,
                    "end": end,
                    "output": output,
                    "success": success and not err,
                    "liveViewUrl": live,
                    "error": err,
                    "duration": max(0, (end - start) / 1000.0),
                }
            )
        self._step_results = results
        return results

    def stop_recording(self) -> list[dict[str, Any]]:
        self._frames = self._run(self.recorder.stop(), timeout=60.0)
        return self._frames

    def save_frames(self, directory: str) -> None:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        for i, frame in enumerate(self._frames):
            (d / f"frame_{i:06d}.jpg").write_bytes(frame["data"])

    def save_step_log(self, path: str) -> None:
        Path(path).write_text(json.dumps(self._step_results, indent=2), encoding="utf-8")

    def close_session(self, reason: str) -> None:
        log.info("close session: %s", reason)
        try:
            if self.recorder.running or self.recorder.browser or self.recorder._cdp_url:
                self.stop_recording()
        except Exception as exc:  # noqa: BLE001
            log.warning("recorder stop: %s", exc)
        if self.scrape_id and not self._interaction_stopped:
            try:
                if hasattr(self.client, "stop_interaction"):
                    self.client.stop_interaction(self.scrape_id)
                elif hasattr(self.client, "stopInteraction"):
                    self.client.stopInteraction(self.scrape_id)
                self._interaction_stopped = True
                log.info("firecrawl interaction stopped scrape_id=%s", self.scrape_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("stop_interaction: %s", exc)
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
        except Exception:
            pass
        try:
            if not self._loop.is_closed():
                self._loop.close()
        except Exception:
            pass

    def _interact_with_retry(self, prompt: str, *, attempts: int = 3) -> Any:
        last_err: Exception | None = None
        for i in range(1, attempts + 1):
            try:
                if i > 1:
                    time.sleep(min(8.0, 1.0 * (2 ** (i - 2))))
                return self._interact(prompt)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                log.warning("interact attempt %s/%s failed: %s", i, attempts, exc)
                if not _is_transient(exc) or i == attempts:
                    break
        assert last_err is not None
        raise last_err

    def _interact(self, prompt: str) -> Any:
        assert self.scrape_id
        if not hasattr(self.client, "interact"):
            raise RuntimeError("Firecrawl client has no interact method")
        log.info(
            "firecrawl interact POST scrape_id=%s timeout=%ss chars=%s",
            self.scrape_id,
            INTERACT_TIMEOUT_S,
            len(prompt),
        )
        # Keyword-only prompt — never pass a dict as positional `code`.
        return self.client.interact(
            self.scrape_id,
            prompt=prompt,
            timeout=INTERACT_TIMEOUT_S,
        )


def _pick(obj: Any, *keys: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
        return None
    for k in keys:
        if hasattr(obj, k):
            val = getattr(obj, k)
            if val is not None:
                return val
    if hasattr(obj, "model_dump"):
        try:
            return _pick(obj.model_dump(), *keys)
        except Exception:
            pass
    return None


def _pick_scrape_id(result: Any) -> str | None:
    meta = _pick(result, "metadata", "metadata_typed") or {}
    sid = _pick(meta, "scrapeId", "scrape_id") or _pick(
        result, "id", "scrapeId", "scrape_id"
    )
    return str(sid) if sid else None


def _extract_cdp(res: Any) -> str | None:
    val = _pick(res, "cdpUrl", "cdp_url")
    return str(val) if val else None


def _extract_live(res: Any) -> str | None:
    val = _pick(res, "liveViewUrl", "live_view_url")
    return str(val) if val else None
