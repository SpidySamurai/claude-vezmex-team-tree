from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("herdr_agent_tree.py")
spec = importlib.util.spec_from_file_location("herdr_agent_tree", MODULE_PATH)
herdr_agent_tree = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(herdr_agent_tree)


def test_normalize_status_maps_common_states() -> None:
    assert herdr_agent_tree.normalize_status("running") == "working"
    assert herdr_agent_tree.normalize_status("completed") == "done"
    assert herdr_agent_tree.normalize_status("failed") == "blocked"
    assert herdr_agent_tree.normalize_status("idle") == "idle"
    assert herdr_agent_tree.normalize_status("unexpected") == "unknown"


def test_native_children_prefers_future_herdr_snapshot_fields() -> None:
    agent = {
        "subagents": [
            {"id": "a", "name": "Scout", "agent_status": "completed"},
            {"id": "b", "label": "Worker", "state": "running"},
        ]
    }

    assert herdr_agent_tree.native_children(agent) == [
        {"id": "a", "name": "Scout", "status": "done", "source": "herdr"},
        {"id": "b", "name": "Worker", "status": "working", "source": "herdr"},
    ]


def test_slot_line_combines_state_glyph_and_name() -> None:
    assert herdr_agent_tree.slot_line({"name": "Scout", "status": "completed"}) == "✓ Scout"


def test_slot_line_animates_the_working_glyph_by_frame() -> None:
    child = {"name": "Worker", "status": "running"}
    assert herdr_agent_tree.slot_line(child, frame=0) == "⠋ Worker"
    assert herdr_agent_tree.slot_line(child, frame=1) == "⠙ Worker"
    # cycles back after the frame set length
    wrapped = herdr_agent_tree.slot_line(child, frame=len(herdr_agent_tree.SPINNER_FRAMES))
    assert wrapped == herdr_agent_tree.slot_line(child, frame=0)


def test_publish_reports_one_slot_token_per_child_and_clears_the_rest() -> None:
    calls = []
    original = herdr_agent_tree.run_herdr
    herdr_agent_tree.run_herdr = lambda *args: calls.append(args) or {}
    try:
        count = herdr_agent_tree.publish(
            {
                "agents": [
                    {
                        "pane_id": "pane-1",
                        "agent": "pi",
                        "agent_status": "working",
                        "subagents": [
                            {"id": "a", "name": "Scout", "agent_status": "done"},
                            {"id": "b", "name": "Worker", "agent_status": "working"},
                        ],
                    },
                    {"pane_id": "pane-2", "agent": "codex", "agent_status": "idle"},
                ]
            },
            "plugin:test:agent-tree",
        )
    finally:
        herdr_agent_tree.run_herdr = original

    assert count == 2
    args1 = calls[0]
    assert args1[:5] == ("pane", "report-metadata", "pane-1", "--source", "plugin:test:agent-tree")
    assert args1[5:9] == ("--token", "subagent_1=✓ Scout", "--token", "subagent_2=⠋ Worker")
    # every remaining slot is explicitly cleared, not left as a placeholder
    for index in range(3, herdr_agent_tree.SLOT_COUNT + 1):
        assert ("--clear-token", f"subagent_{index}") in tuple(zip(args1, args1[1:]))

    args2 = calls[1]
    assert args2[:5] == ("pane", "report-metadata", "pane-2", "--source", "plugin:test:agent-tree")
    # no children at all: every slot is cleared, nothing is shown
    for index in range(1, herdr_agent_tree.SLOT_COUNT + 1):
        assert ("--clear-token", f"subagent_{index}") in tuple(zip(args2, args2[1:]))
    assert "--token" not in args2
    # neither pane has a session_id, so the entry-point row is cleared too
    assert args1[-2:] == ("--clear-token", "session_summary")
    assert args2[-2:] == ("--clear-token", "session_summary")


def test_session_summary_line_reports_history_and_artifacts_counts() -> None:
    with tempfile.TemporaryDirectory() as state_home:
        old_state_home = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = state_home
        try:
            assert herdr_agent_tree.session_summary_line("s1") is None  # nothing recorded yet
            assert herdr_agent_tree.session_summary_line(None) is None

            root = herdr_agent_tree.plugin_state_root()
            root.mkdir(parents=True, exist_ok=True)
            (root / "history.jsonl").write_text(
                '{"session":"s1","name":"a"}\n{"session":"s1","name":"b"}\n{"session":"other","name":"c"}\n',
                encoding="utf-8",
            )
            assert herdr_agent_tree.session_summary_line("s1") == "historial · 2"

            (root / "artifacts.jsonl").write_text('{"session":"s1","title":"x"}\n', encoding="utf-8")
            assert herdr_agent_tree.session_summary_line("s1") == "historial · 2 · 1 artifact"
        finally:
            if old_state_home is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state_home
