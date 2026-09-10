#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INVENTORY="$ROOT/inventory.yml"

command -v sshpass >/dev/null || {
    echo "sshpass is required: apt-get install sshpass" >&2
    exit 1
}

SSH_OPTS=(
    -n
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -o ConnectTimeout=10
)

read_defaults() {
    awk '
        /^defaults:/ { in_def = 1; next }
        /^[a-z]/     { in_def = 0 }
        in_def && $1 == "username:" { print "username", $2 }
        in_def && $1 == "password:" { print "password", $2 }
    ' "$INVENTORY"
}

read_devices() {
    awk '
        /^devices:/ { in_dev = 1; next }
        /^[a-z]/    { in_dev = 0 }
        in_dev && /^  [A-Za-z0-9_-]+:/ {
            if (name != "") print name, role, host
            name = $1; sub(":", "", name); role = ""; host = ""
            next
        }
        in_dev && $1 == "role:" { role = $2 }
        in_dev && $1 == "host:" { host = $2 }
        END { if (name != "") print name, role, host }
    ' "$INVENTORY"
}

eval "$(read_defaults | awk '{ printf "%s=%s\n", $1, $2 }')"

remote() {
    local host=$1 command=$2
    sshpass -p "$password" ssh "${SSH_OPTS[@]}" "${username}@${host}" "$command"
}

collect_device() {
    local name=$1 role=$2 host=$3
    echo "=== $name ($role @ $host) ==="

    if ! remote "$host" true 2>/dev/null; then
        echo "  ERROR: unreachable over SSH"
        return 1
    fi

    remote "$host" 'ip -br -4 addr show' | sed 's/^/  /'

    if [[ $role == router ]]; then
        echo "  --- ospf neighbours ---"
        remote "$host" 'vtysh -c "show ip ospf neighbor"' | tail -n +2 | sed 's/^/  /'
        echo "  --- ospf routes ---"
        remote "$host" 'vtysh -c "show ip route ospf"' | grep -E '^O' | sed 's/^/  /' || echo "  none"
    fi
}

status=0
wanted=("$@")
while read -r name role host; do
    [[ -z $name ]] && continue
    if (( ${#wanted[@]} )) && [[ ! " ${wanted[*]} " == *" $name "* ]]; then
        continue
    fi
    collect_device "$name" "$role" "$host" || status=1
done < <(read_devices)

exit "$status"
