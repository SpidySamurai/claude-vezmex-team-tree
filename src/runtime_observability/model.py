"""Canonical runtime-observability vocabulary and record helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from . import ids

SCHEMA = "herdr.runtime_observability.snapshot"
SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 30.0
ALLOWED_RUNTIMES = {"claude", "codex", "pi"}
STATUSES = {"working", "idle", "blocked", "done", "ended", "interrupted", "unknown"}
PRESENCES = {"present", "ended", "unknown"}
FRESHNESSES = {"fresh", "stale", "unknown"}
CAPABILITY_VALUES = {"supported", "unsupported", "unavailable", "legacy-only", "complete", "partial", "unknown"}

_STATUS_ALIASES = {
    "running": "working", "active": "working", "pending": "working", "in_progress": "working", "started": "working",
    "complete": "done", "completed": "done", "success": "done", "succeeded": "done", "stopped": "done",
    "failed": "blocked", "failure": "blocked", "error": "blocked", "errored": "blocked", "waiting": "blocked",
    "needs_attention": "blocked",
}


def normalize_status(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    status = value.strip().lower().replace("-", "_")
    if status in STATUSES:
        return status
    return _STATUS_ALIASES.get(status, "unknown")


def normalize_presence(value: Any) -> str:
    return value if isinstance(value, str) and value in PRESENCES else "unknown"


def normalize_capability(value: Any) -> str:
    return value if isinstance(value, str) and value in CAPABILITY_VALUES else "unknown"


def capabilities(**overrides: str) -> dict[str, str]:
    caps = {
        "presence": "unknown", "status": "unknown", "activity": "unknown",
        "completion": "unknown", "history": "unknown", "artifacts": "unknown",
    }
    for key, value in overrides.items():
        if key not in caps:
            raise ValueError(f"unsupported capability key: {key}")
        if value not in CAPABILITY_VALUES:
            raise ValueError(f"unsupported capability: {value}")
        caps[key] = value
    return caps


def source(runtime: str, collector: str = "unknown", kind: str = "unknown", confidence: str = "unknown") -> dict[str, str]:
    if runtime not in ALLOWED_RUNTIMES:
        raise ValueError("unsupported runtime")
    return {"runtime": runtime, "collector": collector, "kind": kind, "confidence": confidence}


@dataclass
class Activity:
    runtime: str
    raw_session_id: str
    raw_activity_id: str
    name: str
    status: str = "unknown"
    observed_at: float | None = None
    heartbeat_at: float | None = None
    expires_at: float | None = None
    freshness: str = "unknown"
    source: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        session = ids.session_id(self.runtime, self.raw_session_id)
        data = asdict(self)
        data["id"] = ids.activity_id(session, self.raw_activity_id)
        data["status"] = normalize_status(self.status)
        data["freshness"] = self.freshness if self.freshness in FRESHNESSES else "unknown"
        return data


@dataclass
class Session:
    runtime: str
    raw_session_id: str
    presence: str = "unknown"
    status: str = "unknown"
    observed_at: float | None = None
    heartbeat_at: float | None = None
    expires_at: float | None = None
    freshness: str = "unknown"
    capabilities: dict[str, str] = field(default_factory=capabilities)
    source: dict[str, str] = field(default_factory=dict)
    activities: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["id"] = ids.session_id(self.runtime, self.raw_session_id)
        data["presence"] = normalize_presence(self.presence)
        data["status"] = normalize_status(self.status)
        data["capabilities"] = {k: normalize_capability(v) for k, v in self.capabilities.items()}
        return data
