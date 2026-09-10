from __future__ import annotations

import pytest

from netqa.backends import RouteManager
from netqa.wait import wait_until

from tests.conftest import ECMP_NEXT_HOPS, FAR_PREFIX, HOSTS, ROUTERS, TRANSIT_NEXT_HOP

pytestmark = pytest.mark.parity

def test_backend_lists_all_devices(backend: RouteManager) -> None:
    assert set(backend.device_names()) == set(ROUTERS) | set(HOSTS)


@pytest.mark.parametrize("router", ROUTERS)
def test_router_has_full_ospf_adjacency(backend: RouteManager, router: str) -> None:
    neighbours = backend.get_ospf_neighbors(router)
    assert neighbours, f"{router} has no OSPF neighbours"

    states = [
        session["nbrState"]
        for sessions in neighbours.values()
        for session in sessions
    ]
    assert all(state.startswith("Full") for state in states), states


@pytest.mark.parametrize("router", ROUTERS)
def test_router_learns_far_side_prefix_via_ospf(backend: RouteManager, router: str) -> None:
    prefix = FAR_PREFIX[router]
    ospf_routes = backend.list_routes(router, protocol="ospf")
    assert prefix in ospf_routes, f"{router} did not learn {prefix} via OSPF"
    assert backend.route_next_hops(router, prefix) == ECMP_NEXT_HOPS[router]


def test_end_to_end_reachability_across_routed_path(backend: RouteManager) -> None:
    result = backend.ping("h1", HOSTS["h2"], count=3)
    assert result["success"], result
    assert result["loss_pct"] == 0.0, result


def test_static_route_lifecycle(backend: RouteManager, route_sandbox) -> None:
    prefix = "192.168.240.0/24"
    next_hop = TRANSIT_NEXT_HOP["r1"]

    assert not backend.has_route("r1", prefix)

    route_sandbox("r1", prefix, next_hop)
    wait_until(
        lambda: backend.has_route("r1", prefix),
        timeout=15,
        interval=0.5,
        description=f"{prefix} to appear on r1",
    )
    assert backend.route_next_hops("r1", prefix) == [next_hop]

    backend.delete_static_route("r1", prefix, next_hop)
    wait_until(
        lambda: not backend.has_route("r1", prefix),
        timeout=15,
        interval=0.5,
        description=f"{prefix} to disappear from r1",
    )


def test_rejects_unknown_device(backend: RouteManager) -> None:
    with pytest.raises(Exception):
        backend.list_routes("does-not-exist")
