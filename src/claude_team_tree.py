#!/usr/bin/env python3
"""A narrow subagent dashboard for Herdr — agent-agnostic (see
RECOGNIZED_AGENTS): Claude, Codex, or Pi, whichever Herdr detects in the pane.

It uses Herdr only to locate the recognized agent leader for each visible
pane. Its tree and all subagent lifecycle states come from that provider's
SubagentStart/SubagentStop hooks (wired for Claude and Codex today; Pi's own
hooks are not wired yet, so a Pi pane shows its leader but no subagent
history until that's added). It never reads a terminal pane, so it cannot
move the leader's scroll position.

Its only input surface is mouse clicks (SGR reporting), and only for the
gear/submenu in the header — clicking the header row toggles a small config
menu (see dashboard_config.py) whose options cycle through preset values on
click. Nothing else here reads keyboard/mouse input.
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from dashboard_config import (  # noqa: E402
    CYCLES,
    SECTION_KEYS,
    DEFAULTS as CONFIG_DEFAULTS,
    MENU_LABELS,
    MENU_OPTIONS,
    cycle_position,
    cycle_value,
    load_config,
    save_config,
)

FRAMES = ("▰▰▱", "▱▰▰", "▱▱▰", "▱▰▰")
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
COLORS = {
    "working": "\033[96m",  # bright sky
    "idle": "\033[94m",     # bright blue
    "done": "\033[92m",     # bright green
    "blocked": "\033[91m",  # bright red
    "unknown": "\033[95m",  # bright purple
    # The session behind the panel is over: grey it out rather than let a
    # dead tree keep wearing live colours.
    "ended": "\033[90m",       # grey
    "interrupted": "\033[93m",  # yellow — it never reported finishing
}
STATIC = {"idle": "●", "done": "✓", "blocked": "●", "unknown": "?", "ended": "○", "interrupted": "▪"}
# Agent-agnostic: any of these get the dashboard, not just Claude — matches
# the same design already applied to herdr_agent_tree.py's sidebar tokens.
RECOGNIZED_AGENTS = {"claude", "codex", "pi"}
BG_ROW = "\033[48;5;237m"  # zebra-stripe background for every other list row
NAME_W = 15
TIME_W = 5
DUR_W = 5
TOK_W = 6
BAR_W = 8  # cells in the historial weight gauge
HISTORIAL_FIXED = 1 + TIME_W + 1 + DUR_W + 1 + TOK_W  # separators + fixed columns

# Click targets. render() records which row carries which target and the
# click handler resolves against that map, so a row moving (a section folding,
# a band appearing, the menu opening) can never point a click at the wrong
# thing the way a hardcoded row number would.
TARGET_MENU = "menu"
TARGET_MENU_CLOSE = "menu.close"
TARGET_SECTION_HISTORY = "section.history_collapsed"
TARGET_SECTION_ARTIFACTS = "section.artifacts_collapsed"


def option_target(option: str) -> str:
    return f"option.{option}"


# This module is also loaded directly by path, so make the sibling package
# importable before reaching for it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_observability import ids, reader, store  # noqa: E402


def plugin_state_path(name: str) -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return state_home / "herdr" / "claude-vezmex-team-tree" / name


def session_id_for(agent: dict[str, Any]) -> str | None:
    """Return the agent session Herdr associated with a leader pane."""
    agent_session = agent.get("agent_session")
    if isinstance(agent_session, dict):
        value = agent_session.get("value")
        return value if isinstance(value, str) and value else None
    return agent_session if isinstance(agent_session, str) and agent_session else None


def hook_children(session_id: str | None) -> list[dict[str, str]]:
    """Live children for one leader session, via the shared runtime reader."""
    children = [
        {
            "id": child.id,
            "name": child.name,
            "agent_status": child.status,
            # The only live per-subagent fact collectors keep, so it is the only
            # one the tree can report while one is still running.
            "started": child.started,
        }
        for child in reader.children_for_session(session_id)
    ]
    return sorted(children, key=lambda child: (child["name"].casefold(), child["id"]))


# The idle screen. A pane with no agent has nothing true to show: the tree,
# the historial and the artifacts all belong to a session, and borrowing
# another one's is worse than showing nothing. So it shows nothing — as a
# deliberate screen rather than an empty panel with broken sections.
#
# A 12-petal rose curve (r = cos(6*theta) in polar form, filled and shaded by
# distance from the boundary), not hand-drawn: both mirror axes are exact by
# construction, because the formula only depends on |cos| and the radius —
# not by eyeballing a hand-drawn shape. Precomputed at 12 rotation angles
# spanning one twelfth of a full turn (the shape's own 12-fold symmetry
# means that arc already loops back onto the start), cycled by the same
# frame counter that drives the working-status spinner, so it spins in
# place instead of sitting static. Baked in here rather than computed at
# draw time, so the idle screen stays a plain constant-time lookup.
MANDALA_FRAMES = [
    [
        '                  ..                  ',
        '         ...     .::.     ...         ',
        '          .::    .--.    ::.          ',
        '           :--.  :==:  .--:           ',
        '   ...      -==: .==. :==-      ...   ',
        '    .::--:   -++: ++ :++-   :--::.    ',
        '       :-===-  +* ** *+  -===-:       ',
        '           -+**=+#**#+=**+-           ',
        ' ...:::---===-. #%%%%# .-===---:::... ',
        ' ...:::---===-. #%%%%# .-===---:::... ',
        '           -+**=+#**#+=**+-           ',
        '       :-===-  +* ** *+  -===-:       ',
        '    .::--:   -++: ++ :++-   :--::.    ',
        '   ...      -==: .==. :==-      ...   ',
        '           :--.  :==:  .--:           ',
        '          .::    .--.    ::.          ',
        '         ...     .::.     ...         ',
        '                  ..                  ',
    ],
    [
        '                   ..                 ',
        '          ...     .::      ..         ',
        '           :::    :-:    .::.         ',
        '           .---   -=-   :--:          ',
        '   .....    .==-  =+-  -=-:       .   ',
        '     .:---:   =+= ++- =+=    ::::..   ',
        '        :-=+=: +*-+* **- .===--:      ',
        '           .=***:#=##* **+=-          ',
        '...::---===++++ *%%%%#=  .:::::...    ',
        '    ...:::::.  =#%%%%* ++++===---::...',
        '          -=+** *##=#:***=.           ',
        '      :--===. -** *+-*+ :=+=-:        ',
        '   ..::::    =+= -++ =+=   :---:.     ',
        '   .       :-=-  -+=  -==.    .....   ',
        '          :--:   -=-   ---.           ',
        '         .::.    :-:    :::           ',
        '         ..      ::.     ...          ',
        '                 ..                   ',
    ],
    [
        '                   ...                ',
        '           ...     ::.      ..        ',
        '           .::.   .--:    .::.        ',
        '            :--:  :==.   :-:.         ',
        '    ..::.    -==. -+=  :==-           ',
        '      .:---:  -++ -+= -+=:    .:::..  ',
        '         :=++= -*+=*:+*+  :-==-::     ',
        '            :+** # #*# +*++=:         ',
        ' ..::--===+++**+:%%%##*.              ',
        '              .*##%%%:+**+++===--::.. ',
        '         :=++*+ #*# # **+:            ',
        '     ::-==-:  +*+:*=+*- =++=:         ',
        '  ..:::.    :=+- =+- ++-  :---:.      ',
        '           -==:  =+- .==-    .::..    ',
        '         .:-:   .==:  :--:            ',
        '        .::.    :--.   .::.           ',
        '        ..      .::     ...           ',
        '                ...                   ',
    ],
    [
        '            .       ..                ',
        '           ...     .::.               ',
        '            :::    :-:     .:.        ',
        '    ...      ---   -=-   .:-:         ',
        '     .::::   .==-  =+-  -=-:          ',
        '       .--=-. .++: ++  =+=      ....  ',
        '          -=++: ** *+-*+:  :----:..   ',
        ' ....:::.    =**:#:#+#:-+++==:.       ',
        '  ..::--==++**** %%###*+              ',
        '              +*###%% ****++==--::..  ',
        '       .:==+++-:#+#:#:**=    .:::.... ',
        '   ..:----:  :+*-+* ** :++=-          ',
        '  ....      =+=  ++ :++. .-=--.       ',
        '          :-=-  -+=  -==.   ::::.     ',
        '         :-:.   -=-   ---      ...    ',
        '        .:.     :-:    :::            ',
        '               .::.     ...           ',
        '                ..       .            ',
    ],
    [
        '            ..       ..               ',
        '            .:.     .::               ',
        '             :-:    --:     ...       ',
        '     ...     :--:  :=-.   :::.        ',
        '      .:--:   -==  -+=  .---.         ',
        '        :-==-  =+= ++- =+=-           ',
        '          .=++= +* ** +*=   :---::..  ',
        ' ..:::---:.  .*#+#*# #+ =+++=-:.      ',
        '    ..:--=++***#+%%*-##*=.            ',
        '            .=*##-*%%+#***++=--:..    ',
        '      .:-=+++= +# #*#+#*.  .:---:::.. ',
        '  ..::---:   =*+ ** *+ =++=.          ',
        '           -=+= -++ =+=  -==-:        ',
        '         .---.  =+-  ==-   :--:.      ',
        '        .:::   .-=:  :--:     ...     ',
        '       ...     :--    :-:             ',
        '               ::.     .:.            ',
        '               ..       ..            ',
    ],
    [
        '             ..       ..              ',
        '             .:.     ::.              ',
        '             .--.   :--.     ...      ',
        '     ..:.     -=-   -=-    :::.       ',
        '       .:--.  .==- :==:  :--:.        ',
        '         :===: -++ =+= :===.          ',
        '           :=++ =*:** +*+:   .:::::.. ',
        ' ..::----=-:  +***## #* :=++==-::.    ',
        '      ..:-=++*##*#%=:##*+=:           ',
        '           :=+*##:=%#*##*++=-:..      ',
        '    .::-==++=: *# ##***+  :-=----::.. ',
        ' ..:::::.   :+*+ **:*= ++=:           ',
        '          .===: =+= ++- :===:         ',
        '        .:--:  :==: -==.  .--:.       ',
        '       .:::    -=-   -=-     .:..     ',
        '      ...     .--:   .--.             ',
        '              .::     .:.             ',
        '              ..       ..             ',
    ],
    [
        '              ..      ..              ',
        '             .::.    .::.             ',
        '      ..      :-:    :-:      ..      ',
        '      .:::    .-=:  :=-.    :::.      ',
        '        :---   -==  ==-   ---:        ',
        '          -==-  ++..++  -==-          ',
        ' ......     =++-:*++*:-++=     ...... ',
        '   .::--====- :*#=##=#*: -====--::.   ',
        '         :-=+**##*##*##**+=-:         ',
        '         :-=+**##*##*##**+=-:         ',
        '   .::--====- :*#=##=#*: -====--::.   ',
        ' ......     =++-:*++*:-++=     ...... ',
        '          -==-  ++..++  -==-          ',
        '        :---   -==  ==-   ---:        ',
        '      .:::    .-=:  :=-.    :::.      ',
        '      ..      :-:    :-:      ..      ',
        '             .::.    .::.             ',
        '              ..      ..              ',
    ],
    [
        '              ..       ..             ',
        '              .::     .:.             ',
        '      ...     .--:   .--.             ',
        '       .:::    -=-   -=-     .:..     ',
        '        .:--:  :==: -==.  .--:.       ',
        '          .===: =+= ++- :===:         ',
        ' ..:::::.   :+*+ **:*= ++=:           ',
        '    .::-==++=: *# ##***+  :-=----::.. ',
        '           :=+*##:=%#*##*++=-:..      ',
        '      ..:-=++*##*#%=:##*+=:           ',
        ' ..::----=-:  +***## #* :=++==-::.    ',
        '           :=++ =*:** +*+:   .:::::.. ',
        '         :===: -++ =+= :===.          ',
        '       .:--.  .==- :==:  :--:.        ',
        '     ..:.     -=-   -=-    :::.       ',
        '             .--.   :--.     ...      ',
        '             .:.     ::.              ',
        '             ..       ..              ',
    ],
    [
        '               ..       ..            ',
        '               ::.     .:.            ',
        '       ...     :--    :-:             ',
        '        .:::   .-=:  :--:     ...     ',
        '         .---.  =+-  ==-   :--:.      ',
        '           -=+= -++ =+=  -==-:        ',
        '  ..::---:   =*+ ** *+ =++=.          ',
        '      .:-=+++= +# #*#+#*.  .:---:::.. ',
        '            .=*##-*%%+#***++=--:..    ',
        '    ..:--=++***#+%%*-##*=.            ',
        ' ..:::---:.  .*#+#*# #+ =+++=-:.      ',
        '          .=++= +* ** +*=   :---::..  ',
        '        :-==-  =+= ++- =+=-           ',
        '      .:--:   -==  -+=  .---.         ',
        '     ...     :--:  :=-.   :::.        ',
        '             :-:    --:     ...       ',
        '            .:.     .::               ',
        '            ..       ..               ',
    ],
    [
        '                ..       .            ',
        '               .::.     ...           ',
        '        .:.     :-:    :::            ',
        '         :-:.   -=-   ---      ...    ',
        '          :-=-  -+=  -==.   ::::.     ',
        '  ....      =+=  ++ :++. .-=--.       ',
        '   ..:----:  :+*-+* ** :++=-          ',
        '       .:==+++-:#+#:#:**=    .:::.... ',
        '              +*###%% ****++==--::..  ',
        '  ..::--==++**** %%###*+              ',
        ' ....:::.    =**:#:#+#:-+++==:.       ',
        '          -=++: ** *+-*+:  :----:..   ',
        '       .--=-. .++: ++  =+=      ....  ',
        '     .::::   .==-  =+-  -=-:          ',
        '    ...      ---   -=-   .:-:         ',
        '            :::    :-:     .:.        ',
        '           ...     .::.               ',
        '            .       ..                ',
    ],
    [
        '                ...                   ',
        '        ..      .::     ...           ',
        '        .::.    :--.   .::.           ',
        '         .:-:   .==:  :--:            ',
        '           -==:  =+- .==-    .::..    ',
        '  ..:::.    :=+- =+- ++-  :---:.      ',
        '     ::-==-:  +*+:*=+*- =++=:         ',
        '         :=++*+ #*# # **+:            ',
        '              .*##%%%:+**+++===--::.. ',
        ' ..::--===+++**+:%%%##*.              ',
        '            :+** # #*# +*++=:         ',
        '         :=++= -*+=*:+*+  :-==-::     ',
        '      .:---:  -++ -+= -+=:    .:::..  ',
        '    ..::.    -==. -+=  :==-           ',
        '            :--:  :==.   :-:.         ',
        '           .::.   .--:    .::.        ',
        '           ...     ::.      ..        ',
        '                   ...                ',
    ],
    [
        '                 ..                   ',
        '         ..      ::.     ...          ',
        '         .::.    :-:    :::           ',
        '          :--:   -=-   ---.           ',
        '   .       :-=-  -+=  -==.    .....   ',
        '   ..::::    =+= -++ =+=   :---:.     ',
        '      :--===. -** *+-*+ :=+=-:        ',
        '          -=+** *##=#:***=.           ',
        '    ...:::::.  =#%%%%* ++++===---::...',
        '...::---===++++ *%%%%#=  .:::::...    ',
        '           .=***:#=##* **+=-          ',
        '        :-=+=: +*-+* **- .===--:      ',
        '     .:---:   =+= ++- =+=    ::::..   ',
        '   .....    .==-  =+-  -=-:       .   ',
        '           .---   -=-   :--:          ',
        '           :::    :-:    .::.         ',
        '          ...     .::      ..         ',
        '                   ..                 ',
    ],
]
MANDALA_COMPACT_FRAMES = [
    [
        '          ..          ',
        '      ::  --  ::      ',
        '  ..   -= == =-   ..  ',
        '    :==.-*==*-.==:    ',
        '        +#%%#+        ',
        '        +#%%#+        ',
        '    :==.-*==*-.==:    ',
        '  ..   -= == =-   ..  ',
        '      ::  --  ::      ',
        '          ..          ',
    ],
    [
        '      .    :    .     ',
        '      .-  :-  .:      ',
        '  .:.  := -+ -=    .  ',
        '    .-=- *.++= -=-.   ',
        ' ..:::: =#%##*.       ',
        '       .*##%#= ::::.. ',
        '   .-=- =++.* -=-.    ',
        '  .    =- +- =:  .:.  ',
        '      :.  -:  -.      ',
        '     .    :    .      ',
    ],
    [
        '      ..   :.         ',
        '       -:  -.  :.     ',
        '   ::.  =: + :=:      ',
        '     -== * *++ :--:   ',
        '..:--==: #%#**=       ',
        '       =**#%# :==--:..',
        '   :--: ++* * ==-     ',
        '      :=: + :=  .::   ',
        '     .:  .-  :-       ',
        '         .:   ..      ',
    ],
    [
        '       .   .:         ',
        '       :-  -:  .:     ',
        '   .::  == +: =-      ',
        '     .=+ * *:+  --:.  ',
        ' .:-==+= #%*+*+:      ',
        '      :+*+*%# =+==-:. ',
        '  .:--  +:* * +=.     ',
        '      -= :+ ==  ::.   ',
        '     :.  :-  -:       ',
        '         :.   .       ',
    ],
    [
        '       ..   :         ',
        '       .-. :-   :.    ',
        '    :-. -= =- --      ',
        '      -+:+-* *: .:::. ',
        ' .:-==++:##- **=.     ',
        '     .=** -##:++==-:. ',
        ' .:::. :* *-+:+-      ',
        '      -- -= =- .-:    ',
        '    .:   -: .-.       ',
        '         :   ..       ',
    ],
    [
        '       ..   ..        ',
        '   .    -:  -.  ..    ',
        '    .-: .+ == :-:     ',
        '      :+==+* +=  .::. ',
        '  .:-=+*+*#  **+-     ',
        '     -+**  #*+*+=-:.  ',
        ' .::.  =+ *+==+:      ',
        '     :-: == +. :-.    ',
        '    ..  .-  :-    .   ',
        '        ..   ..       ',
    ],
    [
        '        .    .        ',
        '   ..   :-  -:   ..   ',
        '     --  +::+  --     ',
        ' ..    ++.**.++    .. ',
        '   .:=+**+**+**+=:.   ',
        '   .:=+**+**+**+=:.   ',
        ' ..    ++.**.++    .. ',
        '     --  +::+  --     ',
        '   ..   :-  -:   ..   ',
        '        .    .        ',
    ],
    [
        '        ..   ..       ',
        '    ..  .-  :-    .   ',
        '     :-: == +. :-.    ',
        ' .::.  =+ *+==+:      ',
        '     -+**  #*+*+=-:.  ',
        '  .:-=+*+*#  **+-     ',
        '      :+==+* +=  .::. ',
        '    .-: .+ == :-:     ',
        '   .    -:  -.  ..    ',
        '       ..   ..        ',
    ],
    [
        '         :   ..       ',
        '    .:   -: .-.       ',
        '      -- -= =- .-:    ',
        ' .:::. :* *-+:+-      ',
        '     .=** -##:++==-:. ',
        ' .:-==++:##- **=.     ',
        '      -+:+-* *: .:::. ',
        '    :-. -= =- --      ',
        '       .-. :-   :.    ',
        '       ..   :         ',
    ],
    [
        '         :.   .       ',
        '     :.  :-  -:       ',
        '      -= :+ ==  ::.   ',
        '  .:--  +:* * +=.     ',
        '      :+*+*%# =+==-:. ',
        ' .:-==+= #%*+*+:      ',
        '     .=+ * *:+  --:.  ',
        '   .::  == +: =-      ',
        '       :-  -:  .:     ',
        '       .   .:         ',
    ],
    [
        '         .:   ..      ',
        '     .:  .-  :-       ',
        '      :=: + :=  .::   ',
        '   :--: ++* * ==-     ',
        '       =**#%# :==--:..',
        '..:--==: #%#**=       ',
        '     -== * *++ :--:   ',
        '   ::.  =: + :=:      ',
        '       -:  -.  :.     ',
        '      ..   :.         ',
    ],
    [
        '     .    :    .      ',
        '      :.  -:  -.      ',
        '  .    =- +- =:  .:.  ',
        '   .-=- =++.* -=-.    ',
        '       .*##%#= ::::.. ',
        ' ..:::: =#%##*.       ',
        '    .-=- *.++= -=-.   ',
        '  .:.  := -+ -=    .  ',
        '      .-  :-  .:      ',
        '      .    :    .     ',
    ],
]

# Neutral, register-agnostic Spanish — no voseo: this ships to any
# Spanish-speaking install, not only a Rioplatense one.
IDLE_LINES = ("sin agente en este pane", "abre Claude, Codex o Pi aquí")

def idle_art(width: int, frame: int = 0) -> list[str]:
    """One rotation frame of the widest mandala that fits, with a column of
    margin on each side.

    Checked against every rotation's own width, not just frame 0's — the
    frames are already padded to a shared width per variant, but the variant
    choice itself must hold for all of them or a later spin would overflow
    the pane frame 0 fit into.

    Plain ASCII on purpose: box-drawing and emoji presentation vary by font,
    and an idle screen that renders as tofu is exactly the broken state this
    replaces.
    """
    for frames in (MANDALA_FRAMES, MANDALA_COMPACT_FRAMES):
        if max(len(line) for f in frames for line in f) <= width - 2:
            return frames[frame % len(frames)]
    return []


def idle_screen(width: int, height: int | None = None, frame: int = 0) -> str:
    """The mandala, centred across the pane, with a line saying what is
    missing. `frame` selects its rotation — the same counter main()'s loop
    already advances for the working-status spinner.

    Centred as a BLOCK, not row by row: each row keeps its own leading spaces
    so the drawing holds its shape, and the whole block is indented once.
    """
    art = idle_art(width, frame)
    block = [*art, "", *IDLE_LINES] if art else list(IDLE_LINES)
    block_width = max(len(line) for line in block)
    indent = max(0, (width - block_width) // 2)
    rows = [
        f"{DIM}{' ' * indent}{line}{RESET}" if line.strip() else ""
        for line in block
    ]
    if height is None:
        return "\n".join(trim_ansi(row, width) for row in rows)
    above = max(0, (height - len(rows)) // 2)
    below = max(0, height - len(rows) - above)
    rows = [""] * above + rows + [""] * below
    return "\n".join(trim_ansi(row, width) for row in rows[:height])


def read_snapshot() -> dict[str, Any] | None:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    try:
        result = subprocess.run(
            [herdr, "api", "snapshot"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode:
            return None
        return json.loads(result.stdout)["result"]["snapshot"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def glyph(status: str, frame: int) -> str:
    return FRAMES[frame % len(FRAMES)] if status == "working" else STATIC.get(status, "?")


def title_for(agent: dict[str, Any]) -> str:
    label = agent.get("display_agent") or agent.get("terminal_title_stripped") or agent.get("agent") or "agente"
    return str(label).replace("Claude Code", "Claude")


def subagent_label(agent: dict[str, str]) -> str:
    identifier = agent.get("id", "")
    suffix = identifier.removeprefix("agent-")[-6:]
    return f"{agent.get('name', 'subagent')} · {suffix}" if suffix else agent.get("name", "subagent")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def session_history(session_ids: set[str], limit: int = 6) -> tuple[list[dict[str, Any]], int]:
    """Returns (most-recent `limit` records, total matching count) — the
    caller needs the total to show a "+N más" hint when older entries exist
    beyond what's displayed.
    """
    records = [r for r in read_jsonl(plugin_state_path("history.jsonl")) if r.get("session") in session_ids]
    records.sort(key=lambda r: r.get("stopped") or 0, reverse=True)
    return records[:limit], len(records)


def session_artifacts(session_ids: set[str], limit: int = 4) -> list[dict[str, Any]]:
    records = [r for r in read_jsonl(plugin_state_path("artifacts.jsonl")) if r.get("session") in session_ids]
    records.sort(key=lambda r: r.get("at") or 0, reverse=True)
    return records[:limit]


def format_tokens(count: int) -> str:
    """A token count that always fits `TOK_W`.

    Step up a unit before the mantissa would need a fourth digit, so the
    label is never wider than `999.9k`. A single `k` tier was not enough: an
    ordinary multi-million-token session rendered as `15044.3k`, two columns
    past the header, which pushed every history row past the pane width and
    clipped the trailing weight gauge off the end.
    """
    if count < 1_000:
        return str(count)
    for unit, scale in (("k", 1_000), ("M", 1_000_000), ("G", 1_000_000_000)):
        scaled = count / scale
        if scaled < 999.95:  # 999.9k is six columns; 1000.0k would be seven
            return f"{scaled:.1f}{unit}"
    # Nothing real reaches this, but a corrupted record must not be the one
    # thing that pushes a row past the pane width.
    return ">999G"


def format_duration(seconds: float | None) -> str:
    """M:SS, or H:MM:SS past an hour — the one duration format the whole
    panel uses (subagent durations, the session-elapsed timer)."""
    if seconds is None:
        return "?"
    minutes, secs = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_clock(epoch: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(epoch)) if epoch else "--:--"



def session_started_at(session_id: str | None) -> float | None:
    """First-seen SessionStart timestamp for this exact session_id, recorded
    by claude_profile_hook.py — untouched by later compact/resume events for
    the same session, unlike its 'updated' field."""
    if not session_id:
        return None
    try:
        sessions = json.loads(plugin_state_path("profiles.json").read_text(encoding="utf-8")).get("sessions", {})
    except (OSError, ValueError):
        return None
    entry = sessions.get(session_id) if isinstance(sessions, dict) else None
    started = entry.get("started") if isinstance(entry, dict) else None
    return started if isinstance(started, (int, float)) else None


def session_ended_at(session_id: str | None, runtime: str | None = None) -> float | None:
    """When this session ended, if it has. profiles.json (Claude's and
    Codex's SessionEnd hook) is the first source, and a SessionStart for the
    same ID rebuilds its record without this field, so resuming a session
    brings it back to life.

    Runtimes with no SessionEnd hook — Pi — never get a profiles.json entry,
    so fall back to the canonical snapshot, which Pi's companion extension
    updates on its own shutdown event. Raw session ids can collide across
    runtimes, so the fallback is keyed by (runtime, raw id), never raw id
    alone.
    """
    if not session_id:
        return None
    try:
        sessions = json.loads(plugin_state_path("profiles.json").read_text(encoding="utf-8")).get("sessions", {})
    except (OSError, ValueError):
        sessions = {}
    entry = sessions.get(session_id) if isinstance(sessions, dict) else None
    ended = entry.get("ended") if isinstance(entry, dict) else None
    if isinstance(ended, (int, float)):
        return ended
    if not runtime:
        return None
    snapshot = store.read_snapshot()
    if not snapshot.available:
        return None
    try:
        canonical_id = ids.session_id(runtime, session_id)
    except ValueError:
        return None
    record = snapshot.sessions.get(canonical_id)
    if not isinstance(record, dict):
        return None
    if record.get("status") != "ended" and record.get("presence") != "ended":
        return None
    observed = record.get("observed_at")
    return observed if isinstance(observed, (int, float)) else None


GEAR_CHIP = " ⚙ ajustes "
GEAR_CHIP_ENDED = " ⚙ finalizada "
CLOSE_SHORT = " ^C"


def header_hint(session_ended: bool, subtitle_width: int, width: int) -> tuple[str, int]:
    """The right-hand end of the header row, and its VISIBLE width.

    The gear rides an inverted chip — the same background the historial
    already zebra-stripes with — because a grey glyph at the end of a grey
    line does not read as something you can click, and that is exactly how
    the settings menu went unnoticed. Escapes make len() useless here, so the
    visible width comes back separately for the caller's padding.

    The chip is never what gets dropped when the pane is narrow: the close
    shortcut goes first.
    """
    chip = GEAR_CHIP_ENDED if session_ended else GEAR_CHIP
    rendered = f"{BG_ROW}{BOLD}{chip}{RESET}"
    if width >= subtitle_width + 1 + len(chip) + len(CLOSE_SHORT):
        return f"{rendered}{DIM}{CLOSE_SHORT}{RESET}", len(chip) + len(CLOSE_SHORT)
    return rendered, len(chip)


def problem_band(groups: list[tuple[dict[str, Any], list[dict[str, Any]]]],
                 ended_sessions: set[str], width: int) -> str | None:
    """One row naming what is stuck, or None when nothing is.

    A blocked subagent used to be one coloured dot in a list of coloured
    dots, halfway down a panel nobody reads closely. What holds up the work
    belongs at the top, with a name on it.
    """
    stuck: list[tuple[str, str]] = []
    for root, children in groups:
        ended = session_id_for(root) in ended_sessions
        for child in children:
            status = stale_status(str(child.get("agent_status", "unknown")), ended)
            if status in ("blocked", "interrupted"):
                stuck.append((status, str(child.get("name", "subagent"))))
    if not stuck:
        return None
    kind = "blocked" if any(s == "blocked" for s, _ in stuck) else "interrupted"
    words = {"blocked": ("bloqueado", "bloqueados"), "interrupted": ("interrumpido", "interrumpidos")}
    relevant = [name for status, name in stuck if status == kind]
    label = words[kind][0] if len(relevant) == 1 else words[kind][1]
    head = f"{COLORS[kind]}▎{RESET} {COLORS[kind]}{BOLD}{len(relevant)} {label}{RESET}"
    names = ", ".join(dict.fromkeys(relevant))
    return f"{head}{DIM} · {clip(names, max(1, width - len(str(len(relevant))) - len(label) - 6))}{RESET}"


def session_duration(started: float | None, ended: float | None, now: float) -> float | None:
    """Elapsed session time — frozen at the end for a finished session.

    Left ticking, the header would claim a session that exited an hour ago is
    still an hour longer than it ever ran.
    """
    if started is None:
        return None
    return (ended if ended is not None else now) - started


def stale_status(status: str, session_ended: bool) -> str:
    """A subagent still marked "working" when its session ended never got a
    SubagentStop — the agent CLI was killed out from under it. Report that as
    interrupted instead of animating a spinner for a process that is gone.
    """
    return "interrupted" if session_ended and status == "working" else status


def wrap_stats(parts: list[str], width: int) -> list[str]:
    """Greedily pack "LABEL value" segments onto as many lines as needed —
    the footer's numbers grow without bound (more agents, tokens, artifacts),
    so a single fixed-width line would eventually clip; wrapping instead
    guarantees nothing is ever cut off.
    """
    lines: list[str] = []
    current = ""
    for part in parts:
        candidate = part if not current else f"{current} · {part}"
        if len(candidate) > width and current:
            lines.append(current)
            current = part
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def tool_tally_text(tools: dict[str, Any]) -> str:
    ranked = sorted(tools.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{name}×{count}" for name, count in ranked)


def _detail_line(prefix: str, text: str, highlighted: bool, width: int) -> str:
    text = clip(f"{prefix}{text}", max(1, width - 6))
    if highlighted:
        # Same 4-space indent as the non-highlighted branch below (2 here +
        # 2 more after the background starts) — it was 6 before (2 + 4),
        # so highlighted detail lines sat two columns further right and the
        # left edge looked jagged scanning down the list.
        pad = " " * max(0, (width - 4) - (4 + len(text)))
        return f"  {BG_ROW}  {text}{pad}"
    return f"    {DIM}{text}{RESET}"


def historial_detail_lines(
    record: dict[str, Any],
    highlighted: bool,
    width: int,
    task_segment_max: int = 32,
    detail_level: str = "compact",
) -> list[str]:
    """Advanced per-subagent detail — what it was actually asked to do
    (agent_type/name is just a generic category like "general-purpose", not
    a task description), which tools it called, whether it delegated to a
    nested subagent of its own, and its final reply. Entirely absent (no
    field recorded — history predating this feature, or a subagent that used
    no tools and left no message) means no extra line at all, not an empty
    one. `detail_level` ("minimal"/"compact"/"full", see dashboard_config.py)
    controls how much of this ever renders:
      minimal: nothing — just the data row.
      compact: everything joined with " → " onto one line (the default).
      full: the task gets its own "Tarea: ..." line, the rest another.
    """
    if detail_level == "minimal":
        return []

    task = record.get("task")
    tools = record.get("tools")
    tool_uses = int(record.get("tool_uses") or 0)
    nested = int(record.get("nested_agents") or 0)
    last_message = record.get("last_message")
    has_task = isinstance(task, str) and task.strip()
    # Capped independently of the other segments — an uncapped task prompt
    # can run long enough to eat the whole line's width budget, silently
    # dropping the tools/result that follow it.
    task_text = clip(task.strip(), task_segment_max) if has_task else ""

    rest: list[str] = []
    if tool_uses and isinstance(tools, dict):
        rest.append(tool_tally_text(tools))
    if nested:
        rest.append(f"delegó a {nested}")
    if isinstance(last_message, str) and last_message.strip():
        rest.append(f"“{last_message.strip()}”")

    if detail_level == "full":
        lines: list[str] = []
        if has_task:
            lines.append(_detail_line("Tarea: ", task_text, highlighted, width))
        if rest:
            lines.append(_detail_line("", " · ".join(rest), highlighted, width))
        return lines

    parts = ([task_text] if has_task else []) + rest
    if not parts:
        return []
    return [_detail_line("", " → ".join(parts), highlighted, width)]


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def weight_bar(value: float, cells: int = None) -> str:
    """A filled/empty gauge of fixed length. Clamped, so a bad ratio can never
    push the row past the panel width.
    """
    cells = BAR_W if cells is None else cells
    filled = max(0, min(cells, round(value * cells)))
    return "▰" * filled + "▱" * (cells - filled)


def show_weight_bars(width: int) -> bool:
    """The bar is worth a column only while the name column still gets its
    minimum — on a narrow pane, knowing WHICH subagent beats knowing how
    heavy it was.
    """
    return width - 4 - (HISTORIAL_FIXED + 1 + BAR_W) >= NAME_W


def historial_name_width(width: int, bars: bool = False) -> int:
    """Give the name column whatever room the pane has to spare, instead of a
    fixed width — a wider pane should read as more spacious, not just padded
    with dead space past a fixed-width table."""
    fixed = HISTORIAL_FIXED + ((1 + BAR_W) if bars else 0)
    return max(NAME_W, width - 4 - fixed)


def historial_row(glyph_char: str, name: str, hora: str, dur: str, tok: str, name_w: int,
                  peso: str = "") -> str:
    row = f"{glyph_char} {clip(name, name_w):<{name_w}} {hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}"
    return f"{row} {peso:>{BAR_W}}" if peso else row


def historial_data_row(record: dict[str, Any], highlighted: bool, width: int,
                       max_tokens: int = 0) -> str:
    """One history row. With `max_tokens` known and the pane wide enough, a
    trailing gauge shows this subagent's token cost against the heaviest one
    of the session — turning a column of numbers into a profile you can read
    without comparing digits.
    """
    name = str(record.get("name", "?"))
    hora = format_clock(record.get("stopped"))
    dur = format_duration(record.get("duration_s"))
    tokens = int(record.get("tokens") or 0)
    tok = format_tokens(tokens)
    bars = max_tokens > 0 and show_weight_bars(width)
    name_w = historial_name_width(width, bars)
    body = f"{clip(name, name_w):<{name_w}} {hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}"
    gauge = weight_bar(tokens / max_tokens) if bars else ""
    if not highlighted:
        row = f"  {COLORS['done']}✓{RESET} {clip(name, name_w):<{name_w}} " \
              f"{DIM}{hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}{RESET}"
        return f"{row} {COLORS['idle']}{gauge}{RESET}" if gauge else row
    if gauge:
        body = f"{body} {gauge}"
    body = body.ljust(max(len(body), width - 4))
    return f"  {BG_ROW}{COLORS['done']}✓{RESET}{BG_ROW} {body}"


def hyperlink(text: str, url: str | None) -> str:
    """Wrap text in an OSC 8 terminal hyperlink when a URL is known — most
    terminals (ctrl-)click it straight through, no underline styling implied.
    """
    if not url:
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def artifact_data_row(record: dict[str, Any], highlighted: bool, width: int) -> str:
    title = str(record.get("title", "artifact"))
    kind = str(record.get("kind", "publish"))
    clock = format_clock(record.get("at"))
    url = record.get("url")
    url = url if isinstance(url, str) and url else None
    label_w = max(1, width - 2 - 1 - 1 - TIME_W - 1)
    # Clip/pad on the PLAIN label first — OSC 8 codes are invisible but not
    # zero-length as far as str padding/slicing are concerned, so the link
    # wrapping happens last, only around the already-sized text.
    label_plain = clip(f"{title} · {kind}", label_w)
    label_padded = hyperlink(label_plain, url) + " " * max(0, label_w - len(label_plain))
    if not highlighted:
        return f"  {COLORS['working']}↗{RESET} {label_padded} {DIM}{clock:>{TIME_W}}{RESET}"
    body = f"{label_padded} {clock:>{TIME_W}}"
    pad_more = " " * max(0, (width - 4) - (label_w + 1 + TIME_W))
    return f"  {BG_ROW}{COLORS['working']}↗{RESET}{BG_ROW} {body}{pad_more}"


def _escape_end(text: str, index: int) -> int | None:
    """If text[index:] opens a CSI (`\\033[...m`) or OSC (`\\033]...`, e.g. an
    OSC 8 hyperlink) escape, return the index just past it; otherwise None.
    Both kinds are zero-width for layout purposes.
    """
    if text[index] != "\033" or index + 1 >= len(text):
        return None
    following = text[index + 1]
    if following == "[":
        end = text.find("m", index + 2)
        return end + 1 if end != -1 else None
    if following == "]":
        # OSC sequences terminate with ST (ESC \) or BEL; take whichever comes first.
        st = text.find("\033\\", index + 2)
        bel = text.find("\007", index + 2)
        ends = [e for e in (st, bel) if e != -1]
        if not ends:
            return None
        end = min(ends)
        return end + 2 if end == st else end + 1
    return None


def trim_ansi(text: str, width: int) -> str:
    """Fit an ANSI/OSC-styled row without slicing an escape sequence or wrapping."""
    output: list[str] = []
    visible = 0
    index = 0
    while index < len(text) and visible < width:
        end = _escape_end(text, index)
        if end is not None:
            output.append(text[index:end])
            index = end
            continue
        output.append(text[index])
        visible += 1
        index += 1
    # Drain any trailing escape-only sequences first — a line whose real
    # content ends exactly at `width` still carries a closing reset code,
    # and that must never count as real overflow needing an ellipsis.
    while index < len(text):
        end = _escape_end(text, index)
        if end is None:
            break
        output.append(text[index:end])
        index = end
    if index < len(text) and width >= 1:
        while visible >= width:
            output.pop()
            visible -= 1
        output.append("…")
    return "".join(output) + RESET


MENU_TITLE = "⚙ AJUSTES"
MENU_CLOSE = "✕ cerrar"
MENU_BACK_HINT = "click der: atrás"
MENU_INDENT = "  "
MENU_GAP = "  "
# Rows the menu spends on its own frame before the first option — the click
# handler adds the same offset, so the two must never drift apart.
MENU_TITLE_ROWS = 1


def menu_lines(config: dict[str, Any], width: int) -> list[str]:
    """The clickable submenu: a title row that frames the block and carries
    the close affordance, then one row per MENU_OPTIONS entry in order.

    Every row is a click target, and handle_click() maps a clicked screen row
    back to this exact layout, so the order here is a contract. Columns are
    aligned (label left, value right, cycle position last) and each piece is
    dropped rather than truncated when the pane is too narrow for it — this
    panel must fit a narrow side split without ever overflowing.
    """
    label_width = max(len(MENU_LABELS[option]) for option in MENU_OPTIONS)
    value_width = max(len(str(value)) for option in MENU_OPTIONS for value in CYCLES[option])
    marker_width = max(len(f"({len(CYCLES[o])}/{len(CYCLES[o])})") for o in MENU_OPTIONS)
    row_width = len(MENU_INDENT) + label_width + len(MENU_GAP) + value_width
    show_marker = width >= row_width + len(MENU_GAP) + marker_width

    # Stretch the value/marker block to the panel's right edge (one column of
    # margin short of it — a line ending in RESET at exactly `width` reads as
    # overflow to trim_ansi and loses its last character) so the block reads
    # as a table spanning the panel, like the historial columns above it.
    lines = [menu_title_line(width)]
    for option in MENU_OPTIONS:
        current = config.get(option, CONFIG_DEFAULTS[option])
        label = MENU_LABELS[option].ljust(label_width)
        right = str(current).rjust(value_width)
        visible = row_width
        marker = ""
        if show_marker:
            place, total = cycle_position(option, current)
            marker = f"({place}/{total})"
            visible += len(MENU_GAP) + len(marker)
        stretch = max(0, width - 1 - visible)
        row = f"{MENU_INDENT}{DIM}{label}{RESET}{MENU_GAP}{' ' * stretch}{BOLD}{right}{RESET}"
        if marker:
            row += f"{MENU_GAP}{DIM}{marker}{RESET}"
        lines.append(row)
    return lines


def menu_title_line(width: int) -> str:
    """"⚙ AJUSTES" on the left, "✕ cerrar" pinned right, and the right-click
    hint squeezed in between only when it genuinely fits — at a narrow width
    the hint is the first thing to go, never the close affordance.
    """
    visible = len(MENU_INDENT) + len(MENU_TITLE)
    hint = ""
    if width >= visible + len(MENU_GAP) + len(MENU_BACK_HINT) + 1 + len(MENU_CLOSE):
        hint = f"{MENU_GAP}{DIM}{MENU_BACK_HINT}{RESET}"
        visible += len(MENU_GAP) + len(MENU_BACK_HINT)
    pad = max(1, width - visible - len(MENU_CLOSE))
    return f"{MENU_INDENT}{BOLD}{MENU_TITLE}{RESET}{hint}{' ' * pad}{DIM}{MENU_CLOSE}{RESET}"


def clip_for_menu(lines: list, footer_len: int, height: int, protect: int,
                  notice=None) -> list:
    """Keep the whole frame inside `height` while the submenu is open.

    Closed, the panel deliberately prints more than fits so the pane's own
    scrollback can reveal older agents and artifacts. Open, that would push
    the header — and with it the gear and the menu itself — off the top of
    the pane, and the row-based click mapping would stop matching what is on
    screen. So while the menu is open, rows are dropped from the end of the
    body (the oldest ones), the pinned footer is kept, and the cut is stated
    on its own row instead of silently swallowing content. `protect` is the
    header plus the menu block: in a pane too short even for those, the menu
    stays intact and the frame overflows, since a menu you cannot click is
    worse than a scrolled one.
    """
    overflow = len(lines) - height
    if overflow <= 0:
        return lines
    body = lines[: len(lines) - footer_len]
    footer = lines[len(lines) - footer_len :]
    keep = max(protect, len(body) - overflow - 1)  # -1 for the notice row below
    hidden = len(body) - keep
    if hidden <= 0:
        return lines
    make = notice or (lambda count: f"  {DIM}+{count} filas ocultas{RESET}")
    return [*body[:keep], make(hidden), *footer]


@dataclass
class Frame:
    """One drawn panel: the text to write, and which row carries which click
    target. Targets are derived AFTER the viewport clip, so a click always
    resolves against the rows the user is actually looking at.
    """

    text: str
    targets: dict[int, str]


def activity_line(child: dict[str, Any], last: bool, now: float) -> str | None:
    """How long a live subagent has been running, on its own dim line.

    The live tree says that something is happening, not what — but the only
    live fact the hooks record per subagent is its start time, so that is all
    this claims. A subagent with no recorded start says nothing rather than
    showing an invented elapsed time.
    """
    started = child.get("started")
    if not isinstance(started, (int, float)):
        return None
    stem = "     " if last else "  \u2502  "
    return f"{stem}{DIM}corriendo {format_duration(max(0.0, now - started))}{RESET}"


def section_header(title: str, count: int, collapsed: bool) -> str:
    marker = "\u25b8" if collapsed else "\u25be"
    return f"{COLORS['working']}{marker}{RESET} {BOLD}{title}{RESET}  {DIM}{count}{RESET}"


def render_frame(
    snapshot: dict[str, Any] | None,
    frame: int,
    width: int,
    height: int | None = None,
    menu_open: bool = False,
    now: float | None = None,
) -> Frame:
    width = max(26, width)
    now = time.time() if now is None else now
    rule = "\u2500" * width

    def only(text: str) -> Frame:
        return Frame(text=text, targets={})

    if snapshot is None:
        return only(f"{COLORS['blocked']}\u25cf conexi\u00f3n no disponible{RESET}")

    config = load_config()

    # A side pane must follow its own workspace, even when the user has focused
    # a different Herdr workspace elsewhere in the client.
    active_workspace = os.environ.get("HERDR_WORKSPACE_ID") or snapshot.get("focused_workspace_id")
    leaders = [
        agent for agent in snapshot.get("agents", [])
        if agent.get("agent") in RECOGNIZED_AGENTS and agent.get("workspace_id") == active_workspace
    ]
    if not leaders:
        # No panel at all rather than a hollow one. There used to be a
        # cwd-matching fallback here that recovered a Claude session from
        # profiles.json when Herdr detected nothing — but cwd is shared by
        # every past session in a project directory, so what it actually
        # produced in an agent-less pane was some unrelated session's
        # history and artifacts, presented as if they were this pane's.
        return only(idle_screen(width, height, frame))

    roots = sorted(leaders, key=lambda agent: (not agent.get("focused", False), agent.get("pane_id", "")))
    groups = [(root, hook_children(session_id_for(root))) for root in roots]
    ended_sessions = {
        sid
        for root in roots
        if (sid := session_id_for(root)) and session_ended_at(sid, root.get("agent")) is not None
    }

    # rows carry their own click target, so folding a section or raising the
    # problem band can never shift a target onto the wrong row.
    rows: list[tuple[str, str | None]] = []

    # The pane's own Herdr chrome already shows "Claude Agents" as its title
    # (herdr-plugin.toml's [[panes]] title) - printing it again here would be
    # a redundant duplicate, so the subtitle carries the close hint instead.
    subtitle = str(
        roots[0].get("terminal_title_stripped") or roots[0].get("display_agent") or roots[0].get("agent") or "agente"
    )
    # Once the agent CLI exits, everything below is a post-mortem, not a live
    # view: say so in the header and stop the clock, instead of leaving a
    # ticking duration that keeps claiming a session which is already gone.
    ended_at = session_ended_at(session_id_for(roots[0]), roots[0].get("agent"))
    elapsed = session_duration(session_started_at(session_id_for(roots[0])), ended_at, now)
    if elapsed is not None:
        subtitle = f"{subtitle}   \u00b7   {format_duration(elapsed)}"
    hint, hint_width = header_hint(ended_at is not None, len(subtitle), width)
    header_pad = max(1, width - len(subtitle) - hint_width)
    # The whole header row is one click target (it toggles the submenu).
    rows.append((f"{DIM}{subtitle}{RESET}{' ' * header_pad}{hint}", TARGET_MENU))

    menu = menu_lines(config, width) if menu_open else []
    for index, line in enumerate(menu):
        target = TARGET_MENU_CLOSE if index < MENU_TITLE_ROWS else option_target(
            MENU_OPTIONS[index - MENU_TITLE_ROWS]
        )
        rows.append((line, target))

    band = problem_band(groups, ended_sessions, width)
    if band is not None:
        rows.append((band, None))

    rows.append((rule, None))
    for root_index, (root, child_rows) in enumerate(groups):
        if root_index:
            rows.append(("", None))
        # Herdr's last screen-derived status is whatever the pane happened to
        # show when the agent died - "working", usually. The session's own end
        # marker is the authority here, for the root and for every child that
        # never got its SubagentStop.
        session_ended = session_id_for(root) in ended_sessions
        status = "ended" if session_ended else root.get("agent_status", "unknown")
        rows.append((
            f"{COLORS.get(status, COLORS['unknown'])}{glyph(status, frame)}{RESET} {BOLD}{title_for(root)}{RESET} "
            f"{COLORS.get(status, COLORS['unknown'])}{status}{RESET}",
            None,
        ))
        for index, child in enumerate(child_rows):
            status = stale_status(child.get("agent_status", "unknown"), session_ended)
            last = index == len(child_rows) - 1
            branch = "\u2514\u2500" if last else "\u251c\u2500"
            rows.append((
                f"  {branch} {COLORS.get(status, COLORS['unknown'])}{glyph(status, frame)}{RESET} "
                f"{subagent_label(child)} {DIM}{status}{RESET}",
                None,
            ))
            if status == "working":
                activity = activity_line(child, last, now)
                if activity is not None:
                    rows.append((activity, None))

    session_ids = {sid for sid in (session_id_for(root) for root in roots) if sid}
    history, history_total = session_history(session_ids, limit=int(config["history_limit"]))
    artifacts = session_artifacts(session_ids, limit=int(config["artifacts_limit"]))
    # No trailing RESET here: trim_ansi() appends its own RESET per line, and
    # one right after exactly `width` visible dashes would leave a dangling
    # escape that trim_ansi mistakes for real overflow, chopping the last
    # dash into an ellipsis.
    dim_rule = f"{DIM}{rule}"
    footer_len = 0

    if history:
        collapsed = bool(config.get("history_collapsed", 0))
        rows.extend([("", None), (dim_rule, None)])
        rows.append((section_header("HISTORIAL DE SESI\u00d3N", history_total, collapsed),
                     TARGET_SECTION_HISTORY))
        if not collapsed:
            max_tokens = max((int(r.get("tokens") or 0) for r in history), default=0)
            bars = max_tokens > 0 and show_weight_bars(width)
            header = historial_row(
                " ", "agente", "hora", "dur.", "tokens",
                historial_name_width(width, bars), "peso" if bars else "",
            )
            rows.extend([("", None), (f"  {DIM}{header}{RESET}", None)])
            for index, record in enumerate(history):
                highlighted = index % 2 == 1
                rows.append((historial_data_row(record, highlighted, width, max_tokens), None))
                rows.extend(
                    (line, None)
                    for line in historial_detail_lines(
                        record, highlighted, width,
                        task_segment_max=int(config["task_segment_max"]),
                        detail_level=str(config["detail_level"]),
                    )
                )
            remaining = history_total - len(history)
            if remaining > 0:
                rows.append((f"  {DIM}+{remaining} m\u00e1s{RESET}", None))

    if artifacts:
        collapsed = bool(config.get("artifacts_collapsed", 0))
        rows.extend([("", None), (dim_rule, None)])
        rows.append((section_header("ARTIFACTS", len(artifacts), collapsed),
                     TARGET_SECTION_ARTIFACTS))
        if not collapsed:
            for index, record in enumerate(artifacts):
                rows.append((artifact_data_row(record, index % 2 == 1, width), None))

    if history or artifacts:
        total_tokens = sum(int(r.get("tokens") or 0) for r in history)
        total_duration = sum(r.get("duration_s") or 0 for r in history)
        stats = [
            f"AG {len(history)}",
            f"TOK {format_tokens(total_tokens)}",
            f"ART {len(artifacts)}",
            f"DUR {format_duration(total_duration)}",
        ]
        footer = [dim_rule] + [
            f"{' ' * max(0, (width - len(stat_line)) // 2)}{DIM}{stat_line}{RESET}"
            for stat_line in wrap_stats(stats, width)
        ]
        # Pin the summary to the pane's last row instead of letting it float
        # right under a short history - pad with blank lines up to the
        # viewport height, then the footer, so it always sits at the bottom.
        if height is not None:
            filler = max(0, height - len(rows) - 1 - len(footer))
            rows.extend([("", None)] * filler)
        rows.extend([("", None)] + [(line, None) for line in footer])
        footer_len = 1 + len(footer)

    if menu and height is not None:
        rows = clip_for_menu(
            rows, footer_len, height, protect=1 + len(menu),
            notice=lambda hidden: (f"  {DIM}+{hidden} filas ocultas{RESET}", None),
        )

    text = "\n".join(trim_ansi(line, width) for line, _target in rows)
    targets = {index: target for index, (_line, target) in enumerate(rows) if target}
    return Frame(text=text, targets=targets)


def render(
    snapshot: dict[str, Any] | None,
    frame: int,
    width: int,
    height: int | None = None,
    menu_open: bool = False,
) -> str:
    """The drawn panel without its click map, for callers that only display."""
    return render_frame(snapshot, frame, width, height, menu_open).text


MOUSE_SGR_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")


def mouse_button(code: int) -> int:
    """Which button an SGR event reports, with the shift/alt/ctrl modifier
    bits masked off (0 = left, 1 = middle, 2 = right).
    """
    return code & 0b11


def handle_click(row_1indexed: int, targets: dict[int, str], menu_open: bool,
                 button: int = 0) -> bool:
    """Act on a click and return the menu's new open state.

    The clicked row is resolved through the frame's own target map, so what
    happens depends on what was drawn there rather than on a row number
    fixed in advance - which is what lets sections fold and the problem band
    appear without a click ever landing on the wrong control. A row with no
    target does nothing.

      header        toggles the settings menu
      menu title    closes it ("cerrar" lives there)
      menu option   cycles its value; the right button cycles backwards
      section head  folds or unfolds that section

    Every value written goes straight to config.json, the single source of
    truth render() reads back on the next frame.
    """
    target = targets.get(row_1indexed - 1)  # 0-indexed to match the drawn rows
    if target is None:
        return menu_open
    if target == TARGET_MENU:
        return not menu_open
    if target == TARGET_MENU_CLOSE:
        return False
    if target.startswith("option."):
        option = target.removeprefix("option.")
        if option not in MENU_OPTIONS:
            return menu_open
        config = load_config()
        step = -1 if mouse_button(button) == 2 else 1
        config[option] = cycle_value(option, config.get(option, CONFIG_DEFAULTS[option]), step)
        save_config(config)
        return menu_open
    if target.startswith("section."):
        key = target.removeprefix("section.")
        if key not in SECTION_KEYS:
            return menu_open
        config = load_config()
        config[key] = 0 if config.get(key, 0) else 1
        save_config(config)
        return menu_open
    return menu_open


def usable_columns(columns: int) -> int:
    """Draw one column short of what the terminal reports.

    Measured in the real pane: a row built at exactly `columns` loses its
    last character on screen (the close shortcut renders "^" instead of
    "^C", an 8-cell gauge shows 7). A wrap test in a plain pane rules out
    double-width glyphs as the cause, so this leaves the last column unused
    rather than pretending to explain the terminal. One column of margin is
    cheap; a silently truncated row is not.
    """
    return max(26, columns - 1)


def main() -> int:
    running = True
    menu_open = False

    def stop(_signal: int, _frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    stdin_fd = sys.stdin.fileno()
    is_tty = os.isatty(stdin_fd)
    old_termios = None
    if is_tty:
        try:
            old_termios = termios.tcgetattr(stdin_fd)
            tty.setcbreak(stdin_fd)  # so mouse-click bytes arrive immediately, unbuffered by line
        except (termios.error, OSError):
            old_termios = None

    sys.stdout.write("\033[?25l")
    if is_tty:
        sys.stdout.write("\033[?1000h\033[?1006h")  # enable SGR mouse click reporting
    sys.stdout.flush()
    try:
        frame = 0
        last_output: str | None = None
        while running:
            size = shutil.get_terminal_size((42, 24))
            drawn = render_frame(
                read_snapshot(), frame, usable_columns(size.columns), size.lines,
                menu_open=menu_open,
            )
            output = drawn.text
            if output != last_output:
                # Redraw in place (cursor home, clear only what's left over
                # below the new content) instead of blanking the whole
                # screen first — a full clear on every tick fights the
                # pane's native scrollback, yanking the view back down if
                # the user tries to scroll up through older history.
                # Skipping the redraw entirely when nothing changed (e.g.
                # the pane is idle) leaves scrollback fully in the user's
                # control between updates.
                # Each line also gets \033[K (clear to end of LINE): \033[0J
                # only clears rows strictly below the cursor, so if this
                # frame's line is shorter than what used to be on that same
                # row (numbers shrinking, or every row shifting when the
                # menu opens/closes), the old row's trailing characters
                # would otherwise bleed through untouched.
                cleared = "\033[K\n".join(output.split("\n")) + "\033[K"
                sys.stdout.write("\033[H" + cleared + "\033[0J")
                sys.stdout.flush()
                last_output = output
            frame += 1

            timeout = float(load_config()["poll_seconds"])
            if is_tty:
                ready, _, _ = select.select([stdin_fd], [], [], timeout)
                if ready:
                    try:
                        chunk = os.read(stdin_fd, 4096).decode("utf-8", "ignore")
                    except OSError:
                        chunk = ""
                    for button, _col, row, kind in (m.groups() for m in MOUSE_SGR_RE.finditer(chunk)):
                        if kind == "M":  # press, not release
                            menu_open = handle_click(int(row), drawn.targets, menu_open, int(button))
            else:
                time.sleep(timeout)
    finally:
        if is_tty:
            sys.stdout.write("\033[?1000l\033[?1006l")
        sys.stdout.write(RESET + "\033[?25h\n")
        sys.stdout.flush()
        if old_termios is not None:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_termios)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
