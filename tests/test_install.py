#!/usr/bin/env python3
"""Checks for the installer's hook wiring — the part that edits the user's
own agent settings, so it has to be exact and exactly reversible.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import install  # noqa: E402

FOREIGN = {"type": "command", "command": 'node "/somewhere/else.js"', "timeout": 5}


class InstallTest(unittest.TestCase):
    def test_wiring_adds_one_command_per_declared_event(self) -> None:
        settings: dict = {}
        changed = install.wire(settings, ROOT)
        self.assertEqual(sorted(changed), sorted(install.HOOK_EVENTS))
        for event, script in install.HOOK_EVENTS.items():
            commands = [
                hook["command"]
                for group in settings["hooks"][event]
                for hook in group["hooks"]
            ]
            self.assertIn(install.hook_command(ROOT, script), commands)

    def test_wiring_is_idempotent(self) -> None:
        settings: dict = {}
        install.wire(settings, ROOT)
        before = json.dumps(settings, sort_keys=True)
        self.assertEqual(install.wire(settings, ROOT), [])
        self.assertEqual(json.dumps(settings, sort_keys=True), before)

    def test_wiring_joins_an_existing_group_and_leaves_foreign_hooks_alone(self) -> None:
        settings = {"hooks": {"PostToolUse": [{"matcher": "", "hooks": [dict(FOREIGN)]}]}}
        install.wire(settings, ROOT)
        commands = [h["command"] for g in settings["hooks"]["PostToolUse"] for h in g["hooks"]]
        self.assertIn(FOREIGN["command"], commands)
        self.assertIn(install.hook_command(ROOT, install.HOOK_EVENTS["PostToolUse"]), commands)

    def test_unwiring_removes_exactly_what_wiring_added(self) -> None:
        settings = {"hooks": {"PostToolUse": [{"matcher": "", "hooks": [dict(FOREIGN)]}]}}
        pristine = json.dumps(settings, sort_keys=True)
        install.wire(settings, ROOT)
        removed = install.unwire(settings, ROOT)
        self.assertEqual(sorted(removed), sorted(install.HOOK_EVENTS))
        # every event key we created is gone again, and the foreign hook stayed
        self.assertEqual(json.dumps(prune(settings), sort_keys=True), pristine)

    def test_unwiring_a_clean_file_changes_nothing(self) -> None:
        settings = {"hooks": {"PostToolUse": [{"matcher": "", "hooks": [dict(FOREIGN)]}]}}
        self.assertEqual(install.unwire(settings, ROOT), [])

    def test_wiring_refuses_a_settings_file_that_is_not_an_object(self) -> None:
        with self.assertRaises(TypeError):
            install.wire([], ROOT)  # type: ignore[arg-type]

    def test_status_reports_which_events_are_wired(self) -> None:
        settings: dict = {}
        self.assertEqual(install.wired_events(settings, ROOT), [])
        install.wire(settings, ROOT)
        self.assertEqual(sorted(install.wired_events(settings, ROOT)), sorted(install.HOOK_EVENTS))

    def test_settings_files_only_reports_files_that_exist(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
            (home / ".claude-work").mkdir()          # no settings.json inside
            (home / ".codex").mkdir()
            (home / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
            found = {path.relative_to(home).as_posix() for path in install.settings_files(home)}
        self.assertEqual(found, {".claude/settings.json", ".codex/hooks.json"})


def prune(settings: dict) -> dict:
    """Drop hook events left with no hooks, so an uninstalled file compares
    equal to the one we started from.
    """
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = [g for g in hooks[event] if g.get("hooks")]
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    return settings


if __name__ == "__main__":
    unittest.main()
