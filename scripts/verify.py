from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from netqa.backends import make_backend
from netqa.drift import check_topology, errors, format_report, warnings
from netqa.spec import load_spec


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare live topology state against the intended spec")
    parser.add_argument("--spec", default=None, help="path to the topology spec")
    parser.add_argument("--backend", default="cli", choices=["cli", "api"], help="interface to read through")
    parser.add_argument("--api-url", default=None, help="base URL when using the api backend")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    kwargs = {"base_url": args.api_url} if args.backend == "api" and args.api_url else {}

    with make_backend(args.backend, **kwargs) as backend:
        drifts = check_topology(spec, backend)

    if args.json:
        payload = {
            "errors": [asdict(d) for d in errors(drifts)],
            "warnings": [asdict(d) for d in warnings(drifts)],
        }
        json.dump(payload, sys.stdout, indent=2, default=str)
        print()
    else:
        print(format_report(drifts))

    if errors(drifts):
        return 1
    return 1 if args.strict and warnings(drifts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
