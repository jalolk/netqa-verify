from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from netqa.cli import CliDevice, CliError
from netqa.inventory import Device

BLOCK_CHAIN = "FORWARD"


class FaultError(RuntimeError):
    pass


class FaultInjector:
    def __init__(self, device: Device, transport: str = "docker") -> None:
        self._device = device
        self._client = CliDevice(device, transport=transport)

    @property
    def name(self) -> str:
        return self._device.name

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FaultInjector":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _run(self, command: str) -> str:
        try:
            return self._client.run_shell(command)
        except CliError as exc:
            raise FaultError(str(exc)) from exc

    def link_state(self, interface: str) -> str:
        output = self._run(f"ip -br link show {interface}")
        fields = output.split()
        return fields[1] if len(fields) > 1 else "UNKNOWN"

    def set_link(self, interface: str, up: bool) -> None:
        self._run(f"ip link set {interface} {'up' if up else 'down'}")

    @contextmanager
    def link_down(self, interface: str) -> Iterator[None]:
        self.set_link(interface, up=False)
        try:
            yield
        finally:
            self.set_link(interface, up=True)

    def block_traffic(self, source: str, destination: str) -> None:
        self._run(
            f"iptables -I {BLOCK_CHAIN} -s {source} -d {destination} -j DROP"
        )

    def unblock_traffic(self, source: str, destination: str) -> None:
        self._run(
            f"iptables -D {BLOCK_CHAIN} -s {source} -d {destination} -j DROP"
        )

    def list_filter_rules(self) -> list[str]:
        output = self._run(f"iptables -S {BLOCK_CHAIN}")
        return [line for line in output.splitlines() if line.strip()]

    def flush_filter_rules(self) -> None:
        self._run(f"iptables -F {BLOCK_CHAIN}")

    @contextmanager
    def traffic_blocked(self, source: str, destination: str) -> Iterator[None]:
        self.block_traffic(source, destination)
        try:
            yield
        finally:
            try:
                self.unblock_traffic(source, destination)
            except FaultError:
                self.flush_filter_rules()
