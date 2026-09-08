#!/usr/bin/env python3
"""Record exact leader -> child pane links from the Teams tmux shim trace.

The official launcher records every tmux invocation.  A child pane comes from
``split-window -t %<leader-terminal-id>``; pairing that ordered trace entry
with Herdr's subsequent ``pane.agent_detected`` event gives an explicit edge,
not a workspace-based guess.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    return Path(os.environ["HERDR_PLUGIN_STATE_DIR"])


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, ValueError):
        return fallback


def detected_pane(value: Any) -> str | None:
    if isinstance(value, dict):
        pane = value.get("pane_id")
        if isinstance(pane, str):
            return pane
        for child in value.values():
            if found := detected_pane(child):
                return found
    if isinstance(value, list):
        for child in value:
            if found := detected_pane(child):
                return found
    return None


def split_targets(trace: Path) -> list[str]:
    targets: list[str] = []
    try:
        lines = trace.read_text(encoding="utf-8").splitlines()
    except OSError:
        return targets
    for line in lines:
        try:
            event = json.loads(line)
            if event.get("event") != "verb" or event.get("verb") != "split-window":
                continue
            args = event.get("args", [])
            if "-t" in args:
                target = args[args.index("-t") + 1]
                if isinstance(target, str) and target.startswith("%"):
                    targets.append(target[1:])
        except (ValueError, IndexError, TypeError):
            continue
    return targets


def live_panes() -> list[dict[str, Any]]:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    try:
        result = subprocess.run(
            [herdr, "api", "snapshot"], capture_output=True, text=True, timeout=2, check=False
        )
        return json.loads(result.stdout)["result"]["snapshot"].get("panes", [])
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return []


def main() -> int:
    directory = state_dir()
    state_path = directory / "links.json"
    state = load_json(state_path, {"children": {}, "consumed_splits": 0})
    children = state.setdefault("children", {})
    consumed = int(state.get("consumed_splits", 0))
    event: dict[str, Any] = {}
    try:
        event = json.loads(os.environ.get("HERDR_PLUGIN_EVENT_JSON", "{}"))
    except ValueError:
        pass
    child = detected_pane(event)
    targets = split_targets(directory / "teams-trace.jsonl")
    if child and child not in children and consumed < len(targets):
        # Resolve the trace's stable terminal id to its current Herdr pane id.
        panes = live_panes()
        leader_terminal = targets[consumed]
        leader = next(
            (pane.get("pane_id") for pane in panes if pane.get("terminal_id") == leader_terminal),
            None,
        )
        if isinstance(leader, str):
            children[child] = leader
        state["consumed_splits"] = consumed + 1
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
