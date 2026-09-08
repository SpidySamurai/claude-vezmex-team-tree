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
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
MANIFEST = ROOT / "herdr-plugin.toml"
PLUGIN_ID = "local.claude-vezmex-team-tree"
HOOK_TIMEOUT = 5

# The Pi companion collector is opt-in and explicit: install()/check() only
# report its status here. It is placed only by --link-pi-extension, at Pi's
# own documented global extension directory (~/.pi/agent/extensions/<name>/).
PI_EXTENSION_NAME = "herdr-agent-observability"
PI_EXTENSIONS_DIR = (".pi", "agent", "extensions")

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


def hook_command(root: Path, script: str, runtime: str = "claude") -> str:
    """The exact string written into a settings file. Absolute, and quoted so
    a path with spaces still works — and matched verbatim on uninstall, which
    is why its shape must not drift.

    A non-Claude runtime gets an explicit trailing flag so the hook process
    itself can tell which agent CLI is invoking it — every event and script is
    otherwise identical between Claude Code and Codex.
    """
    base = f'python3 "{root / "src" / script}"'
    return base if runtime == "claude" else f"{base} --runtime {runtime}"


def our_commands(root: Path, runtime: str = "claude") -> set[str]:
    return {hook_command(root, script, runtime) for script in set(HOOK_EVENTS.values())}


def runtime_for(path: Path, home: Path) -> str:
    """Which agent CLI a settings file belongs to, from its known location."""
    return "codex" if path == home.joinpath(*CODEX_HOOKS) else "claude"


def wire(settings: dict, root: Path, runtime: str = "claude") -> list[str]:
    """Add every missing hook. Returns the events actually changed, so an
    already-installed file reports nothing rather than pretending to work.

    A non-Claude runtime also migrates in place: an entry still carrying the
    old unflagged command (every install before this flag existed) is
    rewritten to the runtime-flagged one rather than duplicated.
    """
    if not isinstance(settings, dict):
        raise TypeError("a settings file must be a JSON object")
    changed = []
    hooks = settings.setdefault("hooks", {})
    for event, script in HOOK_EVENTS.items():
        command = hook_command(root, script, runtime)
        legacy_command = hook_command(root, script, "claude") if runtime != "claude" else None
        groups = hooks.setdefault(event, [])
        migrated = False
        if legacy_command and legacy_command != command:
            for group in groups:
                if not isinstance(group, dict):
                    continue
                for entry in group.get("hooks", []):
                    if isinstance(entry, dict) and entry.get("command") == legacy_command:
                        entry["command"] = command
                        migrated = True
        if migrated:
            changed.append(event)
            continue
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


def unwire(settings: dict, root: Path, runtime: str = "claude") -> list[str]:
    """Remove only the commands this installer writes, leaving every other
    hook — and the file's own shape — untouched. Also removes a pre-migration
    unflagged command from a non-Claude file, so uninstall is clean regardless
    of whether that file was ever reinstalled after the runtime flag shipped.
    """
    if not isinstance(settings, dict):
        raise TypeError("a settings file must be a JSON object")
    ours = our_commands(root, runtime)
    if runtime != "claude":
        ours |= our_commands(root, "claude")
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


def wired_events(settings: dict, root: Path, runtime: str = "claude") -> list[str]:
    if not isinstance(settings, dict):
        return []
    present = []
    for event, script in HOOK_EVENTS.items():
        command = hook_command(root, script, runtime)
        if any(h.get("command") == command
               for g in settings.get("hooks", {}).get(event, []) if isinstance(g, dict)
               for h in g.get("hooks", [])):
            present.append(event)
    return present


def pi_extension_source() -> Path:
    return ROOT / "pi" / PI_EXTENSION_NAME


def pi_extension_target(home: Path) -> Path:
    return home.joinpath(*PI_EXTENSIONS_DIR, PI_EXTENSION_NAME)


def pi_extension_status(home: Path) -> str:
    """Read-only: never creates anything, so install()/check() can report it
    without silently wiring unverified Pi runtime configuration.
    """
    target = pi_extension_target(home)
    if not target.exists():
        return "not installed"
    if target.is_symlink() and target.resolve() == pi_extension_source().resolve():
        return "linked"
    return "present (not ours)"


def link_pi_extension(home: Path) -> str:
    """Explicit opt-in placement; never called by plain install()/check()."""
    target = pi_extension_target(home)
    source = pi_extension_source()
    if target.exists():
        return f"{target}: already present, left as-is"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        # Filesystems without symlink support (some Windows configurations).
        shutil.copytree(source, target)
    return f"{target}: linked to {source}"


def unlink_pi_extension(home: Path) -> str:
    """Remove only a link this installer created; a foreign directory at the
    same path is left untouched, matching the hook unwire() safety rule.
    """
    target = pi_extension_target(home)
    if not target.exists():
        return f"{target}: nothing of ours"
    if target.is_symlink() and target.resolve() == pi_extension_source().resolve():
        target.unlink()
        return f"{target}: unlinked"
    return f"{target}: left in place (not ours)"


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
    print(f"pi companion extension: {pi_extension_status(home)} (opt in with --link-pi-extension)")
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
        changed = wire(settings, ROOT, runtime_for(path, home))
        if changed:
            write_settings(path, settings)
        print(f"  {path}: {', '.join(changed) if changed else 'already wired'}")
    print(f"pi companion extension: {pi_extension_status(home)} (opt in with --link-pi-extension)")
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
        changed = unwire(settings, ROOT, runtime_for(path, home))
        if changed:
            write_settings(path, settings)
        print(f"  {path}: {', '.join(sorted(set(changed))) if changed else 'nothing of ours'}")
    print(f"  pi companion extension: {unlink_pi_extension(home)}")
    print("\nRecorded session state under $XDG_STATE_HOME/herdr/claude-vezmex-team-tree"
          "\nwas left in place; delete that directory to remove it too.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--uninstall", action="store_true", help="remove what this installer wired")
    parser.add_argument("--check", action="store_true", help="report the current wiring, change nothing")
    parser.add_argument("--link-pi-extension", action="store_true",
                         help="explicitly place the Pi companion collector at ~/.pi/agent/extensions/")
    parser.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.link_pi_extension:
        print(link_pi_extension(arguments.home))
        return 0
    if arguments.check:
        return check(arguments.home)
    return uninstall(arguments.home) if arguments.uninstall else install(arguments.home)


if __name__ == "__main__":
    raise SystemExit(main())
