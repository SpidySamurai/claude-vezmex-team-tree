#!/usr/bin/env python3
"""Install (or remove) the Agents Tree plugin.

Two things have to be true for the plugin to work, and neither is something
Herdr can do on its own:

  1. Herdr has to know where the plugin lives (`herdr plugin link`), because
     every command in herdr-plugin.toml resolves against that root.
  2. Each agent CLI has to call this plugin's hook scripts, because the panel
     never reads a terminal — the lifecycle hooks are its only source of
     truth. Those live in the CLI's own settings file, with absolute paths.

So moving the checkout breaks the install, and this script is how you fix it:
run it again. It is idempotent, it never touches a hook it did not add, and
`--uninstall` removes exactly what it wired.

    python3 install.py            # link the plugin and wire every agent found
    python3 install.py --check    # report what is wired, change nothing
    python3 install.py --uninstall
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
MANIFEST = ROOT / "herdr-plugin.toml"
PLUGIN_ID = "local.claude-vezmex-team-tree"
HOOK_TIMEOUT = 5

# Which lifecycle event feeds which script. This is the whole contract between
# the agent CLIs and the panel.
HOOK_EVENTS = {
    "SessionStart": "claude_profile_hook.py",   # records the session and its profile
    "SessionEnd": "claude_profile_hook.py",     # marks it finished, so the panel stops
    "SubagentStart": "claude_subagent_hook.py",  # the live tree
    "SubagentStop": "claude_subagent_hook.py",   # the historial
    "PostToolUse": "claude_artifact_hook.py",    # published artifacts
}

# Claude keeps one settings file per profile directory; Codex uses the same
# schema under a different name.
CLAUDE_PROFILES = (".claude", ".claude-work", ".claude-vezmex")
CODEX_HOOKS = (".codex", "hooks.json")

KEYBINDING_HINT = f"""
Herdr has no menu for plugin actions, so add the bindings you want to
~/.config/herdr/config.toml yourself:

    [[keys.command]]
    key = "prefix+alt+a"
    type = "shell"
    command = "herdr plugin action invoke open-dashboard --plugin {PLUGIN_ID}"
"""


def hook_command(root: Path, script: str) -> str:
    """The exact string written into a settings file. Absolute, and quoted so
    a path with spaces still works — and matched verbatim on uninstall, which
    is why its shape must not drift.
    """
    return f'python3 "{root / "src" / script}"'


def our_commands(root: Path) -> set[str]:
    return {hook_command(root, script) for script in set(HOOK_EVENTS.values())}


def wire(settings: dict, root: Path) -> list[str]:
    """Add every missing hook. Returns the events actually changed, so an
    already-installed file reports nothing rather than pretending to work.
    """
    if not isinstance(settings, dict):
        raise TypeError("a settings file must be a JSON object")
    changed = []
    hooks = settings.setdefault("hooks", {})
    for event, script in HOOK_EVENTS.items():
        command = hook_command(root, script)
        groups = hooks.setdefault(event, [])
        if any(h.get("command") == command for g in groups if isinstance(g, dict)
               for h in g.get("hooks", [])):
            continue
        entry = {"type": "command", "command": command, "timeout": HOOK_TIMEOUT}
        if groups and isinstance(groups[0], dict):
            groups[0].setdefault("hooks", []).append(entry)
        else:
            groups.append({"matcher": "", "hooks": [entry]})
        changed.append(event)
    return changed


def unwire(settings: dict, root: Path) -> list[str]:
    """Remove only the commands this installer writes, leaving every other
    hook — and the file's own shape — untouched.
    """
    if not isinstance(settings, dict):
        raise TypeError("a settings file must be a JSON object")
    ours = our_commands(root)
    changed = []
    for event in list(settings.get("hooks", {})):
        for group in settings["hooks"][event]:
            if not isinstance(group, dict):
                continue
            kept = [h for h in group.get("hooks", []) if h.get("command") not in ours]
            if len(kept) != len(group.get("hooks", [])):
                group["hooks"] = kept
                changed.append(event)
    return changed


def wired_events(settings: dict, root: Path) -> list[str]:
    if not isinstance(settings, dict):
        return []
    present = []
    for event, script in HOOK_EVENTS.items():
        command = hook_command(root, script)
        if any(h.get("command") == command
               for g in settings.get("hooks", {}).get(event, []) if isinstance(g, dict)
               for h in g.get("hooks", [])):
            present.append(event)
    return present


def settings_files(home: Path) -> list[Path]:
    """Every agent settings file that actually exists. A profile directory
    with no settings.json is one the user does not use, so it is skipped
    rather than created.
    """
    found = [home / profile / "settings.json" for profile in CLAUDE_PROFILES]
    found.append(home.joinpath(*CODEX_HOOKS))
    return [path for path in found if path.is_file()]


def read_settings(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_settings(path: Path, settings: dict) -> None:
    """Back the file up once before the first edit, then write it whole.

    These are the user's own agent settings; a bad write costs them their
    whole hook configuration, so the backup is created before we ever touch
    the file and never overwritten afterwards.
    """
    backup = path.with_suffix(path.suffix + ".agents-tree.bak")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def link_plugin(remove: bool = False) -> str:
    herdr = "herdr"
    args = [herdr, "plugin", "unlink", PLUGIN_ID] if remove else [herdr, "plugin", "link", str(ROOT)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"could not run herdr ({error})"
    if result.returncode:
        return (result.stderr or result.stdout or "herdr refused").strip()[:200]
    return "unlinked" if remove else f"linked at {ROOT}"


def check(home: Path) -> int:
    print(f"plugin root: {ROOT}")
    files = settings_files(home)
    if not files:
        print("no agent settings files found")
    for path in files:
        settings = read_settings(path)
        if settings is None:
            print(f"  {path}: unreadable or not a JSON object")
            continue
        wired = wired_events(settings, ROOT)
        missing = [event for event in HOOK_EVENTS if event not in wired]
        state = "complete" if not missing else f"missing {', '.join(missing)}"
        print(f"  {path}: {len(wired)}/{len(HOOK_EVENTS)} wired — {state}")
    return 0


def install(home: Path) -> int:
    if not MANIFEST.is_file() or not SRC.is_dir():
        print(f"not a plugin checkout: {ROOT}", file=sys.stderr)
        return 2
    print(f"herdr: {link_plugin()}")
    files = settings_files(home)
    if not files:
        print("no agent settings files found — nothing to wire", file=sys.stderr)
    for path in files:
        settings = read_settings(path)
        if settings is None:
            print(f"  {path}: skipped (unreadable or not a JSON object)", file=sys.stderr)
            continue
        changed = wire(settings, ROOT)
        if changed:
            write_settings(path, settings)
        print(f"  {path}: {', '.join(changed) if changed else 'already wired'}")
    print(KEYBINDING_HINT.rstrip())
    print("\nA running agent session keeps the hook paths it started with —"
          "\nrestart it for the wiring to take effect.")
    return 0


def uninstall(home: Path) -> int:
    print(f"herdr: {link_plugin(remove=True)}")
    for path in settings_files(home):
        settings = read_settings(path)
        if settings is None:
            continue
        changed = unwire(settings, ROOT)
        if changed:
            write_settings(path, settings)
        print(f"  {path}: {', '.join(sorted(set(changed))) if changed else 'nothing of ours'}")
    print("\nRecorded session state under $XDG_STATE_HOME/herdr/claude-vezmex-team-tree"
          "\nwas left in place; delete that directory to remove it too.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uninstall", action="store_true", help="remove what this installer wired")
    parser.add_argument("--check", action="store_true", help="report the current wiring, change nothing")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.check:
        return check(arguments.home)
    return uninstall(arguments.home) if arguments.uninstall else install(arguments.home)


if __name__ == "__main__":
    raise SystemExit(main())
