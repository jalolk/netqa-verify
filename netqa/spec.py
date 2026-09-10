from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SPEC = Path(__file__).resolve().parent.parent / "spec" / "expected_topology.yml"


class SpecError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpectedNeighbor:
    id: str
    address: str
    state: str = "Full"


@dataclass(frozen=True)
class ExpectedRoute:
    prefix: str
    protocol: str
    next_hops: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedDevice:
    name: str
    role: str
    interfaces: dict[str, tuple[str, ...]] = field(default_factory=dict)
    neighbors: tuple[ExpectedNeighbor, ...] = ()
    routes: tuple[ExpectedRoute, ...] = ()

    @property
    def is_router(self) -> bool:
        return self.role == "router"


@dataclass(frozen=True)
class ExpectedReachability:
    source: str
    destination: str
    expected: bool = True


@dataclass(frozen=True)
class TopologySpec:
    version: int
    devices: dict[str, ExpectedDevice]
    reachability: tuple[ExpectedReachability, ...] = ()

    @property
    def routers(self) -> list[str]:
        return [name for name, dev in self.devices.items() if dev.is_router]


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise SpecError(f"{context}: missing required key {key!r}")
    return mapping[key]


def load_spec(path: Path | str | None = None) -> TopologySpec:
    path = Path(path) if path else DEFAULT_SPEC
    if not path.is_file():
        raise SpecError(f"spec not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    devices_raw = _require(raw, "devices", str(path))

    devices: dict[str, ExpectedDevice] = {}
    for name, spec in devices_raw.items():
        context = f"{path}: device {name!r}"
        interfaces = {
            iface: tuple(addrs or ())
            for iface, addrs in (spec.get("interfaces") or {}).items()
        }
        neighbors = tuple(
            ExpectedNeighbor(
                id=_require(n, "id", context),
                address=_require(n, "address", context),
                state=n.get("state", "Full"),
            )
            for n in ((spec.get("ospf") or {}).get("neighbors") or [])
        )
        routes = tuple(
            ExpectedRoute(
                prefix=_require(r, "prefix", context),
                protocol=_require(r, "protocol", context),
                next_hops=tuple(r.get("next_hops") or ()),
            )
            for r in (spec.get("routes") or [])
        )
        devices[name] = ExpectedDevice(
            name=name,
            role=_require(spec, "role", context),
            interfaces=interfaces,
            neighbors=neighbors,
            routes=routes,
        )

    reachability = tuple(
        ExpectedReachability(
            source=_require(item, "from", str(path)),
            destination=_require(item, "to", str(path)),
            expected=bool(item.get("expected", True)),
        )
        for item in (raw.get("reachability") or [])
    )

    return TopologySpec(
        version=int(raw.get("version", 1)),
        devices=devices,
        reachability=reachability,
    )
