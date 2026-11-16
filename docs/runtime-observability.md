# Runtime observability

Internal notes on the layer that feeds the live tree. Users do not need any of
this to install or use the plugin; see the [README](../README.md) for that.

## What it is

Live children in the tree come from one shared reader in
`src/runtime_observability/`, not from raw hook-file parsing in the sidebar or
the dashboard. It normalizes Claude Code, Codex and Pi evidence into one
canonical snapshot at
`$XDG_STATE_HOME/herdr/claude-vezmex-team-tree/runtime-observability.json`.
The snapshot is additive: it sits beside the existing `subagents.json`,
`history.jsonl`, `artifacts.jsonl` and `profiles.json` files, which keep their
behavior unchanged.

Herdr remains the authority for which panes are visible leaders. This layer
only enriches what Herdr already exposes, and it never reads terminal output.

## What each runtime can prove

Each runtime declares what it can actually prove, so an empty result reads as
*unknown* rather than a made-up idle, done or zero-active claim. The
capability table in the README's Requirements section is that declaration.

- **Codex** is attributed correctly: `install.py` wires `.codex/hooks.json`
  with an explicit `--runtime codex` flag on the same scripts Claude uses, and
  migrates an older unflagged wiring in place. Its capabilities stay
  conservative because only that hook-compatible surface is verified in this
  repository.
- **Pi** is observed through an optional companion collector,
  `pi/herdr-agent-observability/index.ts`, which is never installed
  automatically:

  ```sh
  python3 install.py --link-pi-extension   # symlinks it into ~/.pi/agent/extensions/
  python3 install.py --check               # also reports its current status
  ```

  It observes only the current Pi process's own top-level session: its agent
  loop, its own tool calls and its own shutdown. It never sees a nested
  delegation such as AskClaude, and never terminal output. `--uninstall`
  removes only a link this installer created; a foreign directory at the same
  path is left untouched, the same safety rule as the hook `unwire()`.

## Session end

Claude Code proves session end through its own `SessionEnd` hook. Pi proves it
through its own native shutdown event: the companion extension emits
`session_shutdown`, this layer normalizes it into a `presence: "ended"`
canonical record, and the dashboard's freeze-clock falls back to that record
whenever `profiles.json` has none for the session. The lookup is keyed by
`(runtime, raw session id)`, since raw ids can collide across runtimes.

Codex's `SessionEnd` hook is wired the same way as Claude's, so it would freeze
the same way, but only that hook-compatible surface is verified here. Codex's
own capability declaration therefore still reports session end as
unsupported/unverified.

## Scope and rollback

Out of scope for this layer: a visual redesign of the dashboard or the sidebar,
a history or artifact redesign, generalizing Claude transcript analytics, and
API-key-based polling.

Rollback is additive-safe: delete `runtime-observability.json` and nothing
else depends on it existing.
