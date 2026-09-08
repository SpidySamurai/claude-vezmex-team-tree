import os
import tempfile
import unittest

from src.runtime_observability import ids, store
from src.runtime_observability.adapters import claude_code, codex


class CodexAdapterTests(unittest.TestCase):
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
        return store.read_snapshot().sessions.get(ids.session_id("codex", raw))

    def test_subagent_start_tags_canonical_state_as_codex_not_claude(self):
        self.assertTrue(codex.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0))
        record = self.session()
        self.assertIsNotNone(record)
        self.assertEqual(record["source"]["runtime"], "codex")
        self.assertEqual(record["source"]["collector"], "codex-hooks")
        self.assertIsNone(store.read_snapshot().sessions.get(ids.session_id("claude", "s1")))

    def test_capabilities_are_conservative_not_claude_complete(self):
        codex.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0)
        caps = self.session()["capabilities"]
        self.assertEqual(caps["activity"], "partial")
        self.assertEqual(caps["completion"], "unsupported")
        self.assertEqual(caps["artifacts"], "unsupported")

    def test_same_raw_session_id_stays_separate_from_a_claude_session(self):
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "same", "agent_id": "a1", "agent_type": "FromClaude"}, now=100.0)
        codex.ingest({"hook_event_name": "SubagentStart", "session_id": "same", "agent_id": "a1", "agent_type": "FromCodex"}, now=100.0)
        snapshot = store.read_snapshot()
        claude_activities = snapshot.sessions[ids.session_id("claude", "same")]["activities"]
        codex_activities = snapshot.sessions[ids.session_id("codex", "same")]["activities"]
        self.assertEqual([a["name"] for a in claude_activities.values()], ["FromClaude"])
        self.assertEqual([a["name"] for a in codex_activities.values()], ["FromCodex"])

    def test_subagent_stop_removes_the_live_codex_activity(self):
        codex.ingest({"hook_event_name": "SubagentStart", "session_id": "s1", "agent_id": "a1", "agent_type": "Explore"}, now=100.0)
        self.assertTrue(codex.ingest({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "a1"}, now=101.0))
        self.assertEqual(self.session()["activities"], {})

    def test_unsupported_or_malformed_events_are_ignored(self):
        for event in (None, {"hook_event_name": "PostToolUse", "session_id": "s1"}, {"hook_event_name": "SubagentStart", "session_id": "s1"}):
            self.assertFalse(codex.ingest(event, now=100.0))
        self.assertEqual(store.read_snapshot().sessions, {})

    def test_session_end_for_an_unseen_codex_session_is_not_invented(self):
        self.assertFalse(codex.ingest({"hook_event_name": "SessionEnd", "session_id": "ghost"}, now=100.0))
        self.assertEqual(store.read_snapshot().sessions, {})


if __name__ == "__main__":
    unittest.main()
