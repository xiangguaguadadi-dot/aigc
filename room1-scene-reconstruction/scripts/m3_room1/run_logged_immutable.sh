#!/usr/bin/env bash
set -uo pipefail

if [[ $# -lt 2 ]]; then
    echo "usage: $0 LOG_FILE COMMAND [ARG ...]" >&2
    exit 64
fi

workspace=/root/scene_recon
log_root=$workspace/logs/m3_room1
log_file=$1
shift

case "$log_file" in
    "$log_root"/*.log) ;;
    *)
        echo "log must be an absolute .log path under $log_root" >&2
        exit 64
        ;;
esac
if [[ -e "$log_file" ]]; then
    echo "refusing to overwrite immutable log: $log_file" >&2
    exit 73
fi

mkdir -p "$log_root"
umask 022

run_command() {
    local available_gb
    printf 'started_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'cwd=%s\n' "$PWD"
    printf 'command='
    printf '%q ' "$@"
    printf '\n'
    available_gb=$(df --output=avail -BG "$workspace" | tail -n 1 | tr -dc '0-9')
    printf 'disk_available_gb=%s\n' "$available_gb"
    printf 'disk_threshold_gb=30\n'
    if (( available_gb < 30 )); then
        echo "free disk space is below 30 GB" >&2
        return 75
    fi
    if [[ -x /usr/bin/time ]]; then
        /usr/bin/time -v "$@"
    else
        echo "warning=/usr/bin/time unavailable; using Bash timing"
        time "$@"
    fi
}

set +e
run_command "$@" 2>&1 | tee "$log_file"
pipeline_status=("${PIPESTATUS[@]}")
set -e

command_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
{
    printf 'PIPESTATUS[0]=%s\n' "$command_status"
    printf 'PIPESTATUS[1]=%s\n' "$tee_status"
    printf 'finished_at=%s\n' "$(date --iso-8601=seconds)"
} >> "$log_file"
chmod 0444 "$log_file"
printf 'PIPESTATUS[0]=%s\nPIPESTATUS[1]=%s\n' "$command_status" "$tee_status"

if [[ "$tee_status" -ne 0 ]]; then
    exit "$tee_status"
fi
exit "$command_status"
