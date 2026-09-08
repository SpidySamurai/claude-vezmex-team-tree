# Project Context — testing-stuff

## Repository identity

- Repository root: `/home/javier/testing-stuff`
- Product: Herdr Agents Tree plugin
- Primary language: Python 3
- Manifest: `herdr-plugin.toml`
- Current plugin id: `local.claude-vezmex-team-tree`

This repository is a Herdr plugin that exposes agent/subagent visibility in Herdr. Herdr is the product and UI boundary: plugin manifest entries, sidebar metadata tokens, the dashboard pane, user actions, pane opening, and pane resizing remain Herdr-facing behavior.

## Current product behavior

The plugin has two Herdr surfaces:

1. A compact sidebar tree of live subagents, published as Herdr pane metadata tokens.
2. A dashboard pane that renders the live subagent tree, session history, artifacts, settings menu, and footer summary.

The plugin does not read terminal panes. It joins Herdr-visible leader panes to locally recorded lifecycle state through Herdr agent session identifiers. Recognized leader agents are Claude Code, Codex, and Pi; unrecognized agents intentionally render as no-agent/idle rather than guessing from cwd or borrowing another session's state.

## Runtime collection context

The repository currently has Claude-oriented collector names and Claude profile support:

- `src/claude_subagent_hook.py` persists `SubagentStart`/`SubagentStop` lifecycle state and history.
- `src/claude_artifact_hook.py` persists Claude Artifact `PostToolUse` publishes/updates.
- `src/claude_profile_hook.py` records Claude profile/session lifecycle state and end markers.
- `src/claude_profile_resume.py` and `src/install_profile_resume.py` support reversible Claude profile-aware resume.

The Herdr-facing code is already partially agent-agnostic:

- `src/herdr_agent_tree.py` publishes sidebar token slots for visible Herdr agents and prefers future Herdr-native child fields before hook-derived children.
- `src/claude_team_tree.py` recognizes `claude`, `codex`, and `pi` leader panes and renders an agent-agnostic dashboard while still using Claude-oriented file/module names.
- `install.py` wires the same hook scripts into existing Claude profile settings and Codex hooks when those files exist.

Desired evolution: add runtime-specific collectors for Pi, Codex, and Claude Code while keeping Herdr as the product/UI boundary. Collection details should be isolated behind runtime-specific adapters/collectors instead of pushing runtime logic into Herdr UI surfaces.

## Source map

- `herdr-plugin.toml`: Herdr manifest, startup/events, dashboard pane, actions.
- `install.py`: reversible plugin link and hook wiring for agent settings.
- `Makefile`: install/check/uninstall/test entry points.
- `src/herdr_agent_tree.py`: compact sidebar token publisher and spinner animator.
- `src/claude_team_tree.py`: dashboard renderer, click mapping, settings menu, session/history/artifact presentation.
- `src/dashboard_config.py`: dashboard config defaults, file persistence, menu option cycles, editor action.
- `src/open_dashboard.py`: Herdr plugin pane open action and right-split resizing.
- `src/claude_subagent_hook.py`: subagent lifecycle state and history writer.
- `src/claude_artifact_hook.py`: Artifact publish/update state writer.
- `src/claude_profile_hook.py`: Claude session/profile lifecycle state writer.
- `src/install_profile_resume.py`: reversible profile-aware Claude launcher installer.
- `legacy/`: earlier unwired approach retained as historical context.

## State and data files

Runtime state is stored under `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree` by default. Important files include:

- `subagents.json`: live session-keyed subagent map.
- `history.jsonl`: completed subagent history, capped by hook logic.
- `artifacts.jsonl`: Artifact publish/update records, capped by hook logic.
- `profiles.json`: Claude profile/session mapping and ended markers.
- `config.json`: dashboard settings loaded on each render/read.

Concurrent hook writers use lock files and atomic replacement patterns where partial writes would be unsafe.

## Testing and commands

Canonical commands:

```sh
make install
make check
make uninstall
make test
```

`make test` currently runs:

```sh
env -u HERDR_WORKSPACE_ID python3 -m unittest discover -s tests -t tests
```

Observed initialization evidence: `make test` passed with 81 tests. Tests isolate state with temporary `XDG_STATE_HOME`; the Makefile deliberately unsets `HERDR_WORKSPACE_ID` to prevent real Herdr pane context from leaking into dashboard/render tests.

## Existing safeguards and conventions

- Do not read terminal pane contents for product behavior.
- Use Herdr snapshot/session metadata plus hook-recorded state as the source of truth.
- Leave unrecognized agents alone; do not infer sessions from cwd.
- Keep installer behavior idempotent and reversible.
- Back up user settings once before the first installer edit.
- Do not remove foreign hooks when uninstalling.
- Preserve existing behavior with strict TDD for product changes.

## SDD initialization settings

- Artifact store: OpenSpec (`openspec/`)
- Strict TDD: enabled for implementation work
- Execution mode: auto
- Delivery strategy: ask-on-risk
- Review budget: 400 changed lines
- Initialization scope: context/config artifacts only; no product implementation changes.
