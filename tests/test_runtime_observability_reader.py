import os
import tempfile
import unittest

from src.runtime_observability import ids, model, paths, reader, store


def leader(runtime="claude", session="s1", **extra):
    data = {"agent": runtime, "pane_id": runtime + "-pane", "workspace_id": "w1", "agent_session": {"value": session}, "agent_status": "working"}
    data.update(extra)
    return data


class RuntimeObservabilityReaderTests(unittest.TestCase):
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

    def read(self, agents, now=10.0):
        return reader.read_agents({"focused_workspace_id": "w1", "agents": agents}, now=now).leaders

    def test_herdr_native_children_take_precedence_over_canonical_and_legacy(self):
        store.update_activity(model.Activity("claude", "s1", "canonical", "Canonical", "working", observed_at=9, expires_at=20))
        paths.legacy_subagents_path().write_text('{"sessions":{"s1":{"legacy":{"name":"Legacy","status":"working"}}}}', encoding="utf-8")
        result = self.read([leader(children=[{"id": "native", "name": "Native", "status": "blocked"}])])[0]
        self.assertEqual(result.source, "herdr")
        self.assertEqual([c.name for c in result.activities], ["Native"])
        self.assertEqual(result.activities[0].status, "blocked")

    def test_fresh_canonical_wins_over_legacy_and_cross_runtime_ids_are_separate(self):
        store.update_activity(model.Activity("claude", "same", "a", "Claude", "working", observed_at=9, expires_at=20))
        store.update_activity(model.Activity("codex", "same", "a", "Codex", "blocked", observed_at=9, expires_at=20))
        result = self.read([leader("claude", "same"), leader("codex", "same")])
        self.assertEqual([r.activities[0].name for r in result], ["Claude", "Codex"])

    def test_legacy_fallback_collision_guard_and_missing_session_no_guessing(self):
        paths.ensure_state_root()
        paths.legacy_subagents_path().write_text('{"sessions":{"same":{"a":{"name":"Legacy","status":"working"}}}}', encoding="utf-8")
        collided = self.read([leader("claude", "same"), leader("codex", "same")])
        self.assertTrue(all(r.source == "unknown" and not r.verified_zero_active for r in collided))
        missing = self.read([leader("claude", "same", agent_session={})])[0]
        self.assertEqual(missing.source, "unknown")
        self.assertEqual(missing.activities, [])

    def test_no_recognized_leader_and_malformed_sources_are_unknown_safe(self):
        paths.ensure_state_root()
        paths.snapshot_path().write_text("bad", encoding="utf-8")
        paths.legacy_subagents_path().write_text("bad", encoding="utf-8")
        self.assertEqual(self.read([leader("bash", "s1")]), [])
        result = self.read([leader("claude", "s1")])[0]
        self.assertEqual(result.status, "working")
        self.assertEqual(result.source, "unknown")

    def test_stale_working_becomes_unknown_but_ended_interrupts_children(self):
        session = model.Session("pi", "s1", presence="present", status="working", observed_at=1, expires_at=2, capabilities=model.capabilities(activity="complete"))
        store.update_session(session)
        store.update_activity(model.Activity("pi", "s1", "a", "Tool", "working", observed_at=1, expires_at=2))
        stale = self.read([leader("pi", "s1")], now=10)[0]
        self.assertEqual(stale.source, "unknown")
        self.assertEqual(stale.activities, [])
        self.assertFalse(stale.verified_zero_active)
        store.update_session(model.Session("pi", "s1", presence="ended", status="ended", observed_at=1, expires_at=2, capabilities=model.capabilities(activity="complete")))
        ended = self.read([leader("pi", "s1")], now=10)[0]
        self.assertEqual(ended.status, "ended")
        self.assertEqual(ended.activities[0].status, "interrupted")

    def test_stale_canonical_does_not_block_legacy_fallback(self):
        store.update_session(model.Session("claude", "s1", presence="present", status="working", observed_at=1, expires_at=2))
        paths.legacy_subagents_path().write_text('{"sessions":{"s1":{"a":{"name":"Legacy","status":"working"}}}}', encoding="utf-8")
        result = self.read([leader("claude", "s1")], now=99)[0]
        self.assertEqual(result.source, "legacy")
        self.assertEqual([c.name for c in result.activities], ["Legacy"])

    def test_absent_state_root_then_three_runtimes_stay_isolated(self):
        self.assertFalse(paths.state_root().exists())
        empty = self.read([leader("claude", "c")])[0]
        self.assertEqual(empty.source, "unknown")
        self.assertEqual(empty.activities, [])
        store.update_activity(model.Activity("pi", "p", "a", "PiTool", "working", observed_at=9, expires_at=20))
        results = {r.runtime: r for r in self.read([leader("claude", "c"), leader("codex", "x"), leader("pi", "p")])}
        self.assertEqual(set(results), {"claude", "codex", "pi"})
        self.assertEqual([c.name for c in results["pi"].activities], ["PiTool"])
        self.assertEqual(results["claude"].activities, [])

    def test_malformed_legacy_state_does_not_hide_valid_canonical_activities(self):
        paths.ensure_state_root()
        paths.legacy_subagents_path().write_text("{broken", encoding="utf-8")
        store.update_activity(model.Activity("codex", "s1", "a", "Canonical", "working", observed_at=9, expires_at=20))
        result = self.read([leader("codex", "s1")])[0]
        self.assertEqual(result.source, "canonical")
        self.assertEqual([c.name for c in result.activities], ["Canonical"])

    def test_verified_zero_active_only_when_activity_complete_and_fresh(self):
        store.update_session(model.Session("claude", "fresh", presence="present", status="idle", observed_at=9, expires_at=20, capabilities=model.capabilities(activity="complete")))
        store.update_session(model.Session("claude", "partial", presence="present", status="idle", observed_at=9, expires_at=20, capabilities=model.capabilities(activity="partial")))
        results = {r.raw_session_id: r for r in self.read([leader("claude", "fresh"), leader("claude", "partial")])}
        self.assertTrue(results["fresh"].verified_zero_active)
        self.assertFalse(results["partial"].verified_zero_active)


if __name__ == "__main__":
    unittest.main()
