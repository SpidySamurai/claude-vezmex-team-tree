#!/usr/bin/env python3
"""Install or remove the reversible Claude profile-resume integration."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
HOOK = ROOT / "claude_profile_hook.py"
WRAPPER = ROOT / "claude_profile_resume.py"
HOOK_COMMAND = f'python3 "{HOOK}"'
PROFILES = (".claude", ".claude-work", ".claude-vezmex")


def paths(home: Path) -> tuple[Path, Path, Path]:
    binary = home / ".local" / "bin" / "claude"
    original = home / ".local" / "bin" / "claude.herdr-original"
    state = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local" / "state"))) / "herdr" / "claude-vezmex-team-tree" / "profiles.json"
    return binary, original, state


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def add_hook(settings: Path) -> bool:
    data = read_json(settings)
    groups = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    for group in groups:
        for hook in group.get("hooks", []):
            if hook.get("command") == HOOK_COMMAND:
                return False
    if groups and isinstance(groups[0], dict):
        groups[0].setdefault("hooks", []).append({"type": "command", "command": HOOK_COMMAND, "timeout": 2})
    else:
        groups.append({"matcher": "", "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 2}]})
    write_json(settings, data)
    return True


def remove_hook(settings: Path) -> bool:
    data = read_json(settings)
    changed = False
    for group in data.get("hooks", {}).get("SessionStart", []):
        hooks = group.get("hooks", [])
        retained = [hook for hook in hooks if hook.get("command") != HOOK_COMMAND]
        if len(retained) != len(hooks):
            group["hooks"] = retained
            changed = True
    if changed:
        write_json(settings, data)
    return changed


def install(home: Path) -> int:
    binary, original, state = paths(home)
    if not binary.exists() and not binary.is_symlink():
        print(f"Claude executable not found: {binary}", file=sys.stderr)
        return 2
    if not (binary.is_symlink() and binary.resolve() == WRAPPER):
        if original.exists() or original.is_symlink():
            print(f"Refusing to overwrite existing rollback target: {original}", file=sys.stderr)
            return 2
        real = binary.resolve()
        if not real.is_file():
            print(f"Claude target is not a file: {real}", file=sys.stderr)
            return 2
        os.rename(binary, original)
        os.symlink(WRAPPER, binary)
        state.parent.mkdir(parents=True, exist_ok=True)
        registry = read_json(state)
        registry["version"] = 1
        registry["real_claude"] = str(real)
        registry.setdefault("sessions", {})
        write_json(state, registry)

    changed = []
    for profile in PROFILES:
        settings = home / profile / "settings.json"
        if settings.exists() and add_hook(settings):
            changed.append(profile)
    print("Profile-aware Claude resume installed.")
    print("Hooks added: " + (", ".join(changed) if changed else "already present"))
    print(f"Rollback: python3 {Path(__file__).resolve()} --uninstall")
    return 0


def uninstall(home: Path) -> int:
    binary, original, _state = paths(home)
    if binary.is_symlink() and binary.resolve() == WRAPPER and (original.exists() or original.is_symlink()):
        binary.unlink()
        os.rename(original, binary)
    else:
        print("Claude wrapper was not removed because the expected rollback target is unavailable.", file=sys.stderr)
        return 2
    for profile in PROFILES:
        settings = home / profile / "settings.json"
        if settings.exists():
            remove_hook(settings)
    print("Profile-aware Claude resume removed; original launcher restored.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    return uninstall(arguments.home) if arguments.uninstall else install(arguments.home)


if __name__ == "__main__":
    raise SystemExit(main())
