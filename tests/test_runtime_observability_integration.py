"""End-to-end: Claude, Codex, and Pi leaders visible simultaneously, plus
stale, malformed, and unrecognized/no-agent cases, exercised through the same
public entrypoints both Herdr surfaces use.
"""
import os
import tempfile
import time
import unittest

from src.runtime_observability import legacy, model, paths, reader, store
from src.runtime_observability.adapters import claude_code, codex, pi_companion


def leader(runtime, session, **extra):
    data = {"agent": runtime, "pane_id": f"{runtime}-pane", "workspace_id": "w1", "agent_session": {"value": session}, "agent_status": "working"}
    data.update(extra)
    return data


class RuntimeObservabilityIntegrationTest(unittest.TestCase):
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

    def test_three_runtimes_stale_and_malformed_state_never_cross_contaminate(self):
        now = time.time()

        # Claude: full lifecycle via its adapter.
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "claude-s", "agent_id": "a1", "agent_type": "Explore"}, now=now)

        # Codex: hook-compatible wiring only, conservative capabilities.
        codex.ingest({"hook_event_name": "SubagentStart", "session_id": "codex-s", "agent_id": "a1", "agent_type": "Verify"}, now=now)

        # Pi: its own top-level session and tool call.
        pi_companion.ingest({"kind": "session_start", "session_id": "pi-s"}, now=now)
        pi_companion.ingest({"kind": "tool_execution_start", "session_id": "pi-s", "tool_call_id": "t1", "tool_name": "bash"}, now=now)

        # A stale fourth Claude session that must not appear as current.
        store.update_activity(model.Activity("claude", "stale-s", "a9", "Old", "working", observed_at=now - 3600, expires_at=now - 3500))

        # Malformed legacy state must not take down canonical reads.
        paths.legacy_subagents_path().write_text("{not json", encoding="utf-8")

        snapshot = {
            "focused_workspace_id": "w1",
            "agents": [
                leader("claude", "claude-s"),
                leader("codex", "codex-s"),
                leader("pi", "pi-s"),
                leader("claude", "stale-s"),
                leader("bash", "unrelated"),  # unrecognized agent kind
            ],
        }
        result = reader.read_agents(snapshot, now=now)
        by_runtime = {(leader_view.runtime, leader_view.raw_session_id): leader_view for leader_view in result.leaders}

        claude_leader = by_runtime[("claude", "claude-s")]
        self.assertEqual([a.name for a in claude_leader.activities], ["Explore"])

        codex_leader = by_runtime[("codex", "codex-s")]
        self.assertEqual([a.name for a in codex_leader.activities], ["Verify"])

        pi_leader = by_runtime[("pi", "pi-s")]
        self.assertEqual([a.name for a in pi_leader.activities], ["bash"])

        stale_leader = by_runtime[("claude", "stale-s")]
        self.assertEqual(stale_leader.activities, [])
        self.assertFalse(stale_leader.verified_zero_active)

        self.assertNotIn(("bash", "unrelated"), by_runtime)
        self.assertEqual(len(result.leaders), 4)

        # Per-session lookup used by both Herdr surfaces stays isolated too.
        self.assertEqual([c.name for c in reader.children_for_session("claude-s", now=now)], ["Explore"])
        self.assertEqual([c.name for c in reader.children_for_session("codex-s", now=now)], ["Verify"])
        self.assertEqual([c.name for c in reader.children_for_session("pi-s", now=now)], ["bash"])

    def test_no_recognized_leader_borrows_nothing_and_reports_no_agent(self):
        now = time.time()
        claude_code.ingest({"hook_event_name": "SubagentStart", "session_id": "elsewhere", "agent_id": "a1", "agent_type": "Explore"}, now=now)
        legacy.children_for_session(None)  # exercise the guard directly too
        result = reader.read_agents({"focused_workspace_id": "w1", "agents": [leader("bash", "elsewhere")]}, now=now)
        self.assertEqual(result.leaders, [])


if __name__ == "__main__":
    unittest.main()
