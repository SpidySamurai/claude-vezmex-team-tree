#!/usr/bin/env python3
"""Publish a compact Herdr agents-sidebar subagent summary token.

This plugin treats subagents as a Herdr-facing concept. Herdr remains the source
of truth for visible leader panes and native agent status. Provider adapters may
contribute child relationships when Herdr does not expose a native hierarchy yet.

Safety boundaries:
- never writes agent_status, state_text, state_icon, or display_agent;
- never reads terminal panes;
- never touches Claude profiles, settings, wrappers, or --resume behavior.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SLOT_COUNT = 6
SLOT_PREFIX = "subagent_"
STATUS_GLYPHS = {
    "done": "✓",
    "blocked": "!",
    "idle": "·",
    "unknown": "?",
}
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
POLL_SECONDS = 0.15
IDLE_GRACE_TICKS = 12  # ~1.8s of nothing working, then the animator self-exits


def herdr_bin() -> str:
    return os.environ.get("HERDR_BIN_PATH", "herdr")


# This module is also loaded directly by path, so make the sibling package
# importable before reaching for it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_observability import reader  # noqa: E402


def plugin_state_root() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return state_home / "herdr" / "claude-vezmex-team-tree"


def run_herdr(*args: str) -> dict[str, Any]:
    try:
        proc = subprocess.run([herdr_bin(), *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0 or not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def read_snapshot() -> dict[str, Any]:
    data = run_herdr("api", "snapshot")
    result = data.get("result")
    if isinstance(result, dict):
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict):
            return snapshot
    snapshot = data.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def visible_agents(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    agents = snapshot.get("agents")
    return [agent for agent in agents if isinstance(agent, dict)] if isinstance(agents, list) else []


def session_id_for(agent: dict[str, Any]) -> str | None:
    session = agent.get("agent_session")
    if isinstance(session, dict):
        value = session.get("value")
        return value if isinstance(value, str) and value else None
    return session if isinstance(session, str) and session else None


def normalize_status(value: Any) -> str:
    status = str(value or "unknown").lower()
    if status in {"working", "running", "active", "pending", "in_progress", "started"}:
        return "working"
    if status in {"done", "complete", "completed", "success", "succeeded", "stopped"}:
        return "done"
    if status in {"blocked", "failed", "failure", "error", "errored", "waiting", "needs_attention"}:
        return "blocked"
    if status == "idle":
        return "idle"
    return "unknown"


def compact_name(value: Any, fallback: str) -> str:
    name = str(value or fallback).strip()
    if not name:
        name = fallback
    return name.replace("\n", " ")[:24]


def native_children(agent: dict[str, Any]) -> list[dict[str, str]]:
    """Read future Herdr-native children if the snapshot grows such fields."""
    raw = agent.get("subagents") or agent.get("children")
    if not isinstance(raw, list):
        return []
    children: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        children.append(
            {
                "id": str(item.get("id") or item.get("agent_id") or index),
                "name": compact_name(item.get("name") or item.get("agent") or item.get("label"), f"subagent-{index + 1}"),
                "status": normalize_status(item.get("agent_status") or item.get("status") or item.get("state")),
                "source": "herdr",
            }
        )
    return children


def hook_children(agent: dict[str, Any]) -> list[dict[str, str]]:
    """Recorded subagent state for this leader, via the shared runtime reader.

    Runtime payload shapes stay inside runtime_observability, so this surface
    never parses a collector's state file itself.
    """
    children = [
        {
            "id": child.id,
            "name": compact_name(child.name, child.id),
            "status": normalize_status(child.status),
            "source": "agent-hook",
        }
        for child in reader.children_for_session(session_id_for(agent))
    ]
    return sorted(children, key=lambda child: (child["status"] != "working", child["name"].casefold(), child["id"]))


def detect_children(agent: dict[str, Any]) -> list[dict[str, str]]:
    children = native_children(agent)
    if children:
        return children
    return hook_children(agent)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def session_summary_line(session_id: str | None) -> str | None:
    """Entry-point line for the compact sidebar: how many finished subagents
    and published artifacts this session has, so far. None (cleared) when
    both are zero, matching the "nothing to show, show nothing" rule the
    subagent slots already follow.
    """
    if not session_id:
        return None
    history_count = sum(1 for r in read_jsonl(plugin_state_root() / "history.jsonl") if r.get("session") == session_id)
    artifact_count = sum(1 for r in read_jsonl(plugin_state_root() / "artifacts.jsonl") if r.get("session") == session_id)
    if not history_count and not artifact_count:
        return None
    parts = [f"historial · {history_count}"]
    if artifact_count:
        parts.append(f"{artifact_count} artifact{'s' if artifact_count != 1 else ''}")
    return " · ".join(parts)


def slot_line(child: dict[str, str], frame: int = 0) -> str:
    status = normalize_status(child.get("status"))
    glyph = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)] if status == "working" else STATUS_GLYPHS.get(status, "?")
    return f"{glyph} {child['name']}"


def report_slots(
    source: str,
    pane_id: str,
    children: list[dict[str, str]],
    frame: int = 0,
    summary: str | None = None,
) -> None:
    """Publish one token per fixed row slot, so each active child gets its own
    sidebar row (see [ui.sidebar.agents(.rows_by_agent)] in config.toml). Slots
    beyond the live child count are cleared, so a pane with no children shows
    no subagent rows at all instead of a placeholder line. The session-summary
    entry point row is reported alongside, in the same call.
    """
    args = ["pane", "report-metadata", pane_id, "--source", source]
    for index in range(SLOT_COUNT):
        name = f"{SLOT_PREFIX}{index + 1}"
        if index < len(children):
            args += ["--token", f"{name}={slot_line(children[index], frame)}"]
        else:
            args += ["--clear-token", name]
    if summary:
        args += ["--token", f"session_summary={summary}"]
    else:
        args += ["--clear-token", "session_summary"]
    run_herdr(*args)


def publish(snapshot: dict[str, Any], source: str, frame: int = 0) -> int:
    count = 0
    for agent in visible_agents(snapshot):
        pane_id = agent.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            continue
        children = detect_children(agent)[:SLOT_COUNT]
        summary = session_summary_line(session_id_for(agent))
        report_slots(source, pane_id, children, frame, summary)
        count += len(children)
    return count


def _tmp_dir() -> Path:
    base = os.environ.get("HERDR_PLUGIN_STATE_DIR") or os.environ.get("TMPDIR", "/tmp")
    directory = Path(base) / "herdr-claude-vezmex-team-tree"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory


def _lock_file() -> Path:
    return _tmp_dir() / "animator.pid"


def _already_running() -> bool:
    lock = _lock_file()
    if lock.is_file():
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)  # raises if the process is gone
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    return False


def spawn_animator() -> None:
    """(Re)start the background spinner animator unless one is already live."""
    if _already_running():
        return
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--animate"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def animate(source: str) -> int:
    """Sole animated writer: re-publishes every pane's slots on a timer so a
    working child gets a cycling spinner frame instead of a static glyph.
    Self-exits once nothing is working, so it costs nothing once idle.
    """
    lock = _lock_file()
    lock.write_text(str(os.getpid()))
    stop_file = _tmp_dir() / "animator.stop"
    stop_file.unlink(missing_ok=True)

    def _bye(*_: Any) -> None:
        lock.unlink(missing_ok=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _bye)

    frame = 0
    idle_ticks = 0
    try:
        while True:
            active_count = publish(read_snapshot(), source, frame)
            idle_ticks = 0 if active_count else idle_ticks + 1
            if idle_ticks >= IDLE_GRACE_TICKS or stop_file.is_file():
                break
            frame += 1
            time.sleep(POLL_SECONDS)
    finally:
        lock.unlink(missing_ok=True)
        stop_file.unlink(missing_ok=True)
    return 0


def stop_animator() -> None:
    lock = _lock_file()
    (_tmp_dir() / "animator.stop").touch()
    if lock.is_file():
        try:
            os.kill(int(lock.read_text().strip()), signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            lock.unlink(missing_ok=True)


def main() -> int:
    plugin_id = os.environ.get("HERDR_PLUGIN_ID", "spidysamurai.agents-tree")
    source = f"plugin:{plugin_id}:agent-tree"
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--animate":
        return animate(source)
    if arg == "--stop":
        stop_animator()
        return 0
    # default (startup / pane.agent_detected / pane.agent_status_changed /
    # refresh action / hook trigger): publish immediately, then make sure the
    # spinner animator is running for whatever is still working.
    publish(read_snapshot(), source)
    spawn_animator()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
