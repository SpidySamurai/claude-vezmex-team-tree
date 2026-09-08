"""Shared reader that joins Herdr-visible leaders to canonical or legacy state.

Precedence is Herdr-native children, then canonical runtime snapshots, then legacy
subagents.json when the visible runtime/session pair is unambiguous.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import ids, legacy, model, store


@dataclass
class ActivityView:
    id: str
    name: str
    status: str
    source: str = "unknown"
    started: float | None = None


@dataclass
class LeaderView:
    runtime: str
    raw_session_id: str | None
    pane_id: str | None
    status: str
    source: str = "unknown"
    activities: list[ActivityView] = field(default_factory=list)
    verified_zero_active: bool = False


@dataclass
class ReaderResult:
    leaders: list[LeaderView]
    canonical_available: bool = True


def _session_id_for(agent: dict[str, Any]) -> str | None:
    value = agent.get("agent_session")
    if isinstance(value, dict):
        value = value.get("value")
    return value if isinstance(value, str) and value else None


def _visible_agents(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    focused = snapshot.get("focused_workspace_id")
    agents = snapshot.get("agents")
    if not isinstance(agents, list):
        return []
    visible = []
    for agent in agents:
        if not isinstance(agent, dict) or agent.get("agent") not in model.ALLOWED_RUNTIMES:
            continue
        if focused and agent.get("workspace_id") not in (None, focused):
            continue
        visible.append(agent)
    return visible


def _native_children(agent: dict[str, Any]) -> list[ActivityView]:
    raw = agent.get("subagents") or agent.get("children") or []
    if not isinstance(raw, list):
        return []
    children = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        child_id = str(item.get("id") or item.get("agent_id") or index)
        name = str(item.get("name") or item.get("agent") or item.get("label") or f"subagent-{index + 1}")
        status = model.normalize_status(item.get("agent_status") or item.get("status") or item.get("state"))
        children.append(ActivityView(child_id, name, status, "herdr"))
    return children


def _activity_view(activity: dict[str, Any], status: str) -> ActivityView:
    started = activity.get("started_at")
    return ActivityView(
        str(activity.get("id", "")),
        str(activity.get("name") or activity.get("raw_activity_id") or "activity"),
        status,
        "canonical",
        started if isinstance(started, (int, float)) else None,
    )


def _by_name(activities: list[ActivityView]) -> list[ActivityView]:
    return sorted(activities, key=lambda child: (child.name.casefold(), child.id))


def children_for_session(raw_session_id: str | None, *, now: float | None = None) -> list[ActivityView]:
    """Live children for one raw agent session, canonical first then legacy.

    This is the per-session entry point the Herdr surfaces use. Terminal-state
    interpretation stays with the caller, which owns its own ended handling.
    """
    if not isinstance(raw_session_id, str) or not raw_session_id:
        return []
    now = time.time() if now is None else now
    canonical = store.read_snapshot()
    if canonical.available:
        matches = [
            record
            for runtime in model.ALLOWED_RUNTIMES
            if isinstance(record := canonical.sessions.get(ids.session_id(runtime, raw_session_id)), dict)
            and _is_fresh(record, now)
        ]
        if len(matches) > 1:
            # Two runtimes claiming one raw session id is ambiguous, not mergeable.
            return []
        if matches:
            record = matches[0]
            activities = [
                _activity_view(activity, model.normalize_status(activity.get("status")) if _is_fresh(activity, now) else "unknown")
                for activity in (record.get("activities") or {}).values()
                if isinstance(activity, dict)
            ]
            if activities:
                return _by_name(activities)
            caps = record.get("capabilities") if isinstance(record.get("capabilities"), dict) else {}
            if caps.get("activity") == "complete":
                # A fresh collector with complete coverage proving zero children is
                # a verified empty, not missing evidence to fill in from legacy.
                return []
    return [
        ActivityView(child["id"], child["name"], child["agent_status"], "legacy", child.get("started"))
        for child in legacy.children_for_session(raw_session_id)
    ]


def _is_fresh(record: dict[str, Any], now: float) -> bool:
    if record.get("status") == "ended" or record.get("presence") == "ended":
        return True
    expires = record.get("expires_at")
    if isinstance(expires, (int, float)):
        return now <= expires
    observed = record.get("observed_at")
    return isinstance(observed, (int, float)) and now <= observed + model.DEFAULT_TTL_SECONDS


def _canonical(agent: dict[str, Any], sessions: dict[str, dict[str, Any]], now: float) -> LeaderView | None:
    runtime = agent.get("agent")
    raw_session = _session_id_for(agent)
    if runtime not in model.ALLOWED_RUNTIMES or not raw_session:
        return None
    record = sessions.get(ids.session_id(runtime, raw_session))
    if not isinstance(record, dict):
        return None
    fresh = _is_fresh(record, now)
    ended = record.get("status") == "ended" or record.get("presence") == "ended"
    if not fresh and not ended:
        # A stale snapshot is not eligible, so it must not preempt the legacy fallback.
        return None
    status = "ended" if ended else model.normalize_status(record.get("status"))
    activities = []
    for activity in (record.get("activities") or {}).values():
        if not isinstance(activity, dict):
            continue
        child_status = model.normalize_status(activity.get("status")) if fresh and _is_fresh(activity, now) else "unknown"
        if ended and child_status in {"working", "unknown"}:
            child_status = "interrupted"
        activities.append(_activity_view(activity, child_status))
    caps = record.get("capabilities") if isinstance(record.get("capabilities"), dict) else {}
    verified_zero = fresh and caps.get("activity") == "complete" and not activities
    return LeaderView(runtime, raw_session, agent.get("pane_id"), status, "canonical", sorted(activities, key=lambda c: (c.name.casefold(), c.id)), verified_zero)


def read_agents(snapshot: dict[str, Any], *, now: float | None = None) -> ReaderResult:
    now = time.time() if now is None else now
    agents = _visible_agents(snapshot)
    canonical = store.read_snapshot()
    collisions: set[str] = set()
    by_session: dict[str, set[str]] = {}
    for agent in agents:
        sid = _session_id_for(agent)
        if sid:
            by_session.setdefault(sid, set()).add(str(agent.get("agent")))
    collisions = {sid for sid, runtimes in by_session.items() if len(runtimes) > 1}
    leaders: list[LeaderView] = []
    for agent in agents:
        raw_session = _session_id_for(agent)
        native = _native_children(agent)
        if native:
            leaders.append(LeaderView(str(agent["agent"]), raw_session, agent.get("pane_id"), model.normalize_status(agent.get("agent_status")), "herdr", native))
            continue
        joined = _canonical(agent, canonical.sessions, now) if canonical.available else None
        if joined is not None:
            leaders.append(joined)
            continue
        if raw_session and raw_session not in collisions:
            children = [ActivityView(c["id"], c["name"], c["agent_status"], "legacy", c.get("started")) for c in legacy.children_for_session(raw_session)]
            if children:
                leaders.append(LeaderView(str(agent["agent"]), raw_session, agent.get("pane_id"), model.normalize_status(agent.get("agent_status")), "legacy", children))
                continue
        leaders.append(LeaderView(str(agent["agent"]), raw_session, agent.get("pane_id"), model.normalize_status(agent.get("agent_status")), "unknown"))
    return ReaderResult(leaders, canonical.available)
