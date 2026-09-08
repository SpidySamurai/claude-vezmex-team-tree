"""Normalize Claude Code hook payloads into canonical runtime state.

Claude-specific field names stay in this module. Transcript paths, prompts,
token tallies, artifacts, and profile directories are deliberately not read
here: they remain legacy Claude features owned by the hook entrypoints.
"""

from __future__ import annotations

import time
from typing import Any

from .. import ids, model, store

RUNTIME = "claude"
COLLECTOR = "claude-code-hooks"

_SESSION_EVENTS = {"SessionStart", "SessionEnd"}
_ACTIVITY_EVENTS = {"SubagentStart", "SubagentStop"}


def _source() -> dict[str, str]:
    return model.source(RUNTIME, COLLECTOR, "hook", "direct")


def _capabilities() -> dict[str, str]:
    # Claude reports every live child through SubagentStart/SubagentStop, so its
    # activity view is complete. History and artifacts stay legacy-owned.
    return model.capabilities(
        presence="supported",
        status="partial",
        activity="complete",
        completion="supported",
        history="legacy-only",
        artifacts="legacy-only",
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _ingest_session(event_name: str, raw_session: str, now: float) -> bool:
    ended = event_name == "SessionEnd"
    result = store.update_session(
        model.Session(
            RUNTIME,
            raw_session,
            presence="ended" if ended else "present",
            status="ended" if ended else "unknown",
            observed_at=now,
            heartbeat_at=now,
            expires_at=None if ended else now + model.DEFAULT_TTL_SECONDS,
            capabilities=_capabilities(),
            source=_source(),
        ),
        only_if_present=ended,
    )
    return ids.session_id(RUNTIME, raw_session) in result.sessions


def _ingest_activity(event_name: str, raw_session: str, raw_activity: str, name: str | None, now: float) -> bool:
    if event_name == "SubagentStop":
        # A finished child leaves the live view, matching the legacy state file.
        store.remove_activity(RUNTIME, raw_session, raw_activity)
        return True
    store.update_activity(
        model.Activity(
            RUNTIME,
            raw_session,
            raw_activity,
            name or raw_activity,
            status="working",
            observed_at=now,
            heartbeat_at=now,
            expires_at=now + model.DEFAULT_TTL_SECONDS,
            source=_source(),
        ),
        session_capabilities=_capabilities(),
        session_source=_source(),
    )
    return True


def ingest(event: Any, *, now: float | None = None) -> bool:
    """Apply one hook payload; return whether canonical state was updated."""
    if not isinstance(event, dict):
        return False
    event_name = _text(event.get("hook_event_name"))
    raw_session = _text(event.get("session_id"))
    if not event_name or not raw_session:
        return False
    now = time.time() if now is None else now
    if event_name in _SESSION_EVENTS:
        return _ingest_session(event_name, raw_session, now)
    if event_name in _ACTIVITY_EVENTS:
        raw_activity = _text(event.get("agent_id"))
        if not raw_activity:
            return False
        return _ingest_activity(event_name, raw_session, raw_activity, _text(event.get("agent_type")), now)
    return False


def ingest_quietly(event: Any) -> None:
    """Ingest without ever failing the surrounding hook."""
    try:
        ingest(event)
    except Exception:  # noqa: BLE001 - observability must never break a hook.
        pass
