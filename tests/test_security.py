from __future__ import annotations

import pytest

from netqa.backends import RouteManager
from netqa.faults import FaultInjector
from netqa.wait import wait_until

from tests.conftest import HOSTS

pytestmark = pytest.mark.security

H1_ADDR = "10.0.1.10"
H2_ADDR = "10.0.2.10"
R2_LOOPBACK = "10.255.255.2"


def test_filter_chain_starts_empty(faults: dict[str, FaultInjector]) -> None:
    rules = faults["r2"].list_filter_rules()
    assert rules == ["-P FORWARD ACCEPT"], rules


def test_acl_blocks_only_the_specified_flow(
    cli_backend: RouteManager, faults: dict[str, FaultInjector]
) -> None:
    injector = faults["r2"]

    assert cli_backend.is_reachable("h1", H2_ADDR, count=2)

    with injector.traffic_blocked(H1_ADDR, H2_ADDR):
        wait_until(
            lambda: not cli_backend.is_reachable("h1", H2_ADDR, count=1),
            timeout=10,
            interval=0.5,
            description="blocked flow to stop being reachable",
        )
        assert cli_backend.is_reachable("h1", R2_LOOPBACK, count=2), (
            "the ACL blocked unrelated traffic, so this proves nothing about the rule"
        )

    wait_until(
        lambda: cli_backend.is_reachable("h1", H2_ADDR, count=1),
        timeout=15,
        interval=0.5,
        description="traffic to recover once the rule is removed",
    )


def test_acl_is_directional(
    cli_backend: RouteManager, faults: dict[str, FaultInjector]
) -> None:
    injector = faults["r2"]

    with injector.traffic_blocked(H1_ADDR, H2_ADDR):
        wait_until(
            lambda: not cli_backend.is_reachable("h1", H2_ADDR, count=1),
            timeout=10,
            interval=0.5,
            description="h1 to h2 to be blocked",
        )
        assert not cli_backend.is_reachable("h2", H1_ADDR, count=2), (
            "return traffic should also fail, since replies to h2's echo request are dropped"
        )


def test_rule_is_installed_while_active(faults: dict[str, FaultInjector]) -> None:
    injector = faults["r2"]

    with injector.traffic_blocked(H1_ADDR, H2_ADDR):
        rules = injector.list_filter_rules()
        assert any(H1_ADDR in rule and H2_ADDR in rule and "DROP" in rule for rule in rules), rules

    assert injector.list_filter_rules() == ["-P FORWARD ACCEPT"]


def test_management_plane_survives_data_plane_filtering(
    cli_backend: RouteManager, faults: dict[str, FaultInjector]
) -> None:
    injector = faults["r2"]

    with injector.traffic_blocked(H1_ADDR, H2_ADDR):
        neighbours = cli_backend.get_ospf_neighbors("r2")
        assert neighbours, "OSPF adjacency lost while filtering user traffic"
        assert cli_backend.list_routes("r2", protocol="ospf")
