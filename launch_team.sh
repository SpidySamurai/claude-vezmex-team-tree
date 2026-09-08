#!/bin/sh
# The official launcher remains the process manager.  This wrapper adds only a
# trace file and a state file so our Herdr plugin can join each spawned child
# pane to its leader by the exact tmux split target.
set -eu

state_dir="${HERDR_PLUGIN_STATE_DIR:?Herdr plugin state directory is required}"
mkdir -p "$state_dir"
export CLAUDE_VEZMEX_TEAM_TREE_STATE="$state_dir/links.json"
export HERDR_CLAUDE_TEAMS_DEBUG="$state_dir/teams-trace.jsonl"
exec herdr-claude-teams
