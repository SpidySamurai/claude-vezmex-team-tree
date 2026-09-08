"""Canonical runtime-observability identity helpers."""

from __future__ import annotations

import base64

_ALLOWED = {"claude", "codex", "pi"}
_PREFIX = "ro:v1"


def _encode(raw: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError("raw id must be a non-empty string")
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(encoded: str) -> str:
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("encoded id is malformed")
    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - invalid external state is one error class here.
        raise ValueError("encoded id is malformed") from exc


def session_id(runtime: str, raw_session_id: str) -> str:
    if runtime not in _ALLOWED:
        raise ValueError("unsupported runtime")
    return f"{_PREFIX}:{runtime}:session:{_encode(raw_session_id)}"


def raw_session_id(canonical_session_id: str) -> str:
    parts = canonical_session_id.split(":") if isinstance(canonical_session_id, str) else []
    if len(parts) != 5 or parts[:2] != ["ro", "v1"] or parts[2] not in _ALLOWED or parts[3] != "session":
        raise ValueError("canonical session id is malformed")
    return _decode(parts[4])


def runtime_of(canonical_session_id: str) -> str:
    raw_session_id(canonical_session_id)
    return canonical_session_id.split(":")[2]


def activity_id(canonical_session_id: str, raw_activity: str) -> str:
    raw_session_id(canonical_session_id)
    return f"{canonical_session_id}:activity:{_encode(raw_activity)}"


def raw_activity_id(canonical_activity_id: str) -> str:
    parts = canonical_activity_id.split(":") if isinstance(canonical_activity_id, str) else []
    if len(parts) != 7 or parts[5] != "activity":
        raise ValueError("canonical activity id is malformed")
    raw_session_id(":".join(parts[:5]))
    return _decode(parts[6])
