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

## Layout

```
herdr-plugin.toml   the manifest — its location is what Herdr calls the plugin root
install.py          links the plugin and wires the agent hooks (reversible)
Makefile            install / check / uninstall / test
src/                every module: panel, sidebar, config, hooks
tests/              the suite
legacy/             an earlier, unwired approach — see legacy/README.md
```

The manifest's commands are relative to the plugin root (`src/...`); the hook
commands in each agent's settings file are absolute. That asymmetry is why
moving the checkout breaks the install, and why re-running the installer is
the fix.

## Install

```sh
git clone https://github.com/SpidySamurai/claude-vezmex-team-tree
cd claude-vezmex-team-tree
make install
```

That does the two things Herdr cannot do for itself:

1. `herdr plugin link` — Herdr resolves every command in the manifest against
   the plugin root, so it has to know where the checkout is.
2. Wires this plugin's hook scripts into each agent settings file it finds
   (`~/.claude/settings.json`, `~/.claude-work`, `~/.claude-vezmex`, and
   `~/.codex/hooks.json`) — the panel never reads a terminal, so lifecycle
   hooks are its only source of truth:

   | event | script | what it feeds |
   |---|---|---|
   | `SessionStart` | `claude_profile_hook.py` | the session, its profile and start time |
   | `SessionEnd` | `claude_profile_hook.py` | the end marker (see "When the session ends") |
   | `SubagentStart` | `claude_subagent_hook.py` | the live tree |
   | `SubagentStop` | `claude_subagent_hook.py` | the historial |
   | `PostToolUse` | `claude_artifact_hook.py` | published artifacts |

A profile directory with no `settings.json` is one you do not use, so it is
skipped rather than created. Each file is backed up once as
`<name>.agents-tree.bak` before its first edit.

```sh
make check       # what is wired right now, changes nothing
make uninstall   # removes only what the installer wrote
make test
```

The installer is idempotent and never touches a hook it did not add, so
running it again after moving the checkout is the whole repair. **A running
agent session keeps the hook paths it started with** — restart it for new
wiring to take effect.

Herdr has no menu or palette for plugin actions, so bind the ones you want in
`~/.config/herdr/config.toml` yourself (`make install` prints this):

```toml
[[keys.command]]
key = "prefix+alt+a"
type = "shell"
command = "herdr plugin action invoke open-dashboard --plugin local.claude-vezmex-team-tree"
```

Optionally, `python3 src/install_profile_resume.py` adds the reversible
`claude` launcher described under "Profile-aware resume".

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

## When the session ends

Leave the agent CLI while the panel is open and everything in it becomes a
post-mortem, so the panel says so instead of presenting stale data as live.
The `SessionEnd` hook records an `ended` timestamp, and from then on:

- the session clock **freezes** at the moment it ended, rather than counting
  up forever against a session that is gone
- the root goes `ended` (`○`, grey) — no more spinner
- any subagent still marked `working` becomes `interrupted` (`▪`): nothing
  wrote its `SubagentStop`, because the CLI was killed out from under it
- the header trades its close hint for `⚙ finalizada` when the pane is too
  narrow for both — the gear is never what gets dropped, since it is the only
  way to open the settings menu

History and artifacts stay on screen and the gear menu keeps working, so the
panel is still readable (and its artifact links still clickable) after the
session it describes is over. Resuming that same session clears the mark and
the panel goes live again.

This depends on a session-end hook, which today means **Claude Code only**.
For Codex and Pi the panel cannot yet tell a finished session from an idle
one, and keeps counting.

## When there is no agent

A pane whose workspace has no recognized leader gets a deliberate idle
screen — an ASCII brain, centred — instead of an empty panel with broken
sections, or another pane's history and artifacts.

There used to be a fallback here: when Herdr detected no agent at all, the
panel dug up a past Claude session from `profiles.json` that had run in the
same working directory. That seemed reasonable until it was actually tested —
cwd is shared by every past session in a project, so what it produced in an
agent-less pane was some unrelated session's history and artifacts, presented
as if they belonged here. Recorded state that merely shares a cwd is not
evidence anything is running; the fallback is gone.

`idle_screen()` picks the widest of two brain drawings that fits the pane
(plain ASCII — box-drawing and emoji presentation vary by font, and tofu is
exactly the broken state this replaces), or neither below ~26 columns, and
centres the block both ways.

## Reading the panel

Beyond the tree, history and artifacts, the panel earns its width in a few
specific ways:

- **Sections fold.** `HISTORIAL DE SESIÓN` and `ARTIFACTS` each carry a marker
  (`▾` open, `▸` folded) and their count, and the header row is a click
  target. Folding the history brings the artifacts into view without touching
  the pane's scroll. The fold is persisted, so it survives a reopen.
- **A weight gauge** trails each history row when the pane is wide enough for
  it without starving the name column: eight cells, normalised to the
  heaviest subagent of the session. It turns the token column into a profile
  you can read without comparing digits — it says *which* delegation was
  expensive, not how much it cost in absolute terms.
- **A live subagent says how long it has been running**, on its own dim line
  under its tree row. That is the only live per-subagent fact the hooks
  record; a subagent with no recorded start time gets no line rather than an
  invented elapsed time. A live tool tally would need `PostToolUse` to
  attribute each call to the running subagent, which it does not do today.
- **A problem band** appears directly under the header, and only when
  something is blocked or interrupted, naming what is stuck. A blocked
  subagent was otherwise one coloured dot among coloured dots.
- **The gear is a chip**, not a glyph — inverted, using the same background
  the history already stripes with, because a grey `⚙` at the end of a grey
  line does not read as something you can click.

### Clicks resolve against the drawn frame

`render_frame()` returns the text *and* a map of which row carries which
click target; `handle_click()` resolves a click through that map. Nothing
depends on a row number fixed in advance, which is what lets a section fold,
the problem band appear, or the menu open without a click ever landing on the
wrong control.

### One column of margin

The panel draws one column short of the width the terminal reports
(`usable_columns()`). Measured in a real pane, a row built at exactly the
reported width loses its last character on screen — the close shortcut
renders `^` instead of `^C`, an eight-cell gauge shows seven. A wrap test in
a plain pane rules out double-width glyphs as the cause, so this leaves the
last column unused rather than pretending to explain the terminal.

## Settings: the in-panel gear menu

The dashboard's header row carries a gear. **Clicking it opens a settings menu
inside the panel** — no editor, no separate pane:

```
Plugin   ·   1:13:32                     ⚙ ajustes  ^C
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
and never reach `select()`. Hit-testing is by row, resolved through the target map the frame carries.

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
make test
```

Every test isolates its state through a temporary `XDG_STATE_HOME`, so a run
never touches the real config, history, or launcher.
