#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${NETQA_API_HOST:-127.0.0.1}"
PORT="${NETQA_API_PORT:-8000}"

exec env PYTHONPATH="$ROOT" "$ROOT/.venv/bin/uvicorn" netqa.api:app --host "$HOST" --port "$PORT" "$@"
