"""Normalize Codex hook payloads into canonical runtime state.

The repository only verifies one Codex surface: install.py optionally wires
this same lifecycle hook shape into an existing ``~/.codex/hooks.json``, using
a ``--runtime codex`` command flag so events are attributed correctly instead
of being misread as Claude Code's. Codex's own native hooks, transcripts,
profiles, and artifact events are unverified, so this adapter declares
capabilities more conservatively than Claude's rather than assuming parity.
"""

from __future__ import annotations

from .. import model
from ._hook_lifecycle import make_ingest

RUNTIME = "codex"
COLLECTOR = "codex-hooks"


def _capabilities() -> dict[str, str]:
    return model.capabilities(
        presence="supported",
        status="partial",
        activity="partial",
        completion="unsupported",
        history="legacy-only",
        artifacts="unsupported",
    )


ingest = make_ingest(RUNTIME, COLLECTOR, _capabilities)


def ingest_quietly(event: object) -> None:
    """Ingest without ever failing the surrounding hook."""
    try:
        ingest(event)
    except Exception:  # noqa: BLE001 - observability must never break a hook.
        pass
