# Apply Progress — Runtime-agnostic agent observability

## Structured status consumed

- Change: `runtime-agnostic-agent-observability`
- Artifact store: `openspec`
- Apply state: `ready`
- Action context: `repo-local`
- Workspace root: `/home/javier/testing-stuff`
- Allowed edit roots: `/home/javier/testing-stuff`
- User delivery boundary: `auto-chain`, `stacked-to-main`, Slice 1 of 4 only, 400 changed-line budget.
- Action context warnings: none.

## Workload / PR boundary

- Current PR boundary: Slice 1 canonical core/reader only.
- Dependency diagram:

```text
📍 Slice 1 canonical core/reader
   ↓
Slice 2 Claude + Herdr consumers
   ↓
Slice 3 Codex + Pi collectors
   ↓
Slice 4 installer/docs/e2e
```

- Start state: legacy readers remain untouched.
- End state reached: model/IDs, paths/store, reader, and legacy compatibility exist with focused tests, triangulate/refactor complete, and the full suite green.
- Changed-line count: 741 lines after the first attempt, 805 lines after triangulate, measured with `wc -l src/runtime_observability/*.py tests/test_runtime_observability_*.py`; this second attempt added 64 net lines plus small in-place corrections.
- Budget decision: no size exception accepted. Slice 1 is re-sliced into three review sub-slices so each future PR stays under 400 lines. No Slice 2 work was attempted.

### Slice 1 review sub-slices

| Sub-slice | Files | Approx. lines |
|---|---|---:|
| 1a canonical model and identities | `__init__.py`, `model.py`, `ids.py`, `tests/test_runtime_observability_model.py` | 232 |
| 1b snapshot paths and store | `paths.py`, `store.py`, `tests/test_runtime_observability_store.py` | 258 |
| 1c legacy compatibility and shared reader | `legacy.py`, `reader.py`, `tests/test_runtime_observability_legacy.py`, `tests/test_runtime_observability_reader.py` | 315 |

## Completed implementation tasks and persisted checkbox updates

The following task checkboxes are visibly marked `- [x]` in `tasks.md`:

- 1.1 RED model/identity tests.
- 1.2 GREEN model/identity implementation.
- 2.1 RED store tests.
- 2.2 GREEN paths/store implementation.
- 3.1 RED reader/legacy tests.
- 3.2 GREEN reader/legacy implementation.
- 1.3 TRIANGULATE model/identity edges.
- 1.4 REFACTOR model/identity APIs.
- 2.3 TRIANGULATE store isolation edges.
- 2.4 REFACTOR store validation helpers.
- 3.3 TRIANGULATE reader precedence edges.
- 3.4 REFACTOR reader boundaries.

## TDD Cycle Evidence

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 1.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model` | Failed with `ModuleNotFoundError: No module named 'src.runtime_observability'`, as expected before canonical model existed. |
| 1.2 | GREEN | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model` | Passed: 5 tests. |
| 2.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_store` | Failed with `ImportError: cannot import name 'paths' from 'src.runtime_observability'`, as expected before store modules existed. |
| 2.2 | GREEN | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_store` | Passed: 5 tests. |
| 3.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_reader tests.test_runtime_observability_legacy` | Failed with missing `reader` and `legacy` imports, as expected before shared reader modules existed. |
| 3.2 | GREEN | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_reader tests.test_runtime_observability_legacy` | Passed: 8 tests. |
| Slice 1 focused | GREEN check | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model tests.test_runtime_observability_store tests.test_runtime_observability_reader tests.test_runtime_observability_legacy` | Passed: 18 tests. |
| 1.3 / 2.3 / 3.3 | RED | Slice 1 focused command | Failed 4 assertions: `capabilities(activty="complete")` raised nothing, one invalid session key made the whole canonical read unavailable, and stale canonical state preempted the legacy fallback in two reader cases. |
| 1.3 | GREEN | Slice 1 focused command | Passed after `capabilities()` rejected unknown capability keys. |
| 2.3 | GREEN | Slice 1 focused command | Passed after `_validate()` skipped only the unreadable session entry. |
| 3.3 | GREEN | Slice 1 focused command | Passed after stale non-ended snapshots became ineligible and `update_activity()` seeded session freshness from its child activity. |
| 1.4 / 2.4 / 3.4 | REFACTOR | Slice 1 focused command | Passed: 23 tests. |
| Slice 1 full | Verification | `make test` | Passed: 104 tests. |

Triangulation found three real defects rather than cosmetic edges:

1. `model.capabilities()` silently accepted a misspelled capability key, which would have made `capabilities.activity` unreadable and permanently suppressed verified-zero-active reporting.
2. `store._validate()` raised on a single malformed session key, discarding every valid canonical session and violating the malformed-source isolation requirement.
3. `reader._canonical()` returned stale snapshots, which both reported non-current state and blocked the legacy fallback. Fixing it exposed that `store.update_activity()` created sessions with no timestamps, so an activity-only runtime would have been permanently stale.

Two planned edges already held without code changes and are reported as such: malformed legacy state while canonical state is valid, and an absent state root with three simultaneous runtimes.

One previously passing assertion was intentionally corrected, not fitted: the stale-session test asserted that stale canonical state stays authoritative for the root row, which contradicted the design rule that Herdr keeps root-row authority and canonical state only downgrades on explicit `ended`.

## Files changed

- `src/runtime_observability/__init__.py`
- `src/runtime_observability/ids.py`
- `src/runtime_observability/model.py`
- `src/runtime_observability/paths.py`
- `src/runtime_observability/store.py`
- `src/runtime_observability/legacy.py`
- `src/runtime_observability/reader.py`
- `tests/test_runtime_observability_model.py`
- `tests/test_runtime_observability_store.py`
- `tests/test_runtime_observability_legacy.py`
- `tests/test_runtime_observability_reader.py`
- `openspec/changes/runtime-agnostic-agent-observability/tasks.md`
- `openspec/changes/runtime-agnostic-agent-observability/apply-progress.md`

## Deviations from design

- Claude/Codex/Pi adapters and Herdr consumers were not modified, per Slice 1 boundary.
- Design alignment correction: stale canonical snapshots are now ineligible instead of authoritative, so Herdr keeps root-row status authority and the legacy fallback is reachable.
- Design addition within scope: `store.update_activity()` seeds session presence and freshness from the child activity, because the design's activity-only collectors would otherwise never be readable.

## Runtime harness evidence

N/A: no runtime adapter, Herdr consumer, Pi extension, terminal, or live harness boundary was modified. Slice 1 remains unreferenced by any product entrypoint, so there is no runtime boundary to exercise yet.

## Remaining tasks

All Slice 1 task lines are complete. Exact unchecked Slice 1 task lines: none.

Previously unchecked lines, now marked `- [x]`:

- [ ] 1.3 TRIANGULATE: Extend `tests/test_runtime_observability_model.py` with malformed/missing raw ids, unicode ids, empty status payloads, and same raw activity id under different sessions. Evidence: focused model test command first fails on at least one edge, then passes after tightening implementation. <!-- sdd-owner: implementation -->
- [ ] 1.4 REFACTOR: Simplify model/identity APIs without changing behavior, keep privacy-sensitive fields out of canonical records, and run `make test`. Evidence: focused model tests and `make test` pass; rollback boundary is `src/runtime_observability/{__init__.py,model.py,ids.py}` plus `tests/test_runtime_observability_model.py`. <!-- sdd-owner: implementation -->
- [ ] 2.3 TRIANGULATE: Add tests for invalid schema version, partial files, duplicate raw ids across runtimes, and activity updates that must not delete sibling activities or sessions. Evidence: focused store test command first exposes a gap, then passes. <!-- sdd-owner: implementation -->
- [ ] 2.4 REFACTOR: Consolidate serialization/validation helpers in `src/runtime_observability/store.py` without introducing a daemon, SQLite, append-only event log, or generated artifacts. Evidence: `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model tests.test_runtime_observability_store` and `make test` pass; rollback boundary is `src/runtime_observability/{paths.py,store.py}` plus store tests. <!-- sdd-owner: implementation -->
- [ ] 3.3 TRIANGULATE: Extend reader tests with simultaneous Claude/Codex/Pi leaders, same raw session id across runtimes, stale canonical plus valid legacy fallback decisions, absent state root, and malformed legacy `subagents.json` while canonical state is valid. Evidence: focused reader/legacy command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [ ] 3.4 REFACTOR: Keep all raw hook parsing out of `src/runtime_observability/reader.py`, keep visual formatting out of the reader, and document reader precedence in short module docstrings only. Evidence: focused model/store/reader tests and `make test` pass; rollback boundary is `src/runtime_observability/{legacy.py,reader.py}` plus associated tests. <!-- sdd-owner: implementation -->

Tasks 4.1–10.4 remain out of scope for this Slice 1 apply attempt.

## Rollback boundary

Per sub-slice, each removable without touching unrelated work:

- 1a: remove `src/runtime_observability/{__init__.py,model.py,ids.py}` and `tests/test_runtime_observability_model.py`.
- 1b: remove `src/runtime_observability/{paths.py,store.py}` and `tests/test_runtime_observability_store.py`.
- 1c: remove `src/runtime_observability/{legacy.py,reader.py}` and `tests/test_runtime_observability_{legacy,reader}.py`.

Removing the whole package plus the four focused test files and reverting the Slice 1 checkboxes in `tasks.md` restores the pre-slice state. Existing legacy readers and Herdr consumers were never touched.

## Risks

- Slice 1 totals 805 lines, so it must ship as the three sub-slices above rather than one PR; no size exception was accepted.
- Sub-slice 1c is the largest at roughly 315 lines and has the least remaining headroom under the 400-line budget.
- Sub-slices are stacked and not independently mergeable: 1b depends on 1a, and 1c depends on both.
- The canonical foundation still has no consumer, so its precedence rules are proven only by unit tests until Slice 2 migrates the Herdr sidebar and dashboard.


## Slice 2a — Claude compatibility adapter

Work units 4.1-4.4 complete. Slice 2 was re-sliced because the honest adapter work is
300 changed lines, so units 5 and 6 (Herdr sidebar and dashboard migration) become
their own review slice rather than sharing one over-budget PR.

- Sub-slice 2a: `adapters/{__init__,claude_code}.py`, `store.py` extensions, hook wiring
  in `claude_subagent_hook.py` and `claude_profile_hook.py`, plus
  `tests/test_runtime_observability_claude_adapter.py`.
- Changed lines: 300 (58 on tracked files via `git diff --stat`, 242 new lines via `wc -l`).
- No size exception accepted; 300 is under the 400-line review budget.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 4.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_claude_adapter` | Failed with `ModuleNotFoundError: No module named 'src.runtime_observability.adapters'`. |
| 4.2 | GREEN | same focused command | Passed: 7 tests. |
| 4.3 | RED | same focused command | Failed 1 assertion: `SessionEnd` for a never-seen session created an `ended` record. |
| 4.3 | GREEN | same focused command | Passed: 11 tests, after `store.update_session(only_if_present=True)`. |
| 4.4 | REFACTOR | `make test` | Passed: 115 tests, up from 104. |

Triangulation found one real defect and one design gap:

1. `SessionEnd` invented a canonical session it never observed starting, contradicting the
   existing profile-hook rule that an unseen session is not ours to invent. Fixed atomically
   inside the store lock rather than with a read-then-write check.
2. `update_activity` never refreshed its parent session, so a Claude session went stale after
   30 seconds even while children kept reporting. Live child activity now refreshes the parent.

Privacy is asserted, not assumed: a test writes transcript paths, prompts, cwd, and token
fields into the payload and then greps the serialized snapshot to prove none of them land in
canonical state.

Rollback boundary for 2a: delete `src/runtime_observability/adapters/`, revert the `store.py`
extensions and the two hook call sites, and delete the adapter test. Legacy `subagents.json`,
history, artifacts, and profile behavior are untouched, and a discarded canonical snapshot
still leaves legacy state readable, which is asserted by test.

## Slice 2b — Herdr consumer migration

Work units 5.1-5.4 and 6.1-6.4 complete. Both surfaces now resolve live children through
`reader.children_for_session`, and neither parses `subagents.json` any more, which is
asserted by a test that removes the legacy file entirely.

- Changed lines: 258 (151 on tracked files via `git diff --stat`, 107 new test lines).
- Signatures were deliberately preserved: the dashboard keeps single-argument
  `hook_children(session_id)` because `tests/test_hook_dashboard.py` monkeypatches it, and
  each surface keeps its own ordering (sidebar working-first, dashboard by name).
- Sidebar and dashboard tests were consolidated into one focused module covering both
  surfaces, rather than split across `test_hook_dashboard.py`, because the migration is a
  single shared-reader contract.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 5.1 / 6.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_consumers` | Failed: `children_for_session` missing, both surfaces returned no children. |
| 5.2 / 6.2 | GREEN | same focused command | Passed: 7 tests. |
| 5.3 / 6.3 | RED | same focused command | Failed 1 assertion: leftover legacy state overrode a collector that had proven zero children. |
| 5.3 / 6.3 | GREEN | same focused command | Passed: 10 tests. |
| 5.4 / 6.4 | REFACTOR | `make test` | Passed: 125 tests, up from 115. |

Design work the migration required, found by scoping rather than guessed:

1. The dashboard renders a per-child elapsed clock from `started`, which canonical activity
   records did not carry. `model.Activity` gained `started_at`, set by the Claude adapter on
   `SubagentStart`, so the clock survives the migration instead of silently disappearing.
2. Triangulation caught a verified-zero defect: a fresh collector declaring complete activity
   coverage and zero children was overridden by stale legacy entries. Missing evidence and
   proven emptiness are now distinguished, so a finished session no longer resurrects children.

Both modules are also loaded directly by path in tests, so each now makes the sibling package
importable before importing it. Without that, `tests/test_herdr_agent_tree.py` broke.

Known limitation, recorded rather than hidden: `children_for_session` resolves one session at a
time, so it cannot apply the cross-runtime legacy collision guard that `read_agents` applies
with full snapshot context. This preserves the previous per-session sidebar behavior rather
than regressing it, and legacy state remains un-namespaced by runtime.

Rollback boundary for 2b: revert the two `hook_children` bodies and their sibling-package
imports, drop `reader.children_for_session` plus the `started_at` field and its adapter
assignment, and delete `tests/test_runtime_observability_consumers.py`.

## Remaining work

- Work units 7-10: Codex adapter, Pi companion collector, installer/docs, end-to-end.


## Slice 3a-i — Codex-attributed adapter core

Scoping this work unit found a real gap before writing any code: `install.py` wires the
identical `claude_subagent_hook.py`/`claude_profile_hook.py` scripts and payload shape into
both Claude and Codex settings files, so a running hook process had no signal for which CLI
invoked it. Writing a Codex adapter on top of that would have attributed every Codex event as
Claude. Presented to the repository owner as a genuine fork; the owner chose a dedicated,
explicitly-flagged wiring path over shipping an unattributed Codex adapter.

This sub-slice is the adapter half of that decision: the shared hook-lifecycle engine and the
Codex adapter itself, refactored out of `claude_code.py` so neither module duplicates the other.
The hook-script dispatch and installer migration that actually select this adapter are the next
sub-slice (3a-ii), so this one has no wired entrypoint yet — it is proven entirely by direct
adapter-level tests.

- Changed lines: 271 (80 on `claude_code.py` via `git diff --numstat`, 191 new lines across
  `_hook_lifecycle.py`, `codex.py`, and their focused test module).
- No size exception accepted; re-slicing was needed because the combined Codex work (adapter +
  hook dispatch + installer migration) totaled 469 lines, over the 400-line budget, discovered
  only after writing it. Splitting here cost no code: every line already existed and simply
  moved to whichever commit/PR it belongs to.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 7.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_codex_adapter` | Failed: `ImportError: cannot import name 'codex'`. |
| 7.2 | GREEN | same focused command | Passed: 6 tests. |

Design decision made here, not in a later slice: Codex's capabilities are declared more
conservatively than Claude's (`activity: partial`, `completion: unsupported`,
`artifacts: unsupported`) because only the hook-compatible wiring shape is verified in this
repository; Claude's own `SubagentStart`/`SubagentStop` coverage is what earns `activity:
complete`, and Codex has not earned that yet.

`claude_code.py` shrank from a full ingestion implementation to a thin declaration of its
runtime, collector, and capabilities over the new shared `_hook_lifecycle.make_ingest()`
factory. Its public `ingest`/`ingest_quietly` behavior is unchanged, so the existing Claude
adapter test suite (11 tests) still passes without modification.

Rollback boundary for 3a-i: delete `src/runtime_observability/adapters/{_hook_lifecycle,codex}.py`
and `tests/test_runtime_observability_codex_adapter.py`, then restore `claude_code.py`'s prior
self-contained implementation. Nothing outside `runtime_observability` was touched.

## Remaining work

- Sub-slice 3a-ii: hook-script runtime dispatch and installer wiring/migration for Codex
  (`install.py`, both hook scripts, and their tests). Written and passing in the working tree;
  not yet committed, to keep this PR focused on the adapter alone.
- Work unit 8: Pi companion collector.
- Work units 9-10: installer/docs polish beyond the Codex migration, end-to-end.


## Slice 3a-ii — Codex hook dispatch and installer migration

The half of the Codex-attribution decision that actually selects the adapter committed in
3a-i. `install.py` now wires `.codex/hooks.json` with an explicit `--runtime codex` flag on
the same script paths; both hook scripts read that flag from argv and pick the matching
adapter, defaulting to Claude when it is absent so every install before this flag existed is
unaffected.

- Changed lines: 224 (57+20+18+75 = 170 on tracked files via `git diff --numstat`, 54 new lines
  in `tests/test_runtime_observability_codex_hook_dispatch.py`).
- Migration is in place, not additive-only: `install.wire()` detects an already-wired
  unflagged command in a non-Claude settings file and rewrites it to the flagged form, per
  event and per script, rather than leaving stale unattributed wiring beside new wiring.
  `install.unwire()` recognizes both forms so uninstall stays clean regardless of whether a
  given install was ever re-run after this flag shipped.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 7.3 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_install` | Failed 1 assertion: a partially migrated Codex file's already-migrated `SubagentStart` entry was reported as changed again. |
| 7.3 | GREEN | same focused command | Passed: 16 tests, after scoping the migration check to only the entries that still carry the legacy command. |
| 7.4 | REFACTOR | `make test` | Passed: 142 tests, up from 138. |

Two more edges were checked and already held without code changes, reported rather than
invented as failures: an unknown `--runtime` value falls back to Claude instead of dropping
the event (the existing `dict.get(..., claude_code)` default), and a fully clean `.codex/hooks.json`
wiring end-to-end (`install.install(home)`) migrates every event in one pass.

Rollback boundary for 3a-ii: revert `install.py`'s `hook_command`/`our_commands`/`wire`/
`unwire`/`wired_events`/`runtime_for` signatures and call sites, revert the `_runtime_adapter()`
dispatch in both hook scripts, and delete `tests/test_runtime_observability_codex_hook_dispatch.py`.
The Codex adapter core from 3a-i is unaffected either way.

## Remaining work

- Work unit 8: Pi companion collector.
- Work units 9-10: installer/docs polish beyond the Codex migration, end-to-end.


## Slice 3b-i — Pi companion adapter core

Pure Python mapping from synthetic Pi extension events to canonical runtime state, tagged
`runtime=pi`, verified entirely without a real Pi process per the design's own guidance.

- Changed lines: 204 (121 in `pi_companion.py`, 83 in its focused test module), both new files.
- No size exception accepted; re-sliced from the full Pi companion work (adapter + ingestion
  CLI + Pi extension = 414 lines, marginally over budget) using the same seam as Slice 3a:
  adapter core first, wiring/ingestion boundary next.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 8.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_pi_companion` | Failed: `ImportError: cannot import name 'pi_companion'`. |
| 8.2 | GREEN | same focused command | Passed: 9 tests. |

Writing the GREEN implementation surfaced a real defect before any test caught it: an initial
draft reset `started_at` to the end time on `tool_execution_end`, which would have broken the
per-child elapsed clock the dashboard renders (added for Claude activities in Slice 2b). Fixed
by reading the existing activity's `started_at` from the current snapshot and carrying it
forward; a test (`test_tool_execution_end_preserves_the_original_start_time`) now guards it.

Capability declaration for Pi: `presence: supported`, `status: partial`, `activity: partial`,
`completion: supported`, `history: unsupported`, `artifacts: unsupported`. `completion` is
`supported` (unlike Codex's `unsupported`) because `session_shutdown` is Pi's own native event
for a process this extension is loaded into, not an opportunistic reuse of another CLI's hook
schema. `agent_end` deliberately does not claim `idle`, because Pi may still auto-retry,
auto-compact, or run a queued follow-up after it fires; only `agent_settled` does.

Rollback boundary for 3b-i: delete `src/runtime_observability/adapters/pi_companion.py` and
`tests/test_runtime_observability_pi_companion.py`. Nothing else was touched.

## Remaining work

- Sub-slice 3b-ii: the Python ingestion CLI and the Pi extension file that actually calls this
  adapter. Written and passing/smoke-tested in the working tree; stashed to keep this commit
  focused on the adapter alone.
- Work units 9-10: installer/docs polish, end-to-end.


## Slice 3b-ii — Pi ingestion CLI and companion extension

The wiring half of the Pi companion collector: `src/runtime_observability_cli.py` (a thin CLI
the extension shells out to, one event per call, always exits 0) and
`pi/herdr-agent-observability/index.ts` (the Pi extension itself, subscribing to
`session_start`, `agent_start`, `agent_end`, `agent_settled`, `tool_execution_start`,
`tool_execution_end`, and `session_shutdown`).

- Changed lines: 210 (33 in the CLI, 52 in its focused test, 125 in the extension), all new
  files.
- Combined with 3b-i, total Pi companion work is 414 lines; splitting cost no code, only which
  commit each file belongs to, matching the seam already used in Slice 3a.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 8.3 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_cli` | Failed: CLI script did not exist, subprocess exited non-zero. |
| 8.3 | GREEN | same focused command | Passed: 3 tests. |
| 8.4 | REFACTOR | `make test` | Passed: 154 tests, up from 151. |

Every event name, field name (`toolCallId`, `toolName`, `isError`), and `sessionManager`
method (`getSessionId()`) in `index.ts` was checked against the installed
`@earendil-works/pi-coding-agent` package's own `.d.ts` declarations before writing the file,
not assumed from documentation prose alone.

This repository has no Node/Pi runtime harness, so `index.ts` cannot run under `make test`.
Two things were still verified, honestly bounded rather than claimed as full coverage:

1. `node --experimental-strip-types --check pi/herdr-agent-observability/index.ts` — confirms
   the file is syntactically valid TypeScript (type-erasure parse, not a full `tsc` type-check;
   no `tsc` was installable in this offline environment).
2. A one-off functional smoke test: imported the module's default export with a fake `pi.on`
   registrar and a synthetic `ctx.sessionManager.getSessionId()`, invoked its `session_start`
   and `tool_execution_start` handlers, and confirmed canonical state was written under a
   temporary `XDG_STATE_HOME`, tagged `runtime: "pi"`, `collector: "pi-extension"`, with the
   `bash` activity present. This is not part of `make test` and is not repeatable from this
   repository alone (it required a scratch script and manual environment setup), so it is
   recorded here as one-time evidence rather than a claimed automated test.

Rollback boundary for 3b-ii: delete `src/runtime_observability_cli.py`,
`tests/test_runtime_observability_cli.py`, and `pi/herdr-agent-observability/index.ts`. The
adapter from 3b-i is unaffected either way.

## Remaining work

- Work units 9-10: installer/docs polish for the Pi companion collector's install path
  (currently resolved via `HERDR_AGENT_OBSERVABILITY_CLI` env override or a path relative to
  the extension file), and end-to-end verification.


## Slice 4 — Installer polish, documentation, and end-to-end verification

Final slice of the first-slice implementation. All ten planned work units are now complete.

- Changed lines: 290 (195 tracked via `git diff --numstat` across `install.py`, `README.md`,
  `tests/test_install.py`; 95 new lines in `tests/test_runtime_observability_integration.py`).
- No size exception needed; this slice fit the 400-line budget on its own.

### Pi companion collector stays explicit

`install.py` gained `--link-pi-extension`, an opt-in flag that symlinks
`pi/herdr-agent-observability/` into Pi's own documented global extension directory
(`~/.pi/agent/extensions/herdr-agent-observability/`), verified against the installed
`@earendil-works/pi-coding-agent` docs rather than assumed. Plain `install()`/`check()` only
*report* its status (`not installed` / `linked` / `present (not ours)`); neither creates it
silently, matching the task's explicit requirement. `unlink_pi_extension()` mirrors the
existing hook `unwire()` safety rule: it removes only a symlink this installer created, and
leaves a foreign directory at the same path untouched — covered by a dedicated test.

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 9.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_install` | Failed 7 errors: `pi_extension_status`/`link_pi_extension`/`unlink_pi_extension`/`pi_extension_target` did not exist. |
| 9.2 | GREEN | same focused command | Passed: 23 tests. |
| 9.3 | TRIANGULATE | same focused command | Extended with a foreign-directory-status test and an end-to-end `--link-pi-extension` subprocess test; both passed without further code changes — reported rather than invented as failures. |
| 9.4 | REFACTOR | `make test` | Passed: 161 tests, up from 154. |

### Documentation

`README.md` gained a "Runtime observability (internal)" section: the canonical snapshot path,
a capability table per runtime (Claude complete/supported, Codex partial/unsupported, Pi
partial/supported-for-its-own-shutdown), how Codex is now attributed correctly, how to opt in
to the Pi collector, and this slice's explicit non-goals (dashboard/sidebar redesign, history
and artifact redesign, Claude transcript analytics, the profile-resume freeze-clock, API-key
polling). The existing "This depends on a session-end hook, which today means Claude Code
only" sentence about the *visible* dashboard root freeze-clock was kept accurate and given a
footnote distinguishing it from the internal layer, rather than silently implying the visible
behavior changed — it did not; only live-children sourcing did, in Slice 2b.

### End-to-end integration test

| Task(s) | Phase | Command | Result |
|---|---|---|---|
| 10.1 | RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_integration` | Failed: file did not exist. |
| 10.2 | GREEN | same focused command | Passed: 2 tests, with no seams needed between prior slices' work. |
| 10.3 | Full verification | `make test` | Passed: 165 tests, up from 161. |
| 10.4 | Final review | `git diff --numstat` / `wc -l` (this slice) | 290 changed lines; diff scoped to installer/docs/tests only, no accidental UI/history/artifact/profile/polling changes. |

The integration test exercises Claude, Codex, and Pi leaders simultaneously through
`reader.read_agents()` and `reader.children_for_session()` — the same entrypoints both Herdr
surfaces use — plus a stale fourth Claude session (must show no activity, not verified-zero),
malformed legacy state (must not take down canonical reads for the other three), and an
unrecognized `bash` agent kind (must not appear as a leader at all). All held on the first run,
which is evidence the four prior slices compose correctly, not evidence they were untested
individually.

### Full first-slice test count

```text
baseline (pre-change):        81 tests
Slice 1 (canonical core):    104 tests
Slice 2a (Claude adapter):   115 tests
Slice 2b (Herdr consumers):  125 tests
Slice 3a (Codex adapter):    142 tests
Slice 3b (Pi companion):     154 tests
Slice 4 (this slice):        165 tests
```

Rollback boundary for Slice 4: revert `install.py`'s Pi-extension functions and the
`--link-pi-extension` flag, revert the README section, and delete
`tests/test_runtime_observability_integration.py`. Every prior slice's commit stands
independently either way.

## Change status

All ten work units in `tasks.md` are complete. `runtime-agnostic-agent-observability` first
slice is implemented across nine commits on `feat/runtime-observability-core`, not yet merged,
pushed, or made into a PR — that remains a separate, explicitly authorized step.


## Post-Slice-4 fix — check() ignored the runtime-flagged Codex wiring

Discovered by actually installing this plugin against the maintainer's real Herdr
environment, not by inspection: `python3 install.py --check` reported `.codex/hooks.json` as
`0/5 wired — missing ...` immediately after `install()` had just correctly migrated it to the
`--runtime codex`-flagged commands and reported all 5 as changed.

Root cause: `check()`'s call to `wired_events(settings, ROOT)` was missing the `runtime`
argument added in Slice 3a-ii, so it always compared against the unflagged Claude-shaped
command regardless of which settings file it was checking. `install()` and `uninstall()` both
correctly passed `runtime_for(path, home)`; only this one call site in `check()` was missed
during that slice's edits.

- Changed lines: small, single-line fix plus one focused test.
- `install.wire()`/`unwire()` were never affected; the actual wiring on disk was always
  correct. Only `check()`'s reporting was wrong, and only for a settings file that isn't
  Claude's own (i.e., only `.codex/hooks.json`).

| Phase | Command | Result |
|---|---|---|
| RED | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_install.InstallTest.test_check_reports_a_migrated_codex_file_as_fully_wired` | Failed: reported `0/5 wired` for a fully migrated Codex file. |
| GREEN | same focused command | Passed: 26 tests. |
| Full verification | `make test` | Passed: 166 tests, up from 165. |
| Live verification | `python3 install.py --check` against the maintainer's real `~/.codex/hooks.json` | Now reports `5/5 wired — complete`, matching the file's actual (already-correct) content. |

Rollback boundary: revert the single `wired_events(settings, ROOT)` call in `check()` and
delete the one new test. No other behavior is affected.
