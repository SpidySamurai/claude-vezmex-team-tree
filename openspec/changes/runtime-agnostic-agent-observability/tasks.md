# Tasks — Runtime-agnostic agent observability

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 900–1,400 changed lines total; each planned PR slice estimated below 400 changed lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 canonical core/reader → PR 2 Claude compatibility + Herdr consumers → PR 3 Codex and Pi collectors → PR 4 installer/docs/e2e verification |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

## Delivery Decision

The prior `ask-on-risk` gate is resolved. Implementation should use `auto-chain` with four stacked-to-main PR slices, each targeting the 400 changed-line review budget. Do not create branches, commits, or PRs from this task artifact; apply should implement and verify slices only.

## Bounded Slicing Pass

This is the single honest slicing pass for the approved task set. The budget constrains review slicing only; do not compress, remove, or under-test required behavior to fit the line budget. If implementation evidence later shows a slice exceeding 400 changed lines, stop that slice and recommend `size:exception` rather than iterating the split.

### Slice 1 — Canonical core and shared reader foundation

| Field | Value |
|-------|-------|
| Start state | No canonical runtime-observability package exists; Herdr surfaces still own legacy live-child parsing. |
| End state | Canonical model, IDs, snapshot paths/store, shared reader, and legacy compatibility are implemented and tested without changing UI consumers. |
| Dependencies | Approved proposal/spec/design only. |
| Exact task IDs | 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4 |
| Expected file surfaces | `src/runtime_observability/{__init__.py,model.py,ids.py,paths.py,store.py,reader.py,legacy.py}`, `tests/test_runtime_observability_model.py`, `tests/test_runtime_observability_store.py`, `tests/test_runtime_observability_reader.py`, `tests/test_runtime_observability_legacy.py` |
| Focused verification | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model tests.test_runtime_observability_store tests.test_runtime_observability_reader tests.test_runtime_observability_legacy` |
| Full verification | `make test` |
| Rollback boundary | Remove `src/runtime_observability/` core/reader files and their focused tests; existing legacy readers remain untouched. |
| Estimated changed lines | 300–390 |

Dependency diagram:

```text
📍 Slice 1 canonical core/reader
   ↓
Slice 2 Claude + Herdr consumers
   ↓
Slice 3 Codex + Pi collectors
   ↓
Slice 4 installer/docs/e2e
```

### Slice 2 — Claude compatibility and Herdr surface migration

| Field | Value |
|-------|-------|
| Start state | Slice 1 is landed; shared reader can read canonical and legacy state, but existing hooks and UI consumers are not migrated. |
| End state | Claude hook shim writes canonical state while preserving legacy files, and sidebar/dashboard live state uses the shared reader with visible behavior parity. |
| Dependencies | Slice 1. |
| Exact task IDs | 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4 |
| Expected file surfaces | `src/runtime_observability/adapters/{__init__.py,claude_code.py}`, `src/claude_subagent_hook.py`, optional `src/claude_profile_hook.py`, `src/herdr_agent_tree.py`, `src/claude_team_tree.py`, `tests/test_runtime_observability_claude_adapter.py`, `tests/test_hook_dashboard.py`, optional `tests/test_runtime_observability_sidebar.py`, optional `tests/test_runtime_observability_dashboard.py` |
| Focused verification | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_claude_adapter tests.test_hook_dashboard` plus optional focused sidebar/dashboard modules if created. |
| Full verification | `make test` |
| Rollback boundary | Revert Claude canonical adapter calls and restore `src/herdr_agent_tree.py` / `src/claude_team_tree.py` legacy live-child reads; `runtime-observability.json` can be ignored. |
| Estimated changed lines | 330–400 |

Dependency diagram:

```text
Slice 1 canonical core/reader
   ↓
📍 Slice 2 Claude + Herdr consumers
   ↓
Slice 3 Codex + Pi collectors
   ↓
Slice 4 installer/docs/e2e
```

### Slice 3 — Limited Codex adapter and Pi companion collector

| Field | Value |
|-------|-------|
| Start state | Slice 2 is landed; canonical reads/writes and Herdr consumers work for Claude-compatible evidence. |
| End state | Codex hook-compatible evidence and synthetic Pi companion events normalize into canonical state without overclaiming unsupported capabilities or nested internals. |
| Dependencies | Slices 1–2. |
| Exact task IDs | 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4 |
| Expected file surfaces | `src/runtime_observability/adapters/codex.py`, `src/runtime_observability/adapters/pi_companion.py`, optional `src/runtime_observability_cli.py`, `pi/herdr-agent-observability/index.ts`, `tests/test_runtime_observability_codex_adapter.py`, `tests/test_runtime_observability_pi_companion.py`, optional `tests/test_runtime_observability_cli.py` |
| Focused verification | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_codex_adapter tests.test_runtime_observability_pi_companion` plus optional CLI tests if created. |
| Full verification | `make test` |
| Rollback boundary | Remove Codex/Pi adapters, optional ingestion CLI, Pi extension file, and their tests; Claude and Herdr consumer migration remains intact. |
| Estimated changed lines | 240–360 |

Dependency diagram:

```text
Slice 1 canonical core/reader
   ↓
Slice 2 Claude + Herdr consumers
   ↓
📍 Slice 3 Codex + Pi collectors
   ↓
Slice 4 installer/docs/e2e
```

### Slice 4 — Installer/docs integration and end-to-end preservation

| Field | Value |
|-------|-------|
| Start state | Slices 1–3 are landed; runtime observability works through core, consumers, and runtime collectors, but install/docs/e2e preservation is not complete. |
| End state | Installer and docs describe explicit Pi companion integration, existing Claude/Codex wiring remains reversible, and end-to-end preservation is verified across runtimes and legacy/canonical state. |
| Dependencies | Slices 1–3. |
| Exact task IDs | 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4 |
| Expected file surfaces | `install.py`, `README.md` or relevant install docs, optional Pi extension install docs, `tests/test_install.py`, `tests/test_runtime_observability_integration.py`, focused docs assertion if present |
| Focused verification | `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_install tests.test_runtime_observability_integration` and any focused docs assertion command if added. |
| Full verification | `env -u HERDR_WORKSPACE_ID python3 -m unittest discover -s tests -t tests`, `make test`, and safe-fixture `make check` when installer/docs change. |
| Rollback boundary | Revert installer/docs/e2e additions; core runtime observability and migrated readers remain reviewable from prior slices. |
| Estimated changed lines | 180–300 |

Dependency diagram:

```text
Slice 1 canonical core/reader
   ↓
Slice 2 Claude + Herdr consumers
   ↓
Slice 3 Codex + Pi collectors
   ↓
📍 Slice 4 installer/docs/e2e
```

## Work Units

### 1. Canonical model and namespaced identities

- [x] 1.1 RED: Add focused failing tests in `tests/test_runtime_observability_model.py` for `src/runtime_observability/model.py` and `src/runtime_observability/ids.py`: allowed runtimes `claude`/`codex`/`pi`, unpadded reversible base64url session/activity ids, cross-runtime raw id collision separation, bounded status normalization to `unknown`, and capability declarations that distinguish complete/partial/unsupported/unavailable/legacy-only/unknown. Evidence: `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model` fails only for missing canonical model behavior. <!-- sdd-owner: implementation -->
- [x] 1.2 GREEN: Implement `src/runtime_observability/__init__.py`, `src/runtime_observability/model.py`, and `src/runtime_observability/ids.py` with schema constants, dataclasses or typed dict helpers, runtime/status/presence/freshness/capability vocabularies, reversible identity helpers, status normalization, and no Herdr command or adapter payload dependencies. Evidence: focused model test command passes. <!-- sdd-owner: implementation -->
- [x] 1.3 TRIANGULATE: Extend `tests/test_runtime_observability_model.py` with malformed/missing raw ids, unicode ids, empty status payloads, and same raw activity id under different sessions. Evidence: focused model test command first fails on at least one edge, then passes after tightening implementation. <!-- sdd-owner: implementation -->
- [x] 1.4 REFACTOR: Simplify model/identity APIs without changing behavior, keep privacy-sensitive fields out of canonical records, and run `make test`. Evidence: focused model tests and `make test` pass; rollback boundary is `src/runtime_observability/{__init__.py,model.py,ids.py}` plus `tests/test_runtime_observability_model.py`. <!-- sdd-owner: implementation -->

### 2. Canonical snapshot paths and store

- [x] 2.1 RED: Add failing store tests in `tests/test_runtime_observability_store.py` for `src/runtime_observability/paths.py` and `src/runtime_observability/store.py`: state root remains `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree`, canonical file is `runtime-observability.json`, writes use valid snapshot schema, malformed canonical JSON is unavailable-safe, and scoped updates do not overwrite other runtime/session records. Evidence: `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_store` fails only for missing store behavior. <!-- sdd-owner: implementation -->
- [x] 2.2 GREEN: Implement `src/runtime_observability/paths.py` and `src/runtime_observability/store.py` with best-effort `0700` state root creation, `.runtime-observability.lock` exclusive update locking, atomic temp-file/fsync/replace writes, safe read errors, and scoped session/activity merge rules. Evidence: focused store test command passes. <!-- sdd-owner: implementation -->
- [x] 2.3 TRIANGULATE: Add tests for invalid schema version, partial files, duplicate raw ids across runtimes, and activity updates that must not delete sibling activities or sessions. Evidence: focused store test command first exposes a gap, then passes. <!-- sdd-owner: implementation -->
- [x] 2.4 REFACTOR: Consolidate serialization/validation helpers in `src/runtime_observability/store.py` without introducing a daemon, SQLite, append-only event log, or generated artifacts. Evidence: `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_model tests.test_runtime_observability_store` and `make test` pass; rollback boundary is `src/runtime_observability/{paths.py,store.py}` plus store tests. <!-- sdd-owner: implementation -->

### 3. Shared reader and legacy compatibility

- [x] 3.1 RED: Add failing reader tests in `tests/test_runtime_observability_reader.py` and legacy compatibility tests in `tests/test_runtime_observability_legacy.py` for `src/runtime_observability/reader.py` and `src/runtime_observability/legacy.py`: Herdr-native `subagents`/`children` precedence, fresh canonical-over-legacy precedence, existing `subagents.json` fallback, cross-runtime legacy collision guard, missing `agent_session` no guessing, no recognized leader no-agent behavior, malformed source isolation, stale `working` becomes `unknown`, explicit `ended` stays terminal, ended parent maps working child to `interrupted`, and verified zero-active only when activity capability is complete and fresh. Evidence: focused reader/legacy command fails only for absent shared reader behavior. <!-- sdd-owner: implementation -->
- [x] 3.2 GREEN: Implement `src/runtime_observability/legacy.py` and `src/runtime_observability/reader.py` so visible leaders are supplied only by Herdr snapshot metadata, workspace scoping remains Herdr-owned, canonical sessions join by `(runtime, raw agent_session)`, legacy `subagents.json` remains readable from the existing state root, and unknown-safe empty state never fabricates idle/done/zero-active. Evidence: focused reader/legacy tests pass. <!-- sdd-owner: implementation -->
- [x] 3.3 TRIANGULATE: Extend reader tests with simultaneous Claude/Codex/Pi leaders, same raw session id across runtimes, stale canonical plus valid legacy fallback decisions, absent state root, and malformed legacy `subagents.json` while canonical state is valid. Evidence: focused reader/legacy command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [x] 3.4 REFACTOR: Keep all raw hook parsing out of `src/runtime_observability/reader.py`, keep visual formatting out of the reader, and document reader precedence in short module docstrings only. Evidence: focused model/store/reader tests and `make test` pass; rollback boundary is `src/runtime_observability/{legacy.py,reader.py}` plus associated tests. <!-- sdd-owner: implementation -->

### 4. Claude compatibility adapter and installed hook shim

- [x] 4.1 RED: Add failing tests in `tests/test_runtime_observability_claude_adapter.py` and narrowly update existing hook tests for `src/runtime_observability/adapters/claude_code.py`, `src/claude_subagent_hook.py`, and optionally `src/claude_profile_hook.py`: `SubagentStart` writes canonical session/activity working state while preserving legacy `subagents.json`, `SubagentStop` removes live canonical activity while preserving existing history behavior, `SessionStart`/`SessionEnd` may write presence/ended only, and transcript paths/prompts/token tallies/artifacts/profile names do not enter canonical state. Evidence: focused adapter/hook command fails only for missing Claude canonical ingestion. <!-- sdd-owner: implementation -->
- [x] 4.2 GREEN: Implement `src/runtime_observability/adapters/__init__.py` and `src/runtime_observability/adapters/claude_code.py`, then call the adapter from the compatibility entrypoint `src/claude_subagent_hook.py` without renaming installed hook paths or changing legacy files; if session start/end is included, wire only minimal canonical presence/ended fields in `src/claude_profile_hook.py`. Evidence: focused Claude adapter/hook tests pass. <!-- sdd-owner: implementation -->
- [x] 4.3 TRIANGULATE: Add tests for malformed Claude hook payloads, unsupported statuses, simultaneous child ids in different sessions, parent end while child is working, and adapter rollback where `runtime-observability.json` can be ignored while legacy reads still work. Evidence: focused adapter/hook command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [x] 4.4 REFACTOR: Keep transcript analytics, history, artifacts, profile resume, and Claude-specific privacy-sensitive fields in existing Claude modules only; avoid moving those concerns into `model.py`, `store.py`, or `reader.py`. Evidence: focused Claude tests and `make test` pass; rollback boundary is `src/runtime_observability/adapters/{__init__.py,claude_code.py}`, `src/claude_subagent_hook.py`, optional `src/claude_profile_hook.py`, and their tests. <!-- sdd-owner: implementation -->

### 5. Herdr sidebar consumer migration

- [x] 5.1 RED: Update or add failing sidebar tests in `tests/test_hook_dashboard.py` or a focused `tests/test_runtime_observability_sidebar.py` for `src/herdr_agent_tree.py`: sidebar metadata uses the shared reader, preserves existing token slot output for fresh legacy/canonical Claude and Codex state, prefers Herdr-native children, displays Pi recognized leaders only when Herdr-visible, preserves no-agent/unrecognized behavior, and does not parse raw `subagents.json` directly. Evidence: focused sidebar test command fails only for old duplicate reader ownership. <!-- sdd-owner: implementation -->
- [x] 5.2 GREEN: Modify `src/herdr_agent_tree.py` to replace duplicate `hook_children()` raw parsing with `src/runtime_observability/reader.py` while preserving Herdr snapshot reading, pane metadata publishing, slot counts, spinner behavior, visible leader discovery, workspace scoping, and no terminal pane reads. Evidence: focused sidebar tests pass. <!-- sdd-owner: implementation -->
- [x] 5.3 TRIANGULATE: Add sidebar tests for missing `agent_session`, same raw session across Claude/Codex with legacy-only state, stale canonical state, malformed canonical file plus valid legacy state, and unknown activity not reported as verified zero active. Evidence: focused sidebar command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [x] 5.4 REFACTOR: Remove or shrink obsolete raw child parsing helpers from `src/herdr_agent_tree.py` without changing the external Herdr command contract. Evidence: focused sidebar tests and `make test` pass; rollback boundary is `src/herdr_agent_tree.py` plus sidebar tests. <!-- sdd-owner: implementation -->

### 6. Herdr dashboard consumer migration

- [x] 6.1 RED: Update or add failing dashboard tests in `tests/test_hook_dashboard.py` or `tests/test_runtime_observability_dashboard.py` for `src/claude_team_tree.py`: dashboard live children use the shared reader, current live tree output remains equivalent for existing Claude/Codex legacy state, history/artifacts/config/profile-resume sections remain unchanged, Herdr workspace scoping and recognized leader behavior remain authoritative, and raw Codex/Pi/Claude payload parsing is absent from rendering. Evidence: focused dashboard test command fails only for old duplicate reader ownership. <!-- sdd-owner: implementation -->
- [x] 6.2 GREEN: Modify `src/claude_team_tree.py` to consume normalized reader results for live runtime/session/activity state while preserving dashboard visual layout, history reads, artifact reads, config menu, click mapping, footer summary, Herdr leader detection, and no terminal pane reads. Evidence: focused dashboard tests pass. <!-- sdd-owner: implementation -->
- [x] 6.3 TRIANGULATE: Add dashboard tests for explicit ended session root behavior, ended parent interrupting still-working child display, missing state root, malformed canonical file, unknown activity versus verified zero, and no session guessing from cwd or most recent runtime record. Evidence: focused dashboard command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [x] 6.4 REFACTOR: Remove obsolete live-child raw parsing from `src/claude_team_tree.py` only after tests prove behavior parity; do not rename the dashboard module or redesign UI in this slice. Evidence: focused dashboard tests and `make test` pass; rollback boundary is `src/claude_team_tree.py` plus dashboard tests. <!-- sdd-owner: implementation -->

### 7. Codex limited adapter

- [x] 7.1 RED: Add failing tests in `tests/test_runtime_observability_codex_adapter.py` for `src/runtime_observability/adapters/codex.py`: accepts only repository-verified Claude-shaped local hook payloads, requires usable `session_id` for supported presence, maps activity as partial, marks completion unsupported, marks artifacts unsupported, keeps history legacy-only, and never claims `ended`, complete activity inventory, profile support, native transcript support, or artifact support from unverified Codex data. Evidence: focused Codex adapter command fails only for missing limited adapter behavior. <!-- sdd-owner: implementation -->
- [x] 7.2 GREEN: Implement `src/runtime_observability/adapters/codex.py` as a thin normalizer over the existing hook-compatible payload shape and canonical store update helpers, with unsupported/unavailable capabilities explicit and no Codex-native schema assumptions. Evidence: focused Codex adapter tests pass. <!-- sdd-owner: implementation -->
- [ ] 7.3 TRIANGULATE: Add tests for malformed hook-compatible payloads, raw id collisions with Claude, absent completion fields, unknown Codex-native-looking payloads, and stale partial activity. Evidence: focused Codex adapter command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [ ] 7.4 REFACTOR: Keep Codex parsing isolated to `src/runtime_observability/adapters/codex.py` and avoid touching installer behavior in this work unit. Evidence: focused Codex tests and `make test` pass; rollback boundary is Codex adapter file plus Codex adapter tests. <!-- sdd-owner: implementation -->

### 8. Pi companion collector and ingestion boundary

- [ ] 8.1 RED: Add failing tests in `tests/test_runtime_observability_pi_companion.py` and, if using a CLI, `tests/test_runtime_observability_cli.py` for `src/runtime_observability/adapters/pi_companion.py`, optional `src/runtime_observability_cli.py`, and `pi/herdr-agent-observability/index.ts`: synthetic `session_start`, `agent_start`, `agent_end`, `agent_settled`, `tool_execution_start/update/end`, `model_select`, `ui_prompt_start/end`, and `session_shutdown` events map to top-level Pi session/activity state without reading terminal panes or claiming nested AskClaude internals. Evidence: focused Pi companion command fails only for missing Pi event normalization/ingestion. <!-- sdd-owner: implementation -->
- [ ] 8.2 GREEN: Implement `src/runtime_observability/adapters/pi_companion.py` and the smallest ingestion boundary needed by the Pi extension, preferring a Python ingestion CLI if TypeScript cannot safely own canonical merge semantics; add `pi/herdr-agent-observability/index.ts` only as a companion collector that emits verified top-level events to the canonical store. Evidence: focused Pi companion tests pass without requiring a real Pi process. <!-- sdd-owner: implementation -->
- [ ] 8.3 TRIANGULATE: Add tests for missing `ctx.sessionManager` values, unavailable child activity source, tool error mapping to `blocked`, normal tool end mapping to `done`, shutdown mapping to `ended`, nested AskClaude represented only as a top-level tool call, and model/provider metadata staying adapter-local/source-only. Evidence: focused Pi companion command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [ ] 8.4 REFACTOR: Keep Pi as a companion collector, not a product boundary replacement; do not move Herdr manifest, panes, sidebar tokens, dashboard rendering, or user actions into Pi. Evidence: focused Pi tests and `make test` pass; rollback boundary is `src/runtime_observability/adapters/pi_companion.py`, optional ingestion CLI, `pi/herdr-agent-observability/index.ts`, and tests. <!-- sdd-owner: implementation -->

### 9. Installer integration and documentation

- [ ] 9.1 RED: Add failing installer/docs tests in `tests/test_install.py` and a focused docs assertion if the repo has one: `install.py` keeps existing Claude/Codex hook commands idempotent and reversible, does not create unverified Pi runtime config files silently, wires or documents Pi companion collector only through explicit verified extension placement, preserves plugin id `local.claude-vezmex-team-tree`, and preserves the state root. Evidence: focused installer command fails only for missing integration/documentation behavior. <!-- sdd-owner: implementation -->
- [ ] 9.2 GREEN: Update `install.py` only as needed for explicit Pi companion placement/check output and canonical collector command paths; update `README.md` or the repository’s relevant install docs to describe the canonical runtime-observability state, supported first-slice runtime capabilities, Pi companion limitations, rollback, and non-goals without changing product branding or visual design. Evidence: focused installer/docs tests pass. <!-- sdd-owner: implementation -->
- [ ] 9.3 TRIANGULATE: Add tests or documented verification for `make check`, `make install`, and `make uninstall` behavior in temporary HOME/config fixtures: no foreign hooks removed, backup-once behavior preserved, Codex wiring remains only for existing `.codex/hooks.json`, and Pi wiring remains explicit rather than silently creating runtime config. Evidence: installer command first fails on an edge, then passes. <!-- sdd-owner: implementation -->
- [ ] 9.4 REFACTOR: Keep docs reviewable and scoped to runtime observability; explicitly list first-slice non-goals for dashboard/sidebar redesign, history/artifacts/profile-resume redesign, transcript analytics generalization, API-key polling, terminal reads, plugin id rename, and moving ownership out of Herdr. Evidence: `make test` passes; rollback boundary is `install.py`, `README.md` or relevant docs, optional Pi extension install docs, and installer tests. <!-- sdd-owner: implementation -->

### 10. End-to-end preservation and final verification

- [ ] 10.1 RED: Add one end-to-end behavior test in `tests/test_runtime_observability_integration.py` covering a Herdr snapshot with visible Claude, Codex, and Pi leaders, canonical plus legacy state, stale records, malformed optional source, and unrecognized/no-agent panes; assert no runtime-only record creates a visible leader and no cwd/session guessing occurs. Evidence: focused integration command fails only for missing cross-surface preservation. <!-- sdd-owner: implementation -->
- [ ] 10.2 GREEN: Fix only integration seams needed for all prior work units to compose; do not add new features outside the proposal/spec/design. Evidence: `env -u HERDR_WORKSPACE_ID python3 -m unittest tests.test_runtime_observability_integration` passes. <!-- sdd-owner: implementation -->
- [ ] 10.3 TRIANGULATE: Run and record focused commands for each work-unit test module plus `env -u HERDR_WORKSPACE_ID python3 -m unittest discover -s tests -t tests`, `make test`, and if installer docs changed, `make check` in a fixture or documented safe environment. Evidence: exact commands and results are captured in apply notes. <!-- sdd-owner: implementation -->
- [ ] 10.4 REFACTOR: Review the final diff by proposed review slice, keep code/tests/docs together per work unit, remove accidental UI redesign/history/artifact/profile/API polling changes, and confirm changed-line count before PR planning. Evidence: diff stat, focused tests, full tests, runtime-harness `N/A` or Pi synthetic event scenario result, and rollback boundaries for each slice are recorded. <!-- sdd-owner: implementation -->
