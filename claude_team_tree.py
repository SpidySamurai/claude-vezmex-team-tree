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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from dashboard_config import (  # noqa: E402
    CYCLES,
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
}
STATIC = {"idle": "●", "done": "✓", "blocked": "●", "unknown": "?"}
# Agent-agnostic: any of these get the dashboard, not just Claude — matches
# the same design already applied to herdr_agent_tree.py's sidebar tokens.
RECOGNIZED_AGENTS = {"claude", "codex", "pi"}
BG_ROW = "\033[48;5;237m"  # zebra-stripe background for every other list row
NAME_W = 15
TIME_W = 5
DUR_W = 5
TOK_W = 6


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
    if not session_id:
        return []
    path = plugin_state_path("subagents.json")
    try:
        agents = json.loads(path.read_text(encoding="utf-8"))["sessions"].get(session_id, {})
        if not isinstance(agents, dict):
            return []
        children = [
            {"id": str(agent_id), "name": str(item["name"]), "agent_status": str(item["status"])}
            for agent_id, item in agents.items()
            if isinstance(item, dict) and "name" in item and "status" in item
        ]
        return sorted(children, key=lambda child: (child["name"].casefold(), child["id"]))
    except (OSError, ValueError, KeyError, TypeError):
        return []


def hook_leader(snapshot: dict[str, Any], workspace_id: str | None) -> dict[str, Any] | None:
    """Recover a Claude leader when Herdr's screen detector has no live agent.

    Claude's SessionStart hook reports its session and cwd directly, so it is a
    safer fallback than treating an old screen-derived ``agent_session`` as
    current.  The newest matching cwd wins when a workspace has several panes.
    """
    cwd_values = {
        pane.get("cwd")
        for pane in snapshot.get("panes", [])
        if pane.get("workspace_id") == workspace_id and isinstance(pane.get("cwd"), str)
    }
    try:
        sessions = json.loads(plugin_state_path("profiles.json").read_text(encoding="utf-8")).get("sessions", {})
        candidates = [
            (session_id, item)
            for session_id, item in sessions.items()
            if isinstance(session_id, str)
            and isinstance(item, dict)
            and item.get("cwd") in cwd_values
            and isinstance(item.get("transcript_path"), str)
            and Path(item["transcript_path"]).is_file()
        ]
    except (OSError, ValueError, TypeError):
        return None
    if not candidates:
        return None
    session_id, item = max(candidates, key=lambda candidate: float(candidate[1].get("updated", 0)))
    return {
        "agent": "claude",
        "agent_session": {"value": session_id},
        "agent_status": "unknown",
        "display_agent": "Claude Code (hook)",
        "workspace_id": workspace_id,
        "cwd": item["cwd"],
        "pane_id": "hook-session",
    }


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
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)


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


def historial_name_width(width: int) -> int:
    """Give the name column whatever room the pane has to spare, instead of a
    fixed width — a wider pane should read as more spacious, not just padded
    with dead space past a fixed-width table."""
    fixed = 1 + TIME_W + 1 + DUR_W + 1 + TOK_W  # separators + the other columns
    return max(NAME_W, width - 4 - fixed)


def historial_row(glyph_char: str, name: str, hora: str, dur: str, tok: str, name_w: int) -> str:
    return f"{glyph_char} {clip(name, name_w):<{name_w}} {hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}"


def historial_data_row(record: dict[str, Any], highlighted: bool, width: int) -> str:
    name = str(record.get("name", "?"))
    hora = format_clock(record.get("stopped"))
    dur = format_duration(record.get("duration_s"))
    tok = format_tokens(int(record.get("tokens") or 0))
    name_w = historial_name_width(width)
    if not highlighted:
        return (
            f"  {COLORS['done']}✓{RESET} {clip(name, name_w):<{name_w}} "
            f"{DIM}{hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}{RESET}"
        )
    body = f"{clip(name, name_w):<{name_w}} {hora:>{TIME_W}} {dur:>{DUR_W}} {tok:>{TOK_W}}"
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


def clip_for_menu(lines: list[str], footer_len: int, height: int, protect: int) -> list[str]:
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
    return [*body[:keep], f"  {DIM}+{hidden} filas ocultas{RESET}", *footer]


def render(
    snapshot: dict[str, Any] | None,
    frame: int,
    width: int,
    height: int | None = None,
    menu_open: bool = False,
) -> str:
    width = max(26, width)
    rule = "─" * width
    if snapshot is None:
        return f"{COLORS['blocked']}● conexión no disponible{RESET}"

    config = load_config()

    # A side pane must follow its own workspace, even when the user has focused
    # a different Herdr workspace elsewhere in the client.
    active_workspace = os.environ.get("HERDR_WORKSPACE_ID") or snapshot.get("focused_workspace_id")
    leaders = [
        agent for agent in snapshot.get("agents", [])
        if agent.get("agent") in RECOGNIZED_AGENTS and agent.get("workspace_id") == active_workspace
    ]
    unrecognized_agent_here = any(
        agent.get("workspace_id") == active_workspace and agent.get("agent") not in ({None} | RECOGNIZED_AGENTS)
        for agent in snapshot.get("agents", [])
    )
    if not leaders and not unrecognized_agent_here:
        # The cwd-matching fallback below is Claude-specific (it reads
        # claude_profile_hook.py's own profiles.json) and only safe when
        # Herdr found no agent at all here (a real Claude session it failed
        # to detect) — if it confidently detected any OTHER kind, guessing
        # by cwd would leak an unrelated session's history/artifacts in
        # here (cwd is shared across many past sessions in the same
        # project directory).
        fallback = hook_leader(snapshot, active_workspace)
        leaders = [fallback] if fallback else []
    if not leaders:
        return f"{DIM}No hay un agente reconocido aquí{RESET}"

    roots = sorted(leaders, key=lambda agent: (not agent.get("focused", False), agent.get("pane_id", "")))
    groups = [(root, hook_children(session_id_for(root))) for root in roots]

    # The pane's own Herdr chrome already shows "Claude Agents" as its title
    # (herdr-plugin.toml's [[panes]] title) — printing it again here would be
    # a redundant duplicate, so the subtitle carries the close hint instead.
    # The whole header row is one click target (toggles the submenu below) —
    # main()'s click handler always maps row 0 to this, regardless of exactly
    # where the eye lands on it, so the ⚙ here is a visual hint, not a
    # precise hitbox.
    gear = "⚙ "
    hint = f"{gear}ctrl-c para cerrar"
    subtitle = str(
        roots[0].get("terminal_title_stripped") or roots[0].get("display_agent") or roots[0].get("agent") or "agente"
    )
    started_at = session_started_at(session_id_for(roots[0]))
    if started_at is not None:
        subtitle = f"{subtitle}   ·   {format_duration(time.time() - started_at)}"
    header_pad = max(1, width - len(subtitle) - len(hint))
    lines = [
        # No trailing RESET: this line's visible length often lands exactly on
        # `width` (see dim_rule above for why that's unsafe here).
        f"{DIM}{subtitle}{RESET}{' ' * header_pad}{DIM}{hint}",
    ]
    menu = menu_lines(config, width) if menu_open else []
    lines.extend(menu)
    lines.append(rule)
    for root_index, (root, child_rows) in enumerate(groups):
        if root_index:
            lines.append("")
        status = root.get("agent_status", "unknown")
        lines.append(
            f"{COLORS.get(status, COLORS['unknown'])}{glyph(status, frame)}{RESET} {BOLD}{title_for(root)}{RESET} "
            f"{COLORS.get(status, COLORS['unknown'])}{status}{RESET}"
        )
        for index, child in enumerate(child_rows):
            status = child.get("agent_status", "unknown")
            branch = "└─" if index == len(child_rows) - 1 else "├─"
            lines.append(
                f"  {branch} {COLORS.get(status, COLORS['unknown'])}{glyph(status, frame)}{RESET} "
                f"{subagent_label(child)} {DIM}{status}{RESET}"
            )
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
        header = historial_row(" ", "agente", "hora", "dur.", "tokens", historial_name_width(width))
        lines.extend(
            [
                "",
                dim_rule,
                f"{BOLD}HISTORIAL DE SESIÓN{RESET}",
                "",
                f"  {DIM}{header}{RESET}",
            ]
        )
        for index, record in enumerate(history):
            highlighted = index % 2 == 1
            lines.append(historial_data_row(record, highlighted, width))
            lines.extend(
                historial_detail_lines(
                    record, highlighted, width,
                    task_segment_max=int(config["task_segment_max"]),
                    detail_level=str(config["detail_level"]),
                )
            )
        remaining = history_total - len(history)
        if remaining > 0:
            lines.append(f"  {DIM}+{remaining} más{RESET}")

    if artifacts:
        lines.extend(["", dim_rule, f"{BOLD}ARTIFACTS{RESET}"])
        for index, record in enumerate(artifacts):
            lines.append(artifact_data_row(record, index % 2 == 1, width))

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
        # right under a short history — pad with blank lines up to the
        # viewport height, then the footer, so it always sits at the bottom.
        if height is not None:
            filler = max(0, height - len(lines) - 1 - len(footer))
            lines.extend([""] * filler)
        lines.extend(["", *footer])
        footer_len = 1 + len(footer)

    if menu and height is not None:
        lines = clip_for_menu(lines, footer_len, height, protect=1 + len(menu))

    return "\n".join(trim_ansi(line, width) for line in lines)


MOUSE_SGR_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")


def mouse_button(code: int) -> int:
    """Which button an SGR event reports, with the shift/alt/ctrl modifier
    bits masked off (0 = left, 1 = middle, 2 = right).
    """
    return code & 0b11


def handle_click(row_1indexed: int, menu_open: bool, button: int = 0) -> bool:
    """Row 0 (the panel header, where the gear sits) always toggles the
    submenu. While open, row 1 is the menu's own title row — it carries the
    "✕ cerrar" affordance, so clicking it closes — and the rows after it are
    MENU_OPTIONS in order. Cycling a value writes it straight to config.json
    (the single source of truth `render()` reads back on the next frame);
    the right button steps backwards through the cycle. Clicking below the
    menu, or anywhere while it's closed, does nothing.
    """
    row = row_1indexed - 1  # 0-indexed to match render()'s line order
    if row == 0:
        return not menu_open
    if not menu_open:
        return menu_open
    if row < 1 + MENU_TITLE_ROWS:
        return False
    option_index = row - 1 - MENU_TITLE_ROWS
    if not (0 <= option_index < len(MENU_OPTIONS)):
        return menu_open
    option = MENU_OPTIONS[option_index]
    config = load_config()
    step = -1 if mouse_button(button) == 2 else 1
    config[option] = cycle_value(option, config.get(option, CONFIG_DEFAULTS[option]), step)
    save_config(config)
    return menu_open


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
            output = render(read_snapshot(), frame, size.columns, size.lines, menu_open=menu_open)
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
                            menu_open = handle_click(int(row), menu_open, int(button))
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
