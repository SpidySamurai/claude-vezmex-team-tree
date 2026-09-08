"""Atomic canonical snapshot reads and scoped updates."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Callable

from . import ids, model, paths


@dataclass
class SnapshotRead:
    available: bool
    sessions: dict[str, dict[str, Any]]
    error: str | None = None

    @property
    def snapshot(self) -> dict[str, Any]:
        return _snapshot(self.sessions)


def _snapshot(sessions: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema": model.SCHEMA,
        "schema_version": model.SCHEMA_VERSION,
        "written_at": time.time(),
        "sessions": sessions or {},
    }


def _validate(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("snapshot is not an object")
    if data.get("schema") != model.SCHEMA or data.get("schema_version") != model.SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema")
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        raise ValueError("sessions must be an object")
    valid: dict[str, dict[str, Any]] = {}
    for sid, session in sessions.items():
        if not isinstance(sid, str) or not isinstance(session, dict):
            continue
        try:
            ids.raw_session_id(sid)
        except ValueError:
            # Isolate one unreadable entry instead of discarding every valid session.
            continue
        valid[sid] = session
    return valid


def read_snapshot() -> SnapshotRead:
    try:
        return SnapshotRead(True, _validate(json.loads(paths.snapshot_path().read_text(encoding="utf-8"))))
    except FileNotFoundError:
        return SnapshotRead(True, {})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return SnapshotRead(False, {}, str(exc))


def _write_snapshot(sessions: dict[str, dict[str, Any]]) -> None:
    root = paths.ensure_state_root()
    fd, tmp = tempfile.mkstemp(prefix=".runtime-observability.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_snapshot(sessions), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, paths.snapshot_path())
        try:
            dir_fd = os.open(root, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update(mutator: Callable[[dict[str, dict[str, Any]]], None]) -> SnapshotRead:
    paths.ensure_state_root()
    with paths.lock_path().open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_snapshot()
        sessions = dict(current.sessions) if current.available else {}
        mutator(sessions)
        _write_snapshot(sessions)
        return SnapshotRead(True, sessions)


def update_session(session: model.Session) -> SnapshotRead:
    record = session.to_dict()
    sid = record["id"]

    def mutate(sessions: dict[str, dict[str, Any]]) -> None:
        existing = sessions.get(sid, {})
        activities = existing.get("activities") if isinstance(existing.get("activities"), dict) else {}
        record["activities"] = activities | record.get("activities", {})
        sessions[sid] = record

    return update(mutate)


def update_activity(activity: model.Activity) -> SnapshotRead:
    record = activity.to_dict()
    sid = ids.session_id(activity.runtime, activity.raw_session_id)

    def mutate(sessions: dict[str, dict[str, Any]]) -> None:
        session = sessions.get(sid)
        if not isinstance(session, dict):
            # Child activity is itself evidence the session exists, so seed its freshness.
            session = model.Session(
                activity.runtime,
                activity.raw_session_id,
                presence="present",
                observed_at=activity.observed_at,
                heartbeat_at=activity.heartbeat_at or activity.observed_at,
                expires_at=activity.expires_at,
            ).to_dict()
        session.setdefault("activities", {})[record["id"]] = record
        sessions[sid] = session

    return update(mutate)
