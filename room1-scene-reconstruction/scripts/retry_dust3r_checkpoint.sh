#!/usr/bin/env bash
set -euo pipefail

ROOT=/root/scene_recon
CHECKPOINT_DIR="$ROOT/checkpoints/planargs"
CHECKPOINT="$CHECKPOINT_DIR/DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth"
PART="$CHECKPOINT.part"
HF_DIR="$CHECKPOINT_DIR/DUSt3R_ViTLarge_BaseDecoder_512_dpt.hf"
RUNNER="$ROOT/scripts/run_network_attempt.sh"
LOG_DIR="$ROOT/logs/m2_planargs"
NAVER_URL=https://download.europe.naverlabs.com/ComputerVision/DUSt3R/DUSt3R_ViTLarge_BaseDecoder_512_dpt.pth
HF_BIN="$ROOT/tools/micromamba-root/envs/planargs/bin/hf"

check_disk() {
    local free_kb
    free_kb=$(df --output=avail -k "$ROOT" | tail -n 1 | tr -d ' ')
    printf 'disk_free_kb=%s\n' "$free_kb"
    if (( free_kb < 30 * 1024 * 1024 )); then
        echo "stopping: less than 30 GiB is available" >&2
        exit 75
    fi
}

if [[ -s "$CHECKPOINT" ]]; then
    printf 'checkpoint already exists: %s (%s bytes)\n' \
        "$CHECKPOINT" "$(stat -c %s "$CHECKPOINT")"
    exit 0
fi

mkdir -p "$CHECKPOINT_DIR" "$LOG_DIR"
printf 'retry_window_started_at=%s\n' "$(date --iso-8601=seconds)"

for attempt in 1 2 3; do
    check_disk
    log="$LOG_DIR/$((74 + attempt))_dust3r_retry2_normal_https_attempt${attempt}.log"
    if "$RUNNER" "$log" 1900 /bin/bash -lc \
        "curl --fail --location --show-error --silent --connect-timeout 30 --max-time 1800 --retry 0 --continue-at - --output '$PART' '$NAVER_URL' && mv '$PART' '$CHECKPOINT'"; then
        printf 'download_strategy=normal_https\ncheckpoint=%s\n' "$CHECKPOINT"
        exit 0
    fi
    case "$attempt" in
        1) sleep 10 ;;
        2) sleep 30 ;;
        3) sleep 90 ;;
    esac
done

for attempt in 1 2 3; do
    check_disk
    log="$LOG_DIR/$((77 + attempt))_dust3r_retry2_http11_attempt${attempt}.log"
    if "$RUNNER" "$log" 1900 /bin/bash -lc \
        "curl --http1.1 --fail --location --show-error --silent --connect-timeout 30 --max-time 1800 --retry 0 --continue-at - --output '$PART' '$NAVER_URL' && mv '$PART' '$CHECKPOINT'"; then
        printf 'download_strategy=http11\ncheckpoint=%s\n' "$CHECKPOINT"
        exit 0
    fi
    case "$attempt" in
        1) sleep 10 ;;
        2) sleep 30 ;;
        3) sleep 90 ;;
    esac
done

for attempt in 1 2 3; do
    check_disk
    log="$LOG_DIR/$((80 + attempt))_dust3r_retry2_official_hf_attempt${attempt}.log"
    if "$RUNNER" "$log" 1900 "$HF_BIN" download \
        naver/DUSt3R_ViTLarge_BaseDecoder_512_dpt \
        --local-dir "$HF_DIR" --max-workers 1; then
        printf 'download_strategy=official_huggingface\nhf_directory=%s\n' "$HF_DIR"
        exit 0
    fi
    case "$attempt" in
        1) sleep 10 ;;
        2) sleep 30 ;;
    esac
done

printf 'retry_window_finished_at=%s\n' "$(date --iso-8601=seconds)"
echo "all nine official-source attempts failed" >&2
exit 1
