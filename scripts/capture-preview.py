#!/usr/bin/env python3
"""Render one real dashboard frame to a committable preview.

The preview in the README is generated, never hand-drawn: it is the exact
output of `render_frame()` reading the same state the live panel reads, so it
cannot drift into showing a layout the code no longer produces.

    python3 scripts/capture-preview.py --columns 46 --lines 30

Writes docs/preview.txt (plain) and docs/preview.svg (colour preserved).
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import claude_team_tree as panel  # noqa: E402

# xterm base16, enough for what the panel actually emits
PALETTE = {
    30: "#1c1f26", 31: "#e06c75", 32: "#98c379", 33: "#e5c07b",
    34: "#61afef", 35: "#c678dd", 36: "#56b6c2", 37: "#c8ccd4",
    90: "#5c6370", 91: "#e06c75", 92: "#98c379", 93: "#e5c07b",
    94: "#61afef", 95: "#c678dd", 96: "#56b6c2", 97: "#ffffff",
}
BG = "#11141a"
FG = "#c8ccd4"
SGR = re.compile(r"\033\[([0-9;]*)m")


def spans(line: str):
    """Split one ANSI line into (text, colour, bold, inverted) spans."""
    out, pos, colour, bold, inverse = [], 0, None, False, False
    for m in SGR.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], colour, bold, inverse))
        for code in (m.group(1) or "0").split(";"):
            code = int(code or 0)
            if code == 0:
                colour, bold, inverse = None, False, False
            elif code == 1:
                bold = True
            elif code == 7:
                inverse = True
            elif code in PALETTE:
                colour = PALETTE[code]
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], colour, bold, inverse))
    return out


def to_svg(text: str, columns: int) -> str:
    cw, lh, pad = 8.4, 17.0, 14.0
    lines = text.split("\n")
    width = int(columns * cw + pad * 2)
    height = int(len(lines) * lh + pad * 2)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Agents Tree dashboard">',
        f'<rect width="{width}" height="{height}" rx="8" fill="{BG}"/>',
        '<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
        'font-size="13" xml:space="preserve">',
    ]
    for row, line in enumerate(lines):
        y = pad + lh * (row + 0.8)
        x = pad
        for chunk, colour, bold, inverse in spans(line):
            if not chunk:
                continue
            w = len(chunk) * cw
            fill = colour or FG
            if inverse:
                parts.append(
                    f'<rect x="{x:.1f}" y="{y - lh * 0.78:.1f}" width="{w:.1f}" '
                    f'height="{lh:.1f}" fill="{fill}"/>'
                )
                fill = BG
            weight = ' font-weight="600"' if bold else ""
            parts.append(
                f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}"{weight}>'
                f"{html.escape(chunk)}</text>"
            )
            x += w
    parts.append("</g></svg>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--columns", type=int, default=46)
    ap.add_argument("--lines", type=int, default=30)
    ap.add_argument("--frame", type=int, default=0)
    args = ap.parse_args()

    drawn = panel.render_frame(
        panel.read_snapshot(), args.frame, args.columns, args.lines, menu_open=False
    )
    out = ROOT / "docs"
    out.mkdir(exist_ok=True)
    plain = SGR.sub("", drawn.text)
    (out / "preview.txt").write_text(plain + "\n", encoding="utf-8")
    (out / "preview.svg").write_text(to_svg(drawn.text, args.columns) + "\n", encoding="utf-8")
    print(f"docs/preview.txt and docs/preview.svg written ({len(plain.splitlines())} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
