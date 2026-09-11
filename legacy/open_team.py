#!/usr/bin/env python3
"""Open a tracked Claude Teams leader in a new Herdr tab."""

from __future__ import annotations

import os
import subprocess


def main() -> int:
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")
    return subprocess.run(
        [
            herdr, "plugin", "pane", "open",
            "--plugin", "spidysamurai.agents-tree",
            "--entrypoint", "team", "--placement", "tab", "--focus",
        ],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
