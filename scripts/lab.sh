#!/usr/bin/env bash
set -euo pipefail

TOPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/topology"
TOPO_FILE="$TOPO_DIR/netqa.clab.yml"

H1=clab-netqa-h1
H2=clab-netqa-h2
H2_ADDR=10.0.2.10

CLAB=(containerlab)
if [[ $EUID -ne 0 ]]; then
    CLAB=(sudo containerlab)
fi

usage() {
    cat <<USAGE
Usage: ${0##*/} <command>

  deploy     bring the topology up
  destroy    tear the topology down
  redeploy   destroy then deploy
  wait       block until the data plane converges
  status     show node and OSPF state
USAGE
}

lab_deploy() {
    "${CLAB[@]}" deploy -t "$TOPO_FILE"
}

lab_destroy() {
    "${CLAB[@]}" destroy -t "$TOPO_FILE" --cleanup
}

lab_wait() {
    local timeout="${1:-90}"
    local deadline=$(( $(date +%s) + timeout ))
    while (( $(date +%s) < deadline )); do
        if docker exec "$H1" ping -c 1 -W 1 "$H2_ADDR" >/dev/null 2>&1; then
            echo "converged in $(( timeout - (deadline - $(date +%s)) ))s"
            return 0
        fi
        sleep 1
    done
    echo "did not converge within ${timeout}s" >&2
    return 1
}

lab_status() {
    "${CLAB[@]}" inspect -t "$TOPO_FILE"
    for r in clab-netqa-r1 clab-netqa-r2; do
        echo "=== $r ==="
        docker exec "$r" vtysh -c "show ip ospf neighbor" 2>/dev/null
    done
}

case "${1:-}" in
    deploy)   lab_deploy ;;
    destroy)  lab_destroy ;;
    redeploy) lab_destroy || true; lab_deploy ;;
    wait)     lab_wait "${2:-90}" ;;
    status)   lab_status ;;
    *)        usage; exit 1 ;;
esac
