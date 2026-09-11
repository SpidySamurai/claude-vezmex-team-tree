#!/usr/bin/env python3
"""Shared, editable settings for the agents dashboard (claude_team_tree.py)
and its opener (open_dashboard.py) — one JSON file with defaults, reloaded
fresh on every read so edits take effect without reopening the pane.

Run directly (the "Configurar dashboard" action) to open it in $EDITOR,
split below the pane the action was invoked from.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    # How much of the split the dashboard keeps vs. the pane it opened from
    # (0.28 = dashboard gets 28%). See open_dashboard.py.
    "dashboard_ratio": 0.28,
    # Most-recent subagents/artifacts shown before a "+N más" hint appears.
    # High enough that scrolling the pane (native terminal scrollback — see
    # claude_team_tree.py's redraw logic) actually reveals older ones, rather
    # than a tight cap leaving nothing printed to scroll to.
    "history_limit": 30,
    "artifacts_limit": 15,
    # Cap on the task-prompt segment in a historial detail line, so a long
    # prompt can't crowd out the tools/result that follow it.
    "task_segment_max": 32,
    # How often the dashboard checks for changes (seconds).
    "poll_seconds": 0.25,
    # "minimal" (data row only, no detail line) | "compact" (one combined
    # "task → tools → result" line, the default) | "full" (task on its own
    # line, tools/delegation/result on a second line).
    "detail_level": "compact",
    # Whether each panel section is folded away, toggled by clicking its own
    # header in the panel. Persisted (0/1) so the fold survives a reopen, and
    # deliberately NOT a menu option: the affordance is the section header.
    "history_collapsed": 0,
    "artifacts_collapsed": 0,
    # The panel's own authored copy (headers, labels, hints — never agent
    # names, tasks, or transcript text, which are data and always stay as
    # recorded). English is the default; Spanish is offered as an equivalent.
    "language": "en",
}
SECTION_KEYS = ("history_collapsed", "artifacts_collapsed")
DETAIL_LEVELS = ("minimal", "compact", "full")
LANGUAGES = ("en", "es")

# The in-panel clickable submenu cycles each of these through a short list of
# presets (see claude_team_tree.py's menu rendering / click handling) — plain
# numeric fields step through a few sane values rather than free-form editing,
# since a mouse click can only pick "the next thing", not type a number.
# Only the value options live here: closing the menu is the job of its own
# title row (which carries the "cerrar" affordance), so it is not an entry —
# one fewer row for a panel that has to fit inside a narrow side pane.
MENU_OPTIONS = ("detail_level", "history_limit", "artifacts_limit", "dashboard_ratio", "language")
# Values here are t() lookup keys (see claude_team_tree.py's STRINGS table),
# not display text — dashboard_config.py stays agnostic of panel copy so the
# menu's own label can be shown in whichever language is selected.
MENU_LABELS = {
    "detail_level": "menu_label_detail_level",
    "history_limit": "menu_label_history_limit",
    "artifacts_limit": "menu_label_artifacts_limit",
    "dashboard_ratio": "menu_label_dashboard_ratio",
    "language": "menu_label_language",
}
CYCLES: dict[str, tuple[Any, ...]] = {
    "detail_level": DETAIL_LEVELS,
    "history_limit": (10, 20, 30, 50),
    "artifacts_limit": (5, 10, 15, 25),
    "dashboard_ratio": (0.20, 0.28, 0.35, 0.45),
    "language": LANGUAGES,
}


def cycle_value(key: str, current: Any, step: int = 1) -> Any:
    """Next value in the option's preset list, or the previous one for a
    negative `step` — a right-click steps backwards so overshooting a
    four-entry cycle costs one click instead of three.
    """
    options = CYCLES[key]
    try:
        index = options.index(current)
    except ValueError:
        index = -1 if step > 0 else 0
    return options[(index + step) % len(options)]


def cycle_position(key: str, current: Any) -> tuple[int, int]:
    """1-based position of `current` in its cycle, and the cycle's length —
    what the menu shows as "(2/3)" so a click is not a blind step into an
    unknown-length list. An unrecognized value reports position 0.
    """
    options = CYCLES[key]
    try:
        return options.index(current) + 1, len(options)
    except ValueError:
        return 0, len(options)


def config_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return state_home / "herdr" / "claude-vezmex-team-tree" / "config.json"


def load_config() -> dict[str, Any]:
    """Defaults merged with whatever the file has — a missing file, an
    unreadable one, or an unknown/malformed key never breaks the caller;
    it just falls back to that key's default.
    """
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    merged = dict(DEFAULTS)
    for key, value in data.items():
        if key not in DEFAULTS:
            continue
        if key == "detail_level":
            if value not in DETAIL_LEVELS:
                continue
        elif key == "language":
            if value not in LANGUAGES:
                continue
        elif not isinstance(value, (int, float)):
            continue
        merged[key] = value
    return merged


def save_config(config: dict[str, Any]) -> None:
    """Write the whole merged config back out — used by the in-panel
    clickable submenu when a click cycles one value.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def ensure_config_file() -> Path:
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        commented = (
            "// Edit and save — the dashboard reloads this on every refresh, no restart needed.\n"
            "// detail_level: \"minimal\" | \"compact\" | \"full\"\n"
            "// language: \"en\" | \"es\"\n"
        )
        # Plain JSON can't carry comments; keep them in a sibling README-ish
        # file instead so this stays valid JSON an editor won't complain about.
        (path.parent / "config.README.txt").write_text(commented, encoding="utf-8")
        path.write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    path = ensure_config_file()
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        print("This action must be invoked from a Herdr pane.", file=sys.stderr)
        return 2
    try:
        split = subprocess.run(
            [herdr, "pane", "split", "--pane", pane_id, "--direction", "down"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        new_pane_id = json.loads(split.stdout)["result"]["pane"]["pane_id"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        print("Could not open a pane to edit the config.", file=sys.stderr)
        return 1
    subprocess.run([herdr, "pane", "run", new_pane_id, f"{editor} {path}"], timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
