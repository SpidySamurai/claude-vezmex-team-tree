#!/usr/bin/env python3
"""Persist PostToolUse events for the built-in Artifact tool.

Confirmed live (not assumed): PostToolUse fires with tool_name == "Artifact"
and tool_input carrying the same arguments the tool call used (action,
file_path, title, url, ...). Publishing is the default action (an omitted
`action` means "publish"); passing `url` targets an existing artifact, so its
presence is what distinguishes an update from a first publish. The exact
shape of tool_response for a publish call was not directly observed here, so
any link extracted from it is best-effort and never required.
"""
from __future__ import annotations
import fcntl
import json
import os
import sys
import tempfile
import time
from pathlib import Path

STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "herdr" / "claude-vezmex-team-tree"
ARTIFACTS_PATH = STATE_ROOT / "artifacts.jsonl"
MAX_ARTIFACT_LINES = 100
PUBLISH_ACTIONS = {"publish", None}


def guess_title(tool_input: dict[str, object]) -> str:
    title = tool_input.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    file_path = tool_input.get("file_path")
    if isinstance(file_path, str) and file_path:
        return Path(file_path).stem
    return "artifact"


def guess_url(tool_response: object) -> str | None:
    if not isinstance(tool_response, dict):
        return None
    for key in ("url", "artifact_url", "publish_url"):
        value = tool_response.get(key)
        if isinstance(value, str) and value:
            return value
    return None


try:
    event = json.load(sys.stdin)
except (ValueError, OSError):
    raise SystemExit(0)
if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") != "Artifact":
    raise SystemExit(0)
tool_input = event.get("tool_input")
if not isinstance(tool_input, dict):
    raise SystemExit(0)
action = tool_input.get("action")
if action not in PUBLISH_ACTIONS:
    raise SystemExit(0)
session = str(event.get("session_id") or "")
if not session:
    raise SystemExit(0)

record = {
    "session": session,
    "title": guess_title(tool_input),
    "kind": "update" if isinstance(tool_input.get("url"), str) and tool_input.get("url") else "publish",
    "url": tool_input.get("url") or guess_url(event.get("tool_response")),
    "at": time.time(),
}

STATE_ROOT.mkdir(parents=True, exist_ok=True)
with (STATE_ROOT / ".artifacts.lock").open("w", encoding="utf-8") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    lines: list[str] = []
    try:
        lines = ARTIFACTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    lines.append(json.dumps(record, separators=(",", ":")))
    lines = lines[-MAX_ARTIFACT_LINES:]
    descriptor, temporary = tempfile.mkstemp(prefix=".artifacts.", dir=STATE_ROOT)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, ARTIFACTS_PATH)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
