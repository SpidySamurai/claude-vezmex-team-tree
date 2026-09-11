# Proposal — Runtime-agnostic agent observability

## Intent

Make the Herdr Agents Tree plugin observe local Pi, Codex, and Claude Code runtimes through a canonical runtime presence/session/status/activity model, while preserving Herdr as the product, UI, action, and state boundary.

Today the plugin already renders Herdr-visible leaders for `claude`, `codex`, and `pi`, but its local collection and state files are still Claude-shaped and Claude-named. This change introduces a runtime-neutral observability boundary behind the existing sidebar and dashboard so future runtime support does not require duplicating UI readers or reading terminal panes.

## Scope

### In scope

- Define a canonical runtime observability model for:
  - runtime identity (`claude`, `codex`, `pi`),
  - leader/session identity,
  - presence,
  - status,
  - child/subagent activity,
  - timestamps and staleness/source metadata.
- Add runtime-specific local collectors/adapters for Claude Code, Codex, and Pi.
- Keep Herdr snapshot/session metadata as the authority for visible panes, workspace scoping, pane ids, and leader discovery.
- Add one shared state reader used by both:
  - `src/herdr_agent_tree.py` sidebar metadata publisher,
  - `src/claude_team_tree.py` dashboard renderer.
- Preserve compatibility with the existing plugin id and state path:
  - plugin id: `local.claude-vezmex-team-tree`,
  - state root: `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree`.
- Keep current Claude/Codex hook state readable during migration.
- Preserve current visible sidebar and dashboard behavior initially.
- Add tests for canonical state reads, runtime adapters, Herdr-session joins, no-agent behavior, and compatibility reads.

### Out of scope

- Dashboard visual redesign.
- Sidebar visual redesign.
- History, artifact lineage, or profile-resume redesign.
- Generalizing Claude transcript analytics beyond current behavior.
- API-key polling architecture.
- Reading terminal pane contents.
- Moving product/UI/action ownership out of Herdr.
- Renaming the installed plugin id or breaking the existing state namespace in this slice.

## Affected areas

| Area | Expected change |
| --- | --- |
| `src/herdr_agent_tree.py` | Stop owning duplicate hook-child parsing; read normalized runtime state through a shared reader while preserving metadata slot output. |
| `src/claude_team_tree.py` | Stop owning duplicate hook-child parsing; render from shared normalized runtime state while preserving current dashboard output. |
| `src/claude_subagent_hook.py` | Remain compatible as a Claude Code collector/source; may feed canonical state or continue writing legacy state that the shared reader understands during migration. |
| `install.py` | Keep reversible Claude/Codex hook wiring and add Pi wiring only through verified local subscription/hook evidence. |
| State files | Add canonical runtime state under the existing state root and continue reading legacy `subagents.json`, `history.jsonl`, `artifacts.jsonl`, `profiles.json`, and `config.json` where relevant. |
| Tests | Extend isolated `XDG_STATE_HOME` tests for canonical model, compatibility migration, runtime-specific adapters, and no cwd/session guessing. |

## Proposed architecture

Use three boundaries:

1. **Herdr product boundary**
   - Owns manifest, sidebar metadata tokens, dashboard pane rendering, pane opening/resizing, user actions, workspace scoping, and visible leader discovery.
   - Continues to use Herdr snapshot/session metadata as the visible-pane authority.

2. **Canonical runtime state**
   - Introduces a small internal model for runtime sessions and child activity.
   - Is keyed by runtime/session identity rather than by Claude-specific assumptions.
   - Represents provider/model identity as optional metadata, not as the core abstraction.
   - Supports additive migration by reading both canonical state and existing legacy files.

3. **Runtime collectors/adapters**
   - Normalize local Claude Code, Codex, and Pi evidence into the canonical model.
   - Prefer local subscription-backed runtime evidence.
   - Do not read terminal panes.
   - Keep runtime-specific schema parsing out of Herdr UI rendering code.

## Migration plan

1. Add the canonical model and shared reader under the existing state root.
2. Make the shared reader understand current legacy state files so existing installs continue to render.
3. Redirect sidebar and dashboard readers to the shared reader without changing visible output.
4. Add or adapt runtime collectors one runtime at a time:
   - Claude Code first, using current hook evidence as the compatibility seed.
   - Codex next, validating whether current hook payload shape is stable or only opportunistically Claude-compatible.
   - Pi once the local subscription/hook seam for presence/session/status/activity is verified.
5. Keep the existing plugin id and state path readable throughout the first slice.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Existing users lose visible sidebar/dashboard state after migration. | Make the migration additive and keep legacy files readable before changing UI readers. |
| Runtime-specific details leak into Herdr UI modules. | Keep adapters responsible for schema parsing and expose only canonical state to UI readers. |
| Pi local observability seam is less complete than Claude/Codex hooks. | Treat heartbeat/staleness/source metadata as first-class model fields and avoid overclaiming rich history in this slice. |
| Codex hook payload shape differs from the current Claude-shaped assumptions. | Validate with adapter tests and keep runtime-specific parsing isolated. |
| Status vocabulary becomes too broad or incompatible with existing UI labels. | Start from current behavior (`working`, `idle`, `done`, `blocked`, `ended`, `interrupted`) and map runtime-specific states into that vocabulary. |
| Migration accidentally changes Herdr workspace scoping or no-agent behavior. | Add tests proving unrecognized/no-agent panes do not borrow cwd-matched or unrelated session state. |

## Rollback

Rollback should be safe because the first slice is additive:

- Revert sidebar/dashboard usage of the shared reader to their current legacy readers.
- Leave the existing plugin id and state root untouched.
- Ignore newly written canonical runtime state files if necessary.
- Keep legacy `subagents.json`-based rendering available until canonical readers are proven stable.

## Success criteria

- Sidebar and dashboard still behave visibly the same for existing Claude/Codex-backed state.
- The plugin observes recognized Herdr leaders for Claude Code, Codex, and Pi without reading terminal panes.
- Sidebar and dashboard both use one shared normalized state reader.
- Existing plugin id and state path remain readable.
- Runtime collectors/adapters keep runtime-specific schema parsing outside Herdr UI modules.
- Tests cover canonical reads, legacy compatibility, recognized leaders, unrecognized/no-agent behavior, and stale/ended runtime state mapping.
- History, artifacts, profile-resume behavior, API-key polling, and UI redesign remain unchanged in this slice.

## Evidence used

- `openspec/config.yaml`
- `openspec/project-context.md`
- `openspec/changes/runtime-agnostic-agent-observability/explore.md`
- Repository references validated for `herdr-plugin.toml`, `install.py`, `Makefile`, `src/*.py`, and `tests/*.py` paths named in exploration.
