from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(f"{method} {path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise ApiError(
                f"{method} {path} returned {response.status_code}: {response.text}",
                status_code=response.status_code,
            )
        return response.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def is_available(self) -> bool:
        try:
            return self.health().get("status") == "ok"
        except ApiError:
            return False

    def list_devices(self) -> list[dict[str, Any]]:
        return self._request("GET", "/devices")

    def get_interfaces(self, device: str) -> dict[str, Any]:
        return self._request("GET", f"/devices/{device}/interfaces")

    def get_addresses(self, device: str) -> dict[str, list[str]]:
        return self._request("GET", f"/devices/{device}/addresses")

    def get_routes(self, device: str, protocol: str | None = None) -> dict[str, Any]:
        params = {"protocol": protocol} if protocol else None
        return self._request("GET", f"/devices/{device}/routes", params=params)

    def get_ospf_neighbors(self, device: str) -> dict[str, Any]:
        return self._request("GET", f"/devices/{device}/ospf/neighbors")

    def add_static_route(self, device: str, prefix: str, next_hop: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/devices/{device}/routes",
            json={"prefix": prefix, "next_hop": next_hop},
        )

    def delete_static_route(self, device: str, prefix: str, next_hop: str | None = None) -> dict[str, Any]:
        params = {"next_hop": next_hop} if next_hop else None
        return self._request("DELETE", f"/devices/{device}/routes/{prefix}", params=params)

    def ping(self, device: str, destination: str, count: int = 3) -> dict[str, Any]:
        return self._request("GET", f"/devices/{device}/ping/{destination}", params={"count": count})
