# Agents Tree

A [Herdr](https://herdr.dev) plugin that gives subagent visibility to agent
CLIs, driven entirely by lifecycle hooks — it never reads a terminal.

Two surfaces:

- a compact **sidebar** tree of live subagents, published as Herdr tokens
- an expanded **dashboard** pane: live subagent tree, session history,
  published artifacts, and a footer summary

The agent CLI remains the work surface; this plugin only shows the lifecycle
state its hooks report.

Recognized agents: **Claude Code**, **Codex**, **Pi**. Anything Herdr detects
as something else is left alone rather than guessed at, so an unrelated
session's history and artifacts can never leak into the panel.

## Install

```sh
herdr plugin link /path/to/claude-vezmex-team-tree
python3 install_profile_resume.py    # optional, see "Profile-aware resume"
```

The lifecycle hooks are wired through the agent CLI's own settings — for
Claude Code, `~/.claude/settings.json` (or the profile directory in use);
for Codex, `~/.codex/hooks.json`.

Herdr has no menu or palette for plugin actions, so bind the ones you want in
`~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+alt+a"
type = "shell"
command = "herdr plugin action invoke open-dashboard --plugin local.claude-vezmex-team-tree"
```

## How the tree is joined

The dashboard never runs `herdr pane read` (or any other terminal read). Herdr
locates the agent pane and supplies its associated session identifier. The tree
then comes entirely from local hook state:

- `SubagentStart`: `{session_id, agent_id, agent_type}` → working/spinner
- `SubagentStop`: `{session_id, agent_id, agent_type, ...}` → done

Claude documents that these event payloads retain the parent session's
`session_id`; Herdr records that ID as the pane's `agent_session.value`. That
exact match is the join key. The panel labels each child with its agent type
and a short suffix of its event ID, and reports its hook state as
working/spinner or done.

## Session history and artifacts

A finished subagent is removed from the live tree, not kept as "done" — it
moves into a session history log instead (`history.jsonl`), with its name,
start/stop time, duration, and a token total read from its own transcript
(`agent_transcript_path` on `SubagentStop`; hook payloads carry no token count
directly). `claude_team_tree.py` renders this as a HISTORIAL section below the
live tree, capped to the most recent entries.

A second hook, `claude_artifact_hook.py`, wires into `PostToolUse` and logs
every real `Artifact` tool publish/update (`artifacts.jsonl`) — filtered to the
`publish` action only, so read-only calls (`status`, `list`, ...) are never
logged. Rendered as an ARTIFACTS section, with a footer line summing
agents/tokens/artifacts/duration for the session.

Token *session* totals (context occupancy, account quota) are intentionally out
of scope here — installed
[herdr-token-dashboard](https://github.com/Davidcreador/herdr-token-dashboard)
covers that at the session/pane level; this plugin stays focused on per-subagent
history and artifacts.

## Settings: the in-panel gear menu

The dashboard's header row carries a gear. **Clicking it opens a settings menu
inside the panel** — no editor, no separate pane:

```
TestingSTUFFV2   ·   1:13:32          ⚙ ctrl-c para cerrar
  ⚙ AJUSTES  click der: atrás                    ✕ cerrar
  Detalle                                 compact  (2/3)
  Historial                                    30  (3/4)
  Artifacts                                    15  (3/4)
  Ancho panel                                0.28  (2/4)
```

Every row is a click target: left click steps a setting to the next preset,
right click steps back, and `(2/3)` says where the current value sits in its
cycle. The title row closes the menu, as does clicking the gear again.

Clicks arrive as SGR mouse reports (`\033[?1000h\033[?1006h`) with stdin in
cbreak mode — without cbreak the click bytes stay buffered by the tty driver
and never reach `select()`. Hit-testing is by row, so the rendered layout in
`menu_lines()` and the row mapping in `handle_click()` are one contract.

A cycled value is written straight to `config.json`, which `render()` reads
back on the next frame, so settings also apply to a running dashboard when
edited by hand. Only Python changes need a restart.

`dashboard_config.py` run directly (the "Configurar dashboard" action) opens
that same file in `$EDITOR` for the settings the menu does not expose.

### Overflow and scrollback

Closed, the panel prints more history and artifacts than fit, so the pane's own
scrollback reveals older entries. Open, that would scroll the header — and with
it the gear and the menu — off the top, breaking the row-based click mapping. So
while the menu is open the frame is clipped to the viewport: the oldest body rows
are dropped, the pinned footer is kept, and the cut is stated as
`+N filas ocultas` rather than silently swallowed.

Nothing in the panel truncates a value it could wrap instead; the footer wraps
across lines rather than ellipsizing.

## Profile-aware resume

`Install Claude profile resume` installs a reversible `claude` launcher. Each
profile's SessionStart hook records its `session_id` and `CLAUDE_CONFIG_DIR`.
When Herdr later runs `claude --resume <session_id>`, the launcher restores the
matching profile before delegating to the original Claude binary. It supports
the default, work, and Vezmex Claude configuration directories.

To revert, run `python3 install_profile_resume.py --uninstall` from the plugin
directory. The original `~/.local/bin/claude` launcher is restored; recorded
session mappings are retained but ignored.

## Tests

```sh
python3 -m unittest test_hook_dashboard test_herdr_agent_tree test_profile_resume
```

Every test isolates its state through a temporary `XDG_STATE_HOME`, so a run
never touches the real config, history, or launcher.
