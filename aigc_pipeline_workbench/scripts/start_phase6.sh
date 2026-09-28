#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
MOCK_DIR="$ROOT/mock_services"
RUNTIME_DIR="${AIGC_RUNTIME_DIR:-/tmp/aigc-phase6}"
mkdir -p "$RUNTIME_DIR"

export ARTIFACT_STORE_ROOT="$RUNTIME_DIR/artifacts"
export DATABASE_PATH="$RUNTIME_DIR/workbench.sqlite3"
export CONTROL_PLANE_BASE_URL="${CONTROL_PLANE_BASE_URL:-http://127.0.0.1:8000}"

start() {
  local name="$1"
  shift
  local project="$1"
  shift
  if pgrep -f "uvicorn .*$name" >/dev/null; then
    echo "$name already running"
  else
    echo "starting $name"
    setsid bash -c 'cd "$1" && shift; "$@"' _ "$project" "${@}" >"$RUNTIME_DIR/${name}.log" 2>&1 < /dev/null &
  fi
}

start backend "$BACKEND_DIR" uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
start mock-fast "$MOCK_DIR" uv run uvicorn mock_services.fast_service:app --host 127.0.0.1 --port 8101
start mock-slow "$MOCK_DIR" uv run uvicorn mock_services.slow_service:app --host 127.0.0.1 --port 8102
