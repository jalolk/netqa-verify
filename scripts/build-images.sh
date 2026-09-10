#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker build -t netqa/frr:10.7.1 "$ROOT/docker/frr"
docker build -t netqa/host:latest "$ROOT/docker/host"

docker images --filter reference='netqa/*' --format 'table {{.Repository}}\t{{.Tag}}\t{{.Size}}'
