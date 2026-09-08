# Technical Design — Runtime-agnostic agent observability

## Decision summary

Introduce a small canonical runtime-observability layer under the existing Herdr plugin state root, then make the sidebar and dashboard consume it through one shared reader. Herdr remains the product boundary and the authority for visible panes, workspace scoping, pane ids, leader detection, metadata publishing, dashboard rendering, pane actions, opening, and resizing.

The first slice uses canonical **snapshots only**, not a new daemon, SQLite database, framework, or append-only event log. Existing `history.jsonl` and `artifacts.jsonl` stay as legacy feature files for current dashboard sections; the new canonical layer is only for live runtime/session/activity observability.

## Constraints satisfied

| Constraint | Design decision |
| --- | --- |
| Preserve plugin identity | Keep `local.claude-vezmex-team-tree` unchanged. |
| Preserve state namespace | Keep `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree` as the only first-slice state root. |
| Keep Herdr authority | Runtime state never creates visible leaders; it only enriches Herdr-visible leaders with matching runtime/session evidence. |
| Avoid terminal reads | Adapters consume local lifecycle hooks, Pi extension events, or verified local files only. |
| Avoid false certainty | Unknown/missing/stale/unsupported state remains unknown, never fake idle/done/zero-active. |
| Keep runtime schemas isolated | Claude, Codex, and Pi raw payload parsing lives in runtime adapters, not UI renderers. |
| Preserve visible behavior | Current Claude/Codex legacy state remains readable through compatibility shims. |

## Python module boundaries

Create a new package under `src/runtime_observability/` and keep existing Herdr-facing entrypoints thin.

```text
src/runtime_observability/
  __init__.py
  model.py              # Canonical dataclasses/enums/schema constants/normalizers.
  ids.py                # Namespaced identity helpers and base64url escaping.
  paths.py              # Existing plugin state root and canonical/legacy file paths.
  store.py              # Atomic snapshot read/write/merge with lock handling.
  reader.py             # Shared Herdr-facing normalized reader and precedence rules.
  legacy.py             # Legacy subagents.json/profile/history/artifact compatibility reads.
  adapters/
    __init__.py
    claude_code.py      # Claude Code hook payload normalization only.
    codex.py            # Repository-verified Codex hook-shape adapter only.
    pi_companion.py     # Canonical event contract for Pi companion extension inputs.
```

Compatibility entrypoints stay in place:

```text
src/claude_subagent_hook.py   # Becomes/uses Claude Code adapter shim; file path stays install-compatible.
src/claude_profile_hook.py    # Keeps legacy profile behavior; may also publish ended snapshot fields.
src/claude_artifact_hook.py   # Stays Claude-specific and outside canonical core.
src/herdr_agent_tree.py       # Herdr sidebar consumer; no raw hook parsing.
src/claude_team_tree.py       # Dashboard consumer; no raw hook parsing for live children.
install.py                   # Existing installer remains reversible; Pi wiring only if verified/explicit.
```

### Ownership by layer

| Layer | Owns | Must not own |
| --- | --- | --- |
| `model.py` / `ids.py` | Stable runtime/session/activity vocabulary, schema version, identity construction. | Herdr commands, adapter-specific payload keys, transcript/profile/artifact details. |
| `store.py` | Canonical snapshot persistence, locks, atomic replacement, safe malformed reads. | Workspace filtering, visual decisions, installer edits. |
| `reader.py` | Joining Herdr-visible leaders to canonical/legacy runtime state, precedence, freshness. | Raw Claude/Codex/Pi payload parsing. |
| `adapters/*` | Runtime-specific local evidence mapping into canonical records. | Herdr UI rendering, pane discovery, terminal reads. |
| `herdr_agent_tree.py` / `claude_team_tree.py` | Current UI formats and Herdr surface behavior. | Duplicate raw `subagents.json` parsing or runtime schema parsing. |

## Canonical snapshot schema

Canonical state is additive and stored at:

```text
$XDG_STATE_HOME/herdr/claude-vezmex-team-tree/runtime-observability.json
```

Schema identity:

```json
{
  "schema": "herdr.runtime_observability.snapshot",
  "schema_version": 1,
  "written_at": 1760000000.0,
  "sessions": {
    "ro:v1:claude:session:bGVhZGVyLXNlc3Npb24": {
      "id": "ro:v1:claude:session:bGVhZGVyLXNlc3Npb24",
      "runtime": "claude",
      "raw_session_id": "leader-session",
      "presence": "present",
      "status": "working",
      "observed_at": 1760000000.0,
      "heartbeat_at": 1760000000.0,
      "expires_at": 1760000030.0,
      "freshness": "fresh",
      "capabilities": {
        "presence": "supported",
        "status": "supported",
        "activity": "complete",
        "completion": "supported",
        "history": "legacy-only",
        "artifacts": "legacy-only"
      },
      "source": {
        "runtime": "claude",
        "collector": "claude-code-hooks",
        "kind": "hook",
        "confidence": "direct"
      },
      "activities": {
        "ro:v1:claude:session:bGVhZGVyLXNlc3Npb24:activity:YWdlbnQtMTIz": {
          "id": "ro:v1:claude:session:bGVhZGVyLXNlc3Npb24:activity:YWdlbnQtMTIz",
          "raw_activity_id": "agent-123",
          "name": "Explore",
          "status": "working",
          "observed_at": 1760000000.0,
          "heartbeat_at": 1760000000.0,
          "expires_at": 1760000030.0,
          "freshness": "fresh",
          "source": {
            "runtime": "claude",
            "collector": "claude-code-hooks",
            "kind": "hook",
            "confidence": "direct"
          }
        }
      }
    }
  }
}
```

### Identity rules

- Allowed runtime values: `claude`, `codex`, `pi`.
- Canonical session id: `ro:v1:{runtime}:session:{base64url(raw_session_id)}`.
- Canonical activity id: `{canonical_session_id}:activity:{base64url(raw_activity_id)}`.
- `raw_session_id` and `raw_activity_id` are preserved for exact Herdr joins and debugging, but dictionary keys always use canonical ids.
- Base64url encoding is unpadded and reversible; raw ids are never concatenated unescaped.
- The schema version is explicit. Future incompatible readers must reject unknown major schema shapes and fall back to legacy/unknown-safe behavior.

## Semantics

### Presence

| Value | Meaning |
| --- | --- |
| `present` | The runtime has fresh local evidence that the session exists. |
| `ended` | The runtime has explicit supported completion/shutdown evidence. |
| `unknown` | Evidence is missing, unsupported, malformed, or stale. |

Presence does not create a visible leader. A session record is eligible only after Herdr exposes a visible recognized leader with matching runtime and `agent_session`.

### Status

Canonical status vocabulary:

```text
working | idle | blocked | done | ended | interrupted | unknown
```

Mapping rules:

- `working`: reliable active run/tool/subagent evidence.
- `idle`: reliable runtime evidence that the session is live and settled.
- `blocked`: reliable error/failure/waiting-for-attention evidence.
- `done`: reliable activity completion evidence for a child/activity, not for a vanished session without completion support.
- `ended`: explicit supported session shutdown/end evidence.
- `interrupted`: parent session ended while a child was still `working`, matching current dashboard behavior.
- `unknown`: missing, malformed, unsupported, or stale evidence.

Malformed or unsupported source statuses always normalize to `unknown`; they are never coerced into `idle`, `done`, or zero-active.

### Activity completeness and capabilities

Each session declares capability support so consumers know whether an empty activity map means verified zero or unknown:

```text
supported | unsupported | unavailable | legacy-only | complete | partial | unknown
```

`capabilities.activity` has these first-slice meanings:

- `complete`: source claims a complete current child/activity set for the session.
- `partial`: source can report some activity but cannot prove absence.
- `unsupported` / `unavailable`: no verified child activity source.
- `legacy-only`: canonical core does not own the feature yet; current legacy file remains authoritative for that feature.
- `unknown`: malformed or stale capability evidence.

UI summaries may report `0 active` only when `activity == "complete"`, the session is fresh, and the activities map is empty. Otherwise no child rows means unknown/no supporting evidence, not verified zero.

### Freshness and TTL

Default first-slice TTLs live in `model.py` and can be made configurable later:

| Record | Default TTL | Notes |
| --- | ---: | --- |
| session presence/status | 30 seconds | Applies to runtimes that use heartbeats or event refresh. |
| child/activity status | 30 seconds | Stale `working` becomes `unknown` unless parent explicitly ended. |
| explicit `ended` session | no TTL | Terminal evidence stays terminal. |
| explicit `done` child | no live retention requirement | Claude live children are removed on stop; history remains legacy. |

Freshness calculation:

1. If `expires_at` exists and `now > expires_at`, mark `freshness = stale` and expose status/presence as `unknown` unless terminal `ended` is explicit.
2. Else if `observed_at + ttl < now`, mark stale.
3. Else mark fresh.
4. A stale record does not publish current activity counts.
5. If a session is explicitly `ended`, still map stale/working child activities to `interrupted` for post-mortem display.

## Source precedence

Herdr remains the outer authority for visible leaders. For each Herdr-visible recognized leader in the active/focused workspace:

1. **Herdr-native children**: if the snapshot contains `subagents` or `children`, use those for child rows. Herdr-native hierarchy has highest child precedence because it is product-native. Runtime state may still provide freshness/source metadata later, but not override Herdr-native child membership.
2. **Canonical runtime state**: if a fresh canonical session exists for `(runtime, Herdr agent_session)`, use canonical session/activity state.
3. **Legacy `subagents.json` compatibility**: if no eligible canonical session exists, project legacy live children into the requested runtime/session only through the shared reader.
4. **Unknown-safe empty**: if no source is eligible, expose unknown supporting evidence and no child rows; do not report verified zero.

Legacy collision guard:

- `subagents.json` is not namespaced by runtime.
- If multiple Herdr-visible recognized leaders with different runtimes share the same raw `agent_session` and only legacy state exists, the reader treats legacy child state as ambiguous and returns unknown activity for those colliding leaders.
- This preserves existing normal installs while avoiding cross-runtime state merging when a collision is observable.

Leader status precedence:

- Herdr leader visibility, pane id, workspace id, display name, and native `agent_status` stay authoritative for the root row.
- Canonical session `ended` may downgrade a dead root from stale Herdr `working` to `ended`, preserving the current profile-end behavior.
- Canonical session status may not promote an invisible runtime record into a leader and may not override workspace scoping.

## Runtime collectors/adapters

### Claude Code adapter

`adapters/claude_code.py` owns Claude Code hook payload parsing:

- Accepts current `SubagentStart` / `SubagentStop` payloads from `claude_subagent_hook.py`.
- Uses `session_id` as the parent session id and `agent_id` as activity id.
- Maps `SubagentStart` to session/activity `present` + `working` with fresh heartbeat.
- Maps `SubagentStop` to activity removal in the live canonical snapshot, while preserving existing legacy history behavior in `claude_subagent_hook.py`.
- Can consume `SessionStart` / `SessionEnd` from `claude_profile_hook.py` only for canonical session presence/ended fields.

Privacy boundary:

- Transcript paths, transcript contents, prompts, token tallies, tool tallies, `last_assistant_message`, artifact titles/ids, profile names, and resume details do not enter `model.py`, `store.py`, or `reader.py`.
- Existing transcript/artifact/profile behavior remains Claude-specific legacy behavior behind the Claude entrypoints.

Compatibility:

- Keep `src/claude_subagent_hook.py` as the installed command path.
- It may call `adapters.claude_code.ingest_hook_event(event)` after/before current legacy writes.
- Rollback can ignore `runtime-observability.json` and current legacy files still work.

### Codex adapter

`adapters/codex.py` is deliberately limited to repository-verified local surfaces:

- The repository currently verifies only installer wiring into an existing `~/.codex/hooks.json` using the same command schema as Claude-shaped hooks.
- Therefore first-slice Codex support accepts only the same locally delivered hook payload shape already wired by `install.py`.
- Unknown Codex-native hooks, transcript formats, profile files, artifact events, or session-end signals must be represented as unsupported/unavailable until verified in this repository.

Capabilities:

```json
{
  "presence": "supported" if hook payload includes session_id else "unknown",
  "status": "partial",
  "activity": "partial",
  "completion": "unsupported",
  "history": "legacy-only",
  "artifacts": "unsupported"
}
```

Codex must not claim `ended`, `done`, complete child inventory, or artifact/profile support unless a local payload explicitly supports it.

### Pi companion collector

Pi support is a companion collector, not a replacement product boundary. Herdr still owns the plugin, panes, metadata tokens, and dashboard.

Ship a Pi extension source file, for example:

```text
pi/herdr-agent-observability/index.ts
```

or a generated copy under a documented install path. The extension subscribes to verified Pi extension lifecycle/tool events:

- `session_start`: observe top-level Pi session id/file/cwd through `ctx.sessionManager.getSessionId()` / `getSessionFile()` and write `presence=present`, initial `status=idle` or `unknown` depending on `ctx.isIdle()`.
- `agent_start`: write top-level session `status=working` and heartbeat.
- `agent_end`: write top-level status from stop/error/abort evidence when available; do not mark settled yet if Pi may auto-retry or auto-compact.
- `agent_settled`: write `status=idle` when `ctx.isIdle()` is true.
- `ui_prompt_start` / `ui_prompt_end`: optionally map waiting-for-user to `blocked` only if the design chooses that label for user-waiting; otherwise keep status `working` with source kind `ui_prompt` to avoid overclaiming failure.
- `tool_execution_start` / `tool_execution_update` / `tool_execution_end`: represent top-level tool calls as `activities` with ids from `toolCallId`, names from `toolName`, `working` while running, and `done`/`blocked` at end based on `isError`.
- `model_select`: update optional source metadata only; provider/model details are adapter-local and should not be needed by core UI.
- `session_shutdown`: write explicit `ended` only for the Pi top-level session being shut down.

Pi top-level versus nested internals:

- The Pi extension can observe the current Pi process top-level session, top-level agent loop, top-level tool executions, UI prompt spans, model changes, and shutdown.
- It can observe a nested `AskClaude`/subagent invocation only as a top-level Pi tool call unless that nested process independently runs a compatible collector and emits its own state.
- The parent Pi extension must not parse nested AskClaude transcripts, spawned child terminal output, hidden child sessions, or provider internals.
- If a Pi subagent tool spawns child Pi processes, each child can become its own top-level Pi session in canonical state only if the extension is loaded in that child process. Herdr will display it as a leader only if Herdr also exposes a visible `pi` pane with a matching `agent_session`; otherwise it remains runtime-only evidence and is not promoted.

The Pi extension should call a small Python ingestion CLI or write the same canonical snapshot contract through an atomic helper. Prefer invoking Python ingestion to keep schema validation and merge semantics in one implementation.

## State store, concurrency, and malformed-state handling

`store.py` responsibilities:

- Create the existing state root with `0700` best-effort permissions.
- Use `.runtime-observability.lock` with `fcntl.flock(LOCK_EX)` around read-modify-write updates.
- Write snapshots via `tempfile.mkstemp(dir=state_root)`, JSON dump, flush, `os.fsync`, and `os.replace`.
- Readers never require a lock; they read the current file and tolerate `OSError`, `JSONDecodeError`, invalid schema, and invalid records.
- If canonical state is malformed, `reader.py` marks only the canonical source unavailable and still attempts legacy compatibility reads.
- If legacy `subagents.json` is malformed, only the legacy source is unavailable; Herdr-native and canonical state still render.
- No partial read may fabricate live status. Last-good caching is optional in memory during a single dashboard process but must not require a daemon.

Canonical merge rules:

- Updates are scoped by canonical session id and activity id.
- A collector update cannot delete another runtime's session.
- Activity updates for one session cannot overwrite another session, even with the same raw activity id.
- Stale pruning may remove or ignore old non-terminal records after a generous retention window, but first-slice readers can simply mark stale without destructive cleanup.

## Migration and rollback

Migration is additive:

1. Add `runtime_observability` modules and tests.
2. Add canonical writes to existing Claude hook shims while leaving legacy writes unchanged.
3. Redirect `herdr_agent_tree.py` and `claude_team_tree.py` live-child reads to `reader.py`.
4. Keep dashboard history/artifact/profile reads unchanged for the first slice, except for optional canonical `ended` use.
5. Add Codex adapter tests against the existing hook-compatible payload shape only.
6. Add Pi companion collector tests using synthetic Pi extension events; do not require a real Pi process in unit tests.

Rollback is safe:

- Revert UI consumers to legacy `hook_children()` reads.
- Leave `runtime-observability.json` in place; old code ignores it.
- Keep `local.claude-vezmex-team-tree` and `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree` unchanged.
- Existing `subagents.json`, `history.jsonl`, `artifacts.jsonl`, `profiles.json`, and `config.json` remain the compatibility source.

## Expected file impact

| File/path | Impact |
| --- | --- |
| `src/runtime_observability/model.py` | New canonical enums/dataclasses/schema constants. |
| `src/runtime_observability/ids.py` | New namespaced id helpers. |
| `src/runtime_observability/paths.py` | New shared state-root helpers preserving current path. |
| `src/runtime_observability/store.py` | New atomic snapshot store. |
| `src/runtime_observability/reader.py` | New shared Herdr-facing reader and source precedence. |
| `src/runtime_observability/legacy.py` | New compatibility shim for `subagents.json` and current session helpers. |
| `src/runtime_observability/adapters/claude_code.py` | New Claude hook adapter. |
| `src/runtime_observability/adapters/codex.py` | New limited Codex adapter. |
| `src/runtime_observability/adapters/pi_companion.py` | New Pi companion event normalizer. |
| `src/runtime_observability_cli.py` or equivalent | Optional ingestion CLI used by hooks/extensions. |
| `src/herdr_agent_tree.py` | Replace duplicate `hook_children()` raw parsing with shared reader; keep Herdr command output. |
| `src/claude_team_tree.py` | Replace live-child parsing with shared reader; keep rendering/history/artifacts/config behavior. |
| `src/claude_subagent_hook.py` | Call Claude adapter while preserving legacy files/history. |
| `src/claude_profile_hook.py` | Optionally write canonical session start/end while preserving profile files. |
| `install.py` | Keep existing Claude/Codex wiring; add Pi collector wiring only through verified explicit extension placement. |
| `tests/test_runtime_observability_*.py` | New strict-TDD coverage for model, store, reader, adapters, migration. |
| Existing tests | Update only where they currently monkeypatch `hook_children`; preserve behavior assertions. |

## Test architecture under strict TDD

Use `python3 -m unittest discover -s tests -t tests` and `make test`. All tests isolate `XDG_STATE_HOME` with temporary directories and never touch real Herdr/Pi/Claude/Codex config.

RED/GREEN slices:

1. **Model/identity tests**
   - canonical ids include runtime namespace and reversible raw ids;
   - same raw session id in Claude and Codex produces different canonical ids;
   - unsupported/malformed statuses normalize to `unknown`.
2. **Store tests**
   - atomic write creates valid JSON;
   - malformed canonical file returns unavailable state, not an exception;
   - concurrent scoped updates do not overwrite other runtime/session records.
3. **Reader precedence tests**
   - Herdr-native children win over canonical/legacy;
   - canonical fresh state wins over legacy;
   - legacy fallback preserves existing `subagents.json` behavior;
   - legacy collision across visible runtimes becomes unknown-safe;
   - no `agent_session` means no guessed state;
   - no recognized leader means idle/no-agent behavior remains.
4. **Freshness tests**
   - stale `working` becomes `unknown`;
   - explicit ended session remains ended;
   - ended parent maps still-working child to `interrupted`;
   - empty activity map reports verified zero only when capability is complete and fresh.
5. **Adapter tests**
   - Claude `SubagentStart` and `SubagentStop` update canonical live activity without leaking transcript/artifact/profile fields;
   - Codex accepts only hook-compatible local payloads and marks unsupported capabilities explicitly;
   - Pi synthetic lifecycle/tool events map to top-level session/activity records without claiming nested AskClaude internals.
6. **Installer tests**
   - existing Claude/Codex commands stay idempotent/reversible;
   - Pi extension wiring is explicit and does not create unverified runtime config files silently.

## Privacy and data minimization

Canonical state stores only runtime identity, raw session/activity ids, display-safe activity names, normalized status/presence, timestamps, capability declarations, and coarse source metadata. It must not store terminal text, transcript content, prompts, artifact contents, profile names, provider payloads, model prompts, API headers, or nested tool outputs.

Legacy Claude history/artifact/profile files keep their current behavior for existing dashboard sections, but those details remain outside the canonical core and outside Codex/Pi claims unless verified later.

## Open unknowns intentionally isolated

- Codex-native hook/event schemas beyond the current `.codex/hooks.json` compatible command shape are unknown and unsupported in this design.
- Pi does not expose another process's nested AskClaude internals through the documented top-level extension events; parent Pi observation is limited to top-level lifecycle and tool events.
- Herdr-native child fields are future-compatible through `subagents`/`children` precedence, but this design does not assume Herdr will provide them.
