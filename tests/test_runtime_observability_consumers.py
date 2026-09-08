import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(ROOT))

from src.runtime_observability import model, paths, reader, store  # noqa: E402
from src.runtime_observability.adapters import claude_code  # noqa: E402

import claude_team_tree  # noqa: E402
import herdr_agent_tree  # noqa: E402


def leader(runtime="claude", session="s1"):
    return {"agent": runtime, "pane_id": "p1", "workspace_id": "w1", "agent_status": "working", "agent_session": {"value": session}}


class HerdrConsumerMigrationTests(unittest.TestCase):
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

    def start_child(self, session="s1", agent_id="a1", name="Explore", now=100.0):
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": session, "agent_id": agent_id, "agent_type": name}, now=now)

    def write_legacy(self, body):
        paths.ensure_state_root()
        paths.legacy_subagents_path().write_text(body, encoding="utf-8")

    def test_canonical_children_report_their_own_start_time(self):
        self.start_child(now=100.0)
        child = reader.children_for_session("s1", now=105.0)[0]
        self.assertEqual((child.name, child.status, child.started), ("Explore", "working", 100.0))

    def test_children_for_session_falls_back_to_legacy_when_canonical_is_absent(self):
        self.write_legacy('{"sessions":{"s1":{"a1":{"name":"Legacy","status":"working","started":50.0}}}}')
        child = reader.children_for_session("s1", now=105.0)[0]
        self.assertEqual((child.name, child.source, child.started), ("Legacy", "legacy", 50.0))

    def test_children_for_session_withholds_ambiguous_cross_runtime_sessions(self):
        self.start_child(session="same", agent_id="a1", name="FromClaude", now=100.0)
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "same", "agent_id": "a2", "agent_type": "Other"}, now=100.0)
        store.update_activity(model.Activity("codex", "same", "a3", "FromCodex", "working", observed_at=100.0, expires_at=130.0))
        self.assertEqual(reader.children_for_session("same", now=105.0), [])

    def test_sidebar_children_resolve_through_the_shared_reader(self):
        # The surfaces read wall-clock time, so this state must be genuinely fresh.
        now = time.time()
        self.start_child(agent_id="a1", name="Explore", now=now)
        store.update_activity(model.Activity("claude", "s1", "a2", "Idle one", "idle", observed_at=now, expires_at=now + 30))
        children = herdr_agent_tree.hook_children(leader())
        self.assertEqual([c["name"] for c in children], ["Explore", "Idle one"])
        self.assertEqual([c["status"] for c in children], ["working", "idle"])

    def test_dashboard_children_preserve_status_and_elapsed_clock_fields(self):
        now = time.time()
        self.start_child(agent_id="a1", name="Explore", now=now)
        children = claude_team_tree.hook_children("s1")
        self.assertEqual(children[0]["agent_status"], "working")
        self.assertEqual(children[0]["started"], now)
        self.assertEqual(children[0]["name"], "Explore")

    def test_both_surfaces_work_without_any_legacy_state_file(self):
        self.start_child(agent_id="a1", name="Explore", now=time.time())
        self.assertFalse(paths.legacy_subagents_path().exists())
        self.assertEqual([c["name"] for c in herdr_agent_tree.hook_children(leader())], ["Explore"])
        self.assertEqual([c["name"] for c in claude_team_tree.hook_children("s1")], ["Explore"])

    def test_verified_zero_children_are_not_overridden_by_leftover_legacy_state(self):
        now = time.time()
        self.start_child(agent_id="a1", name="Explore", now=now)
        claude_code.ingest({"hook_event_name": "SubagentStop", "session_id": "s1", "agent_id": "a1"}, now=now)
        self.write_legacy('{"sessions":{"s1":{"stale":{"name":"Leftover","status":"working"}}}}')
        self.assertEqual(reader.children_for_session("s1", now=now), [])
        self.assertEqual(claude_team_tree.hook_children("s1"), [])

    def test_stale_canonical_state_defers_to_legacy_children(self):
        self.start_child(agent_id="a1", name="Canonical", now=100.0)
        self.write_legacy('{"sessions":{"s1":{"a9":{"name":"Legacy","status":"working"}}}}')
        self.assertEqual([c.name for c in reader.children_for_session("s1", now=100000.0)], ["Legacy"])

    def test_malformed_canonical_state_defers_to_legacy_children(self):
        paths.ensure_state_root()
        paths.snapshot_path().write_text("{not json", encoding="utf-8")
        self.write_legacy('{"sessions":{"s1":{"a9":{"name":"Legacy","status":"working"}}}}')
        self.assertEqual([c["name"] for c in herdr_agent_tree.hook_children(leader())], ["Legacy"])

    def test_missing_session_and_absent_state_stay_empty(self):
        self.assertEqual(herdr_agent_tree.hook_children({"agent": "claude", "agent_session": {}}), [])
        self.assertEqual(claude_team_tree.hook_children(None), [])
        self.assertEqual(reader.children_for_session("nothing", now=105.0), [])


if __name__ == "__main__":
    unittest.main()
