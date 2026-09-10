from __future__ import annotations

import json
import re
import shlex
from typing import Any

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoBaseException

from netqa.inventory import Device

PING_STATS = re.compile(
    r"(?P<sent>\d+) packets transmitted, (?P<received>\d+) (?:packets )?received"
)


class CliError(RuntimeError):
    pass


class CliDevice:
    def __init__(self, device: Device, timeout: int = 20) -> None:
        self.device = device
        self.timeout = timeout
        self._conn: Any | None = None

    def __enter__(self) -> "CliDevice":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def name(self) -> str:
        return self.device.name

    def connect(self) -> None:
        if self._conn is not None:
            return
        try:
            self._conn = ConnectHandler(
                device_type="linux",
                host=self.device.host,
                port=self.device.port,
                username=self.device.username,
                password=self.device.password,
                conn_timeout=self.timeout,
                fast_cli=False,
            )
        except NetmikoBaseException as exc:
            raise CliError(f"{self.name}: SSH connection failed: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.disconnect()
            self._conn = None

    def run_shell(self, command: str) -> str:
        if self._conn is None:
            raise CliError(f"{self.name}: not connected")
        try:
            return self._conn.send_command(command, read_timeout=self.timeout).strip()
        except NetmikoBaseException as exc:
            raise CliError(f"{self.name}: command failed: {command}: {exc}") from exc

    def run_vtysh(self, command: str) -> str:
        if not self.device.is_router:
            raise CliError(f"{self.name}: vtysh is only available on routers")
        return self.run_shell(f"vtysh -c {shlex.quote(command)}")

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
        return prefix in self.get_routes()

    def get_addresses(self) -> dict[str, list[str]]:
        output = self.run_shell("ip -br -4 addr show")
        result: dict[str, list[str]] = {}
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 3:
                result[fields[0].split("@")[0]] = fields[2:]
        return result

    def ping(self, destination: str, count: int = 3, timeout: int = 2) -> dict[str, Any]:
        output = self.run_shell(f"ping -c {count} -W {timeout} {shlex.quote(destination)}")
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
