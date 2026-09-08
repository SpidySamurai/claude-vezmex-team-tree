"""Normalize Claude Code hook payloads into canonical runtime state.

Claude-specific field names stay in this module. Transcript paths, prompts,
token tallies, artifacts, and profile directories are deliberately not read
here: they remain legacy Claude features owned by the hook entrypoints.
"""

from __future__ import annotations

from .. import model
from ._hook_lifecycle import make_ingest

RUNTIME = "claude"
COLLECTOR = "claude-code-hooks"


def _capabilities() -> dict[str, str]:
    # Claude reports every live child through SubagentStart/SubagentStop, so its
    # activity view is complete. History and artifacts stay legacy-owned.
    return model.capabilities(
        presence="supported",
        status="partial",
        activity="complete",
        completion="supported",
        history="legacy-only",
        artifacts="legacy-only",
    )


ingest = make_ingest(RUNTIME, COLLECTOR, _capabilities)


def ingest_quietly(event: object) -> None:
    """Ingest without ever failing the surrounding hook."""
    try:
        ingest(event)
    except Exception:  # noqa: BLE001 - observability must never break a hook.
        pass
