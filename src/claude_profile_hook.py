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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_observability.adapters import claude_code  # noqa: E402


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
    hook_event = event.get("hook_event_name")
    if hook_event not in ("SessionStart", "SessionEnd"):
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
        now = time.time()

        if hook_event == "SessionEnd":
            # Mark the session finished so the dashboard can stop presenting
            # it as live (a frozen clock, no spinner) once the agent CLI is
            # gone. Merge rather than replace: the panel still renders this
            # record's started/cwd/transcript_path afterwards. A session we
            # never saw start is not ours to invent.
            if not isinstance(existing, dict):
                return 0
            existing["ended"] = now
            existing["updated"] = now
            write_state(path, state)
            claude_code.ingest_quietly(event)
            return 0

        started = existing.get("started") if isinstance(existing, dict) else None
        # Rebuilt from scratch on purpose: a resume of this same session drops
        # any previous "ended" mark, which is exactly right — it is live again.
        session = {"config_dir": profile, "updated": now, "started": started if isinstance(started, (int, float)) else now}
        for field in ("cwd", "transcript_path", "source"):
            value = event.get(field)
            if isinstance(value, str) and value:
                session[field] = value
        sessions[session_id] = session
        write_state(path, state)
    # Canonical presence only; profile directories stay a Claude-local concern.
    claude_code.ingest_quietly(event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
