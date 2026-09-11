# Exploration — Runtime-agnostic agent observability

## Outcome

Repository evidence supports a first proposal that keeps Herdr as the product/UI/action/state boundary while introducing a runtime-agnostic agent observability model behind the existing sidebar and dashboard behavior. The first slice should normalize local runtime events for Claude Code, Codex, and Pi into the same Herdr-owned presence/status/activity state, without redesigning history, artifacts, profile resume, or dashboard presentation yet.

## Context

- Change: `runtime-agnostic-agent-observability`
- Product: Herdr Agents Tree plugin
- Artifact store: OpenSpec
- Research: unselected; repository evidence is sufficient for this exploration
- Authoritative context: `openspec/config.yaml`, `openspec/project-context.md`

## Current behavior

| Area | Current behavior | Evidence |
| --- | --- | --- |
| Product boundary | The plugin is a Herdr plugin with manifest-defined startup events, pane, and actions. | `herdr-plugin.toml` |
| Sidebar tokens | `src/herdr_agent_tree.py` reads `herdr api snapshot`, detects visible panes, and publishes fixed metadata token slots through `herdr pane report-metadata`. | `src/herdr_agent_tree.py` |
| Dashboard pane | `src/claude_team_tree.py` renders the dashboard pane from Herdr snapshot state plus plugin state files. | `src/claude_team_tree.py` |
| Leader detection | The dashboard recognizes Herdr leader panes whose `agent` is `claude`, `codex`, or `pi`, scoped to the active/focused workspace. | `src/claude_team_tree.py`, `RECOGNIZED_AGENTS = {"claude", "codex", "pi"}` |
| Agent-session join | Both sidebar and dashboard join child state to a leader via Herdr `agent_session.value` or string `agent_session`. | `src/herdr_agent_tree.py`, `src/claude_team_tree.py` |
| Terminal safety | The plugin does not read terminal panes and intentionally renders idle/no-agent when no recognized Herdr leader exists. | `src/herdr_agent_tree.py`, `src/claude_team_tree.py`, `tests/test_hook_dashboard.py` |
| Runtime state | Local state is stored under `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree`. | `src/*`, `openspec/config.yaml` |
| Live children | Live subagents are read from `subagents.json`, session-keyed by parent session id. | `src/claude_subagent_hook.py`, `src/herdr_agent_tree.py`, `src/claude_team_tree.py` |
| Session history | Completed subagents are appended to `history.jsonl` with transcript-derived task, token, tool, and nested-agent details. | `src/claude_subagent_hook.py` |
| Artifacts | Claude Artifact `PostToolUse` publishes/updates are appended to `artifacts.jsonl`. | `src/claude_artifact_hook.py` |
| Session lifecycle | Claude `SessionStart`/`SessionEnd` records profile/session start and end data in `profiles.json`. | `src/claude_profile_hook.py`, `src/install_profile_resume.py` |
| Installation | `install.py` links the Herdr plugin and wires hook scripts into existing Claude profile settings plus existing Codex hooks settings. | `install.py`, `tests/test_install.py` |

## Concrete Claude coupling

| Coupling | Why it matters | Evidence |
| --- | --- | --- |
| Plugin id and state namespace are Claude-branded. | Renaming or migration requires care because installed hooks, Herdr plugin ids, and persisted state paths are user-visible compatibility surfaces. | `PLUGIN_ID = "local.claude-vezmex-team-tree"`, `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree`, `herdr-plugin.toml` |
| Hook modules are Claude-named. | Runtime collector concepts are currently encoded in filenames and installer wiring. | `src/claude_subagent_hook.py`, `src/claude_artifact_hook.py`, `src/claude_profile_hook.py` |
| Subagent payload assumptions are Claude Code hook schema assumptions. | Codex currently reuses the shape; Pi is not yet wired, and each runtime may need adapter-specific parsing. | `src/claude_subagent_hook.py` docstring and `agent_id`/`agent_type`/`agent_transcript_path` parsing |
| Transcript analysis assumes Claude transcript records. | Tokens, tool uses, nested `Task` tool detection, and task extraction are not a canonical runtime model. | `analyze_transcript()` in `src/claude_subagent_hook.py` |
| Artifact collection is Claude Artifact-specific. | Artifact lineage should remain out of the first slice because it depends on Claude-specific `PostToolUse` and `tool_name == "Artifact"`. | `src/claude_artifact_hook.py` |
| Profile resume is Claude executable/profile-specific. | Runtime-agnostic presence should not depend on Claude profile wrappers or `CLAUDE_CONFIG_DIR`. | `src/claude_profile_hook.py`, `src/claude_profile_resume.py`, `src/install_profile_resume.py` |
| Manifest UI text still says Claude. | Existing UI should be preserved initially, but proposal should plan later naming cleanup separately. | `herdr-plugin.toml` pane/action titles |
| Dashboard module name is Claude-specific. | Rendering is partly runtime-agnostic in behavior but not in module boundaries. | `src/claude_team_tree.py` |
| Hook child readers are duplicated. | Sidebar and dashboard both read `subagents.json` directly and normalize into similar child structures. | `hook_children()` in `src/herdr_agent_tree.py` and `src/claude_team_tree.py` |
| Herdr calls are embedded in render/publisher scripts. | A cleaner architecture needs a Herdr boundary module so runtime collectors do not scatter Herdr command details. | `read_snapshot()`, `run_herdr()`, and `report_slots()` in `src/herdr_agent_tree.py`; `read_snapshot()` in `src/claude_team_tree.py`; `src/open_dashboard.py` |

## Verified extension seams

| Seam | Current proof | Direction |
| --- | --- | --- |
| Herdr leader snapshot | Herdr already provides visible agents, workspace ids, pane ids, agent status, display names, and `agent_session`. | Keep Herdr snapshot as the leader/pane authority. |
| Session id join | Existing state is already keyed by runtime session id and joined through Herdr-visible session ids. | Make the canonical runtime model session-keyed first. |
| Sidebar native children preference | `src/herdr_agent_tree.py` already prefers future Herdr-native `subagents` or `children` fields before hook-derived state. | Preserve this as the highest-priority data source. |
| Hook-derived children | Hook state is already treated as provider-agnostic in the sidebar docstring and can feed any recognized runtime if normalized. | Move file parsing/normalization behind runtime collectors. |
| Installer discovery | `install.py` already scans existing Claude profile settings and Codex hooks settings without creating unused profiles. | Add Pi discovery only if there is a verified local subscription or hook seam. |
| Atomic state writes | Hook writers use locks and atomic replacements/appends for shared files. | Keep the concurrency discipline for any new canonical runtime state writer. |
| Tests isolate state | Tests use temporary `XDG_STATE_HOME` and verify no cwd/session guessing. | Add adapter/model tests without touching real Herdr state. |

## Runtime capability differences observed from repository evidence

| Runtime | Current status in this repository | Implication |
| --- | --- | --- |
| Claude Code | Fullest integration: subagent hooks, Artifact hook, profile session lifecycle, and profile resume support. | Claude adapter can seed the canonical model, but should not define every runtime field. |
| Codex | Installer wires the same hook scripts into `.codex/hooks.json` if it exists; code comments say Codex reuses the same hook shape. | Codex support is opportunistic and schema-compatible today, not independently modeled. |
| Pi | Dashboard recognizes Pi leader panes, and tests verify Pi can render as a leader. Pi hooks are explicitly not wired yet. | First slice must define how Pi presence/status/activity is observed locally before adding richer history. |

## Unknowns to resolve in proposal/design

1. Which local Pi event/subscription surface can reliably report agent presence, status, session id, and child activity without reading terminal panes.
2. Whether Codex hook payloads always match the Claude-shaped `session_id`/`agent_id`/`agent_type` lifecycle contract or only do so for currently observed cases.
3. Whether Herdr snapshots can expose native children soon enough to reduce plugin-owned child collection work.
4. Whether the existing plugin id and state directory should remain permanently for compatibility or gain a migration alias/new namespace later.
5. The minimal canonical status vocabulary needed for Pi, Codex, and Claude Code without losing existing `working`, `idle`, `done`, `blocked`, `ended`, and `interrupted` behavior.
6. How runtime heartbeat/staleness should be represented for local subscription-backed runtimes that do not emit explicit `SessionEnd` events.
7. Whether artifacts and transcript-derived history should be runtime-specific optional capabilities or later canonical event types.

## First-slice boundaries

The first slice should include:

- A canonical runtime observability model for leader presence, session identity, status, child activity, timestamps, and source runtime.
- Runtime-specific collectors/adapters for Claude Code, Codex, and Pi that write or feed that model.
- A shared state reader used by both sidebar and dashboard instead of duplicated `hook_children()` logic.
- Preservation of existing Herdr snapshot authority for visible panes, workspace scoping, pane ids, metadata publishing, dashboard opening, and dashboard actions.
- Compatibility with current Claude/Codex hook state during migration.
- Tests proving recognized leaders render from canonical runtime state and unrecognized/no-agent panes do not borrow cwd-matched state.

The first slice should not include:

- Dashboard visual redesign.
- Artifact lineage redesign.
- Transcript analytics generalization beyond what existing Claude behavior already needs.
- Profile-aware Claude resume redesign.
- API-key-backed polling architecture.
- Reading terminal pane contents.
- Replacing Herdr with a Pi plugin or moving manifest/UI/action ownership out of Herdr.

## Recommended proposal direction

Propose a Herdr-owned observability boundary with three layers:

1. **Herdr product boundary**: manifest, actions, pane opening/resizing, sidebar metadata tokens, dashboard rendering, workspace scoping, and leader-pane discovery remain Herdr-facing.
2. **Canonical runtime state**: introduce a small internal model such as `RuntimeSession`, `RuntimeAgentActivity`, and `RuntimeStatus` stored under the existing plugin state root with compatibility reads from current files.
3. **Runtime collectors/adapters**: implement thin local adapters for Claude Code, Codex, and Pi that subscribe to or receive local lifecycle events and normalize them into the canonical model.

Proposal acceptance should prioritize preserving visible behavior while making the source of children/status/activity runtime-neutral. The safest migration path is additive: keep current files readable, introduce shared canonical readers/writers, redirect the sidebar/dashboard to the shared reader, then add runtime adapters one at a time.

## Evidence checklist

- [x] Herdr remains the manifest/UI/action/state boundary.
- [x] Current dashboard recognizes Claude, Codex, and Pi leader panes.
- [x] Current hook collection is Claude-shaped and Claude-named.
- [x] Codex is wired only when an existing `.codex/hooks.json` exists.
- [x] Pi is recognized for rendering but has no wired hook collector in current code.
- [x] Sidebar already has a future Herdr-native child seam.
- [x] No-agent/unrecognized-agent behavior intentionally avoids cwd guessing.
- [x] History and artifacts are downstream of current Claude-shaped collection and should follow after the canonical runtime model.
