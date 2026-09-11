#!/usr/bin/env python3
"""Offline regression checks for Claude hook payloads and the tree join."""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# The modules under test live in src/; tests sit beside it, not in it.
ROOT = Path(__file__).resolve().parent.parent / "src"
HOOK = ROOT / "claude_subagent_hook.py"
PROFILE_HOOK = ROOT / "claude_profile_hook.py"
sys.path.insert(0, str(ROOT))
import claude_team_tree  # noqa: E402
import dashboard_config  # noqa: E402
from runtime_observability import model, store  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def plain(line: str) -> str:
    """A rendered line without its SGR colour codes, so a test can assert on
    layout (column alignment, visible width) instead of escape soup.
    """
    return ANSI_RE.sub("", line)


SNAPSHOT = {"focused_workspace_id": "w1", "panes": [], "agents": [{
    "agent": "claude", "workspace_id": "w1", "pane_id": "p1", "focused": True,
    "agent_status": "working", "agent_session": {"value": "sess"},
    "terminal_title_stripped": "Proyecto",
}]}


@contextlib.contextmanager
def fake_panel(children=(), history=(), artifacts=(), overrides=None, ended=None):
    """Drive render() from in-memory state instead of hook files, so a panel
    test states exactly the session it is about.
    """
    config = dict(dashboard_config.DEFAULTS) | (overrides or {})
    saved = {name: getattr(claude_team_tree, name) for name in (
        "hook_children", "session_history", "session_artifacts",
        "session_started_at", "session_ended_at", "load_config",
    )}
    claude_team_tree.hook_children = lambda sid: [dict(c) for c in children]
    claude_team_tree.session_history = lambda sids, limit: (list(history)[:limit], len(history))
    claude_team_tree.session_artifacts = lambda sids, limit: list(artifacts)[:limit]
    claude_team_tree.session_started_at = lambda sid: 1000.0
    claude_team_tree.session_ended_at = lambda sid, runtime=None: ended
    claude_team_tree.load_config = lambda: dict(config)
    try:
        yield config
    finally:
        for name, value in saved.items():
            setattr(claude_team_tree, name, value)


def rows_of(frame) -> list[str]:
    return [plain(line) for line in frame.text.split("\n")]


@contextlib.contextmanager
def isolated_state():
    """Point the config file at a throwaway directory, so tests that write it
    (every click that cycles a value does) never touch the real one.
    """
    with tempfile.TemporaryDirectory() as state_home:
        old_state = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = state_home
        try:
            yield Path(state_home)
        finally:
            if old_state is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = old_state


class HookDashboardTest(unittest.TestCase):
    def test_documented_subagent_events_join_herdr_leader_session(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            start = {
                "session_id": "leader-session",
                "transcript_path": "/tmp/leader.jsonl",
                "cwd": "/tmp",
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-123",
                "agent_type": "Explore",
            }
            stop = start | {
                "hook_event_name": "SubagentStop",
                "agent_transcript_path": "/tmp/subagents/agent-123.jsonl",
                "last_assistant_message": "Done.",
            }
            for event in (start, stop):
                completed = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event), text=True, env=environment
                )
                self.assertEqual(completed.returncode, 0)

            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {"focused_workspace_id": "workspace-1", "agents": [{
                    "agent": "claude", "workspace_id": "workspace-1", "pane_id": "leader-pane",
                    "agent_status": "working", "agent_session": {"value": "leader-session"},
                }]}
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        # A finished subagent is removed from the live tree, not shown as
        # "done" there (nor as any placeholder line) — it moves to the
        # HISTORIAL section instead.
        self.assertIn("⚙ settings", rendered)  # the header carries the gear chip
        self.assertNotIn("├─", rendered)
        self.assertNotIn("└─", rendered)
        self.assertIn("SESSION HISTORY", rendered)
        self.assertIn("Explore", rendered)
        self.assertIn("tokens", rendered)

    def test_subagent_stop_captures_tool_tally_nested_agents_and_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as state_home, tempfile.TemporaryDirectory() as project:
            transcript = Path(project) / "agent-999.jsonl"
            transcript.write_text(
                "\n".join(
                    json.dumps(line)
                    for line in [
                        {"type": "user", "message": {"role": "user", "content": "Investiga el bug de tokens"}},
                        {
                            "type": "assistant",
                            "message": {
                                "usage": {"input_tokens": 3, "output_tokens": 7},
                                "content": [{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}],
                            },
                        },
                        {
                            "type": "assistant",
                            "message": {
                                "usage": {"input_tokens": 1, "output_tokens": 2},
                                "content": [{"type": "tool_use", "name": "Task", "id": "t2", "input": {}}],
                            },
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            start = {"session_id": "leader-session", "hook_event_name": "SubagentStart", "agent_id": "agent-999", "agent_type": "Explore"}
            stop = {
                "session_id": "leader-session",
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-999",
                "agent_type": "Explore",
                "agent_transcript_path": str(transcript),
                "last_assistant_message": "todo listo",
            }
            for event in (start, stop):
                completed = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event), text=True, env=environment
                )
                self.assertEqual(completed.returncode, 0)

            history_path = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "history.jsonl"
            record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])

        self.assertEqual(record["task"], "Investiga el bug de tokens")
        self.assertEqual(record["tokens"], 3 + 7 + 1 + 2)
        self.assertEqual(record["tools"], {"Bash": 1, "Task": 1})
        self.assertEqual(record["tool_uses"], 2)
        self.assertEqual(record["nested_agents"], 1)
        self.assertEqual(record["last_message"], "todo listo")

    def test_subagent_stop_captures_model_and_effort_from_the_transcript(self) -> None:
        """model/effort live on the transcript ENTRY, not message.usage, and
        do not vary within one subagent's own transcript — take the first
        real one seen, skipping the synthetic compaction entry a transcript
        can carry."""
        with tempfile.TemporaryDirectory() as state_home, tempfile.TemporaryDirectory() as project:
            transcript = Path(project) / "agent-model.jsonl"
            transcript.write_text(
                "\n".join(
                    json.dumps(line)
                    for line in [
                        {"type": "user", "message": {"role": "user", "content": "Audita el plugin"}},
                        {"type": "assistant", "model": "<synthetic>",
                         "message": {"usage": {"input_tokens": 1, "output_tokens": 1}, "content": []}},
                        {"type": "assistant", "model": "claude-sonnet-5", "effort": "high",
                         "message": {"usage": {"input_tokens": 3, "output_tokens": 7}, "content": []}},
                        {"type": "assistant", "model": "claude-sonnet-5", "effort": "high",
                         "message": {"usage": {"input_tokens": 1, "output_tokens": 2}, "content": []}},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            start = {"session_id": "leader-session", "hook_event_name": "SubagentStart",
                     "agent_id": "agent-model", "agent_type": "Explore"}
            stop = {
                "session_id": "leader-session", "hook_event_name": "SubagentStop",
                "agent_id": "agent-model", "agent_type": "Explore",
                "agent_transcript_path": str(transcript),
            }
            for event in (start, stop):
                completed = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event), text=True, env=environment
                )
                self.assertEqual(completed.returncode, 0)

            history_path = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "history.jsonl"
            record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])

        self.assertEqual(record["model"], "claude-sonnet-5")
        self.assertEqual(record["effort"], "high")

    def test_a_transcript_with_no_model_field_records_none(self) -> None:
        """Predates the field, or a runtime whose transcript shape is
        unverified: absent, not a guess."""
        with tempfile.TemporaryDirectory() as state_home, tempfile.TemporaryDirectory() as project:
            transcript = Path(project) / "agent-old.jsonl"
            transcript.write_text(
                json.dumps({"type": "assistant",
                            "message": {"usage": {"input_tokens": 1, "output_tokens": 1}, "content": []}}) + "\n",
                encoding="utf-8",
            )
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            start = {"session_id": "leader-session", "hook_event_name": "SubagentStart",
                     "agent_id": "agent-old", "agent_type": "Explore"}
            stop = {
                "session_id": "leader-session", "hook_event_name": "SubagentStop",
                "agent_id": "agent-old", "agent_type": "Explore",
                "agent_transcript_path": str(transcript),
            }
            for event in (start, stop):
                completed = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event), text=True, env=environment
                )
                self.assertEqual(completed.returncode, 0)
            history_path = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "history.jsonl"
            record = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertIsNone(record.get("model"))
        self.assertIsNone(record.get("effort"))

    def test_non_lifecycle_event_creates_no_state(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            event = {"session_id": "leader-session", "hook_event_name": "PostToolUse", "agent_id": "agent-123"}
            completed = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(event), text=True,
                env=os.environ | {"XDG_STATE_HOME": state_home},
            )
            self.assertEqual(completed.returncode, 0)
            self.assertFalse((Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "subagents.json").exists())

    def test_dashboard_counts_and_renders_active_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree"
            state.mkdir(parents=True)
            (state / "subagents.json").write_text(json.dumps({"sessions": {"leader-session": {
                "agent-123": {"name": "Explore", "status": "done"},
                "agent-456": {"name": "general-purpose", "status": "working"},
            }}}), encoding="utf-8")
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {"focused_workspace_id": "workspace-1", "agents": [
                    {"agent": "claude", "workspace_id": "workspace-1", "pane_id": "leader-pane",
                     "agent_status": "working", "agent_session": {"value": "leader-session"}},
                ]}
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        self.assertIn("Explore", rendered)
        self.assertIn("general-purpose", rendered)
        self.assertIn("⚙ settings", rendered)  # the header carries the gear chip
        self.assertIn("working", rendered)

    def test_dashboard_hints_at_older_history_entries_beyond_the_shown_limit(self) -> None:
        # Two more entries than the configured limit allows, whatever that
        # default currently is — the assertion below doesn't hardcode it.
        limit = dashboard_config.DEFAULTS["history_limit"]
        with tempfile.TemporaryDirectory() as state_home:
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree"
            state.mkdir(parents=True)
            records = [
                {"session": "leader-session", "name": f"agent-{i}", "stopped": i, "tokens": 100}
                for i in range(limit + 2)
            ]
            (state / "history.jsonl").write_text(
                "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
            )
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {"focused_workspace_id": "workspace-1", "agents": [
                    {"agent": "claude", "workspace_id": "workspace-1", "pane_id": "leader-pane",
                     "agent_status": "idle", "agent_session": {"value": "leader-session"}},
                ]}
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state
        self.assertIn("+2 more", rendered)

    def test_a_persisted_session_with_matching_cwd_is_not_resurrected(self) -> None:
        # There used to be a cwd-matching fallback: when Herdr detected no
        # agent at all, the panel dug up a past Claude session from
        # profiles.json that had run in the same directory. cwd is shared by
        # every past session in a project, so what that produced in an
        # agent-less pane was some unrelated session's history and artifacts,
        # presented as if they belonged here. No agent now means the idle
        # screen, full stop — recorded state that merely shares a cwd is not
        # evidence anything is running.
        with tempfile.TemporaryDirectory() as state_home, tempfile.TemporaryDirectory() as project:
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree"
            state.mkdir(parents=True)
            transcript = Path(project) / "leader.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            (state / "profiles.json").write_text(json.dumps({"sessions": {
                "fresh-session": {
                    "cwd": "/project",
                    "transcript_path": str(transcript),
                    "updated": 2,
                },
            }}), encoding="utf-8")
            (state / "subagents.json").write_text(json.dumps({"sessions": {"fresh-session": {
                "agent-789": {"name": "Explore", "status": "working"},
            }}}), encoding="utf-8")
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {
                    "focused_workspace_id": "workspace-1",
                    "agents": [],
                    "panes": [{"workspace_id": "workspace-1", "cwd": "/project"}],
                }
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        self.assertIn("no agent", rendered)
        self.assertNotIn("Claude (hook)", rendered)
        self.assertNotIn("Explore", rendered)

    def test_dashboard_does_not_leak_a_claude_session_into_an_unrecognized_agents_workspace(self) -> None:
        # Opening the dashboard from a pane running some OTHER, unrecognized
        # tool must never fall back to a cwd-matched Claude session recorded
        # by a different, unrelated workspace that merely shares the same
        # cwd — a real regression this reproduces exactly.
        with tempfile.TemporaryDirectory() as state_home, tempfile.TemporaryDirectory() as project:
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree"
            state.mkdir(parents=True)
            transcript = Path(project) / "leader.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            (state / "profiles.json").write_text(json.dumps({"sessions": {
                "other-workspace-session": {
                    "cwd": "/shared/project",
                    "transcript_path": str(transcript),
                    "updated": 2,
                },
            }}), encoding="utf-8")
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {
                    "focused_workspace_id": "other-workspace",
                    "agents": [
                        {"agent": "some-other-tool", "workspace_id": "other-workspace", "pane_id": "other-pane",
                         "agent_status": "idle"},
                    ],
                    "panes": [{"workspace_id": "other-workspace", "cwd": "/shared/project"}],
                }
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        self.assertIn("no agent", rendered)
        self.assertNotIn("Claude (hook)", rendered)

    def test_dashboard_is_agent_agnostic_and_shows_a_pi_leader_too(self) -> None:
        # Herdr recognizes claude/codex/pi as dashboard leaders — a "pi" pane
        # must render its own state, not the empty "no agent" message, even
        # with no subagent history recorded for it yet.
        with tempfile.TemporaryDirectory() as state_home:
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                snapshot = {
                    "focused_workspace_id": "pi-workspace",
                    "agents": [
                        {"agent": "pi", "workspace_id": "pi-workspace", "pane_id": "pi-pane",
                         "agent_status": "idle", "display_agent": "Pi (Buffy)",
                         "agent_session": {"value": "pi-session"}},
                    ],
                }
                rendered = claude_team_tree.render(snapshot, frame=0, width=80)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        self.assertNotIn("No hay un agente reconocido aquí", rendered)
        self.assertIn("Pi (Buffy)", rendered)

    def test_profile_hook_preserves_started_across_resume_and_compact(self) -> None:
        profiles_path_parts = ("herdr", "claude-vezmex-team-tree", "profiles.json")
        with tempfile.TemporaryDirectory() as state_home:
            environment = os.environ | {"XDG_STATE_HOME": state_home}
            profiles_path = Path(state_home).joinpath(*profiles_path_parts)

            first = {"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup"}
            completed = subprocess.run(
                [sys.executable, str(PROFILE_HOOK)], input=json.dumps(first), text=True, env=environment
            )
            self.assertEqual(completed.returncode, 0)
            started_after_first = json.loads(profiles_path.read_text(encoding="utf-8"))["sessions"]["s1"]["started"]

            second = {"session_id": "s1", "hook_event_name": "SessionStart", "source": "compact"}
            completed = subprocess.run(
                [sys.executable, str(PROFILE_HOOK)], input=json.dumps(second), text=True, env=environment
            )
            self.assertEqual(completed.returncode, 0)
            session_after_second = json.loads(profiles_path.read_text(encoding="utf-8"))["sessions"]["s1"]

        # a second SessionStart (a compact) must not move "started" forward,
        # only "updated" — otherwise the session-elapsed timer would reset.
        self.assertEqual(session_after_second["started"], started_after_first)

    def test_wrap_stats_packs_onto_one_line_when_it_fits(self) -> None:
        parts = ["AGENTES 6", "TOKENS 763.8k", "ARTIFACTS 4", "DUR 1:05"]
        self.assertEqual(claude_team_tree.wrap_stats(parts, 90), [" · ".join(parts)])

    def test_wrap_stats_never_truncates_when_it_does_not_fit(self) -> None:
        # A footer whose numbers grew large enough to overflow a narrow pane
        # must wrap onto more lines, never clip a value with an ellipsis.
        parts = ["AGENTES 42", "TOKENS 12.3M", "ARTIFACTS 17", "DUR 3h14m"]
        wrapped = claude_team_tree.wrap_stats(parts, 20)
        self.assertTrue(all(len(line) <= 20 for line in wrapped))
        self.assertNotIn("…", " ".join(wrapped))
        for part in parts:
            self.assertTrue(any(part in line for line in wrapped))

    def test_format_duration_adds_an_hour_segment_past_an_hour(self) -> None:
        self.assertEqual(claude_team_tree.format_duration(45), "0:45")
        self.assertEqual(claude_team_tree.format_duration(125), "2:05")
        self.assertEqual(claude_team_tree.format_duration(3725), "1:02:05")

    def test_historial_detail_lines_hides_when_nothing_to_report(self) -> None:
        self.assertEqual(claude_team_tree.historial_detail_lines({}, False, 52), [])
        self.assertEqual(
            claude_team_tree.historial_detail_lines({"tool_uses": 0, "nested_agents": 0}, False, 52), []
        )

    def test_historial_detail_lines_reports_task_tools_and_delegation(self) -> None:
        record = {
            "task": "Investiga el bug de tokens",
            "tools": {"Bash": 2, "Read": 1},
            "tool_uses": 3,
            "nested_agents": 1,
            "last_message": "listo",
        }
        lines = claude_team_tree.historial_detail_lines(record, False, 90)
        self.assertEqual(len(lines), 1)
        self.assertIn("Investiga el bug de tokens", lines[0])
        self.assertIn("Bash×2, Read×1", lines[0])
        self.assertIn("delegated to 1", lines[0])
        self.assertIn("listo", lines[0])
        self.assertIn(" → ", lines[0])

    def test_historial_detail_lines_caps_a_long_task_so_tools_and_result_survive(self) -> None:
        record = {
            "task": "This is a deliberately long and detailed task description meant to "
            "test how the dashboard truncates very long task prompts when displayed.",
            "tools": {"Bash": 2},
            "tool_uses": 2,
            "last_message": "todo listo",
        }
        line = claude_team_tree.historial_detail_lines(record, False, 90)[0]
        # the task segment itself gets clipped (short), but tools/result must
        # still be present — previously a long task alone could eat the
        # whole line's clip budget and silently drop everything after it.
        self.assertIn("Bash×2", line)
        self.assertIn("todo listo", line)

    def test_session_started_at_reads_profiles_json(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            state = Path(state_home) / "herdr" / "claude-vezmex-team-tree"
            state.mkdir(parents=True)
            (state / "profiles.json").write_text(
                json.dumps({"sessions": {"s1": {"started": 111.0, "updated": 999.0}}}),
                encoding="utf-8",
            )
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                self.assertEqual(claude_team_tree.session_started_at("s1"), 111.0)
                self.assertIsNone(claude_team_tree.session_started_at("missing"))
                self.assertIsNone(claude_team_tree.session_started_at(None))
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state


    def test_load_config_returns_defaults_when_no_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                self.assertEqual(dashboard_config.load_config(), dashboard_config.DEFAULTS)
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

    def test_load_config_merges_file_over_defaults_and_ignores_bad_values(self) -> None:
        with tempfile.TemporaryDirectory() as state_home:
            path = Path(state_home) / "herdr" / "claude-vezmex-team-tree" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "history_limit": 12,
                "detail_level": "full",
                "unknown_key": "ignored",
                "poll_seconds": "not-a-number",  # wrong type -> falls back to default
            }), encoding="utf-8")
            old_state = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state_home
            try:
                config = dashboard_config.load_config()
            finally:
                if old_state is None:
                    del os.environ["XDG_STATE_HOME"]
                else:
                    os.environ["XDG_STATE_HOME"] = old_state

        self.assertEqual(config["history_limit"], 12)
        self.assertEqual(config["detail_level"], "full")
        self.assertNotIn("unknown_key", config)
        self.assertEqual(config["poll_seconds"], dashboard_config.DEFAULTS["poll_seconds"])

    def test_historial_detail_lines_minimal_shows_nothing(self) -> None:
        record = {"task": "algo", "tools": {"Bash": 1}, "tool_uses": 1, "last_message": "listo"}
        self.assertEqual(
            claude_team_tree.historial_detail_lines(record, False, 90, detail_level="minimal"), []
        )

    def test_historial_detail_lines_full_splits_task_onto_its_own_line(self) -> None:
        record = {"task": "Investiga el bug de tokens", "tools": {"Bash": 1}, "tool_uses": 1, "last_message": "listo"}
        lines = claude_team_tree.historial_detail_lines(record, False, 90, detail_level="full")
        self.assertEqual(len(lines), 2)
        self.assertIn("Task:", lines[0])
        self.assertIn("Investiga el bug de tokens", lines[0])
        self.assertIn("Bash×1", lines[1])
        self.assertIn("listo", lines[1])

    def test_menu_lines_open_with_a_title_row_then_one_row_per_option(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        lines = claude_team_tree.menu_lines(config, 80)
        self.assertEqual(len(lines), 1 + len(dashboard_config.MENU_OPTIONS))
        # The title row frames the block and carries the close affordance, so
        # the menu never looks like content that leaked into the panel.
        self.assertIn("SETTINGS", plain(lines[0]))
        self.assertIn("close", plain(lines[0]))
        self.assertIn("Detail", plain(lines[1]))
        self.assertIn("compact", plain(lines[1]))

    def test_menu_option_rows_show_the_position_inside_their_cycle(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        lines = claude_team_tree.menu_lines(config, 80)
        # "compact" is the 2nd of 3 detail levels — a click is a step in a
        # known-length list, not a blind guess.
        self.assertIn("(2/3)", plain(lines[1]))

    def test_menu_option_values_share_one_right_aligned_column(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        lines = claude_team_tree.menu_lines(config, 80)
        ends = set()
        for option, line in zip(dashboard_config.MENU_OPTIONS, lines[1:]):
            value = str(config[option])
            text = plain(line)
            ends.add(text.index(value) + len(value))
        self.assertEqual(len(ends), 1, f"ragged value column: {ends}")

    def test_menu_lines_never_exceed_the_panel_width(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        for width in (26, 34, 42, 80):
            for line in claude_team_tree.menu_lines(config, width):
                self.assertLessEqual(len(plain(line)), width, f"width={width}: {plain(line)!r}")

    def test_menu_lines_drop_the_cycle_marker_when_the_pane_is_narrow(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        narrow = claude_team_tree.menu_lines(config, 26)
        self.assertNotIn("(2/3)", plain(narrow[1]))
        self.assertIn("compact", plain(narrow[1]))

    # ---- clicks are dispatched through the frame's own target map ----------
    # render() records which row carries which target, so a click resolves
    # against the layout that was actually drawn rather than a hardcoded row
    # number that drifts the moment a section collapses or a band appears.
    def test_handle_click_on_the_header_target_toggles_the_menu(self) -> None:
        targets = {0: claude_team_tree.TARGET_MENU}
        with isolated_state():
            self.assertTrue(claude_team_tree.handle_click(1, targets, menu_open=False))
            self.assertFalse(claude_team_tree.handle_click(1, targets, menu_open=True))

    def test_handle_click_on_the_menu_close_target_closes_it(self) -> None:
        targets = {1: claude_team_tree.TARGET_MENU_CLOSE}
        with isolated_state():
            self.assertFalse(claude_team_tree.handle_click(2, targets, menu_open=True))

    def test_handle_click_on_an_untargeted_row_changes_nothing(self) -> None:
        with isolated_state():
            self.assertTrue(claude_team_tree.handle_click(99, {}, menu_open=True))
            self.assertEqual(
                dashboard_config.load_config()["detail_level"],
                dashboard_config.DEFAULTS["detail_level"],
            )

    def test_handle_click_on_an_option_target_cycles_and_persists_its_value(self) -> None:
        targets = {2: claude_team_tree.option_target("detail_level")}
        with isolated_state():
            still_open = claude_team_tree.handle_click(3, targets, menu_open=True)
            saved = dashboard_config.load_config()

        self.assertTrue(still_open)  # cycling a value doesn't close the menu
        # DEFAULTS["detail_level"] is "compact"; one left click advances it to
        # the next entry in DETAIL_LEVELS ("minimal","compact","full").
        self.assertEqual(saved["detail_level"], "full")

    def test_right_click_on_an_option_target_cycles_backwards(self) -> None:
        targets = {2: claude_team_tree.option_target("detail_level")}
        with isolated_state():
            still_open = claude_team_tree.handle_click(3, targets, menu_open=True, button=2)
            saved = dashboard_config.load_config()

        self.assertTrue(still_open)
        self.assertEqual(saved["detail_level"], "minimal")

    def test_handle_click_on_a_section_target_toggles_and_persists_it(self) -> None:
        targets = {7: claude_team_tree.TARGET_SECTION_HISTORY}
        with isolated_state():
            claude_team_tree.handle_click(8, targets, menu_open=False)
            self.assertEqual(dashboard_config.load_config()["history_collapsed"], 1)
            claude_team_tree.handle_click(8, targets, menu_open=False)
            self.assertEqual(dashboard_config.load_config()["history_collapsed"], 0)

    def test_a_section_click_never_opens_or_closes_the_menu(self) -> None:
        targets = {7: claude_team_tree.TARGET_SECTION_ARTIFACTS}
        with isolated_state():
            self.assertFalse(claude_team_tree.handle_click(8, targets, menu_open=False))
            self.assertTrue(claude_team_tree.handle_click(8, targets, menu_open=True))

    # ---- P1: collapsible sections -----------------------------------------
    HISTORY = [
        {"name": "Explore", "stopped": 1200.0, "duration_s": 74, "tokens": 30300},
        {"name": "review-risk", "stopped": 1300.0, "duration_s": 208, "tokens": 88100},
    ]
    ARTIFACTS = [{"title": "Panel", "kind": "publish", "at": 1250.0}]

    def test_section_headers_are_click_targets_that_report_their_count(self) -> None:
        with fake_panel(history=self.HISTORY, artifacts=self.ARTIFACTS):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 80)
        rows = rows_of(frame)
        history_row = next(i for i, r in enumerate(rows) if "SESSION HISTORY" in r)
        artifacts_row = next(i for i, r in enumerate(rows) if "ARTIFACTS" in r)
        self.assertEqual(frame.targets.get(history_row), claude_team_tree.TARGET_SECTION_HISTORY)
        self.assertEqual(frame.targets.get(artifacts_row), claude_team_tree.TARGET_SECTION_ARTIFACTS)
        self.assertIn("2", rows[history_row])   # the count rides the header
        self.assertIn("▾", rows[history_row])   # open

    def test_a_collapsed_section_keeps_its_header_and_drops_its_rows(self) -> None:
        with fake_panel(history=self.HISTORY, artifacts=self.ARTIFACTS,
                        overrides={"history_collapsed": 1}):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 80)
        rows = rows_of(frame)
        history_row = next(i for i, r in enumerate(rows) if "SESSION HISTORY" in r)
        self.assertIn("▸", rows[history_row])                       # collapsed
        self.assertEqual(frame.targets.get(history_row), claude_team_tree.TARGET_SECTION_HISTORY)
        self.assertFalse(any("Explore" in r for r in rows))
        self.assertTrue(any("ARTIFACTS" in r for r in rows))        # the other one stays
        # the footer still counts what the collapsed section holds
        self.assertTrue(any("AG 2" in r for r in rows))

    # ---- P2: proportional weight bars --------------------------------------
    # ---- the idle screen: no agent means no panel, and it spins -----------
    def test_idle_art_picks_the_widest_variant_that_fits(self) -> None:
        wide = claude_team_tree.idle_art(60, frame=0)
        narrow = claude_team_tree.idle_art(30, frame=0)
        self.assertEqual(wide, claude_team_tree.MANDALA_FRAMES[0])
        self.assertEqual(narrow, claude_team_tree.MANDALA_COMPACT_FRAMES[0])
        self.assertEqual(claude_team_tree.idle_art(12, frame=0), [])  # nothing fits

    def test_idle_art_cycles_through_every_rotation_and_wraps(self) -> None:
        frames = claude_team_tree.MANDALA_FRAMES
        self.assertEqual(claude_team_tree.idle_art(60, frame=3), frames[3])
        # main()'s frame counter never resets, so it must wrap forever
        self.assertEqual(claude_team_tree.idle_art(60, frame=len(frames)), frames[0])
        self.assertEqual(claude_team_tree.idle_art(60, frame=len(frames) * 5 + 2), frames[2])

    def test_mandala_frame_zero_is_symmetric_on_both_axes_and_plain_ascii(self) -> None:
        # A 12-petal rose curve (r = cos(6*theta)), filled and shaded by
        # distance from the boundary — generated from the formula, not drawn
        # by hand, so both mirror axes hold exactly for the unrotated frame,
        # not approximately. Later frames are deliberately NOT symmetric —
        # that asymmetry is what makes the rotation visible.
        for frames in (claude_team_tree.MANDALA_FRAMES, claude_team_tree.MANDALA_COMPACT_FRAMES):
            frame = frames[0]
            for line in frame:
                self.assertEqual(line[::-1], line, f"not left-right symmetric: {line!r}")
            self.assertEqual(frame[::-1], frame, "not top-bottom symmetric")
            self.assertTrue(all(c.isascii() for line in frame for c in line))

    def test_every_mandala_frame_is_the_same_size_and_actually_differs(self) -> None:
        # Same size so the rotation never makes the idle screen jitter or
        # reflow; genuinely different content so it is a rotation and not
        # 12 copies of the same drawing.
        for frames in (claude_team_tree.MANDALA_FRAMES, claude_team_tree.MANDALA_COMPACT_FRAMES):
            shape = {(len(f), len(f[0])) for f in frames}
            self.assertEqual(len(shape), 1, f"frames differ in size: {shape}")
            self.assertEqual(len({tuple(f) for f in frames}), len(frames))

    def test_no_mandala_frame_has_a_fully_blank_row(self) -> None:
        # A real bug found by generating this: certain rotation angles put
        # the whole middle row or column exactly on the curve's axis, where
        # theta is constant regardless of position — if that constant makes
        # cos(k*theta) vanish, the ENTIRE row/column reads radius zero and
        # goes blank. Fixed by sampling cell centres on an even-sized grid
        # (odd dimensions still land a cell dead on the axis); this guards
        # the fix.
        for frames in (claude_team_tree.MANDALA_FRAMES, claude_team_tree.MANDALA_COMPACT_FRAMES):
            for index, frame in enumerate(frames):
                self.assertTrue(all(line.strip() for line in frame), f"frame {index} has a blank row")

    def test_the_idle_screen_centres_the_art_in_both_directions(self) -> None:
        text = claude_team_tree.idle_screen(60, 30)
        rows = text.split("\n")
        self.assertEqual(len(rows), 30)
        art_rows = [i for i, r in enumerate(rows) if "%" in plain(r)]
        self.assertTrue(art_rows)
        # vertically centred: comparable blank space above and below the block
        filled = [i for i, r in enumerate(rows) if plain(r).strip()]
        above, below = filled[0], len(rows) - 1 - filled[-1]
        self.assertLessEqual(abs(above - below), 2)
        # horizontally centred: the art block's own left margin is balanced
        widest = max((plain(r) for r in rows), key=len)
        left = len(widest) - len(widest.lstrip())
        self.assertLessEqual(abs(left - (60 - len(widest.strip()) - left)), 2)

    def test_the_idle_screen_uses_the_requested_rotation(self) -> None:
        first = claude_team_tree.idle_screen(60, 30, frame=0)
        other = claude_team_tree.idle_screen(60, 30, frame=3)
        self.assertNotEqual(first, other)

    def test_the_idle_screen_never_exceeds_the_pane(self) -> None:
        for width in (26, 34, 48, 90):
            for height in (12, 24, 50):
                rows = claude_team_tree.idle_screen(width, height).split("\n")
                self.assertEqual(len(rows), height)
                for row in rows:
                    self.assertLessEqual(len(plain(row)), width, (width, height, repr(row)))

    def test_no_recognized_agent_draws_the_idle_screen_and_no_session_data(self) -> None:
        empty = {"focused_workspace_id": "w1", "panes": [], "agents": []}
        with fake_panel(history=self.HISTORY, artifacts=self.ARTIFACTS):
            frame = claude_team_tree.render_frame(empty, 0, 48, 24)
        text = frame.text
        self.assertIn("no agent", plain(text))
        # nothing from any other session may reach a pane with no agent
        for leaked in ("SESSION HISTORY", "ARTIFACTS", "Explore", "review-risk", "settings"):
            self.assertNotIn(leaked, plain(text))

    def test_an_unrecognized_agent_also_gets_the_idle_screen(self) -> None:
        other = {"focused_workspace_id": "w1", "panes": [], "agents": [
            {"agent": "somethingelse", "workspace_id": "w1", "pane_id": "p9"}]}
        with fake_panel():
            frame = claude_team_tree.render_frame(other, 0, 48, 24)
        self.assertIn("no agent", plain(frame.text))

    def test_a_recognized_agent_with_nothing_recorded_shows_just_the_live_tree(self) -> None:
        # A real leader with no subagents yet is true, not broken: the tree
        # itself is live data, so no history/artifacts section — and no
        # placeholder copy inventing something to say — is the right panel.
        with fake_panel():  # no children, no history, no artifacts
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 48, 24)
        rows = rows_of(frame)
        self.assertTrue(any("Proyecto" in r for r in rows))
        self.assertFalse(any("SESSION HISTORY" in r for r in rows))
        self.assertFalse(any("ARTIFACTS" in r for r in rows))

    def test_usable_columns_leaves_the_last_column_alone(self) -> None:
        # Measured in the real pane: a row built at exactly the reported width
        # loses its last character on screen. One column of margin, floored so
        # a tiny pane still gets render()'s own minimum.
        self.assertEqual(claude_team_tree.usable_columns(48), 47)
        self.assertEqual(claude_team_tree.usable_columns(130), 129)
        self.assertEqual(claude_team_tree.usable_columns(10), 26)

    def test_weight_bar_fills_proportionally_and_never_overflows(self) -> None:
        cells = claude_team_tree.BAR_W
        self.assertEqual(claude_team_tree.weight_bar(1.0).count("▰"), cells)
        self.assertEqual(claude_team_tree.weight_bar(0.0).count("▰"), 0)
        self.assertEqual(len(claude_team_tree.weight_bar(0.5)), cells)
        self.assertEqual(len(claude_team_tree.weight_bar(4.0)), cells)   # clamped
        self.assertEqual(len(claude_team_tree.weight_bar(-1.0)), cells)

    def test_weight_bars_appear_only_when_the_name_column_survives(self) -> None:
        self.assertTrue(claude_team_tree.show_weight_bars(48))
        self.assertFalse(claude_team_tree.show_weight_bars(40))
        self.assertGreaterEqual(
            claude_team_tree.historial_name_width(48, bars=True), claude_team_tree.NAME_W
        )

    def test_the_heaviest_subagent_gets_a_full_bar(self) -> None:
        with fake_panel(history=self.HISTORY):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 48)
        rows = rows_of(frame)
        heaviest = next(r for r in rows if "review-risk" in r)
        lightest = next(r for r in rows if "Explore" in r)
        self.assertEqual(heaviest.count("▰"), claude_team_tree.BAR_W)
        self.assertLess(lightest.count("▰"), heaviest.count("▰"))

    def test_no_row_exceeds_the_panel_width_with_bars_on(self) -> None:
        with fake_panel(history=self.HISTORY, artifacts=self.ARTIFACTS):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 48)
        for row in rows_of(frame):
            self.assertLessEqual(len(row), 48, repr(row))

    # ---- P3: live subagent activity ----------------------------------------
    def test_a_live_subagent_reports_how_long_it_has_been_running(self) -> None:
        children = [{"id": "agent-abc123", "name": "Explore",
                     "agent_status": "working", "started": 1000.0}]
        with fake_panel(children=children):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60, now=1074.0)
        rows = rows_of(frame)
        self.assertTrue(any("Explore" in r for r in rows))
        self.assertTrue(any("1:14" in r for r in rows), rows)

    def test_a_finished_or_untimed_subagent_gets_no_activity_line(self) -> None:
        children = [{"id": "agent-abc123", "name": "Explore", "agent_status": "working"}]
        with fake_panel(children=children):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60, now=1074.0)
        # no `started` recorded: say nothing rather than invent an elapsed time
        self.assertEqual(sum("Explore" in r for r in rows_of(frame)), 1)

    # ---- P4: problem band ---------------------------------------------------
    def test_a_blocked_subagent_raises_a_band_under_the_header(self) -> None:
        children = [
            {"id": "a1", "name": "Explore", "agent_status": "working"},
            {"id": "a2", "name": "general-purpose", "agent_status": "blocked"},
        ]
        with fake_panel(children=children):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60)
        rows = rows_of(frame)
        self.assertIn("blocked", rows[1])
        self.assertIn("general-purpose", rows[1])

    def test_no_band_when_nothing_is_blocked(self) -> None:
        children = [{"id": "a1", "name": "Explore", "agent_status": "working"}]
        with fake_panel(children=children):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60)
        self.assertFalse(any("blocked" in r for r in rows_of(frame)))

    def test_the_band_counts_interrupted_subagents_of_an_ended_session(self) -> None:
        children = [
            {"id": "a1", "name": "Explore", "agent_status": "working"},
            {"id": "a2", "name": "review-risk", "agent_status": "working"},
        ]
        with fake_panel(children=children, ended=2000.0):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60)
        self.assertIn("2 interrupted", rows_of(frame)[1])

    def test_mouse_button_ignores_modifier_bits(self) -> None:
        # SGR encodes shift/alt/ctrl in the high bits of the button field; a
        # ctrl-right-click (2 + 16) is still the right button.
        self.assertEqual(claude_team_tree.mouse_button(0), 0)
        self.assertEqual(claude_team_tree.mouse_button(2), 2)
        self.assertEqual(claude_team_tree.mouse_button(18), 2)

    def test_clip_for_menu_keeps_the_frame_inside_the_viewport(self) -> None:
        lines = [f"row{index}" for index in range(30)]
        clipped = claude_team_tree.clip_for_menu(lines, footer_len=3, height=20, protect=6)
        self.assertEqual(len(clipped), 20)
        # the pinned footer survives, and the cut is announced rather than silent
        self.assertEqual(clipped[-3:], lines[-3:])
        self.assertIn("hidden rows", plain(clipped[-4]))

    def test_clip_for_menu_leaves_a_fitting_frame_untouched(self) -> None:
        lines = [f"row{index}" for index in range(10)]
        self.assertEqual(
            claude_team_tree.clip_for_menu(lines, footer_len=3, height=24, protect=6), lines
        )

    def test_clip_for_menu_never_cuts_into_the_menu_itself(self) -> None:
        lines = [f"row{index}" for index in range(30)]
        clipped = claude_team_tree.clip_for_menu(lines, footer_len=3, height=8, protect=6)
        self.assertEqual(clipped[:6], lines[:6])

    def test_cycle_value_steps_backwards_and_wraps(self) -> None:
        self.assertEqual(dashboard_config.cycle_value("history_limit", 10, step=-1), 50)
        self.assertEqual(dashboard_config.cycle_value("history_limit", 10), 20)

    def test_session_ended_at_reads_the_recorded_end_timestamp(self) -> None:
        with isolated_state() as state_home:
            path = state_home / "herdr" / "claude-vezmex-team-tree" / "profiles.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"sessions": {
                "live": {"started": 100.0},
                "gone": {"started": 100.0, "ended": 160.0},
            }}), encoding="utf-8")
            self.assertIsNone(claude_team_tree.session_ended_at("live"))
            self.assertIsNone(claude_team_tree.session_ended_at("missing"))
            self.assertEqual(claude_team_tree.session_ended_at("gone"), 160.0)

    def test_a_pi_session_marked_ended_in_the_canonical_snapshot_freezes_the_clock(self) -> None:
        # Pi has no profiles.json hook — its only proof of session end is the
        # canonical snapshot its companion extension writes.
        with isolated_state():
            store.update_session(model.Session(
                "pi", "raw-pi-1", presence="ended", status="ended", observed_at=200.0,
            ))
            self.assertEqual(claude_team_tree.session_ended_at("raw-pi-1", "pi"), 200.0)

    def test_profiles_json_ended_wins_over_a_present_canonical_record(self) -> None:
        with isolated_state() as state_home:
            path = state_home / "herdr" / "claude-vezmex-team-tree" / "profiles.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"sessions": {"raw-2": {"started": 10.0, "ended": 99.0}}}), encoding="utf-8")
            store.update_session(model.Session("pi", "raw-2", presence="present", status="working", observed_at=500.0))
            self.assertEqual(claude_team_tree.session_ended_at("raw-2", "pi"), 99.0)

    def test_a_present_canonical_session_does_not_freeze(self) -> None:
        with isolated_state():
            store.update_session(model.Session("pi", "raw-3", presence="present", status="working", observed_at=10.0))
            self.assertIsNone(claude_team_tree.session_ended_at("raw-3", "pi"))

    def test_ending_one_runtimes_session_does_not_freeze_the_same_raw_id_under_another(self) -> None:
        # Raw session ids can collide across runtimes, so the fallback must be
        # keyed by (runtime, raw id), not raw id alone.
        with isolated_state():
            store.update_session(model.Session("pi", "same-raw", presence="ended", status="ended", observed_at=42.0))
            store.update_session(model.Session("claude", "same-raw", presence="present", status="working", observed_at=10.0))
            self.assertIsNone(claude_team_tree.session_ended_at("same-raw", "claude"))
            self.assertEqual(claude_team_tree.session_ended_at("same-raw", "pi"), 42.0)

    def test_a_malformed_canonical_snapshot_reads_as_not_ended(self) -> None:
        with isolated_state() as state_home:
            snap_path = state_home / "herdr" / "claude-vezmex-team-tree" / "runtime-observability.json"
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            snap_path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(claude_team_tree.session_ended_at("whatever", "pi"))

    def test_an_ended_canonical_record_with_no_usable_timestamp_returns_none(self) -> None:
        with isolated_state():
            store.update_session(model.Session("pi", "raw-4", presence="ended", status="ended", observed_at=None))
            self.assertIsNone(claude_team_tree.session_ended_at("raw-4", "pi"))

    def test_session_duration_freezes_once_the_session_ended(self) -> None:
        # A live session counts up to now; a finished one must stop at the
        # moment it ended, not keep ticking as if the agent were still there.
        self.assertEqual(
            claude_team_tree.session_duration(started=100.0, ended=None, now=175.0), 75.0
        )
        self.assertEqual(
            claude_team_tree.session_duration(started=100.0, ended=160.0, now=999.0), 60.0
        )
        self.assertIsNone(
            claude_team_tree.session_duration(started=None, ended=160.0, now=999.0)
        )

    # ---- P5: the gear reads as a button, not a grey glyph -----------------
    def test_header_hint_renders_the_gear_as_a_chip(self) -> None:
        text, visible = claude_team_tree.header_hint(False, subtitle_width=20, width=48)
        self.assertIn("⚙", text)
        self.assertIn("settings", text)
        self.assertIn(claude_team_tree.BG_ROW, text)  # inverted, so it reads as a control
        self.assertEqual(visible, len(plain(text)))

    def test_header_hint_reports_a_visible_width_that_excludes_escapes(self) -> None:
        for ended in (False, True):
            for width in (30, 48, 90):
                text, visible = claude_team_tree.header_hint(ended, 20, width)
                self.assertEqual(visible, len(plain(text)), (ended, width))
                self.assertLessEqual(20 + 1 + visible, max(width, 20 + 1 + visible))

    def test_header_hint_drops_the_close_shortcut_before_the_gear(self) -> None:
        narrow_width = 20 + 1 + len(plain(claude_team_tree.header_hint(True, 20, 200)[0]))
        text, visible = claude_team_tree.header_hint(True, 20, narrow_width - 2)
        self.assertIn("⚙", text)            # the affordance is never what goes
        self.assertIn("ended", text)
        self.assertNotIn("^C", text)
        self.assertLessEqual(20 + 1 + visible, narrow_width - 2)

    def test_stale_status_marks_a_still_working_agent_as_interrupted(self) -> None:
        # Nothing writes SubagentStop when the agent CLI is killed, so a
        # subagent frozen at "working" would otherwise keep on spinning.
        self.assertEqual(claude_team_tree.stale_status("working", session_ended=True), "interrupted")
        self.assertEqual(claude_team_tree.stale_status("working", session_ended=False), "working")
        self.assertEqual(claude_team_tree.stale_status("done", session_ended=True), "done")

    def test_ended_and_interrupted_statuses_have_a_colour_and_a_static_glyph(self) -> None:
        for status in ("ended", "interrupted"):
            self.assertIn(status, claude_team_tree.COLORS)
            self.assertIn(status, claude_team_tree.STATIC)
            # never animated: a dead session must not look busy
            self.assertEqual(
                claude_team_tree.glyph(status, 0), claude_team_tree.glyph(status, 3)
            )

    def test_cycle_position_reports_place_and_length(self) -> None:
        self.assertEqual(dashboard_config.cycle_position("detail_level", "compact"), (2, 3))
        self.assertEqual(dashboard_config.cycle_position("history_limit", 999), (0, 4))


if __name__ == "__main__":
    unittest.main()


class TokenColumnWidthTests(unittest.TestCase):
    """A history row must never be wider than the pane it is drawn into.

    Found from the generated README preview: a real session showed
    `15044.3k` in a six-wide column, so every row overflowed by two and the
    trailing weight gauge was clipped away. Multi-million-token sessions are
    ordinary now, not an edge case.
    """

    def test_token_label_never_exceeds_its_column(self) -> None:
        counts = [
            0, 1, 999, 1000, 1500, 99_000, 999_000, 999_949,
            1_000_000, 1_500_000, 9_648_100, 15_044_300,
            999_000_000, 1_500_000_000, 9_999_999_999,
            10**12, 10**15, 10**20,  # corrupted records must not overflow either
        ]
        for count in counts:
            with self.subTest(count=count):
                label = claude_team_tree.format_tokens(count)
                self.assertLessEqual(
                    len(label), claude_team_tree.TOK_W,
                    f"{count} formatted as {label!r} ({len(label)} > "
                    f"{claude_team_tree.TOK_W} columns)",
                )

    def test_a_history_row_fits_the_pane_width(self) -> None:
        record = {
            "name": "general-purpose",
            "stopped": 1789000000,
            "duration_s": 624,
            "tokens": 15_044_300,
        }
        for width in (46, 58, 66, 80, 120):
            with self.subTest(width=width):
                row = claude_team_tree.historial_data_row(
                    record, False, width, max_tokens=15_044_300
                )
                plain = ANSI_RE.sub("", row)
                self.assertLessEqual(
                    len(plain), width,
                    f"row is {len(plain)} chars in a {width}-column pane: {plain!r}",
                )

    def test_the_weight_gauge_survives_at_every_width_that_shows_it(self) -> None:
        record = {"name": "worker", "stopped": 1789000000,
                  "duration_s": 60, "tokens": 15_044_300}
        for width in (58, 66, 80, 120):
            with self.subTest(width=width):
                if not claude_team_tree.show_weight_bars(width):
                    continue
                plain = ANSI_RE.sub("", claude_team_tree.historial_data_row(
                    record, False, width, max_tokens=15_044_300))
                self.assertNotIn("…", plain, "the row was clipped")
                gauge = plain.rstrip()[-claude_team_tree.BAR_W:]
                self.assertEqual(len(gauge), claude_team_tree.BAR_W)
                self.assertTrue(set(gauge) <= {"▰", "▱"}, f"gauge mangled: {gauge!r}")


class RuntimeThreadingEndToEndTests(unittest.TestCase):
    """Prove the runtime actually reaches the canonical lookup from a pane.

    Every other render test stubs `session_ended_at`, so the value the panel
    threads into it — `agent.get("agent")` off the Herdr leader record — was
    never exercised against the real function. A label the canonical id
    builder rejects is swallowed by its `except ValueError` guard and reads
    as "not ended", so the Pi freeze could fail silently with every test green.
    """

    PI = {"focused_workspace_id": "w1", "panes": [], "agents": [{
        "agent": "pi", "workspace_id": "w1", "pane_id": "p1", "focused": True,
        "agent_status": "working", "agent_session": {"value": "pi-sess"},
        "terminal_title_stripped": "Proyecto"}]}

    @contextlib.contextmanager
    def _ended(self, runtime, raw, at):
        with tempfile.TemporaryDirectory() as home:
            old = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = home
            try:
                store.update_session(model.Session(
                    runtime, raw, presence="ended", status="ended", observed_at=at))
                yield
            finally:
                os.environ.pop("XDG_STATE_HOME", None) if old is None else \
                    os.environ.__setitem__("XDG_STATE_HOME", old)

    def test_a_pi_pane_freezes_from_canonical_state_through_render(self):
        saved = {n: getattr(claude_team_tree, n) for n in (
            "hook_children", "session_history", "session_artifacts",
            "session_started_at", "load_config")}
        claude_team_tree.hook_children = lambda sid: []
        claude_team_tree.session_history = lambda sids, limit: ([], 0)
        claude_team_tree.session_artifacts = lambda sids, limit: []
        claude_team_tree.session_started_at = lambda sid: 1000.0
        claude_team_tree.load_config = lambda: dict(dashboard_config.DEFAULTS)
        try:
            # session_ended_at is deliberately NOT stubbed: it is under test.
            with self._ended("pi", "pi-sess", 1600.0):
                rows = rows_of(claude_team_tree.render_frame(self.PI, 0, 80, 24, now=5000.0))
        finally:
            for n, v in saved.items():
                setattr(claude_team_tree, n, v)
        # 1000 -> 1600 is ten minutes; a clock still running would read 1:06:40.
        self.assertIn("10:00", rows[0], f"clock did not freeze: {rows[0]!r}")
        self.assertIn("ended", " ".join(rows))

    def test_every_herdr_runtime_label_resolves(self):
        """The ValueError guard must never be why a real runtime fails to freeze."""
        for runtime in sorted(model.ALLOWED_RUNTIMES):
            with self.subTest(runtime=runtime), self._ended(runtime, "s", 1600.0):
                self.assertEqual(claude_team_tree.session_ended_at("s", runtime), 1600.0)


class HistorialBreakpointTests(unittest.TestCase):
    """A narrow pane must drop whole columns, never truncate a value.

    The pane this was found in is 33 columns. The historial row was a fixed
    38 — indent 4 + a 15-column name minimum + 19 columns of fixed fields —
    so it was clipped, and the token cost, the most valuable thing in the
    history, was the first casualty. Below 38 the layout simply had no
    definition.
    """

    REC = {"name": "general-purpose", "stopped": 1789000000,
           "duration_s": 624, "tokens": 9648100}

    def _plain(self, width, max_tokens=9648100):
        return ANSI_RE.sub("", claude_team_tree.historial_data_row(
            self.REC, False, width, max_tokens=max_tokens))

    def test_no_value_column_is_ever_clipped(self) -> None:
        """A name may still ellipsize — names are arbitrarily long. A value
        column may not: half a token count is worse than none at all."""
        for width in range(claude_team_tree.MIN_HISTORIAL_WIDTH, 121):
            for highlighted in (False, True):
                with self.subTest(width=width, highlighted=highlighted):
                    row = ANSI_RE.sub("", claude_team_tree.historial_data_row(
                        self.REC, highlighted, width, max_tokens=9648100))
                    self.assertLessEqual(len(row), width)
                    columns = claude_team_tree.historial_columns(width)
                    if "tokens" in columns:
                        self.assertIn("9.6M", row, f"token value lost at {width}: {row!r}")
                    if "dur" in columns:
                        self.assertIn("10:24", row, f"duration lost at {width}: {row!r}")

    def test_columns_drop_in_a_defined_order_as_the_pane_narrows(self) -> None:
        """Tokens outlive duration, which outlives the clock."""
        for width, expect in (
            (60, ("hora", "dur", "tokens", "peso")),
            (40, ("hora", "dur", "tokens")),
            (34, ("dur", "tokens")),
            (28, ("tokens",)),
        ):
            with self.subTest(width=width):
                cols = claude_team_tree.historial_columns(width)
                self.assertEqual(tuple(cols), expect)

    def test_the_header_carries_exactly_its_rows_columns(self) -> None:
        """A header that keeps a column its rows dropped reads as misaligned.

        Forced to Spanish here (rather than the new English default) so this
        keeps testing what it always tested — the width/column-set behaviour
        — decoupled from which language happens to be the panel's default.
        """
        for width in range(claude_team_tree.MIN_HISTORIAL_WIDTH, 121):
            with self.subTest(width=width):
                cols = claude_team_tree.historial_columns(width)
                header = ANSI_RE.sub(
                    "", claude_team_tree.historial_header(width, bars="peso" in cols, language="es")
                )
                self.assertLessEqual(len(header), width)
                for label, present in (("hora", "hora" in cols), ("dur.", "dur" in cols),
                                       ("tokens", "tokens" in cols)):
                    self.assertEqual(label in header, present, f"{label} at {width}: {header!r}")

    def test_the_narrowest_pane_still_names_the_subagent(self) -> None:
        row = self._plain(claude_team_tree.MIN_HISTORIAL_WIDTH)
        # Enough of the name to tell two subagents apart, plus the cost.
        self.assertIn("gener", row)
        self.assertIn("9.6M", row)


class ModelEffortBadgeTests(unittest.TestCase):
    """A compact, symbolic model+effort badge for the historial detail line.

    Provider is deliberately absent from the badge: today only Claude Code's
    transcript exposes model/effort at all (Codex's own is unverified, per
    its adapter's conservative capability declaration), so every badge in one
    dashboard view already shares one runtime - a provider glyph there would
    repeat the same thing on every row.
    """

    def test_model_badge_abbreviates_known_families(self) -> None:
        cases = [
            ("claude-opus-5", "O5"),
            ("claude-opus-5[1m]", "O5"),
            ("claude-sonnet-5", "S5"),
            ("claude-haiku-4-5-20251001", "H4.5"),
            ("claude-fable-5-1", "F5.1"),
        ]
        for model, expected in cases:
            with self.subTest(model=model):
                self.assertEqual(claude_team_tree.model_badge(model), expected)

    def test_model_badge_is_empty_for_none_or_unrecognized(self) -> None:
        for model in (None, "", "<synthetic>", "gpt-5-codex", "some-other-thing"):
            with self.subTest(model=model):
                self.assertEqual(claude_team_tree.model_badge(model), "")

    def test_effort_bar_ranks_every_known_level_in_the_weight_gauge_alphabet(self) -> None:
        # low..ultra, one more filled cell per level - real transcripts have
        # shown "high", "medium", and "xhigh" so far; low/max/ultra are taken
        # on the maintainer's word since nothing observed yet contradicts them.
        cases = [
            ("low",    "▰▱▱▱▱▱"),
            ("medium", "▰▰▱▱▱▱"),
            ("high",   "▰▰▰▱▱▱"),
            ("xhigh",  "▰▰▰▰▱▱"),
            ("max",    "▰▰▰▰▰▱"),
            ("ultra",  "▰▰▰▰▰▰"),
        ]
        for effort, expected in cases:
            with self.subTest(effort=effort):
                self.assertEqual(claude_team_tree.effort_bar(effort), expected)

    def test_effort_bar_is_empty_for_none_or_unrecognized(self) -> None:
        for effort in (None, "", "extreme", "default"):
            with self.subTest(effort=effort):
                self.assertEqual(claude_team_tree.effort_bar(effort), "")

    def test_the_detail_line_carries_the_badge_when_present(self) -> None:
        record = {"model": "claude-sonnet-5", "effort": "high",
                  "task": "Audita el plugin", "tools": {}, "tool_uses": 0}
        lines = claude_team_tree.historial_detail_lines(record, False, 80, detail_level="compact")
        self.assertTrue(lines)
        plain = ANSI_RE.sub("", lines[0])
        self.assertIn("S5", plain)
        self.assertIn("▰▰▰", plain)

    def test_the_detail_line_omits_the_badge_when_model_is_unknown(self) -> None:
        record = {"model": None, "effort": None, "task": "Audita el plugin", "tools": {}, "tool_uses": 0}
        lines = claude_team_tree.historial_detail_lines(record, False, 80, detail_level="compact")
        plain = ANSI_RE.sub("", lines[0]) if lines else ""
        self.assertNotIn("S5", plain)
        self.assertNotIn("▰", plain)


class LocalizationTests(unittest.TestCase):
    """The panel's own authored copy is bilingual (English default, Spanish
    available) via `t()` and the "language" gear-menu option — never the
    agent/task/tool/transcript data the panel merely displays.
    """

    EMPTY_SNAPSHOT = {"focused_workspace_id": "w1", "panes": [], "agents": []}

    def test_t_falls_back_to_english_for_an_unrecognized_language(self) -> None:
        self.assertEqual(
            claude_team_tree.t("idle_no_agent", "fr"),
            claude_team_tree.t("idle_no_agent", "en"),
        )
        self.assertEqual(claude_team_tree.t("idle_no_agent", "fr"), "no agent in this pane")

    def test_t_returns_the_key_itself_for_a_key_missing_from_both_languages(self) -> None:
        self.assertEqual(claude_team_tree.t("this_key_does_not_exist"), "this_key_does_not_exist")
        self.assertEqual(claude_team_tree.t("this_key_does_not_exist", "es"), "this_key_does_not_exist")

    def test_the_language_menu_option_cycles_persists_and_the_next_frame_reflects_it(self) -> None:
        targets = {2: claude_team_tree.option_target("language")}
        with isolated_state():
            frame = claude_team_tree.render_frame(self.EMPTY_SNAPSHOT, 0, 48, 24)
            self.assertIn("no agent", plain(frame.text))

            claude_team_tree.handle_click(3, targets, menu_open=True)
            self.assertEqual(dashboard_config.load_config()["language"], "es")
            frame = claude_team_tree.render_frame(self.EMPTY_SNAPSHOT, 0, 48, 24)
            self.assertIn("sin agente", plain(frame.text))

            claude_team_tree.handle_click(3, targets, menu_open=True)
            self.assertEqual(dashboard_config.load_config()["language"], "en")
            frame = claude_team_tree.render_frame(self.EMPTY_SNAPSHOT, 0, 48, 24)
            self.assertIn("no agent", plain(frame.text))

    def test_the_no_snapshot_message_is_translated_too(self) -> None:
        """Found after the writer's own inventory: this line renders before
        `render_frame` ever loads config in the original code, so adding it
        required moving the config read earlier - a real gap the delegated
        brief's inventory missed, not something to leave unfixed."""
        with isolated_state():
            frame = claude_team_tree.render_frame(None, 0, 48, 24)
            self.assertIn("connection unavailable", plain(frame.text))

            path = dashboard_config.config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"language": "es"}), encoding="utf-8")
            frame = claude_team_tree.render_frame(None, 0, 48, 24)
            self.assertIn("conexión no disponible", plain(frame.text))

    def test_the_generic_agent_fallback_label_is_translated(self) -> None:
        """title_for()/the subtitle both fall back to a bare word when Herdr
        supplies no display_agent/terminal_title/agent name at all - found
        by the same grep sweep that caught connection_unavailable."""
        no_name_leader = {"agent": "", "workspace_id": "w1", "pane_id": "p1",
                           "focused": True, "agent_status": "working", "agent_session": {"value": "s"}}
        with isolated_state():
            self.assertEqual(claude_team_tree.title_for(no_name_leader, "en"), "agent")
            self.assertEqual(claude_team_tree.title_for(no_name_leader, "es"), "agente")

    def test_a_malformed_language_value_renders_in_english_without_crashing(self) -> None:
        for bad_value in ("fr", 123, None):
            with self.subTest(bad_value=bad_value), isolated_state() as state_home:
                path = state_home / "herdr" / "claude-vezmex-team-tree" / "config.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"language": bad_value}), encoding="utf-8")
                frame = claude_team_tree.render_frame(self.EMPTY_SNAPSHOT, 0, 48, 24)
                text = plain(frame.text)
                self.assertIn("no agent", text)
                self.assertNotIn("idle_no_agent", text)
