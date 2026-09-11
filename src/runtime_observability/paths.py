"""Paths for the additive canonical snapshot under the existing plugin state root."""

from __future__ import annotations

import os
from pathlib import Path

# Deliberately frozen to the plugin's old id (`local.claude-vezmex-team-tree`)
# for state compatibility with existing installs — this is NOT the plugin id.
# Do not rename this directory when the plugin id changes; doing so would
# orphan every user's existing history, artifacts, and profiles.
PLUGIN_STATE_DIR = Path("herdr") / "claude-vezmex-team-tree"
SNAPSHOT_FILE = "runtime-observability.json"
LOCK_FILE = ".runtime-observability.lock"
LEGACY_SUBAGENTS_FILE = "subagents.json"


def state_root() -> Path:
    home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return home / PLUGIN_STATE_DIR


def ensure_state_root() -> Path:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def snapshot_path() -> Path:
    return state_root() / SNAPSHOT_FILE


def lock_path() -> Path:
    return state_root() / LOCK_FILE


def legacy_subagents_path() -> Path:
    return state_root() / LEGACY_SUBAGENTS_FILE
