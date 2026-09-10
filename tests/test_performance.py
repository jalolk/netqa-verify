from __future__ import annotations

import time

import pytest

from netqa.backends import RouteManager
from netqa.faults import FaultInjector
from netqa.wait import wait_until

from tests.conftest import ECMP_NEXT_HOPS, FAR_PREFIX, HOSTS

pytestmark = [pytest.mark.performance, pytest.mark.slow]

REROUTE_BUDGET_S = 5.0
RECOVERY_BUDGET_S = 60.0


def _next_hops(backend: RouteManager, router: str) -> list[str]:
    return backend.route_next_hops(router, FAR_PREFIX[router])


@pytest.mark.parametrize("router", ["r1", "r2"])
def test_far_prefix_is_installed_over_both_paths(cli_backend: RouteManager, router: str) -> None:
    assert _next_hops(cli_backend, router) == ECMP_NEXT_HOPS[router]


def test_traffic_survives_single_link_failure(
    cli_backend: RouteManager, faults: dict[str, FaultInjector], converged: None
) -> None:
    injector = faults["r1"]

    with injector.link_down("eth2"):
        elapsed = wait_until(
            lambda: _next_hops(cli_backend, "r1") == ["10.0.13.2"],
            timeout=REROUTE_BUDGET_S,
            interval=0.2,
            description="r1 to withdraw the failed next hop",
        )
        assert cli_backend.is_reachable("h1", HOSTS["h2"], count=2), (
            "traffic did not survive failure of one of two equal-cost paths"
        )

    assert elapsed < REROUTE_BUDGET_S


def test_reroute_completes_within_budget(
    cli_backend: RouteManager, faults: dict[str, FaultInjector], converged: None
) -> None:
    injector = faults["r1"]
    assert _next_hops(cli_backend, "r1") == ECMP_NEXT_HOPS["r1"]

    started = time.monotonic()
    injector.set_link("eth2", up=False)
    try:
        wait_until(
            lambda: _next_hops(cli_backend, "r1") == ["10.0.13.2"],
            timeout=REROUTE_BUDGET_S,
            interval=0.2,
            description="next hop withdrawal",
        )
        reroute_s = time.monotonic() - started
    finally:
        injector.set_link("eth2", up=True)

    assert reroute_s < REROUTE_BUDGET_S, f"reroute took {reroute_s:.2f}s"


def test_full_path_recovery_within_budget(
    cli_backend: RouteManager, faults: dict[str, FaultInjector], converged: None
) -> None:
    injector = faults["r1"]

    injector.set_link("eth2", up=False)
    wait_until(
        lambda: _next_hops(cli_backend, "r1") == ["10.0.13.2"],
        timeout=REROUTE_BUDGET_S,
        interval=0.2,
        description="failed path withdrawal",
    )

    started = time.monotonic()
    injector.set_link("eth2", up=True)
    recovery_s = wait_until(
        lambda: _next_hops(cli_backend, "r1") == ECMP_NEXT_HOPS["r1"],
        timeout=RECOVERY_BUDGET_S,
        interval=0.2,
        description="both equal-cost paths to return",
    )

    assert recovery_s < RECOVERY_BUDGET_S, f"recovery took {recovery_s:.2f}s"
    assert cli_backend.is_reachable("h1", HOSTS["h2"], count=2)


def test_total_outage_when_all_transit_paths_fail(
    cli_backend: RouteManager, faults: dict[str, FaultInjector], converged: None
) -> None:
    injector = faults["r1"]

    injector.set_link("eth2", up=False)
    injector.set_link("eth3", up=False)
    try:
        wait_until(
            lambda: not _next_hops(cli_backend, "r1"),
            timeout=REROUTE_BUDGET_S,
            interval=0.2,
            description="all forwarding paths to the far prefix to be withdrawn",
        )
        assert not cli_backend.is_reachable("h1", HOSTS["h2"], count=1)
    finally:
        injector.set_link("eth2", up=True)
        injector.set_link("eth3", up=True)
