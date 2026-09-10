from __future__ import annotations

import pytest

from netqa.backends import RouteManager
from netqa.drift import Severity, check_topology, errors, format_report, warnings
from netqa.spec import TopologySpec
from netqa.wait import wait_until

from tests.conftest import TRANSIT_NEXT_HOP


@pytest.mark.functional
def test_spec_describes_every_inventory_device(spec: TopologySpec, backend: RouteManager) -> None:
    assert set(spec.devices) == set(backend.device_names())


@pytest.mark.functional
def test_live_topology_matches_intended_state(spec: TopologySpec, backend: RouteManager) -> None:
    drifts = check_topology(spec, backend)
    assert not errors(drifts), format_report(drifts)


@pytest.mark.functional
def test_live_topology_has_no_undeclared_state(spec: TopologySpec, backend: RouteManager) -> None:
    drifts = check_topology(spec, backend)
    assert not warnings(drifts), format_report(drifts)


@pytest.mark.regression
def test_drift_detected_when_undeclared_route_is_added(
    spec: TopologySpec, backend: RouteManager, route_sandbox
) -> None:
    prefix = "192.168.242.0/24"

    assert not check_topology(spec, backend)

    route_sandbox("r1", prefix, TRANSIT_NEXT_HOP["r1"])
    wait_until(
        lambda: backend.has_route("r1", prefix),
        timeout=15,
        interval=0.5,
        description=f"{prefix} to be installed",
    )

    drifts = check_topology(spec, backend)
    undeclared = [d for d in drifts if d.category == "undeclared_route" and d.subject == prefix]
    assert undeclared, format_report(drifts)
    assert undeclared[0].severity is Severity.WARNING


@pytest.mark.functional
@pytest.mark.parametrize("check_index", range(3))
def test_declared_reachability_holds(
    spec: TopologySpec, backend: RouteManager, check_index: int
) -> None:
    check = spec.reachability[check_index]
    actual = backend.is_reachable(check.source, check.destination)
    assert actual == check.expected, f"{check.source} -> {check.destination}"
