#!/usr/bin/env python3
"""Checks for the installer's hook wiring — the part that edits the user's
own agent settings, so it has to be exact and exactly reversible.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import install  # noqa: E402

FOREIGN = {"type": "command", "command": 'node "/somewhere/else.js"', "timeout": 5}
STALE_ROOT = Path("/tmp/old-agents-tree-checkout")


@contextlib.contextmanager
def marker_env(path: Path):
    """Point the autowire marker at a throwaway directory for the duration of
    the block, so it never touches the real user's state directory.

    The marker follows the frozen state root, never HERDR_PLUGIN_CONFIG_DIR —
    see `install.autowire_marker_path`. This also clears the config dir
    variable, so a test can never pass by accident because the marker fell
    back to a location Herdr happened to inject.
    """
    old_state = os.environ.get("XDG_STATE_HOME")
    old_config = os.environ.get("HERDR_PLUGIN_CONFIG_DIR")
    os.environ["XDG_STATE_HOME"] = str(path)
    os.environ.pop("HERDR_PLUGIN_CONFIG_DIR", None)
    try:
        yield
    finally:
        if old_state is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = old_state
        if old_config is not None:
            os.environ["HERDR_PLUGIN_CONFIG_DIR"] = old_config


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

    def test_hook_command_only_flags_a_non_claude_runtime(self) -> None:
        script = next(iter(install.HOOK_EVENTS.values()))
        self.assertEqual(install.hook_command(ROOT, script), install.hook_command(ROOT, script, "claude"))
        self.assertNotIn("--runtime", install.hook_command(ROOT, script))
        self.assertTrue(install.hook_command(ROOT, script, "codex").endswith("--runtime codex"))

    def test_wiring_a_codex_file_adds_runtime_flagged_commands(self) -> None:
        settings: dict = {}
        install.wire(settings, ROOT, "codex")
        for event, script in install.HOOK_EVENTS.items():
            commands = [h["command"] for g in settings["hooks"][event] for h in g["hooks"]]
            self.assertIn(install.hook_command(ROOT, script, "codex"), commands)
            self.assertNotIn(install.hook_command(ROOT, script), commands)

    def test_wiring_migrates_a_pre_flag_codex_command_in_place(self) -> None:
        script = install.HOOK_EVENTS["SubagentStart"]
        legacy = {"type": "command", "command": install.hook_command(ROOT, script), "timeout": 5}
        settings = {"hooks": {"SubagentStart": [{"matcher": "", "hooks": [dict(legacy)]}]}}
        changed = install.wire(settings, ROOT, "codex")
        self.assertIn("SubagentStart", changed)
        commands = [h["command"] for g in settings["hooks"]["SubagentStart"] for h in g["hooks"]]
        self.assertEqual(commands, [install.hook_command(ROOT, script, "codex")])

    def test_wiring_a_codex_file_is_idempotent_after_migration(self) -> None:
        settings: dict = {}
        install.wire(settings, ROOT, "codex")
        before = json.dumps(settings, sort_keys=True)
        self.assertEqual(install.wire(settings, ROOT, "codex"), [])
        self.assertEqual(json.dumps(settings, sort_keys=True), before)

    def test_unwiring_a_codex_file_removes_both_legacy_and_flagged_commands(self) -> None:
        script = install.HOOK_EVENTS["SubagentStart"]
        legacy_entry = {"type": "command", "command": install.hook_command(ROOT, script), "timeout": 5}
        settings = {"hooks": {"SubagentStart": [{"matcher": "", "hooks": [dict(legacy_entry), dict(FOREIGN)]}]}}
        install.unwire(settings, ROOT, "codex")
        commands = [h["command"] for g in settings["hooks"]["SubagentStart"] for h in g["hooks"]]
        self.assertEqual(commands, [FOREIGN["command"]])

    def test_wiring_a_partially_migrated_codex_file_only_touches_unmigrated_entries(self) -> None:
        start_script = install.HOOK_EVENTS["SubagentStart"]
        stop_script = install.HOOK_EVENTS["SubagentStop"]
        settings = {"hooks": {
            "SubagentStart": [{"matcher": "", "hooks": [{"type": "command", "command": install.hook_command(ROOT, start_script, "codex"), "timeout": 5}]}],
            "SubagentStop": [{"matcher": "", "hooks": [{"type": "command", "command": install.hook_command(ROOT, stop_script), "timeout": 5}]}],
        }}
        changed = install.wire(settings, ROOT, "codex")
        # SubagentStart was already migrated, so wire() must not touch it again;
        # every other event (including SubagentStop) is genuinely new work.
        self.assertNotIn("SubagentStart", changed)
        self.assertIn("SubagentStop", changed)
        start_commands = [h["command"] for g in settings["hooks"]["SubagentStart"] for h in g["hooks"]]
        stop_commands = [h["command"] for g in settings["hooks"]["SubagentStop"] for h in g["hooks"]]
        self.assertEqual(start_commands, [install.hook_command(ROOT, start_script, "codex")])
        self.assertEqual(stop_commands, [install.hook_command(ROOT, stop_script, "codex")])

    def test_runtime_for_identifies_only_the_codex_hooks_file(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            self.assertEqual(install.runtime_for(home / ".codex" / "hooks.json", home), "codex")
            self.assertEqual(install.runtime_for(home / ".claude" / "settings.json", home), "claude")

    def test_install_migrates_an_existing_codex_wiring_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            (home / ".codex").mkdir()
            legacy_settings: dict = {}
            install.wire(legacy_settings, ROOT, "claude")
            (home / ".codex" / "hooks.json").write_text(json.dumps(legacy_settings), encoding="utf-8")
            install.link_plugin = lambda remove=False: "skipped"
            install.install(home)
            migrated = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            script = install.HOOK_EVENTS["SubagentStart"]
            commands = [h["command"] for g in migrated["hooks"]["SubagentStart"] for h in g["hooks"]]
            self.assertEqual(commands, [install.hook_command(ROOT, script, "codex")])

    def test_check_reports_a_migrated_codex_file_as_fully_wired(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            (home / ".codex").mkdir()
            settings: dict = {}
            install.wire(settings, ROOT, "codex")
            (home / ".codex" / "hooks.json").write_text(json.dumps(settings), encoding="utf-8")
            import io
            import contextlib
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                install.check(home)
            self.assertIn("5/5 wired — complete", buffer.getvalue())

    def test_pi_extension_status_is_not_installed_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            self.assertEqual(install.pi_extension_status(Path(home_dir)), "not installed")

    def test_link_pi_extension_is_explicit_and_never_runs_during_plain_install(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            install.link_plugin = lambda remove=False: "skipped"
            install.install(home)
            self.assertEqual(install.pi_extension_status(home), "not installed")
            target = install.pi_extension_target(home)
            self.assertFalse(target.exists())

    def test_link_pi_extension_symlinks_to_the_checkout_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            first = install.link_pi_extension(home)
            self.assertIn("linked", first)
            self.assertEqual(install.pi_extension_status(home), "linked")
            target = install.pi_extension_target(home)
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(), install.pi_extension_source().resolve())
            second = install.link_pi_extension(home)
            self.assertIn("already", second)

    def test_link_pi_extension_leaves_a_foreign_directory_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            target = install.pi_extension_target(home)
            target.mkdir(parents=True)
            (target / "index.ts").write_text("// not ours", encoding="utf-8")
            result = install.link_pi_extension(home)
            self.assertIn("already present", result)
            self.assertEqual((target / "index.ts").read_text(encoding="utf-8"), "// not ours")

    def test_unlink_pi_extension_only_removes_our_own_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            install.link_pi_extension(home)
            self.assertIn("unlinked", install.unlink_pi_extension(home))
            self.assertFalse(install.pi_extension_target(home).exists())

    def test_unlink_pi_extension_leaves_a_foreign_directory_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            target = install.pi_extension_target(home)
            target.mkdir(parents=True)
            (target / "index.ts").write_text("// not ours", encoding="utf-8")
            result = install.unlink_pi_extension(home)
            self.assertIn("not ours", result)
            self.assertTrue((target / "index.ts").exists())

    def test_pi_extension_status_reports_a_foreign_directory_distinctly(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            target = install.pi_extension_target(home)
            target.mkdir(parents=True)
            (target / "index.ts").write_text("// not ours", encoding="utf-8")
            self.assertEqual(install.pi_extension_status(home), "present (not ours)")

    def test_the_link_pi_extension_flag_is_explicit_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            completed = subprocess.run(
                [sys.executable, str(ROOT / "install.py"), "--link-pi-extension", "--home", str(home)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(install.pi_extension_status(home), "linked")

    def test_uninstall_removes_only_a_pi_extension_link_this_installer_created(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            install.link_plugin = lambda remove=False: "skipped"
            install.link_pi_extension(home)
            install.uninstall(home)
            self.assertFalse(install.pi_extension_target(home).exists())

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

    # -- --sync-hooks -----------------------------------------------------

    def test_sync_hooks_is_a_noop_when_already_current(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            settings_path = home / ".claude" / "settings.json"
            settings: dict = {}
            install.wire(settings, ROOT)
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            before = settings_path.read_text(encoding="utf-8")
            with marker_env(Path(config_dir)):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    result = install.sync_hooks(home)
            self.assertEqual(result, 0)
            self.assertEqual(settings_path.read_text(encoding="utf-8"), before)
            self.assertEqual(buffer.getvalue(), "")

    def test_sync_hooks_repairs_a_stale_root(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            settings_path = home / ".claude" / "settings.json"
            settings: dict = {}
            install.wire(settings, STALE_ROOT)
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            with marker_env(Path(config_dir)):
                result = install.sync_hooks(home)
            self.assertEqual(result, 0)
            migrated = json.loads(settings_path.read_text(encoding="utf-8"))
            for event, script in install.HOOK_EVENTS.items():
                commands = [h["command"] for g in migrated["hooks"][event] for h in g["hooks"]]
                self.assertIn(install.hook_command(ROOT, script), commands)
                self.assertNotIn(install.hook_command(STALE_ROOT, script), commands)

    def test_sync_hooks_wires_from_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            settings_path = home / ".claude" / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with marker_env(Path(config_dir)):
                result = install.sync_hooks(home)
            self.assertEqual(result, 0)
            wired = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(install.wired_events(wired, ROOT)),
                sorted(install.HOOK_EVENTS),
            )

    def test_sync_hooks_does_nothing_when_opted_out(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            settings_path = home / ".claude" / "settings.json"
            settings: dict = {}
            install.wire(settings, STALE_ROOT)  # stale, so a real sync would change it
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            before = settings_path.read_text(encoding="utf-8")
            with marker_env(Path(config_dir)):
                marker = install.autowire_marker_path()
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(json.dumps({"autowire": False}), encoding="utf-8")
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    result = install.sync_hooks(home)
            self.assertEqual(result, 0)
            self.assertEqual(settings_path.read_text(encoding="utf-8"), before)
            self.assertEqual(buffer.getvalue(), "")

    def test_sync_hooks_leaves_foreign_hooks_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            (home / ".claude").mkdir()
            settings_path = home / ".claude" / "settings.json"
            script = install.HOOK_EVENTS["PostToolUse"]
            stale = {"type": "command", "command": install.hook_command(STALE_ROOT, script), "timeout": 5}
            settings = {"hooks": {"PostToolUse": [{"matcher": "", "hooks": [dict(FOREIGN), dict(stale)]}]}}
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            with marker_env(Path(config_dir)):
                install.sync_hooks(home)
            migrated = json.loads(settings_path.read_text(encoding="utf-8"))
            commands = [h["command"] for g in migrated["hooks"]["PostToolUse"] for h in g["hooks"]]
            self.assertIn(FOREIGN["command"], commands)
            self.assertIn(install.hook_command(ROOT, script), commands)
            self.assertNotIn(install.hook_command(STALE_ROOT, script), commands)

    def test_uninstall_writes_marker_and_install_removes_it(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as config_dir:
            home = Path(home_dir)
            install.link_plugin = lambda remove=False: "skipped"
            with marker_env(Path(config_dir)):
                marker = install.autowire_marker_path()
                install.uninstall(home)
                self.assertTrue(marker.is_file())
                self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), {"autowire": False})
                install.install(home)
                self.assertFalse(marker.exists())

    def test_renamed_plugin_id_appears_in_manifest_and_code_fallbacks(self) -> None:
        self.assertEqual(install.PLUGIN_ID, "spidysamurai.agents-tree")
        manifest = (ROOT / "herdr-plugin.toml").read_text(encoding="utf-8")
        self.assertIn('id = "spidysamurai.agents-tree"', manifest)
        agent_tree_source = (ROOT / "src" / "herdr_agent_tree.py").read_text(encoding="utf-8")
        self.assertIn('"HERDR_PLUGIN_ID", "spidysamurai.agents-tree"', agent_tree_source)
        self.assertNotIn("local.claude-vezmex-team-tree", agent_tree_source)
        self.assertNotIn("local.claude-vezmex-team-tree", manifest)


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



class SyncHooksCorrectionTests(unittest.TestCase):
    """Regression cover for the two defects the bounded review found."""

    def test_optout_marker_location_ignores_the_herdr_config_dir(self) -> None:
        # The uninstall runs from a plain shell and the startup hook runs under
        # Herdr. If the marker moved with HERDR_PLUGIN_CONFIG_DIR the two would
        # disagree and an explicit opt-out would be silently re-wired away.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            config = Path(tmp) / "config"
            config.mkdir(parents=True, exist_ok=True)
            env = {"XDG_STATE_HOME": str(state)}
            with unittest.mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("HERDR_PLUGIN_CONFIG_DIR", None)
                without = install.autowire_marker_path()
            with unittest.mock.patch.dict(
                os.environ, {**env, "HERDR_PLUGIN_CONFIG_DIR": str(config)}, clear=False
            ):
                with_config = install.autowire_marker_path()
            self.assertEqual(without, with_config)
            self.assertNotIn(str(config), str(with_config))

    def test_sync_hooks_keeps_repairing_after_one_unusable_file(self) -> None:
        # A settings file that parses to a non-object made repair_stale_roots
        # raise, which aborted every file behind it in settings_files() order.
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            state = home / "state"
            broken = home / ".claude" / "settings.json"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("[]", encoding="utf-8")
            good = home / ".codex" / "hooks.json"
            good.parent.mkdir(parents=True, exist_ok=True)
            good.write_text("{}", encoding="utf-8")
            with unittest.mock.patch.dict(
                os.environ, {"XDG_STATE_HOME": str(state)}, clear=False
            ):
                os.environ.pop("HERDR_PLUGIN_CONFIG_DIR", None)
                rc = install.sync_hooks(home)
            self.assertEqual(rc, 0)
            # The file behind the unusable one still got wired.
            self.assertIn("hooks", json.loads(good.read_text(encoding="utf-8")))

if __name__ == "__main__":
    unittest.main()
