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
