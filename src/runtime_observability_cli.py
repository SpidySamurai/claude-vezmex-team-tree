#!/usr/bin/env python3
"""Ingest one Pi extension event into canonical runtime state.

The companion Pi extension (pi/herdr-agent-observability/index.ts) spawns
this process once per lifecycle/tool event and writes the event as JSON on
stdin. Schema validation and merge semantics stay in one Python
implementation instead of being duplicated in TypeScript. Always exits 0:
observability must never fail the extension's own event handling.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_observability.adapters import pi_companion  # noqa: E402


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    try:
        pi_companion.ingest(event)
    except Exception:  # noqa: BLE001 - observability must never break the caller.
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
