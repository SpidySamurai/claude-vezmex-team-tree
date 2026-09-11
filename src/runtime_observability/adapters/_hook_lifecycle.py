"""Shared engine behind the hook-payload adapters.

Claude Code and Codex are wired to the same lifecycle hook events and payload
shape (see install.py), but with different real-world guarantees. This module
holds the one parsing/mapping implementation; each adapter supplies only its
runtime identity, collector label, and capability declaration.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .. import ids, model, store

_SESSION_EVENTS = {"SessionStart", "SessionEnd"}
_ACTIVITY_EVENTS = {"SubagentStart", "SubagentStop"}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def make_ingest(
    runtime: str, collector: str, capabilities: Callable[[], dict[str, str]]
) -> Callable[..., bool]:
    def source() -> dict[str, str]:
        return model.source(runtime, collector, "hook", "direct")

    def ingest_session(event_name: str, raw_session: str, now: float) -> bool:
        ended = event_name == "SessionEnd"
        result = store.update_session(
            model.Session(
                runtime,
                raw_session,
                presence="ended" if ended else "present",
                status="ended" if ended else "unknown",
                observed_at=now,
                heartbeat_at=now,
                expires_at=None if ended else now + model.DEFAULT_TTL_SECONDS,
                capabilities=capabilities(),
                source=source(),
            ),
            only_if_present=ended,
        )
        return ids.session_id(runtime, raw_session) in result.sessions

    def ingest_activity(event_name: str, raw_session: str, raw_activity: str, name: str | None, now: float) -> bool:
        if event_name == "SubagentStop":
            store.remove_activity(runtime, raw_session, raw_activity)
            return True
        store.update_activity(
            model.Activity(
                runtime,
                raw_session,
                raw_activity,
                name or raw_activity,
                status="working",
                started_at=now,
                observed_at=now,
                heartbeat_at=now,
                expires_at=now + model.DEFAULT_TTL_SECONDS,
                source=source(),
            ),
            session_capabilities=capabilities(),
            session_source=source(),
        )
        return True

    def ingest(event: Any, *, now: float | None = None) -> bool:
        if not isinstance(event, dict):
            return False
        event_name = _text(event.get("hook_event_name"))
        raw_session = _text(event.get("session_id"))
        if not event_name or not raw_session:
            return False
        resolved_now = time.time() if now is None else now
        if event_name in _SESSION_EVENTS:
            return ingest_session(event_name, raw_session, resolved_now)
        if event_name in _ACTIVITY_EVENTS:
            raw_activity = _text(event.get("agent_id"))
            if not raw_activity:
                return False
            return ingest_activity(event_name, raw_session, raw_activity, _text(event.get("agent_type")), resolved_now)
        return False

    return ingest
