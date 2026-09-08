# Runtime Observability Specification

## Purpose

Define the first-slice runtime observability contract for the Herdr Agents Tree plugin so Claude Code, Codex, and Pi agent evidence is normalized behind Herdr-owned sidebar and dashboard behavior without reading terminal panes, guessing sessions, or breaking existing installs.

## Requirements

### Requirement: Herdr Authority Boundary

The system MUST keep Herdr snapshot/session metadata as the authority for visible panes, workspace scoping, pane identifiers, leader discovery, sidebar metadata publishing, dashboard rendering, pane opening, pane resizing, and user actions.

#### Scenario: Visible leader panes come from Herdr

- GIVEN Herdr snapshot metadata includes visible panes for `claude`, `codex`, and `pi`
- WHEN the plugin determines which leaders to display
- THEN it MUST use the Herdr-provided visible pane, workspace, pane id, agent name, and agent session metadata
- AND it MUST NOT promote any runtime-only record into a visible leader without a matching Herdr-visible leader pane.

#### Scenario: Workspace scoping remains Herdr-owned

- GIVEN runtime state exists for multiple workspaces or sessions
- WHEN Herdr indicates the active or focused workspace
- THEN the plugin MUST join and display only state eligible for Herdr-visible leaders in that workspace
- AND it MUST NOT use runtime state to override Herdr workspace authority.

### Requirement: Canonical Runtime Identity

The system MUST represent runtime observability using canonical namespaced identities for runtime, session, and agent activity across `claude`, `codex`, and `pi`.

#### Scenario: Runtime identity is explicit

- GIVEN normalized state is available for Claude Code, Codex, and Pi
- WHEN a reader inspects a runtime session or child activity
- THEN each record MUST include a canonical runtime identity of `claude`, `codex`, or `pi`
- AND records from different runtimes MUST remain distinguishable even when raw session or child identifiers collide.

#### Scenario: Session identity is namespaced

- GIVEN Claude Code and Codex both report a raw session identifier with the same string value
- WHEN the shared reader builds canonical session records
- THEN it MUST preserve separate canonical session identities for each runtime
- AND it MUST NOT merge state across runtimes solely because raw identifiers match.

#### Scenario: Agent activity identity is stable within a session

- GIVEN a runtime collector reports child or subagent activity for a leader session
- WHEN the activity is normalized
- THEN the activity MUST be keyed by runtime, session identity, and agent activity identity
- AND duplicate activity identifiers from another runtime or session MUST NOT overwrite it.

### Requirement: Minimal Canonical Runtime State Model

The system MUST expose a minimal canonical model containing presence, status, child or subagent activity, timestamps, source metadata, and optional capability metadata for each observed runtime session.

#### Scenario: Present session has minimal fields

- GIVEN local runtime evidence exists for a Herdr-visible leader session
- WHEN the shared reader returns normalized state
- THEN the session record MUST include presence, status, last observed timestamp, source metadata, runtime identity, and session identity
- AND any child activity records MUST include status, last observed timestamp, source metadata, and an activity identity.

#### Scenario: Absence is represented without fabrication

- GIVEN Herdr exposes a recognized leader with no matching local runtime state
- WHEN sidebar or dashboard state is read
- THEN the system MUST represent the leader as lacking supporting runtime evidence or as unknown according to the canonical model
- AND it MUST NOT fabricate child activity, completed work, token counts, zero counts, idle state, or done state.

### Requirement: Status Normalization

The system MUST normalize runtime-specific statuses into a bounded canonical status vocabulary while preserving uncertainty and preventing false zero, idle, or done claims.

#### Scenario: Known active states normalize safely

- GIVEN a runtime collector reports reliable evidence that a session or child activity is working, idle, blocked, done, ended, or interrupted
- WHEN the evidence is normalized
- THEN the canonical status SHOULD use the closest existing status label among `working`, `idle`, `blocked`, `done`, `ended`, and `interrupted`
- AND the source metadata MUST identify the evidence used for that mapping.

#### Scenario: Stale state is not reported as current

- GIVEN the most recent runtime evidence is older than the configured or model-defined freshness threshold
- WHEN the shared reader returns session or activity state
- THEN the system MUST mark the state as stale or unknown
- AND it MUST NOT claim the session is currently idle, done, or active solely because the last stale record had that value.

#### Scenario: Unsupported or malformed status becomes unknown

- GIVEN a runtime collector receives an unsupported, missing, or malformed status payload
- WHEN the payload is normalized
- THEN the canonical status MUST be `unknown` or equivalent uncertainty
- AND the system MUST NOT coerce the value into `idle`, `done`, or `0 active` unless reliable evidence supports that claim.

#### Scenario: No false zero active count

- GIVEN a recognized Herdr leader has no readable child activity evidence
- WHEN sidebar or dashboard output summarizes activity
- THEN the system MUST distinguish unknown activity from a verified zero-active state
- AND it MUST NOT report zero active children unless the source explicitly supports a complete child-activity view for that session.

### Requirement: Runtime Capability Declarations

The system MUST declare per-runtime evidence capabilities so unsupported presence, status, activity, timestamp, history, artifact, or completion evidence is represented explicitly rather than inferred.

#### Scenario: Pi lacks a child activity source

- GIVEN Pi presence evidence is available but no verified Pi child activity source is available
- WHEN Pi state is normalized
- THEN the Pi runtime capability declaration MUST identify child activity as unsupported or unavailable
- AND the UI readers MUST treat child activity as unknown rather than zero.

#### Scenario: Runtime supports only partial evidence

- GIVEN a runtime collector supports presence and timestamps but not completion events
- WHEN a session disappears or stops refreshing
- THEN the canonical state MUST use stale or unknown behavior according to the available capability
- AND it MUST NOT emit `done` or `ended` without supported completion evidence.

### Requirement: Shared State Reader for Herdr Surfaces

The system MUST use one shared normalized state reader for both the sidebar metadata publisher and the dashboard renderer.

#### Scenario: Sidebar and dashboard read the same canonical state

- GIVEN canonical runtime state and legacy-compatible state exist under the plugin state root
- WHEN `src/herdr_agent_tree.py` publishes sidebar metadata and `src/claude_team_tree.py` renders the dashboard
- THEN both surfaces MUST obtain runtime/session/activity data through the same shared reader contract
- AND neither surface SHOULD duplicate raw hook child parsing logic.

#### Scenario: Visible behavior remains consistent across surfaces

- GIVEN a Herdr-visible leader has matching child activity state
- WHEN sidebar and dashboard read the state
- THEN both surfaces MUST apply the same session join, runtime scoping, staleness, and compatibility rules
- AND differences in display format MUST NOT reflect different state interpretation.

### Requirement: Additive Legacy Compatibility

The system MUST preserve compatibility with the existing plugin id, existing state root, and current legacy files including `subagents.json` behavior during the first slice.

#### Scenario: Existing plugin id remains valid

- GIVEN an existing user has the plugin installed as `local.claude-vezmex-team-tree`
- WHEN the first-slice observability change is applied
- THEN the installed plugin id MUST remain usable
- AND users MUST NOT be required to reinstall under a renamed plugin id.

#### Scenario: Existing state path remains readable

- GIVEN legacy state exists under `$XDG_STATE_HOME/herdr/claude-vezmex-team-tree`
- WHEN the shared reader loads runtime state
- THEN it MUST read compatible legacy files from that state root
- AND it MAY also read additive canonical state under the same root.

#### Scenario: Legacy subagents remain visible

- GIVEN legacy `subagents.json` contains session-keyed child state in the current format
- WHEN a matching Herdr-visible leader session is displayed
- THEN the shared reader MUST preserve the current compatible child visibility behavior
- AND any canonical migration MUST be additive rather than destructive.

### Requirement: Runtime-Specific Collector Isolation

The system MUST isolate Claude Code, Codex, and Pi raw payload schemas inside runtime-specific collectors or adapters and expose only canonical state to Herdr UI readers.

#### Scenario: Claude-shaped hook payload stays in collector code

- GIVEN a Claude Code hook payload includes Claude-specific field names
- WHEN the plugin normalizes that payload
- THEN Claude-specific schema parsing MUST occur in the Claude collector or adapter
- AND sidebar and dashboard modules MUST consume only canonical runtime state.

#### Scenario: Codex and Pi payloads do not leak into rendering

- GIVEN Codex or Pi evidence uses a runtime-specific local payload format
- WHEN sidebar metadata or dashboard output is produced
- THEN Codex or Pi schema parsing MUST NOT be implemented in the Herdr rendering modules
- AND rendering MUST depend on canonical model fields only.

### Requirement: Terminal and Guessing Prohibition

The system MUST NOT read terminal pane contents and MUST NOT infer runtime session identity from cwd, pane title, process text, or unrelated runtime state.

#### Scenario: Terminal panes are never read

- GIVEN a Herdr-visible pane contains terminal text that mentions an agent or session
- WHEN the plugin builds sidebar or dashboard state
- THEN it MUST NOT read or parse terminal pane contents
- AND it MUST rely on Herdr snapshot/session metadata and local runtime collector state only.

#### Scenario: No cwd-based session borrowing

- GIVEN local runtime state exists for a cwd that matches an unrelated Herdr pane
- WHEN the pane has no recognized Herdr agent session match
- THEN the plugin MUST render no matching agent state or unknown state as appropriate
- AND it MUST NOT borrow the runtime session based on cwd similarity.

#### Scenario: No session guessing for missing identifiers

- GIVEN a recognized Herdr leader lacks a usable `agent_session` value
- WHEN matching runtime state exists elsewhere
- THEN the plugin MUST NOT guess the session id from runtime state order, cwd, most recent timestamp, or pane metadata outside the explicit Herdr session contract
- AND it MUST display only behavior supported by authoritative metadata.

### Requirement: Safe State Handling

The system MUST safely handle missing, malformed, stale, concurrently written, or cross-runtime state without crashing or leaking state between leaders.

#### Scenario: Missing state files are safe

- GIVEN the plugin state root or runtime state files do not exist
- WHEN sidebar or dashboard state is read
- THEN the reader MUST return an empty or unknown-safe result
- AND the Herdr surfaces MUST preserve no-agent or no-activity behavior without errors.

#### Scenario: Malformed state files are isolated

- GIVEN one runtime state file contains malformed JSON or an invalid record
- WHEN the shared reader loads available state
- THEN it MUST ignore or mark only the malformed source as unavailable
- AND it MUST continue reading other valid canonical or legacy sources when possible.

#### Scenario: Concurrent writes are tolerated

- GIVEN a runtime collector writes state while a sidebar or dashboard read occurs
- WHEN the shared reader encounters a partial, locked, or transient state file
- THEN it MUST avoid crashing
- AND it SHOULD return the last safely readable state or an unknown-safe result rather than a fabricated current state.

#### Scenario: Cross-runtime state is not mixed

- GIVEN Claude Code, Codex, and Pi state are present simultaneously
- WHEN a Herdr-visible leader session is matched
- THEN only state for that leader's canonical runtime and session identity MUST be used
- AND state from another runtime MUST NOT contribute child activity, status, timestamps, or completion claims.

### Requirement: Visible Behavior Preservation

The system MUST preserve existing visible sidebar and dashboard behavior for current users during the first slice, except where uncertainty must be represented more safely to avoid false claims.

#### Scenario: Existing Claude and Codex displays remain stable

- GIVEN existing Claude or Codex hook-derived state is readable and fresh
- WHEN the sidebar and dashboard render after the change
- THEN their user-visible leader and child activity behavior MUST remain equivalent to the current behavior
- AND any internal canonical state migration MUST be invisible to users.

#### Scenario: No-agent behavior remains stable

- GIVEN no recognized Herdr leader pane exists
- WHEN the sidebar metadata publisher or dashboard renderer runs
- THEN the plugin MUST preserve current no-agent or idle-empty presentation behavior
- AND it MUST NOT use runtime files alone to display an agent.

### Requirement: First-Slice Non-Goals

The system MUST exclude first-slice non-goals from the runtime observability implementation and specification scope.

#### Scenario: UI redesign is excluded

- GIVEN the first-slice runtime observability work is implemented
- WHEN reviewers inspect sidebar and dashboard behavior
- THEN there MUST be no dashboard visual redesign or sidebar visual redesign as part of this slice
- AND presentation changes MUST be limited to preserving existing behavior or representing uncertainty safely.

#### Scenario: History, artifacts, profiles, and polling are excluded

- GIVEN canonical runtime presence and activity state is introduced
- WHEN the first slice is delivered
- THEN it MUST NOT redesign history, artifact lineage, profile-resume behavior, Claude transcript analytics, or API-key polling architecture
- AND existing compatible behavior in those areas MUST remain unchanged unless needed only to keep legacy reads working.

#### Scenario: Product ownership remains Herdr

- GIVEN runtime collectors normalize Claude Code, Codex, or Pi evidence
- WHEN product-facing behavior is exposed
- THEN Herdr MUST remain the product, UI, action, and state boundary
- AND the change MUST NOT replace Herdr with a Pi plugin or move manifest, sidebar, dashboard, pane, or action ownership out of Herdr.
