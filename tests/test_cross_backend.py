from __future__ import annotations

import pytest

from netqa.backends import RouteManager
from netqa.wait import wait_until

from tests.conftest import ROUTERS, TRANSIT_NEXT_HOP

pytestmark = pytest.mark.parity


@pytest.fixture
def backends(cli_backend: RouteManager, api_backend: RouteManager) -> dict[str, RouteManager]:
    return {"cli": cli_backend, "api": api_backend}


@pytest.mark.parametrize("router", ROUTERS)
def test_ospf_routes_agree_across_backends(backends: dict[str, RouteManager], router: str) -> None:
    via_cli = sorted(backends["cli"].list_routes(router, protocol="ospf"))
    via_api = sorted(backends["api"].list_routes(router, protocol="ospf"))
    assert via_cli == via_api


@pytest.mark.parametrize("router", ROUTERS)
def test_ospf_neighbours_agree_across_backends(backends: dict[str, RouteManager], router: str) -> None:
    via_cli = sorted(backends["cli"].get_ospf_neighbors(router))
    via_api = sorted(backends["api"].get_ospf_neighbors(router))
    assert via_cli == via_api


@pytest.mark.parametrize(
    ("writer", "reader"),
    [("cli", "api"), ("api", "cli")],
    ids=["write-cli-read-api", "write-api-read-cli"],
)
def test_route_written_by_one_backend_is_visible_to_the_other(
    backends: dict[str, RouteManager], writer: str, reader: str
) -> None:
    prefix = "192.168.241.0/24"
    next_hop = TRANSIT_NEXT_HOP["r2"]
    write, read = backends[writer], backends[reader]

    assert not read.has_route("r2", prefix)

    write.add_static_route("r2", prefix, next_hop)
    try:
        wait_until(
            lambda: read.has_route("r2", prefix),
            timeout=15,
            interval=0.5,
            description=f"{prefix} visible via {reader}",
        )
        assert read.route_next_hops("r2", prefix) == [next_hop]
    finally:
        write.delete_static_route("r2", prefix, next_hop)

    wait_until(
        lambda: not read.has_route("r2", prefix),
        timeout=15,
        interval=0.5,
        description=f"{prefix} withdrawn via {reader}",
    )
