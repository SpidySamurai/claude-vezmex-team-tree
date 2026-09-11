"""Normalize Pi extension lifecycle/tool events into canonical runtime state.

The companion Pi extension observes only its own top-level session: its own
agent loop, its own tool calls, and its own shutdown. A nested delegation such
as AskClaude is visible here only as one top-level tool call; this module
never assumes it can see inside another process's session. Verification for
these mappings is synthetic-event unit tests, per the design; no real Pi
process is required or assumed here.
"""

from __future__ import annotations

import time
from typing import Any

from .. import ids, model, store

RUNTIME = "pi"
COLLECTOR = "pi-extension"

_SIMPLE_SESSION_STATUS = {
    "session_start": "idle",
    "agent_start": "working",
    # Pi may still auto-retry, auto-compact, or run a queued follow-up after
    # agent_end, so this is not settled evidence of idle yet.
    "agent_end": "working",
    "agent_settled": "idle",
}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _source() -> dict[str, str]:
    return model.source(RUNTIME, COLLECTOR, "extension", "direct")


def _capabilities() -> dict[str, str]:
    return model.capabilities(
        presence="supported",
        status="partial",
        activity="partial",
        completion="supported",
        history="unsupported",
        artifacts="unsupported",
    )


def _session(raw_session: str, status: str, now: float, *, only_if_present: bool = False) -> bool:
    ended = status == "ended"
    result = store.update_session(
        model.Session(
            RUNTIME,
            raw_session,
            presence="ended" if ended else "present",
            status=status,
            observed_at=now,
            heartbeat_at=now,
            expires_at=None if ended else now + model.DEFAULT_TTL_SECONDS,
            capabilities=_capabilities(),
            source=_source(),
        ),
        only_if_present=only_if_present,
    )
    return ids.session_id(RUNTIME, raw_session) in result.sessions


def ingest(event: Any, *, now: float | None = None) -> bool:
    """Apply one Pi extension event; return whether canonical state was updated."""
    if not isinstance(event, dict):
        return False
    kind = _text(event.get("kind"))
    raw_session = _text(event.get("session_id"))
    if not kind or not raw_session:
        return False
    resolved_now = time.time() if now is None else now

    if kind in _SIMPLE_SESSION_STATUS:
        return _session(raw_session, _SIMPLE_SESSION_STATUS[kind], resolved_now)

    if kind == "session_shutdown":
        return _session(raw_session, "ended", resolved_now, only_if_present=True)

    if kind in {"tool_execution_start", "tool_execution_end"}:
        raw_activity = _text(event.get("tool_call_id"))
        tool_name = _text(event.get("tool_name"))
        if not raw_activity or not tool_name:
            return False
        if kind == "tool_execution_start":
            status = "working"
            started_at = resolved_now
        else:
            status = "blocked" if event.get("is_error") else "done"
            # Preserve the real start time recorded by tool_execution_start; an
            # end event must not reset the elapsed clock the dashboard renders.
            existing = store.read_snapshot().sessions.get(ids.session_id(RUNTIME, raw_session), {})
            existing_activity = (existing.get("activities") or {}).get(
                ids.activity_id(ids.session_id(RUNTIME, raw_session), raw_activity), {}
            )
            prior_started = existing_activity.get("started_at")
            started_at = prior_started if isinstance(prior_started, (int, float)) else resolved_now
        store.update_activity(
            model.Activity(
                RUNTIME,
                raw_session,
                raw_activity,
                tool_name,
                status=status,
                started_at=started_at,
                observed_at=resolved_now,
                heartbeat_at=resolved_now,
                expires_at=resolved_now + model.DEFAULT_TTL_SECONDS,
                source=_source(),
            ),
            session_capabilities=_capabilities(),
            session_source=_source(),
        )
        return True

    return False
