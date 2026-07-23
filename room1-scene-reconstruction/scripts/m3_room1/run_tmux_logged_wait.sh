#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
    echo "usage: $0 SESSION LOG_FILE COMMAND [ARG ...]" >&2
    exit 64
fi

session=$1
log_file=$2
shift 2
wrapper=/root/scene_recon/scripts/m3_room1/run_logged_immutable.sh

if tmux has-session -t "$session" 2>/dev/null; then
    echo "refusing existing tmux session: $session" >&2
    exit 73
fi
if [[ -e "$log_file" ]]; then
    echo "refusing existing log: $log_file" >&2
    exit 73
fi

tmux new-session -d -s "$session" "$wrapper" "$log_file" "$@"
echo "tmux_session_started=$session"

while tmux has-session -t "$session" 2>/dev/null; do
    sleep 5
done

if [[ ! -f "$log_file" ]]; then
    echo "tmux ended without a log: $log_file" >&2
    exit 74
fi

status=$(sed -n 's/^PIPESTATUS\[0\]=//p' "$log_file" | tail -n 1)
if [[ ! "$status" =~ ^[0-9]+$ ]]; then
    echo "log is missing a valid PIPESTATUS[0]: $log_file" >&2
    exit 74
fi
echo "tmux_session_finished=$session"
echo "logged_command_status=$status"
exit "$status"
