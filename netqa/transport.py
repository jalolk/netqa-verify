from __future__ import annotations

from typing import Protocol, runtime_checkable

from netqa.inventory import Device


class TransportError(RuntimeError):
    pass


@runtime_checkable
class Transport(Protocol):
    name: str

    def run(self, command: str) -> str: ...

    def close(self) -> None: ...


class SshTransport:
    name = "ssh"

    def __init__(self, device: Device, timeout: int = 20) -> None:
        self.device = device
        self.timeout = timeout
        self._conn = None

    def _ensure(self):
        if self._conn is not None:
            return self._conn
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoBaseException

        try:
            self._conn = ConnectHandler(
                device_type="linux",
                host=self.device.host,
                port=self.device.port,
                username=self.device.username,
                password=self.device.password,
                conn_timeout=self.timeout,
                fast_cli=True,
            )
        except NetmikoBaseException as exc:
            raise TransportError(f"{self.device.name}: SSH connection failed: {exc}") from exc
        return self._conn

    def run(self, command: str) -> str:
        from netmiko.exceptions import NetmikoBaseException

        conn = self._ensure()
        try:
            return conn.send_command(command, read_timeout=self.timeout).strip()
        except NetmikoBaseException as exc:
            raise TransportError(f"{self.device.name}: {command!r} failed: {exc}") from exc

    def close(self) -> None:
        if self._conn is not None:
            self._conn.disconnect()
            self._conn = None


class DockerTransport:
    name = "docker"

    def __init__(self, device: Device, timeout: int = 20) -> None:
        self.device = device
        self.timeout = timeout
        self._container = None

    def _ensure(self):
        if self._container is not None:
            return self._container
        import docker
        from docker.errors import DockerException, NotFound

        try:
            client = docker.from_env(timeout=self.timeout)
            self._container = client.containers.get(self.device.container)
        except NotFound as exc:
            raise TransportError(f"{self.device.name}: container {self.device.container!r} not found") from exc
        except DockerException as exc:
            raise TransportError(f"{self.device.name}: docker unavailable: {exc}") from exc
        return self._container

    def run(self, command: str) -> str:
        from docker.errors import DockerException

        container = self._ensure()
        try:
            exit_code, output = container.exec_run(["sh", "-c", command], demux=False)
        except DockerException as exc:
            raise TransportError(f"{self.device.name}: {command!r} failed: {exc}") from exc
        text = output.decode("utf-8", errors="replace").strip()
        if exit_code != 0:
            raise TransportError(f"{self.device.name}: {command!r} exited {exit_code}: {text}")
        return text

    def close(self) -> None:
        self._container = None


TRANSPORTS = {"ssh": SshTransport, "docker": DockerTransport}


def make_transport(device: Device, kind: str = "ssh", timeout: int = 20) -> Transport:
    try:
        factory = TRANSPORTS[kind]
    except KeyError:
        raise TransportError(f"unknown transport {kind!r}; expected one of {sorted(TRANSPORTS)}") from None
    return factory(device, timeout=timeout)
