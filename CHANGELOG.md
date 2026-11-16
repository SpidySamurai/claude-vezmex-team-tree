# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Extra Claude Code profiles are configurable through the
  `AGENTS_TREE_CLAUDE_PROFILES` environment variable or the `claude_profiles`
  list in `config.json`. Uninstall also cleans every `~/.claude*` directory.
- CI on GitHub Actions: the test suite on Python 3.10, 3.11 and 3.12, plus ruff.
- `pyproject.toml` with project metadata and the ruff configuration, and a
  `make lint` target.

### Changed

- Only `~/.claude` is wired by default. Previously three profile directories
  were hardcoded.
- The pane and its actions are named "Agents Tree" everywhere, and the
  configure action is in English like the rest of the manifest.
- The README follows a shorter install-first structure, and the internal
  runtime observability notes moved to `docs/runtime-observability.md`.

### Removed

- The unwired `legacy/` launcher scripts.

## [0.5.0] - 2026-09-11

First version published as a Herdr plugin. It covers the work from
2026-09-07 to 2026-09-11.

### Added

- A compact subagent tree in the Herdr sidebar and a dashboard pane, driven
  only by agent CLI lifecycle hooks, with no terminal reads.
- Session history per finished subagent: duration, token total, a weight
  gauge, and the model and reasoning effort on their own detail row.
- An artifacts log of every `Artifact` publish, clickable from the panel.
- Foldable sections, a live elapsed time per running subagent, and a problem
  band for blocked or interrupted subagents.
- An in-panel settings menu (detail level, limits, panel width, language),
  with English as the default and Spanish as an option.
- Session end detection: the clock freezes and the panel marks the session as
  ended, for Claude Code and for Pi.
- A shared runtime observability layer that normalizes Claude Code, Codex and
  Pi evidence into one canonical snapshot, written atomically.
- Codex support through the same hooks, attributed with an explicit
  `--runtime codex` flag and migrated in place for older wiring.
- An optional Pi companion extension, placed only with
  `install.py --link-pi-extension`.
- An installer that links the plugin, wires each agent settings file
  idempotently, backs files up before the first edit, repairs stale paths at
  every Herdr start, and removes exactly what it wrote.
- A reversible Claude launcher that resumes each session with the profile it
  started in.
- An idle screen with a generated, rotating mandala when no agent is running.
- A README preview generated from a real rendered frame.
- The MIT license.

### Fixed

- Token labels stay inside their column past 1M.
- History columns drop by breakpoint instead of being clipped.
- Reasoning effort is ranked on six levels instead of three.
- The Codex wiring check honors the runtime flag.
- An agent-less pane no longer shows an unrelated past session found by
  working directory.

[Unreleased]: https://github.com/SpidySamurai/herdr-agents-tree/compare/e4235d9...HEAD
[0.5.0]: https://github.com/SpidySamurai/herdr-agents-tree/tree/e4235d9
