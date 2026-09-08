# Legacy

An earlier approach, kept only because it is not yet clear it will never be
wanted again. Nothing here is wired: no `herdr-plugin.toml` entry, no hook, no
config reference, and none of them import each other.

These files traced Claude Teams leader/child pane pairs by wrapping the
official launcher and reading its tmux invocation log
(`launch_team.sh` → `map_team_child.py` → `open_team.py`). The plugin now joins
subagents to their leader through the CLI's own lifecycle hooks and the session
id Herdr reports, which needs no launcher wrapper and no terminal reads — see
"How the tree is joined" in the top-level README.

Delete this directory when you are sure. The history keeps it either way.
