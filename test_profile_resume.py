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

ROOT = Path(__file__).parent
HOOK = ROOT / "claude_profile_hook.py"
INSTALLER = ROOT / "install_profile_resume.py"
WRAPPER = ROOT / "claude_profile_resume.py"


class ProfileResumeTest(unittest.TestCase):
    def test_hook_records_profile_by_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "session-vezmex",
                "cwd": "/projects/vezmex",
                "transcript_path": "/profiles/vezmex/projects/session-vezmex.jsonl",
                "source": "startup",
            }
            result = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(event), text=True,
                env=os.environ | {"XDG_STATE_HOME": state_home, "CLAUDE_CONFIG_DIR": "/profiles/vezmex"},
            )
            self.assertEqual(result.returncode, 0)
            state = json.loads((Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "profiles.json").read_text())
        self.assertEqual(state["sessions"]["session-vezmex"]["config_dir"], "/profiles/vezmex")
        self.assertEqual(state["sessions"]["session-vezmex"]["cwd"], "/projects/vezmex")
        self.assertEqual(
            state["sessions"]["session-vezmex"]["transcript_path"],
            "/profiles/vezmex/projects/session-vezmex.jsonl",
        )

    def test_installer_is_reversible_and_adds_each_profile_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            binary = home / ".local" / "bin"
            binary.mkdir(parents=True)
            real = binary / "claude-real"
            real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            real.chmod(0o755)
            (binary / "claude").symlink_to(real)
            for profile in (".claude", ".claude-work", ".claude-vezmex"):
                settings = home / profile / "settings.json"
                settings.parent.mkdir()
                settings.write_text('{"hooks":{"SessionStart":[]}}', encoding="utf-8")
            environment = os.environ | {"XDG_STATE_HOME": str(home / "state")}
            install = subprocess.run([sys.executable, str(INSTALLER), "--home", str(home)], text=True, env=environment)
            self.assertEqual(install.returncode, 0)
            self.assertTrue((binary / "claude").is_symlink())
            for profile in (".claude", ".claude-work", ".claude-vezmex"):
                settings = json.loads((home / profile / "settings.json").read_text())
                commands = [hook["command"] for group in settings["hooks"]["SessionStart"] for hook in group["hooks"]]
                self.assertIn(f'python3 "{HOOK}"', commands)
            remove = subprocess.run([sys.executable, str(INSTALLER), "--home", str(home), "--uninstall"], text=True, env=environment)
            self.assertEqual(remove.returncode, 0)
            self.assertEqual((binary / "claude").resolve(), real)

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
                "sessions": {"session-vezmex": {"config_dir": "/profiles/vezmex"}},
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(WRAPPER), "--resume", "session-vezmex"],
                text=True,
                capture_output=True,
                env=os.environ | {
                    "XDG_STATE_HOME": str(state_home),
                    "PROFILE_TEST_OUTPUT": str(output),
                    "CLAUDE_CONFIG_DIR": "/profiles/default",
                },
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(output.read_text(), "/profiles/vezmex")
            self.assertIn("resuming Claude session with profile /profiles/vezmex", result.stderr)


if __name__ == "__main__":
    unittest.main()
