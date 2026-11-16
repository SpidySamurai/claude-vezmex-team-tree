"""Which Claude Code profile directories the plugin wires.

Claude Code keeps its settings in `~/.claude` by default. Running more than
one profile means pointing `CLAUDE_CONFIG_DIR` at another directory, and only
the user knows which ones exist, so `~/.claude` is always wired and every
extra profile is named explicitly, from either of two sources (merged in this
order, without duplicates):

  - the `AGENTS_TREE_CLAUDE_PROFILES` environment variable, entries separated
    by `:` or `,`
  - the `claude_profiles` list in the plugin's `config.json`
    (see dashboard_config.py)

An entry is a directory relative to `$HOME` (`.claude-work`), a `~/` path, or
an absolute path.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dashboard_config import load_config

DEFAULT_PROFILE = ".claude"
ENV_VAR = "AGENTS_TREE_CLAUDE_PROFILES"


def configured_profiles(
    environ: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    """The default profile, then the environment's, then the config file's."""
    environ = os.environ if environ is None else environ
    config = load_config() if config is None else config
    names = [DEFAULT_PROFILE]
    names += re.split(r"[:,]", environ.get(ENV_VAR, ""))
    extra = config.get("claude_profiles", [])
    if isinstance(extra, list):
        names += [name for name in extra if isinstance(name, str)]
    unique: list[str] = []
    for name in (name.strip() for name in names):
        if name and name not in unique:
            unique.append(name)
    return unique


def profile_dir(home: Path, name: str) -> Path:
    """Resolve one entry against `home`. An absolute path stays absolute."""
    if name == "~":
        return home
    if name.startswith("~/"):
        return home / name[2:]
    return home / name


def profile_dirs(
    home: Path,
    *,
    sweep: bool = False,
    environ: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[Path]:
    """Every configured profile directory, existing or not.

    `sweep` also adds each `~/.claude*` directory. Removal uses it so a
    profile that was wired and later dropped from the configuration still
    gets cleaned up; it is safe because removal only ever deletes the exact
    commands this plugin writes.
    """
    dirs = [profile_dir(home, name) for name in configured_profiles(environ, config)]
    if sweep:
        dirs += sorted(path for path in home.glob(".claude*") if path.is_dir())
    unique: list[Path] = []
    for path in dirs:
        if path not in unique:
            unique.append(path)
    return unique
