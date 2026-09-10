from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from netqa.backends import BackendError, RouteManager
from netqa.spec import ExpectedDevice, TopologySpec


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Drift:
    category: str
    device: str
    subject: str
    expected: Any
    actual: Any
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        return (
            f"[{self.severity.value}] {self.device}: {self.category} on {self.subject}: "
            f"expected {self.expected!r}, actual {self.actual!r}"
        )


def _is_loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_interface(address).ip.is_loopback
    except ValueError:
        return False


def _normalise(addresses: Iterable[str]) -> set[str]:
    return {a for a in addresses if not _is_loopback_address(a)}


def _compare_interfaces(
    expected: ExpectedDevice, actual: dict[str, list[str]]
) -> list[Drift]:
    drifts: list[Drift] = []

    for iface, want in expected.interfaces.items():
        if iface not in actual:
            drifts.append(
                Drift("missing_interface", expected.name, iface, sorted(want), None)
            )
            continue

        want_set = _normalise(want)
        have_set = _normalise(actual[iface])

        if want_set - have_set:
            drifts.append(
                Drift("missing_address", expected.name, iface, sorted(want_set), sorted(have_set))
            )
        if have_set - want_set:
            drifts.append(
                Drift(
                    "unexpected_address",
                    expected.name,
                    iface,
                    sorted(want_set),
                    sorted(have_set),
                    Severity.WARNING,
                )
            )

    for iface in actual:
        if iface not in expected.interfaces and _normalise(actual[iface]):
            drifts.append(
                Drift(
                    "undeclared_interface",
                    expected.name,
                    iface,
                    None,
                    sorted(_normalise(actual[iface])),
                    Severity.WARNING,
                )
            )

    return drifts


def _compare_neighbors(expected: ExpectedDevice, actual: dict[str, Any]) -> list[Drift]:
    drifts: list[Drift] = []

    for want in expected.neighbors:
        sessions = actual.get(want.id)
        if not sessions:
            drifts.append(
                Drift("missing_ospf_neighbor", expected.name, want.id, want.state, None)
            )
            continue

        states = [s.get("nbrState", "") for s in sessions]
        if not any(state.startswith(want.state) for state in states):
            drifts.append(
                Drift("ospf_neighbor_state", expected.name, want.id, want.state, states)
            )

        addresses = {s.get("ifaceAddress") for s in sessions}
        if want.address not in addresses:
            drifts.append(
                Drift(
                    "ospf_neighbor_address",
                    expected.name,
                    want.id,
                    want.address,
                    sorted(a for a in addresses if a),
                )
            )

    declared = {n.id for n in expected.neighbors}
    for neighbor_id in actual:
        if neighbor_id not in declared:
            drifts.append(
                Drift("undeclared_ospf_neighbor", expected.name, neighbor_id, None, neighbor_id)
            )

    return drifts


def _compare_routes(expected: ExpectedDevice, actual: dict[str, Any]) -> list[Drift]:
    drifts: list[Drift] = []

    for want in expected.routes:
        entries = actual.get(want.prefix)
        if not entries:
            drifts.append(
                Drift("missing_route", expected.name, want.prefix, want.protocol, None)
            )
            continue

        protocols = {e.get("protocol") for e in entries}
        if want.protocol not in protocols:
            drifts.append(
                Drift(
                    "route_protocol",
                    expected.name,
                    want.prefix,
                    want.protocol,
                    sorted(p for p in protocols if p),
                )
            )

        if want.next_hops:
            have = sorted(
                hop["ip"]
                for entry in entries
                for hop in entry.get("nexthops", [])
                if hop.get("ip") and hop.get("active")
            )
            if have != sorted(want.next_hops):
                drifts.append(
                    Drift("route_next_hop", expected.name, want.prefix, sorted(want.next_hops), have)
                )

    declared = {r.prefix for r in expected.routes}
    for prefix, entries in actual.items():
        if prefix in declared:
            continue
        protocols = {e.get("protocol") for e in entries}
        if protocols <= {"local", "kernel"}:
            continue
        drifts.append(
            Drift(
                "undeclared_route",
                expected.name,
                prefix,
                None,
                sorted(p for p in protocols if p),
                Severity.WARNING,
            )
        )

    return drifts


def check_topology(spec: TopologySpec, backend: RouteManager) -> list[Drift]:
    drifts: list[Drift] = []
    live_devices = set(backend.device_names())

    for name, expected in spec.devices.items():
        if name not in live_devices:
            drifts.append(Drift("missing_device", name, name, expected.role, None))
            continue

        try:
            drifts.extend(_compare_interfaces(expected, backend.get_addresses(name)))
            if expected.is_router:
                drifts.extend(_compare_neighbors(expected, backend.get_ospf_neighbors(name)))
                drifts.extend(_compare_routes(expected, backend.list_routes(name)))
        except BackendError as exc:
            drifts.append(Drift("unreachable_device", name, name, "reachable", str(exc)))

    for name in live_devices - set(spec.devices):
        drifts.append(Drift("undeclared_device", name, name, None, "present", Severity.WARNING))

    for check in spec.reachability:
        try:
            reachable = backend.is_reachable(check.source, check.destination)
        except BackendError as exc:
            drifts.append(
                Drift("reachability_error", check.source, check.destination, check.expected, str(exc))
            )
            continue
        if reachable != check.expected:
            drifts.append(
                Drift("reachability", check.source, check.destination, check.expected, reachable)
            )

    return drifts


def errors(drifts: Iterable[Drift]) -> list[Drift]:
    return [d for d in drifts if d.severity is Severity.ERROR]


def warnings(drifts: Iterable[Drift]) -> list[Drift]:
    return [d for d in drifts if d.severity is Severity.WARNING]


def format_report(drifts: Iterable[Drift]) -> str:
    drifts = list(drifts)
    if not drifts:
        return "no drift detected"
    lines = [f"{len(errors(drifts))} error(s), {len(warnings(drifts))} warning(s)", ""]
    lines.extend(str(d) for d in sorted(drifts, key=lambda d: (d.severity.value, d.device, d.category)))
    return "\n".join(lines)
