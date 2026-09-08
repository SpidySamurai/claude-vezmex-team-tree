#!/usr/bin/env python3
"""Profile-aware replacement for the ``claude`` executable used by Herdr."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def state_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return state_home / "herdr" / "claude-vezmex-team-tree" / "profiles.json"


def resume_id(arguments: list[str]) -> str | None:
    for index, argument in enumerate(arguments[:-1]):
        if argument == "--resume":
            return arguments[index + 1]
    return None


def profile_for(session_id: str) -> str | None:
    try:
        state: dict[str, Any] = json.loads(state_path().read_text(encoding="utf-8"))
        session = state.get("sessions", {}).get(session_id, {})
        profile = session.get("config_dir") if isinstance(session, dict) else None
        return profile if isinstance(profile, str) and profile else None
    except (OSError, ValueError, TypeError):
        return None


def real_binary() -> str | None:
    try:
        state: dict[str, Any] = json.loads(state_path().read_text(encoding="utf-8"))
        binary = state.get("real_claude")
        return binary if isinstance(binary, str) and os.path.isfile(binary) else None
    except (OSError, ValueError, TypeError):
        return None


def main() -> int:
    binary = real_binary()
    if not binary:
        print("claude profile wrapper: original Claude binary is unavailable", file=sys.stderr)
        return 127
    if session_id := resume_id(sys.argv[1:]):
        if profile := profile_for(session_id):
            os.environ["CLAUDE_CONFIG_DIR"] = profile
            print(f"herdr: resuming Claude session with profile {profile}", file=sys.stderr)
    os.execv(binary, [binary, *sys.argv[1:]])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
