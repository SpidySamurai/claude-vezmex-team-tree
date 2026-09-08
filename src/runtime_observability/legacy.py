"""Compatibility reads for the existing live subagents.json state file."""

from __future__ import annotations

import json
from typing import Any

from . import model, paths


def children_for_session(session_id: str | None) -> list[dict[str, Any]]:
    if not isinstance(session_id, str) or not session_id:
        return []
    try:
        state = json.loads(paths.legacy_subagents_path().read_text(encoding="utf-8"))
        raw_agents = state["sessions"].get(session_id, {})
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return []
    if not isinstance(raw_agents, dict):
        return []
    children: list[dict[str, Any]] = []
    for agent_id, item in raw_agents.items():
        if not isinstance(item, dict) or "name" not in item or "status" not in item:
            continue
        child = {
            "id": str(agent_id),
            "name": str(item["name"]),
            "agent_status": model.normalize_status(item.get("status")),
            "source": "legacy",
        }
        if isinstance(item.get("started"), (int, float)):
            child["started"] = item["started"]
        children.append(child)
    return sorted(children, key=lambda child: (child["name"].casefold(), child["id"]))
