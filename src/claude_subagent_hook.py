#!/usr/bin/env python3
"""Persist SubagentStart/SubagentStop lifecycle events for the Herdr panel.

Claude Code documents this hook payload shape; other agent CLIs wired to
invoke this same script (e.g. Codex) reuse it as-is, keyed only on the
generic ``session_id``/``agent_id`` fields. Both events carry the *parent*
session_id, which is the same identifier Herdr stores as ``agent_session.value``
for the leader pane, so the panel can select this data without ever reading
the agent's terminal. Unrecognized event shapes are ignored, not errored.
"""
from __future__ import annotations
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from runtime_observability.adapters import claude_code

AGENT_TREE_SCRIPT = Path(__file__).with_name("herdr_agent_tree.py")

STATE_ROOT = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "herdr" / "claude-vezmex-team-tree"
path = STATE_ROOT / "subagents.json"
HISTORY_PATH = STATE_ROOT / "history.jsonl"
MAX_HISTORY_LINES = 200


def analyze_transcript(transcript_path: str | None) -> dict[str, object]:
    """Best-effort detail for one finished subagent, read from its own
    transcript (the SubagentStop event's agent_transcript_path): the original
    task prompt (its first 'user' line — what it was actually asked to do,
    since agent_type/name is just a generic category like "general-purpose"),
    total token usage (hook payloads never include a token count directly), a
    per-tool call tally, and whether it delegated to a nested subagent of its
    own (a "Task" tool_use block). Every 'assistant' line's message.content
    list can carry zero or more tool_use blocks alongside text/thinking ones.
    """
    result: dict[str, object] = {"task": None, "tokens": 0, "tools": {}, "nested_agents": 0}
    if not transcript_path:
        return result
    task: str | None = None
    tokens = 0
    tools: dict[str, int] = {}
    nested_agents = 0
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                if task is None and entry.get("type") == "user":
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        task = content.strip()
                if entry.get("type") != "assistant":
                    continue
                usage = message.get("usage")
                if isinstance(usage, dict):
                    tokens += sum(
                        int(usage.get(key) or 0)
                        for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
                    )
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tool_name = str(block.get("name") or "?")
                    tools[tool_name] = tools.get(tool_name, 0) + 1
                    if tool_name == "Task":
                        nested_agents += 1
    except (OSError, ValueError, TypeError):
        pass
    result["task"] = task
    result["tokens"] = tokens
    result["tools"] = tools
    result["nested_agents"] = nested_agents
    return result


def append_history(record: dict[str, object]) -> None:
    """Append one completed-subagent record and trim the file so it never
    grows unbounded; the dashboard reads this for its session history.
    """
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    try:
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    lines.append(json.dumps(record, separators=(",", ":")))
    lines = lines[-MAX_HISTORY_LINES:]
    descriptor, temporary = tempfile.mkstemp(prefix=".history.", dir=STATE_ROOT)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, HISTORY_PATH)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_state() -> dict[str, object]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {"sessions": {}}
    except (OSError, ValueError):
        return {"sessions": {}}


def save_state(state: dict[str, object]) -> None:
    """Replace the state atomically so dashboard refreshes never see partial JSON."""
    descriptor, temporary = tempfile.mkstemp(prefix=".subagents.", dir=path.parent)
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


try:
    event = json.load(sys.stdin)
except (ValueError, OSError):
    raise SystemExit(0)
if event.get("hook_event_name") not in {"SubagentStart", "SubagentStop"}:
    raise SystemExit(0)
session = str(event.get("session_id") or "")
# Claude documents agent_id on both SubagentStart and SubagentStop.  tool_use_id
# belongs to tool events and must not be used as a lifecycle identity.
agent_id = str(event.get("agent_id") or "")
if not session or not agent_id:
    raise SystemExit(0)
path.parent.mkdir(parents=True, exist_ok=True)
with (path.parent / ".subagents.lock").open("w", encoding="utf-8") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    state = load_state()
    sessions = state.setdefault("sessions", {})
    if not isinstance(sessions, dict):
        sessions = state["sessions"] = {}
    agents = sessions.setdefault(session, {})
    if not isinstance(agents, dict):
        agents = sessions[session] = {}
    if event["hook_event_name"] == "SubagentStop":
        # A finished subagent is removed from the live map rather than kept
        # as "done" (the sidebar row only reflects currently active
        # subagents), but first record it in the session history log the
        # dashboard reads for its historial/token-stats view.
        finished = agents.pop(agent_id, None)
        if not agents:
            sessions.pop(session, None)
        if isinstance(finished, dict):
            started = finished.get("started")
            now = time.time()
            detail = analyze_transcript(event.get("agent_transcript_path"))
            last_message = event.get("last_assistant_message")
            append_history(
                {
                    "session": session,
                    "agent_id": agent_id,
                    "name": finished.get("name", agent_id),
                    "started": started,
                    "stopped": now,
                    "duration_s": round(now - started, 1) if isinstance(started, (int, float)) else None,
                    "task": detail["task"],
                    "tokens": detail["tokens"],
                    "tools": detail["tools"],
                    "tool_uses": sum(detail["tools"].values()),
                    "nested_agents": detail["nested_agents"],
                    "last_message": last_message if isinstance(last_message, str) else None,
                }
            )
    else:
        current = agents.get(agent_id, {})
        if not isinstance(current, dict):
            current = {}
        current.setdefault("started", time.time())
        current.update(
            {
                "name": str(event.get("agent_type") or current.get("name") or agent_id),
                "status": "working",
                "updated": time.time(),
            }
        )
        agents[agent_id] = current
    save_state(state)

# Mirror the same lifecycle into runtime-neutral canonical state. The legacy file
# above stays authoritative until the Herdr surfaces read the canonical snapshot,
# so this write is additive and safe to ignore on rollback.
claude_code.ingest_quietly(event)

# Herdr only re-runs herdr_agent_tree.py on its own pane events (startup,
# pane.agent_detected, pane.agent_status_changed) — a subagent lifecycle event
# is none of those, so nothing else republishes the sidebar token. Trigger the
# same refresh path here; a failure here must not fail this hook.
try:
    subprocess.run(
        [sys.executable, str(AGENT_TREE_SCRIPT)],
        timeout=5,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
except (OSError, subprocess.TimeoutExpired):
    pass
