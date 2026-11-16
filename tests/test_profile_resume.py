#!/usr/bin/env python3
"""Offline checks for the Claude profile-resume migration."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The modules under test live in src/; tests sit beside it, not in it.
ROOT = Path(__file__).resolve().parent.parent / "src"
HOOK = ROOT / "claude_profile_hook.py"
INSTALLER = ROOT / "install_profile_resume.py"
WRAPPER = ROOT / "claude_profile_resume.py"


class ProfileResumeTest(unittest.TestCase):
    def test_hook_records_profile_by_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "session-work",
                "cwd": "/projects/work",
                "transcript_path": "/profiles/work/projects/session-work.jsonl",
                "source": "startup",
            }
            result = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(event), text=True,
                env=os.environ | {"XDG_STATE_HOME": state_home, "CLAUDE_CONFIG_DIR": "/profiles/work"},
            )
            self.assertEqual(result.returncode, 0)
            state = json.loads((Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "profiles.json").read_text())
        self.assertEqual(state["sessions"]["session-work"]["config_dir"], "/profiles/work")
        self.assertEqual(state["sessions"]["session-work"]["cwd"], "/projects/work")
        self.assertEqual(
            state["sessions"]["session-work"]["transcript_path"],
            "/profiles/work/projects/session-work.jsonl",
        )

    def _fake_claude(self, home: Path) -> tuple[Path, Path]:
        binary = home / ".local" / "bin"
        binary.mkdir(parents=True)
        real = binary / "claude-real"
        real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        real.chmod(0o755)
        (binary / "claude").symlink_to(real)
        for profile in (".claude", ".claude-work", ".claude-unlisted"):
            settings = home / profile / "settings.json"
            settings.parent.mkdir()
            settings.write_text('{"hooks":{"SessionStart":[]}}', encoding="utf-8")
        return binary, real

    def _commands(self, home: Path, profile: str, event: str) -> list[str]:
        settings = json.loads((home / profile / "settings.json").read_text())
        return [h["command"] for g in settings["hooks"].get(event, []) for h in g["hooks"]]

    def test_installer_is_reversible_and_adds_each_configured_profile_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            binary, real = self._fake_claude(home)
            events = ("SessionStart", "SessionEnd")
            environment = os.environ | {
                "XDG_STATE_HOME": str(home / "state"),
                "AGENTS_TREE_CLAUDE_PROFILES": ".claude-work",
            }
            install = subprocess.run([sys.executable, str(INSTALLER), "--home", str(home)], text=True, env=environment)
            self.assertEqual(install.returncode, 0)
            self.assertTrue((binary / "claude").is_symlink())
            for profile in (".claude", ".claude-work"):
                for event in events:
                    self.assertIn(f'python3 "{HOOK}"', self._commands(home, profile, event),
                                  f"{profile} is missing {event}")
            # a profile nobody configured is left alone
            for event in events:
                self.assertNotIn(f'python3 "{HOOK}"', self._commands(home, ".claude-unlisted", event))
            remove = subprocess.run([sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"], text=True, env=environment)
            self.assertEqual(remove.returncode, 0)
            self.assertEqual((binary / "claude").resolve(), real)
            for profile in (".claude", ".claude-work"):
                for event in events:
                    self.assertNotIn(f'python3 "{HOOK}"', self._commands(home, profile, event),
                                     f"{profile} kept {event}")

    def test_uninstall_cleans_a_profile_dropped_from_the_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            self._fake_claude(home)
            state = {"XDG_STATE_HOME": str(home / "state")}
            install = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home)], text=True,
                env=os.environ | state | {"AGENTS_TREE_CLAUDE_PROFILES": ".claude-work"},
            )
            self.assertEqual(install.returncode, 0)
            self.assertIn(f'python3 "{HOOK}"', self._commands(home, ".claude-work", "SessionStart"))
            environment = {k: v for k, v in os.environ.items() if k != "AGENTS_TREE_CLAUDE_PROFILES"}
            remove = subprocess.run(
                [sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"], text=True,
                env=environment | state,
            )
            self.assertEqual(remove.returncode, 0)
            self.assertNotIn(f'python3 "{HOOK}"', self._commands(home, ".claude-work", "SessionStart"))

    def test_hook_marks_a_session_ended_and_a_restart_clears_the_mark(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            environment = os.environ | {"XDG_STATE_HOME": state_home, "CLAUDE_CONFIG_DIR": "/profiles/work"}
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "profiles.json"

            def run(event: dict) -> None:
                completed = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event), text=True, env=environment
                )
                self.assertEqual(completed.returncode, 0)

            run({"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/tmp",
                 "transcript_path": "/tmp/s1.jsonl"})
            session = json.loads(state.read_text())["sessions"]["s1"]
            self.assertNotIn("ended", session)

            run({"hook_event_name": "SessionEnd", "session_id": "s1", "reason": "prompt_input_exit"})
            ended = json.loads(state.read_text())["sessions"]["s1"]
            self.assertIsInstance(ended.get("ended"), float)
            # the end marker must not cost the fields the panel still renders
            self.assertEqual(ended["started"], session["started"])
            self.assertEqual(ended["transcript_path"], "/tmp/s1.jsonl")

            # resuming the same session brings it back to life
            run({"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/tmp",
                 "transcript_path": "/tmp/s1.jsonl", "source": "resume"})
            self.assertNotIn("ended", json.loads(state.read_text())["sessions"]["s1"])

    def test_hook_ignores_session_end_for_an_unknown_session(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            completed = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps({"hook_event_name": "SessionEnd", "session_id": "never-seen"}),
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0)
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "profiles.json"
            if state.exists():
                self.assertNotIn("never-seen", json.loads(state.read_text()).get("sessions", {}))

    def test_wrapper_selects_recorded_profile_for_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            state_home = temporary_path / "state"
            output = temporary_path / "received-profile.txt"
            real = temporary_path / "real-claude"
            real.write_text(
                "#!/bin/sh\nprintf '%s' \"$CLAUDE_CONFIG_DIR\" > \"$PROFILE_TEST_OUTPUT\"\n",
                encoding="utf-8",
            )
            real.chmod(0o755)
            state = state_home / "herdr" / "claude-vezmex-team-tree" / "profiles.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({
                "version": 1,
                "real_claude": str(real),
                "sessions": {"session-work": {"config_dir": "/profiles/work"}},
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(WRAPPER), "--resume", "session-work"],
                text=True,
                capture_output=True,
                env=os.environ | {
                    "XDG_STATE_HOME": str(state_home),
                    "PROFILE_TEST_OUTPUT": str(output),
                    "CLAUDE_CONFIG_DIR": "/profiles/default",
                },
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "/profiles/work")
            self.assertIn("resuming Claude session with profile /profiles/work", result.stderr)


if __name__ == "__main__":
    unittest.main()
