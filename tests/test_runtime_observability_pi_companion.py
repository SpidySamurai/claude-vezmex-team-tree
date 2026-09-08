"""Synthetic Pi extension events, per design: no real Pi process is required."""
import os
import tempfile
import unittest

from src.runtime_observability import ids, store
from src.runtime_observability.adapters import pi_companion


class PiCompanionAdapterTests(unittest.TestCase):
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
        return store.read_snapshot().sessions.get(ids.session_id("pi", raw))

    def test_session_start_reports_present_and_idle(self):
        self.assertTrue(pi_companion.ingest({"kind": "session_start", "session_id": "s1"}, now=100.0))
        record = self.session()
        self.assertEqual((record["presence"], record["status"]), ("present", "idle"))
        self.assertEqual(record["source"]["runtime"], "pi")
        self.assertEqual(record["source"]["collector"], "pi-extension")

    def test_agent_start_reports_working_and_settled_reports_idle(self):
        pi_companion.ingest({"kind": "session_start", "session_id": "s1"}, now=100.0)
        pi_companion.ingest({"kind": "agent_start", "session_id": "s1"}, now=101.0)
        self.assertEqual(self.session()["status"], "working")
        pi_companion.ingest({"kind": "agent_settled", "session_id": "s1"}, now=102.0)
        self.assertEqual(self.session()["status"], "idle")

    def test_agent_end_does_not_claim_idle_because_pi_may_still_retry_or_compact(self):
        pi_companion.ingest({"kind": "agent_start", "session_id": "s1"}, now=100.0)
        pi_companion.ingest({"kind": "agent_end", "session_id": "s1"}, now=101.0)
        self.assertEqual(self.session()["status"], "working")

    def test_tool_execution_reports_activity_working_then_done_or_blocked(self):
        pi_companion.ingest({"kind": "tool_execution_start", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash"}, now=100.0)
        activity = list(self.session()["activities"].values())[0]
        self.assertEqual((activity["name"], activity["status"], activity["started_at"]), ("bash", "working", 100.0))
        pi_companion.ingest({"kind": "tool_execution_end", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash", "is_error": False}, now=101.0)
        self.assertEqual(list(self.session()["activities"].values())[0]["status"], "done")

    def test_tool_execution_end_preserves_the_original_start_time(self):
        pi_companion.ingest({"kind": "tool_execution_start", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash"}, now=100.0)
        pi_companion.ingest({"kind": "tool_execution_end", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash", "is_error": False}, now=145.0)
        self.assertEqual(list(self.session()["activities"].values())[0]["started_at"], 100.0)

    def test_failed_tool_execution_reports_blocked(self):
        pi_companion.ingest({"kind": "tool_execution_start", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash"}, now=100.0)
        pi_companion.ingest({"kind": "tool_execution_end", "session_id": "s1", "tool_call_id": "t1", "tool_name": "bash", "is_error": True}, now=101.0)
        self.assertEqual(list(self.session()["activities"].values())[0]["status"], "blocked")

    def test_session_shutdown_ends_only_a_session_already_on_record(self):
        self.assertFalse(pi_companion.ingest({"kind": "session_shutdown", "session_id": "ghost"}, now=100.0))
        pi_companion.ingest({"kind": "session_start", "session_id": "s1"}, now=100.0)
        self.assertTrue(pi_companion.ingest({"kind": "session_shutdown", "session_id": "s1"}, now=101.0))
        self.assertEqual((self.session()["presence"], self.session()["status"]), ("ended", "ended"))

    def test_capabilities_declare_top_level_only_evidence(self):
        pi_companion.ingest({"kind": "session_start", "session_id": "s1"}, now=100.0)
        caps = self.session()["capabilities"]
        self.assertEqual(caps["activity"], "partial")
        self.assertEqual(caps["completion"], "supported")
        self.assertEqual(caps["history"], "unsupported")
        self.assertEqual(caps["artifacts"], "unsupported")

    def test_unsupported_or_malformed_events_are_ignored(self):
        for event in (None, {"kind": "unknown_event", "session_id": "s1"}, {"kind": "session_start", "session_id": ""}, {"kind": "tool_execution_start", "session_id": "s1", "tool_name": "bash"}):
            self.assertFalse(pi_companion.ingest(event, now=100.0))
        self.assertEqual(store.read_snapshot().sessions, {})


if __name__ == "__main__":
    unittest.main()
