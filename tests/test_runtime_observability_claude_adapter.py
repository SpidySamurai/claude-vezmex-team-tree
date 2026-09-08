import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.runtime_observability import ids, paths, reader, store
from src.runtime_observability.adapters import claude_code

HOOK = Path(__file__).resolve().parent.parent / "src" / "claude_subagent_hook.py"
PROFILE_HOOK = Path(__file__).resolve().parent.parent / "src" / "claude_profile_hook.py"


class ClaudeCodeAdapterTests(unittest.TestCase):
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

    def session(self, raw="s1"):
        return store.read_snapshot().sessions.get(ids.session_id("claude", raw))

    def test_subagent_start_records_canonical_session_and_activity(self):
        self.assertTrue(claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0))
        record = self.session()
        self.assertEqual(record["presence"], "present")
        activity = record["activities"][ids.activity_id(ids.session_id("claude", "s1"), "a1")]
        self.assertEqual((activity["name"], activity["status"]), ("Explore", "working"))
        self.assertEqual(record["capabilities"]["activity"], "complete")
        self.assertEqual(record["source"]["collector"], "claude-code-hooks")

    def test_subagent_stop_removes_live_activity_but_keeps_the_session(self):
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a2", "agent_type": "Verify"}, now=101.0)
        self.assertTrue(claude_code.ingest({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "a1"}, now=102.0))
        activities = self.session()["activities"]
        self.assertEqual([a["name"] for a in activities.values()], ["Verify"])

    def test_activity_refreshes_parent_session_freshness(self):
        claude_code.ingest({"hook_event_name": "SessionStart", "session_id": "s1"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=500.0)
        self.assertEqual(self.session()["observed_at"], 500.0)

    def test_session_lifecycle_records_presence_and_explicit_end_only(self):
        claude_code.ingest({"hook_event_name": "SessionStart", "session_id": "s1"}, now=100.0)
        self.assertEqual((self.session()["presence"], self.session()["status"]), ("present", "unknown"))
        claude_code.ingest({"hook_event_name": "SessionEnd", "session_id": "s1"}, now=200.0)
        self.assertEqual((self.session()["presence"], self.session()["status"]), ("ended", "ended"))

    def test_unsupported_malformed_and_incomplete_events_are_ignored(self):
        for event in (
            None,
            {"hook_event_name": "PostToolUse", "session_id": "s1"},
            {"hook_event_name": "SubagentStart", "session_id": "", "agent_id": "a1"},
            {"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": ""},
            {"hook_event_name": "SubagentStart", "session_id": "s1"},
        ):
            self.assertFalse(claude_code.ingest(event, now=100.0))
        self.assertEqual(store.read_snapshot().sessions, {})

    def test_transcript_prompt_and_token_fields_never_enter_canonical_state(self):
        claude_code.ingest(
            {
                "hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore",
                "agent_transcript_path": "/tmp/secret-transcript.jsonl", "last_assistant_message": "secret prompt text",
                "cwd": "/home/someone/private-project", "usage": {"input_tokens": 42},
            },
            now=100.0,
        )
        serialized = paths.snapshot_path().read_text(encoding="utf-8")
        for leaked in ("secret-transcript", "secret prompt text", "private-project", "input_tokens"):
            self.assertNotIn(leaked, serialized)

    def test_session_end_for_an_unseen_session_is_not_invented(self):
        self.assertFalse(claude_code.ingest({"hook_event_name": "SessionEnd", "session_id": "ghost"}, now=100.0))
        self.assertEqual(store.read_snapshot().sessions, {})

    def test_same_child_id_in_two_sessions_stays_separate(self):
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "shared", "agent_type": "One"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s2", "agent_id": "shared", "agent_type": "Two"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "shared"}, now=101.0)
        self.assertEqual(self.session("s1")["activities"], {})
        self.assertEqual([a["name"] for a in self.session("s2")["activities"].values()], ["Two"])

    def test_parent_end_while_child_works_is_reported_as_interrupted(self):
        claude_code.ingest({"hook_event_name": "SessionStart", "session_id": "s1"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0)
        claude_code.ingest({"hook_event_name": "SessionEnd", "session_id": "s1"}, now=101.0)
        snapshot = {"focused_workspace_id": "w1", "agents": [{"agent": "claude", "workspace_id": "w1", "pane_id": "p1", "agent_status": "working", "agent_session": {"value": "s1"}}]}
        leader = reader.read_agents(snapshot, now=102.0).leaders[0]
        self.assertEqual(leader.status, "ended")
        self.assertEqual([a.status for a in leader.activities], ["interrupted"])

    def run_hook(self, script, event):
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=os.environ | {"XDG_STATE_HOME": self.tmp.name},
            timeout=30,
            check=False,
        )

    def test_installed_hooks_write_canonical_state_beside_legacy_state(self):
        self.run_hook(HOOK, {"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"})
        legacy = json.loads(paths.legacy_subagents_path().read_text(encoding="utf-8"))
        self.assertIn("a1", legacy["sessions"]["s1"])
        self.assertIn(ids.activity_id(ids.session_id("claude", "s1"), "a1"), self.session()["activities"])
        self.run_hook(PROFILE_HOOK, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/tmp"})
        self.assertEqual(self.session()["presence"], "present")

    def test_discarding_canonical_state_leaves_legacy_state_readable(self):
        self.run_hook(HOOK, {"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"})
        paths.snapshot_path().unlink()
        legacy = json.loads(paths.legacy_subagents_path().read_text(encoding="utf-8"))
        self.assertIn("a1", legacy["sessions"]["s1"])
        self.assertTrue(store.read_snapshot().available)
        self.assertEqual(store.read_snapshot().sessions, {})


if __name__ == "__main__":
    unittest.main()
