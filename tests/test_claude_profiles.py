#!/usr/bin/env python3
"""Which Claude profile directories get wired: ~/.claude always, plus the
ones the user names in the environment or the plugin's config file.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
import claude_profiles  # noqa: E402
import install  # noqa: E402

NO_CONFIG: dict = {}


class ConfiguredProfilesTest(unittest.TestCase):
    def test_only_the_default_profile_without_configuration(self) -> None:
        self.assertEqual(claude_profiles.configured_profiles({}, NO_CONFIG), [".claude"])

    def test_environment_entries_split_on_colon_and_comma(self) -> None:
        environ = {"AGENTS_TREE_CLAUDE_PROFILES": ".claude-work:.claude-client, /opt/claude"}
        self.assertEqual(
            claude_profiles.configured_profiles(environ, NO_CONFIG),
            [".claude", ".claude-work", ".claude-client", "/opt/claude"],
        )

    def test_config_entries_follow_the_environment_without_duplicates(self) -> None:
        environ = {"AGENTS_TREE_CLAUDE_PROFILES": ".claude-work"}
        config = {"claude_profiles": [".claude-work", ".claude-client", 7, ".claude"]}
        self.assertEqual(
            claude_profiles.configured_profiles(environ, config),
            [".claude", ".claude-work", ".claude-client"],
        )

    def test_entries_resolve_against_home(self) -> None:
        home = Path("/home/someone")
        self.assertEqual(claude_profiles.profile_dir(home, ".claude-work"), home / ".claude-work")
        self.assertEqual(claude_profiles.profile_dir(home, "~/profiles/a"), home / "profiles" / "a")
        self.assertEqual(claude_profiles.profile_dir(home, "/opt/claude"), Path("/opt/claude"))

    def test_sweep_adds_every_claude_directory_once(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            for name in (".claude", ".claude-old", ".config"):
                (home / name).mkdir()
            (home / ".claude.json").write_text("{}", encoding="utf-8")
            self.assertEqual(claude_profiles.profile_dirs(home, environ={}, config=NO_CONFIG), [home / ".claude"])
            self.assertEqual(
                claude_profiles.profile_dirs(home, sweep=True, environ={}, config=NO_CONFIG),
                [home / ".claude", home / ".claude-old"],
            )

    def test_the_config_file_is_read_when_no_config_is_given(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            path = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"claude_profiles": [".claude-work"]}), encoding="utf-8")
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                profiles = claude_profiles.configured_profiles({})
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state
        self.assertEqual(profiles, [".claude", ".claude-work"])


class InstallerProfilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.home_dir.name)
        for name in (".claude", ".claude-work"):
            (self.home / name).mkdir()
            (self.home / name / "settings.json").write_text("{}", encoding="utf-8")
        self.saved = {key: os.environ.get(key) for key in ("XDG_STATE_HOME", "AGENTS_TREE_CLAUDE_PROFILES")}
        os.environ["XDG_STATE_HOME"] = str(self.home / "state")
        os.environ.pop("AGENTS_TREE_CLAUDE_PROFILES", None)

    def tearDown(self) -> None:
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.home_dir.cleanup()

    def test_installer_wires_only_the_default_profile_unless_told_otherwise(self) -> None:
        self.assertEqual(install.settings_files(self.home), [self.home / ".claude" / "settings.json"])

    def test_installer_wires_profiles_named_in_the_environment(self) -> None:
        os.environ["AGENTS_TREE_CLAUDE_PROFILES"] = ".claude-work"
        self.assertEqual(
            install.settings_files(self.home),
            [self.home / ".claude" / "settings.json", self.home / ".claude-work" / "settings.json"],
        )

    def test_uninstall_reaches_unconfigured_claude_profiles(self) -> None:
        self.assertIn(self.home / ".claude-work" / "settings.json", install.settings_files(self.home, sweep=True))


if __name__ == "__main__":
    unittest.main()
