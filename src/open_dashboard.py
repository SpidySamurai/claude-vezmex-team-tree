#!/usr/bin/env python3
"""Open the dashboard as a right-hand Herdr plugin pane.

A plain split defaults to a 50/50 ratio, which is far too wide for a
history/stats readout. There is no "narrow split" option on the open call
itself (checked: plugin.pane.open ignores an extra `ratio` field), so this
grows the caller's own pane right afterward via `herdr pane resize`, which
does support a ratio delta — leaving the dashboard at DASHBOARD_RATIO of the
total split width regardless of terminal size.
"""

from __future__ import annotations

import os
import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dashboard_config import load_config  # noqa: E402


def main() -> int:
    dashboard_ratio = load_config()["dashboard_ratio"]
    pane_id = os.environ.get("HERDR_PANE_ID")
    socket_path = os.environ.get("HERDR_SOCKET_PATH")
    herdr_bin = os.environ.get("HERDR_BIN_PATH", "herdr")
    if not pane_id or not socket_path:
        print("This action must be invoked from a Herdr pane.", file=sys.stderr)
        return 2
    request = {
        "id": "claude-vezmex-team-tree:open-dashboard",
        "method": "plugin.pane.open",
        "params": {
            "plugin_id": "spidysamurai.agents-tree",
            "entrypoint": "dashboard",
            "placement": "split",
            "target_pane_id": pane_id,
            "direction": "right",
            "focus": False,
        },
    }
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(socket_path)
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        response = json.loads(client.recv(65536).decode("utf-8"))
    finally:
        client.close()
    if response.get("error"):
        print(response["error"].get("message", "Could not open dashboard"), file=sys.stderr)
        return 1
    try:
        subprocess.run(
            [
                herdr_bin, "pane", "resize",
                "--pane", pane_id,
                "--direction", "right",
                "--amount", str(0.5 - dashboard_ratio),
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass  # the dashboard still opened; a stale 50/50 split is cosmetic only
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
