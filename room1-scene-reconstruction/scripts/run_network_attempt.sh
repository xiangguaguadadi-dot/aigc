#!/usr/bin/env bash
set -uo pipefail

if [[ $# -lt 3 ]]; then
    echo "usage: $0 LOG_FILE TIMEOUT_SECONDS COMMAND [ARG ...]" >&2
    exit 64
fi

log_file=$1
timeout_seconds=$2
shift 2

mkdir -p "$(dirname "$log_file")"
if [[ -e "$log_file" ]]; then
    echo "refusing to overwrite existing log: $log_file" >&2
    exit 73
fi

started_at=$(date --iso-8601=seconds)
started_epoch=$(date +%s)

set +e
{
    printf 'started_at=%s\n' "$started_at"
    printf 'cwd=%s\n' "$PWD"
    printf 'command=timeout %q ' "$timeout_seconds"
    printf '%q ' "$@"
    printf '\n'
    timeout "$timeout_seconds" "$@"
} 2>&1 | tee "$log_file"
pipeline_status=("${PIPESTATUS[@]}")
set -e

command_status=${pipeline_status[0]}
tee_status=${pipeline_status[1]}
elapsed_seconds=$(( $(date +%s) - started_epoch ))

if [[ "$command_status" -eq 0 ]]; then
    error_category=none
elif [[ "$command_status" -eq 130 ]] || [[ "$tee_status" -eq 130 ]]; then
    error_category=operator_cancelled
elif rg -qi 'HTTP[^0-9]*404|repository not found|invalid credentials|authentication failed|permission denied|access denied' "$log_file"; then
    error_category=deterministic
elif [[ "$command_status" -eq 124 ]] || rg -qi 'timed out|operation too slow|timeout: the monitored command' "$log_file"; then
    error_category=timeout
elif rg -qi 'connection reset|connection was reset|recv failure' "$log_file"; then
    error_category=connection_reset
elif rg -qi 'HTTP/2.*framing|curl 16|stream.*not closed cleanly' "$log_file"; then
    error_category=http2_framing
elif rg -qi 'TLS|SSL.*(connect|read|error)|unexpected eof' "$log_file"; then
    error_category=tls_interruption
elif rg -qi 'could not resolve|temporary failure in name resolution|name or service not known' "$log_file"; then
    error_category=dns_failure
else
    error_category=other
fi

{
    printf 'elapsed_seconds=%s\n' "$elapsed_seconds"
    printf 'PIPESTATUS[0]=%s\n' "$command_status"
    printf 'PIPESTATUS[1]=%s\n' "$tee_status"
    printf 'error_category=%s\n' "$error_category"
    printf 'finished_at=%s\n' "$(date --iso-8601=seconds)"
} >> "$log_file"
printf 'elapsed_seconds=%s\nPIPESTATUS[0]=%s\nPIPESTATUS[1]=%s\nerror_category=%s\n' \
    "$elapsed_seconds" "$command_status" "$tee_status" "$error_category"

if [[ "$tee_status" -ne 0 ]]; then
    exit "$tee_status"
fi
exit "$command_status"
