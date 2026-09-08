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
    claude_team_tree.session_ended_at = lambda sid: ended
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
        self.assertIn("⚙ ajustes", rendered)  # the header carries the gear chip
        self.assertNotIn("├─", rendered)
        self.assertNotIn("└─", rendered)
        self.assertIn("HISTORIAL", rendered)
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
        self.assertIn("⚙ ajustes", rendered)  # the header carries the gear chip
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
        self.assertIn("+2 más", rendered)

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

        self.assertIn("sin agente", rendered)
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

        self.assertIn("sin agente", rendered)
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
        self.assertIn("delegó a 1", lines[0])
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
        self.assertIn("Tarea:", lines[0])
        self.assertIn("Investiga el bug de tokens", lines[0])
        self.assertIn("Bash×1", lines[1])
        self.assertIn("listo", lines[1])

    def test_menu_lines_open_with_a_title_row_then_one_row_per_option(self) -> None:
        config = dict(dashboard_config.DEFAULTS)
        lines = claude_team_tree.menu_lines(config, 80)
        self.assertEqual(len(lines), 1 + len(dashboard_config.MENU_OPTIONS))
        # The title row frames the block and carries the close affordance, so
        # the menu never looks like content that leaked into the panel.
        self.assertIn("AJUSTES", plain(lines[0]))
        self.assertIn("cerrar", plain(lines[0]))
        self.assertIn("Detalle", plain(lines[1]))
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
        history_row = next(i for i, r in enumerate(rows) if "HISTORIAL" in r)
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
        history_row = next(i for i, r in enumerate(rows) if "HISTORIAL" in r)
        self.assertIn("▸", rows[history_row])                       # collapsed
        self.assertEqual(frame.targets.get(history_row), claude_team_tree.TARGET_SECTION_HISTORY)
        self.assertFalse(any("Explore" in r for r in rows))
        self.assertTrue(any("ARTIFACTS" in r for r in rows))        # the other one stays
        # the footer still counts what the collapsed section holds
        self.assertTrue(any("AG 2" in r for r in rows))

    # ---- P2: proportional weight bars --------------------------------------
    # ---- the idle screen: no agent means no panel ---------------------------
    def test_idle_art_picks_the_widest_variant_that_fits(self) -> None:
        wide = claude_team_tree.idle_art(60)
        narrow = claude_team_tree.idle_art(30)
        self.assertEqual(wide, claude_team_tree.MANDALA)
        self.assertEqual(narrow, claude_team_tree.MANDALA_COMPACT)
        self.assertEqual(claude_team_tree.idle_art(12), [])  # nothing fits: draw none

    def test_mandala_is_symmetric_on_both_axes_and_plain_ascii(self) -> None:
        # A 12-petal rose curve (r = cos(6*theta)), filled and shaded by
        # distance from the boundary — generated from the formula, not drawn
        # by hand, so both mirror axes hold exactly, not approximately.
        for art in (claude_team_tree.MANDALA, claude_team_tree.MANDALA_COMPACT):
            width = max(len(line) for line in art)
            padded = [line.ljust(width) for line in art]
            for line in padded:
                self.assertEqual(line[::-1], line, f"not left-right symmetric: {line!r}")
            self.assertEqual(padded[::-1], padded, "not top-bottom symmetric")
            self.assertTrue(all(c.isascii() for line in art for c in line))

    def test_the_idle_screen_centres_the_art_in_both_directions(self) -> None:
        text = claude_team_tree.idle_screen(60, 30)
        rows = text.split("\n")
        self.assertEqual(len(rows), 30)
        art_rows = [i for i, r in enumerate(rows) if "@" in plain(r)]
        self.assertTrue(art_rows)
        # vertically centred: comparable blank space above and below the block
        filled = [i for i, r in enumerate(rows) if plain(r).strip()]
        above, below = filled[0], len(rows) - 1 - filled[-1]
        self.assertLessEqual(abs(above - below), 2)
        # horizontally centred: the art block's own left margin is balanced
        widest = max((plain(r) for r in rows), key=len)
        left = len(widest) - len(widest.lstrip())
        self.assertLessEqual(abs(left - (60 - len(widest.strip()) - left)), 2)

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
        self.assertIn("sin agente", plain(text))
        # nothing from any other session may reach a pane with no agent
        for leaked in ("HISTORIAL", "ARTIFACTS", "Explore", "review-risk", "ajustes"):
            self.assertNotIn(leaked, plain(text))

    def test_an_unrecognized_agent_also_gets_the_idle_screen(self) -> None:
        other = {"focused_workspace_id": "w1", "panes": [], "agents": [
            {"agent": "somethingelse", "workspace_id": "w1", "pane_id": "p9"}]}
        with fake_panel():
            frame = claude_team_tree.render_frame(other, 0, 48, 24)
        self.assertIn("sin agente", plain(frame.text))

    def test_a_recognized_agent_with_nothing_recorded_shows_just_the_live_tree(self) -> None:
        # A real leader with no subagents yet is true, not broken: the tree
        # itself is live data, so no history/artifacts section — and no
        # placeholder copy inventing something to say — is the right panel.
        with fake_panel():  # no children, no history, no artifacts
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 48, 24)
        rows = rows_of(frame)
        self.assertTrue(any("Proyecto" in r for r in rows))
        self.assertFalse(any("HISTORIAL" in r for r in rows))
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
        self.assertIn("bloqueado", rows[1])
        self.assertIn("general-purpose", rows[1])

    def test_no_band_when_nothing_is_blocked(self) -> None:
        children = [{"id": "a1", "name": "Explore", "agent_status": "working"}]
        with fake_panel(children=children):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60)
        self.assertFalse(any("bloqueado" in r for r in rows_of(frame)))

    def test_the_band_counts_interrupted_subagents_of_an_ended_session(self) -> None:
        children = [
            {"id": "a1", "name": "Explore", "agent_status": "working"},
            {"id": "a2", "name": "review-risk", "agent_status": "working"},
        ]
        with fake_panel(children=children, ended=2000.0):
            frame = claude_team_tree.render_frame(SNAPSHOT, 0, 60)
        self.assertIn("2 interrumpidos", rows_of(frame)[1])

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
        self.assertIn("filas ocultas", plain(clipped[-4]))

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
        self.assertIn("ajustes", text)
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
        self.assertIn("finalizada", text)
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
