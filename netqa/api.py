from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from netqa.cli import CliDevice, CliError
from netqa.inventory import Device, InventoryError, load_inventory

TRANSPORT = "docker"


class StaticRoute(BaseModel):
    prefix: str = Field(examples=["192.168.50.0/24"])
    next_hop: str = Field(examples=["10.0.12.2"])


class DeviceSummary(BaseModel):
    name: str
    role: str
    host: str
    container: str


def create_app(inventory: dict[str, Device] | None = None) -> FastAPI:
    app = FastAPI(
        title="netqa device API",
        description="HTTP interface to the simulated network, backed by the Docker transport.",
        version="1.0.0",
    )
    app.state.inventory = inventory or load_inventory()

    def lookup(name: str) -> Device:
        try:
            return app.state.inventory[name]
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown device {name!r}") from None

    def require_router(name: str) -> Device:
        device = lookup(name)
        if not device.is_router:
            raise HTTPException(status_code=400, detail=f"{name} is not a router")
        return device

    @contextmanager
    def session(device: Device) -> Iterator[CliDevice]:
        client = CliDevice(device, transport=TRANSPORT)
        try:
            yield client
        except CliError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            client.close()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "transport": TRANSPORT, "devices": len(app.state.inventory)}

    @app.get("/devices", response_model=list[DeviceSummary])
    def list_devices() -> list[DeviceSummary]:
        return [
            DeviceSummary(name=d.name, role=d.role, host=d.host, container=d.container)
            for d in app.state.inventory.values()
        ]

    @app.get("/devices/{name}/interfaces")
    def get_interfaces(name: str) -> dict[str, Any]:
        with session(require_router(name)) as client:
            return client.get_interfaces()

    @app.get("/devices/{name}/addresses")
    def get_addresses(name: str) -> dict[str, list[str]]:
        with session(lookup(name)) as client:
            return client.get_addresses()

    @app.get("/devices/{name}/routes")
    def get_routes(name: str, protocol: str | None = None) -> dict[str, Any]:
        with session(require_router(name)) as client:
            return client.get_routes(protocol=protocol)

    @app.get("/devices/{name}/ospf/neighbors")
    def get_ospf_neighbors(name: str) -> dict[str, Any]:
        with session(require_router(name)) as client:
            return client.get_ospf_neighbors()

    @app.post("/devices/{name}/routes", status_code=201)
    def add_static_route(name: str, route: StaticRoute) -> dict[str, Any]:
        device = require_router(name)
        with session(device) as client:
            try:
                client.add_static_route(route.prefix, route.next_hop)
            except CliError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"device": name, "prefix": route.prefix, "next_hop": route.next_hop, "created": True}

    @app.delete("/devices/{name}/routes/{prefix:path}", status_code=200)
    def delete_static_route(name: str, prefix: str, next_hop: str | None = None) -> dict[str, Any]:
        device = require_router(name)
        with session(device) as client:
            try:
                client.delete_static_route(prefix, next_hop)
            except CliError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"device": name, "prefix": prefix, "deleted": True}

    @app.get("/devices/{name}/ping/{destination}")
    def ping(name: str, destination: str, count: int = 3, interval: float = 0.2) -> dict[str, Any]:
        with session(lookup(name)) as client:
            return client.ping(destination, count=count, interval=interval)

    return app


try:
    app = create_app()
except InventoryError:
    app = None
