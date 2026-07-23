#!/usr/bin/env bash
set -uo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 LOG_FILE COMMAND [ARG ...]" >&2
    exit 64
fi

log_file=$1
shift

mkdir -p "$(dirname "$log_file")"
if [[ -e "$log_file" ]]; then
    echo "refusing to overwrite existing log: $log_file" >&2
    exit 73
fi

set +e
{
    printf 'started_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'cwd=%s\n' "$PWD"
    printf 'command='
    printf '%q ' "$@"
    printf '\n'
    if [[ -x /usr/bin/time ]]; then
        /usr/bin/time -v "$@"
    else
        echo "warning=/usr/bin/time unavailable; using Bash timing"
        time "$@"
    fi
} 2>&1 | tee "$log_file"
pipeline_status=("${PIPESTATUS[@]}")
set -e

command_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
{
    printf 'PIPESTATUS[0]=%s\n' "$command_status"
    printf 'PIPESTATUS[1]=%s\n' "$tee_status"
    printf 'finished_at=%s\n' "$(date --iso-8601=seconds)"
} >> "$log_file"
printf 'PIPESTATUS[0]=%s\nPIPESTATUS[1]=%s\n' "$command_status" "$tee_status"

if [[ "$tee_status" -ne 0 ]]; then
    exit "$tee_status"
fi
exit "$command_status"
