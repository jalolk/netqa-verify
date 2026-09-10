from __future__ import annotations

import argparse
import json
import sys

from netqa.cli import CliDevice, CliError
from netqa.inventory import load_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect state from lab devices over SSH")
    parser.add_argument("devices", nargs="*", help="device names (default: all)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    inventory = load_inventory()
    selected = args.devices or list(inventory)

    unknown = [name for name in selected if name not in inventory]
    if unknown:
        parser.error(f"unknown device(s): {', '.join(unknown)}")

    report: dict[str, object] = {}
    for name in selected:
        device = inventory[name]
        try:
            with CliDevice(device) as cli:
                entry: dict[str, object] = {"addresses": cli.get_addresses()}
                if device.is_router:
                    entry["ospf_neighbors"] = cli.get_ospf_neighbors()
                    entry["ospf_routes"] = sorted(cli.get_routes(protocol="ospf"))
                report[name] = entry
        except CliError as exc:
            report[name] = {"error": str(exc)}

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    for name, entry in report.items():
        print(f"=== {name} ===")
        if "error" in entry:
            print(f"  ERROR: {entry['error']}")
            continue
        for iface, addrs in entry["addresses"].items():
            print(f"  {iface:<8} {' '.join(addrs)}")
        if "ospf_neighbors" in entry:
            for nbr, sessions in entry["ospf_neighbors"].items():
                for session in sessions:
                    print(f"  neighbour {nbr} {session['nbrState']} via {session['ifaceAddress']}")
            print(f"  ospf routes: {', '.join(entry['ospf_routes']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
