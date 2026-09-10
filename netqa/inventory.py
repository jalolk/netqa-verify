from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_INVENTORY = Path(__file__).resolve().parent.parent / "inventory.yml"

ROLE_ROUTER = "router"
ROLE_HOST = "host"


@dataclass(frozen=True)
class Device:
    name: str
    role: str
    host: str
    container: str
    username: str
    password: str
    port: int = 22

    @property
    def is_router(self) -> bool:
        return self.role == ROLE_ROUTER


class InventoryError(RuntimeError):
    pass


def load_inventory(path: Path | str | None = None) -> dict[str, Device]:
    path = Path(path) if path else DEFAULT_INVENTORY
    if not path.is_file():
        raise InventoryError(f"inventory not found: {path}")

    raw = yaml.safe_load(path.read_text()) or {}
    defaults = raw.get("defaults", {})
    entries = raw.get("devices") or {}
    if not entries:
        raise InventoryError(f"inventory defines no devices: {path}")

    devices: dict[str, Device] = {}
    for name, spec in entries.items():
        merged = {**defaults, **spec}
        missing = {"host", "role", "container", "username", "password"} - merged.keys()
        if missing:
            raise InventoryError(f"device {name!r} missing keys: {sorted(missing)}")
        devices[name] = Device(
            name=name,
            role=merged["role"],
            host=merged["host"],
            container=merged["container"],
            username=merged["username"],
            password=merged["password"],
            port=int(merged.get("port", 22)),
        )
    return devices


def by_role(devices: dict[str, Device], role: str) -> dict[str, Device]:
    return {name: dev for name, dev in devices.items() if dev.role == role}
