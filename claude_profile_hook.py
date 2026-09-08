#!/usr/bin/env python3
"""Record the Claude profile that owns a native Claude session ID."""
from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def state_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return state_home / "herdr" / "claude-vezmex-team-tree" / "profiles.json"


def read_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {"version": 1, "sessions": {}}
    except (OSError, ValueError):
        return {"version": 1, "sessions": {}}


def write_state(path: Path, state: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".profiles.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0
    if event.get("hook_event_name") != "SessionStart":
        return 0
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return 0

    profile = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".profiles.lock").open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state(path)
        sessions = state.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = state["sessions"] = {}
        existing = sessions.get(session_id)
        started = existing.get("started") if isinstance(existing, dict) else None
        now = time.time()
        session = {"config_dir": profile, "updated": now, "started": started if isinstance(started, (int, float)) else now}
        for field in ("cwd", "transcript_path", "source"):
            value = event.get(field)
            if isinstance(value, str) and value:
                session[field] = value
        sessions[session_id] = session
        write_state(path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
