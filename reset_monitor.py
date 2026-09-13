"""Opt-in reset notifications with persisted, content-free deduplication."""

from __future__ import annotations

import asyncio
import hashlib
import json

from .client import AihotError
from .formatter import format_codex_resets

RESET_STATE_KV = "aihot_reset_watch"
POLL_SECONDS = 300


def _fingerprint(event: dict) -> str:
    # Scan timestamps and bookkeeping edits alone must not send notifications.
    content = {
        key: value
        for key, value in event.items()
        if key not in ("id", "createdAt", "updatedAt")
    }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class ResetMonitor:
    """Own one session subscription and acknowledge only successful sends."""

    def __init__(
        self, client, *, load_state, save_state, delete_state, send, logger
    ) -> None:
        self.client = client
        self._load_state = load_state
        self._save_state = save_state
        self._delete_state = delete_state
        self._send = send
        self._logger = logger
        self.state: dict | None = None
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def restore(self) -> None:
        state = await self._load_state(RESET_STATE_KV, None)
        if state is None:
            return
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or not isinstance(state.get("target"), str)
            or not state["target"].strip()
            or not isinstance(state.get("fingerprints"), dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in state["fingerprints"].items()
            )
        ):
            self._logger.warning("AI HOT reset watch state is invalid; not restored.")
            return
        self.state = state
        self._start()

    def _start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="aihot-reset-watch")

    async def enable(self, target: str) -> None:
        if not target.strip():
            raise ValueError("target session is required")
        async with self._lock:
            if self.state and self.state["target"] == target:
                self._start()
                return
            data = await self.client.get_codex_resets()
            state = {
                "version": 1,
                "target": target,
                "fingerprints": {
                    event["id"]: _fingerprint(event) for event in data["events"]
                },
            }
            await self._save_state(RESET_STATE_KV, state)
            self.state = state
            self._start()

    async def disable(self) -> None:
        async with self._lock:
            await self._delete_state(RESET_STATE_KV)
            self.state = None

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while True:
            # Delay after each completed check, including backoff and delivery.
            await asyncio.sleep(POLL_SECONDS)
            try:
                await self.poll()
            except Exception as exc:  # noqa: BLE001 - keep monitoring after failures
                self._logger.error("AI HOT reset watch check failed: %s", exc)

    async def poll(self) -> None:
        async with self._lock:
            if self.state is None:
                return
            data = await self.client.get_codex_resets()
            target = self.state["target"]
            previous = self.state["fingerprints"]
            # Replace the full snapshot so withdrawn entries do not linger.
            current = {event["id"] for event in data["events"]}
            acknowledged = {k: v for k, v in previous.items() if k in current}
            for event in data["events"]:
                fingerprint = _fingerprint(event)
                if previous.get(event["id"]) == fingerprint:
                    continue
                text = format_codex_resets(
                    {**data, "events": [event]}, 1, notification=True
                )
                delivered = await self._send(target, text)
                if delivered is False:
                    raise AihotError("No platform accepted the reset notification")
                acknowledged[event["id"]] = fingerprint
                # Persist each success so a later send failure retries only the rest.
                state = {**self.state, "fingerprints": dict(acknowledged)}
                await self._save_state(RESET_STATE_KV, state)
                self.state = state
            state = {**self.state, "fingerprints": acknowledged}
            if state != self.state:
                await self._save_state(RESET_STATE_KV, state)
                self.state = state
