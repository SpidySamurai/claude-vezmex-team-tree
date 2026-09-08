"""How a wired hook script picks its adapter, from install.py's own flag."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.runtime_observability import ids, store

HOOK = Path(__file__).resolve().parent.parent / "src" / "claude_subagent_hook.py"


class CodexHookDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = self.old
        self.tmp.cleanup()

    def run_hook(self, *argv):
        event = {"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}
        completed = subprocess.run(
            [sys.executable, str(HOOK), *argv],
            input=json.dumps(event), text=True, capture_output=True,
            env=os.environ | {"XDG_STATE_HOME": self.tmp.name}, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0)
        return store.read_snapshot().sessions

    def test_no_flag_still_selects_claude_matching_every_install_before_this_flag_existed(self):
        sessions = self.run_hook()
        self.assertIn(ids.session_id("claude", "s1"), sessions)
        self.assertNotIn(ids.session_id("codex", "s1"), sessions)

    def test_the_installed_codex_flag_selects_the_codex_adapter(self):
        sessions = self.run_hook("--runtime", "codex")
        self.assertIn(ids.session_id("codex", "s1"), sessions)
        self.assertNotIn(ids.session_id("claude", "s1"), sessions)

    def test_an_unknown_runtime_value_falls_back_to_claude_rather_than_dropping_the_event(self):
        sessions = self.run_hook("--runtime", "made-up")
        self.assertIn(ids.session_id("claude", "s1"), sessions)


if __name__ == "__main__":
    unittest.main()
