from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from netqa.cli import CliDevice, CliError, validate_prefix
from netqa.client import ApiClient, ApiError
from netqa.inventory import Device, load_inventory


class BackendError(RuntimeError):
    pass


class RouteManager(ABC):
    name: str

    @abstractmethod
    def device_names(self) -> list[str]: ...

    @abstractmethod
    def list_routes(self, device: str, protocol: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def get_addresses(self, device: str) -> dict[str, list[str]]: ...

    @abstractmethod
    def get_ospf_neighbors(self, device: str) -> dict[str, Any]: ...

    @abstractmethod
    def add_static_route(self, device: str, prefix: str, next_hop: str) -> None: ...

    @abstractmethod
    def delete_static_route(self, device: str, prefix: str, next_hop: str | None = None) -> None: ...

    @abstractmethod
    def ping(self, device: str, destination: str, count: int = 3) -> dict[str, Any]: ...

    @abstractmethod
    def close(self) -> None: ...

    def has_route(self, device: str, prefix: str) -> bool:
        return validate_prefix(prefix) in self.list_routes(device)

    def route_next_hops(self, device: str, prefix: str, active_only: bool = True) -> list[str]:
        entries = self.list_routes(device).get(validate_prefix(prefix), [])
        return sorted(
            hop["ip"]
            for entry in entries
            for hop in entry.get("nexthops", [])
            if hop.get("ip") and (hop.get("active") or not active_only)
        )

    def is_reachable(self, device: str, destination: str, count: int = 3) -> bool:
        return bool(self.ping(device, destination, count=count)["success"])

    def __enter__(self) -> "RouteManager":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"


class CliBackend(RouteManager):
    name = "cli"

    def __init__(self, inventory: dict[str, Device] | None = None, transport: str = "ssh") -> None:
        self._inventory = inventory or load_inventory()
        self._transport = transport
        self._sessions: dict[str, CliDevice] = {}

    def _session(self, device: str) -> CliDevice:
        if device not in self._inventory:
            raise BackendError(f"unknown device {device!r}")
        if device not in self._sessions:
            self._sessions[device] = CliDevice(self._inventory[device], transport=self._transport)
        return self._sessions[device]

    def device_names(self) -> list[str]:
        return list(self._inventory)

    def list_routes(self, device: str, protocol: str | None = None) -> dict[str, Any]:
        try:
            return self._session(device).get_routes(protocol=protocol)
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def get_addresses(self, device: str) -> dict[str, list[str]]:
        try:
            return self._session(device).get_addresses()
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def get_ospf_neighbors(self, device: str) -> dict[str, Any]:
        try:
            return self._session(device).get_ospf_neighbors()
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def add_static_route(self, device: str, prefix: str, next_hop: str) -> None:
        try:
            self._session(device).add_static_route(prefix, next_hop)
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def delete_static_route(self, device: str, prefix: str, next_hop: str | None = None) -> None:
        try:
            self._session(device).delete_static_route(prefix, next_hop)
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def ping(self, device: str, destination: str, count: int = 3) -> dict[str, Any]:
        try:
            return self._session(device).ping(destination, count=count)
        except CliError as exc:
            raise BackendError(str(exc)) from exc

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()


class ApiBackend(RouteManager):
    name = "api"

    def __init__(self, base_url: str | None = None) -> None:
        self._client = ApiClient(base_url) if base_url else ApiClient()

    def device_names(self) -> list[str]:
        try:
            return [entry["name"] for entry in self._client.list_devices()]
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def list_routes(self, device: str, protocol: str | None = None) -> dict[str, Any]:
        try:
            return self._client.get_routes(device, protocol=protocol)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def get_addresses(self, device: str) -> dict[str, list[str]]:
        try:
            return self._client.get_addresses(device)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def get_ospf_neighbors(self, device: str) -> dict[str, Any]:
        try:
            return self._client.get_ospf_neighbors(device)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def add_static_route(self, device: str, prefix: str, next_hop: str) -> None:
        try:
            self._client.add_static_route(device, prefix, next_hop)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def delete_static_route(self, device: str, prefix: str, next_hop: str | None = None) -> None:
        try:
            self._client.delete_static_route(device, prefix, next_hop)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def ping(self, device: str, destination: str, count: int = 3) -> dict[str, Any]:
        try:
            return self._client.ping(device, destination, count=count)
        except ApiError as exc:
            raise BackendError(str(exc)) from exc

    def close(self) -> None:
        self._client.close()


BACKENDS: dict[str, type[RouteManager]] = {"cli": CliBackend, "api": ApiBackend}


def make_backend(kind: str, **kwargs: Any) -> RouteManager:
    try:
        factory = BACKENDS[kind]
    except KeyError:
        raise BackendError(f"unknown backend {kind!r}; expected one of {sorted(BACKENDS)}") from None
    return factory(**kwargs)
