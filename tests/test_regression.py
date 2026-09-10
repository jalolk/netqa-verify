from __future__ import annotations

import pytest

from netqa.backends import RouteManager
from netqa.drift import check_topology, errors, format_report
from netqa.faults import FaultInjector
from netqa.spec import TopologySpec
from netqa.wait import wait_until

from tests.conftest import ECMP_NEXT_HOPS, FAR_PREFIX, HOSTS, ROUTERS, TRANSIT_NEXT_HOP

pytestmark = pytest.mark.regression


def _assert_core_paths_healthy(backend: RouteManager, spec: TopologySpec) -> None:
    drifts = check_topology(spec, backend)
    assert not errors(drifts), format_report(drifts)


def test_core_paths_survive_static_route_churn(
    cli_backend: RouteManager, spec: TopologySpec, route_sandbox
) -> None:
    _assert_core_paths_healthy(cli_backend, spec)

    prefix = "192.168.240.0/24"
    route_sandbox("r1", prefix, TRANSIT_NEXT_HOP["r1"])
    wait_until(
        lambda: cli_backend.has_route("r1", prefix),
        timeout=15,
        interval=0.5,
        description="churn route to install",
    )

    cli_backend.delete_static_route("r1", prefix, TRANSIT_NEXT_HOP["r1"])
    wait_until(
        lambda: not cli_backend.has_route("r1", prefix),
        timeout=15,
        interval=0.5,
        description="churn route to be withdrawn",
    )

    _assert_core_paths_healthy(cli_backend, spec)


@pytest.mark.slow
def test_core_paths_recover_after_link_failure(
    cli_backend: RouteManager,
    spec: TopologySpec,
    faults: dict[str, FaultInjector],
    converged: None,
) -> None:
    _assert_core_paths_healthy(cli_backend, spec)

    with faults["r1"].link_down("eth2"):
        wait_until(
            lambda: cli_backend.route_next_hops("r1", FAR_PREFIX["r1"]) == ["10.0.13.2"],
            timeout=5,
            interval=0.2,
            description="traffic to reroute onto the surviving path",
        )

    wait_until(
        lambda: cli_backend.route_next_hops("r1", FAR_PREFIX["r1"]) == ECMP_NEXT_HOPS["r1"],
        timeout=60,
        interval=0.5,
        description="both paths to return",
    )

    _assert_core_paths_healthy(cli_backend, spec)


def test_core_paths_recover_after_traffic_filtering(
    cli_backend: RouteManager, spec: TopologySpec, faults: dict[str, FaultInjector]
) -> None:
    with faults["r2"].traffic_blocked("10.0.1.10", "10.0.2.10"):
        wait_until(
            lambda: not cli_backend.is_reachable("h1", HOSTS["h2"], count=1),
            timeout=10,
            interval=0.5,
            description="filtered flow to drop",
        )

    wait_until(
        lambda: cli_backend.is_reachable("h1", HOSTS["h2"], count=1),
        timeout=15,
        interval=0.5,
        description="filtered flow to recover",
    )

    _assert_core_paths_healthy(cli_backend, spec)


@pytest.mark.parametrize("router", ROUTERS)
def test_running_config_is_intact(cli_backend: RouteManager, router: str) -> None:
    neighbours = cli_backend.get_ospf_neighbors(router)
    assert len(neighbours) == 1, neighbours
    sessions = next(iter(neighbours.values()))
    assert len(sessions) == 2, "both transit adjacencies should be established"
    assert all(s["nbrState"].startswith("Full") for s in sessions), sessions
