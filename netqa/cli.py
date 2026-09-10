from __future__ import annotations

import ipaddress
import json
import re
import shlex
from typing import Any

from netqa.inventory import Device
from netqa.transport import Transport, TransportError, make_transport

PING_STATS = re.compile(
    r"(?P<sent>\d+) packets transmitted, (?P<received>\d+) (?:packets )?received"
)


class CliError(RuntimeError):
    pass


def validate_prefix(prefix: str) -> str:
    try:
        return str(ipaddress.ip_network(prefix, strict=True))
    except ValueError as exc:
        raise CliError(f"invalid prefix {prefix!r}: {exc}") from None


def validate_address(address: str) -> str:
    try:
        return str(ipaddress.ip_address(address))
    except ValueError as exc:
        raise CliError(f"invalid address {address!r}: {exc}") from None


class CliDevice:
    def __init__(
        self,
        device: Device,
        transport: Transport | str = "ssh",
        timeout: int = 20,
    ) -> None:
        self.device = device
        self._transport = (
            make_transport(device, transport, timeout)
            if isinstance(transport, str)
            else transport
        )

    def __enter__(self) -> "CliDevice":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def transport_name(self) -> str:
        return self._transport.name

    def close(self) -> None:
        self._transport.close()

    def run_shell(self, command: str) -> str:
        try:
            return self._transport.run(command)
        except TransportError as exc:
            raise CliError(str(exc)) from exc

    def run_vtysh(self, *commands: str) -> str:
        if not self.device.is_router:
            raise CliError(f"{self.name}: vtysh is only available on routers")
        args = " ".join(f"-c {shlex.quote(c)}" for c in commands)
        return self.run_shell(f"vtysh {args}")

    def run_vtysh_json(self, command: str) -> Any:
        output = self.run_vtysh(f"{command} json")
        start = min(
            (i for i in (output.find("{"), output.find("[")) if i != -1),
            default=-1,
        )
        if start == -1:
            raise CliError(f"{self.name}: no JSON in response to {command!r}: {output!r}")
        try:
            return json.loads(output[start:])
        except json.JSONDecodeError as exc:
            raise CliError(f"{self.name}: malformed JSON from {command!r}: {exc}") from exc

    def get_running_config(self) -> str:
        return self.run_vtysh("show running-config")

    def get_interfaces(self) -> dict[str, Any]:
        return self.run_vtysh_json("show interface")

    def get_routes(self, protocol: str | None = None) -> dict[str, Any]:
        routes = self.run_vtysh_json("show ip route")
        if protocol is None:
            return routes
        return {
            prefix: entries
            for prefix, entries in routes.items()
            if any(e.get("protocol") == protocol for e in entries)
        }

    def get_ospf_neighbors(self) -> dict[str, Any]:
        return self.run_vtysh_json("show ip ospf neighbor").get("neighbors", {})

    def has_route(self, prefix: str) -> bool:
        return validate_prefix(prefix) in self.get_routes()

    def add_static_route(self, prefix: str, next_hop: str) -> None:
        prefix = validate_prefix(prefix)
        next_hop = validate_address(next_hop)
        self.run_vtysh("configure terminal", f"ip route {prefix} {next_hop}")

    def delete_static_route(self, prefix: str, next_hop: str | None = None) -> None:
        prefix = validate_prefix(prefix)
        statement = f"no ip route {prefix}"
        if next_hop:
            statement = f"{statement} {validate_address(next_hop)}"
        self.run_vtysh("configure terminal", statement)

    def get_addresses(self) -> dict[str, list[str]]:
        output = self.run_shell("ip -br -4 addr show")
        result: dict[str, list[str]] = {}
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 3:
                result[fields[0].split("@")[0]] = fields[2:]
        return result

    def ping(
        self,
        destination: str,
        count: int = 3,
        timeout: int = 2,
        interval: float = 0.2,
    ) -> dict[str, Any]:
        output = self.run_shell(
            f"ping -c {count} -i {interval} -W {timeout} {shlex.quote(destination)}"
        )
        match = PING_STATS.search(output)
        if not match:
            raise CliError(f"{self.name}: unparsable ping output: {output!r}")
        sent = int(match.group("sent"))
        received = int(match.group("received"))
        return {
            "destination": destination,
            "sent": sent,
            "received": received,
            "loss_pct": 100.0 * (sent - received) / sent if sent else 100.0,
            "success": received > 0,
        }
