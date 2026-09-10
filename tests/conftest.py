from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest

from netqa.backends import RouteManager, make_backend
from netqa.client import ApiClient
from netqa.faults import FaultInjector
from netqa.inventory import Device, load_inventory
from netqa.spec import TopologySpec, load_spec
from netqa.wait import wait_until

ROOT = Path(__file__).resolve().parent.parent
LAB_SCRIPT = ROOT / "scripts" / "lab.sh"
SERVE_SCRIPT = ROOT / "scripts" / "serve.sh"

ROUTERS = ("r1", "r2")
HOSTS = {"h1": "10.0.1.10", "h2": "10.0.2.10"}
TRANSIT_NEXT_HOP = {"r1": "10.0.12.2", "r2": "10.0.12.1"}
TRANSIT_LINKS = {"r1": ("eth2", "eth3"), "r2": ("eth2", "eth3")}
ECMP_NEXT_HOPS = {
    "r1": ["10.0.12.2", "10.0.13.2"],
    "r2": ["10.0.12.1", "10.0.13.1"],
}
FAR_PREFIX = {"r1": "10.0.2.0/24", "r2": "10.0.1.0/24"}
TEST_PREFIXES = ("192.168.240.0/24", "192.168.241.0/24", "192.168.242.0/24")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("netqa")
    group.addoption("--redeploy", action="store_true", help="tear down and redeploy the lab first")
    group.addoption("--destroy-lab", action="store_true", help="destroy the lab after the session")
    group.addoption("--api-url", default=None, help="use an already running API service")
    group.addoption("--backend", default=None, choices=["cli", "api"], help="restrict to one backend")


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=check)


def _lab_is_running() -> bool:
    result = _run("docker", "ps", "--filter", "name=clab-netqa-", "--format", "{{.Names}}", check=False)
    running = {line for line in result.stdout.split() if line}
    return {f"clab-netqa-{n}" for n in (*ROUTERS, *HOSTS)}.issubset(running)


@pytest.fixture(scope="session")
def inventory() -> dict[str, Device]:
    return load_inventory()


@pytest.fixture(scope="session")
def spec() -> TopologySpec:
    return load_spec()


@pytest.fixture(scope="session")
def lab(request: pytest.FixtureRequest) -> Iterator[None]:
    deployed_here = False

    if request.config.getoption("--redeploy"):
        _run(str(LAB_SCRIPT), "destroy", check=False)

    if not _lab_is_running():
        result = _run(str(LAB_SCRIPT), "deploy", check=False)
        if result.returncode != 0:
            pytest.fail(f"lab deploy failed:\n{result.stdout}\n{result.stderr}")
        deployed_here = True

    result = _run(str(LAB_SCRIPT), "wait", "120", check=False)
    if result.returncode != 0:
        pytest.fail(f"lab did not converge:\n{result.stdout}\n{result.stderr}")

    yield

    if deployed_here and request.config.getoption("--destroy-lab"):
        _run(str(LAB_SCRIPT), "destroy", check=False)


@pytest.fixture(scope="session")
def api_url(request: pytest.FixtureRequest, lab: None) -> Iterator[str]:
    external = request.config.getoption("--api-url")
    if external:
        yield external
        return

    url = "http://127.0.0.1:8000"
    process = subprocess.Popen(
        [str(SERVE_SCRIPT)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    probe = ApiClient(url)
    try:
        wait_until(probe.is_available, timeout=45, interval=1, description="API service to start")
    except Exception:
        process.terminate()
        output = process.communicate(timeout=10)[0]
        pytest.fail(f"API service did not start:\n{output}")
    finally:
        probe.close()

    yield url

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="session")
def cli_backend(lab: None) -> Iterator[RouteManager]:
    backend = make_backend("cli")
    yield backend
    backend.close()


@pytest.fixture(scope="session")
def api_backend(api_url: str) -> Iterator[RouteManager]:
    backend = make_backend("api", base_url=api_url)
    yield backend
    backend.close()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "backend" not in metafunc.fixturenames:
        return
    selected = metafunc.config.getoption("--backend")
    kinds = [selected] if selected else ["cli", "api"]
    metafunc.parametrize("backend", kinds, indirect=True, ids=kinds)


@pytest.fixture
def backend(request: pytest.FixtureRequest) -> RouteManager:
    return request.getfixturevalue(f"{request.param}_backend")


@pytest.fixture
def faults(inventory: dict[str, Device], lab: None) -> Iterator[dict[str, FaultInjector]]:
    injectors = {
        name: FaultInjector(device)
        for name, device in inventory.items()
    }
    yield injectors

    for name, injector in injectors.items():
        try:
            for interface in TRANSIT_LINKS.get(name, ()):
                injector.set_link(interface, up=True)
            if name in TRANSIT_LINKS:
                injector.flush_filter_rules()
        except Exception:
            pass
        injector.close()


@pytest.fixture
def converged(cli_backend: RouteManager) -> Iterator[None]:
    yield
    wait_until(
        lambda: cli_backend.is_reachable("h1", HOSTS["h2"], count=1),
        timeout=120,
        interval=1,
        description="topology to reconverge after the test",
    )


@pytest.fixture
def route_sandbox(backend: RouteManager) -> Iterator[callable]:
    added: list[tuple[str, str, str]] = []

    def add(device: str, prefix: str, next_hop: str) -> None:
        backend.add_static_route(device, prefix, next_hop)
        added.append((device, prefix, next_hop))

    yield add

    for device, prefix, next_hop in reversed(added):
        try:
            backend.delete_static_route(device, prefix, next_hop)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _no_leaked_test_routes(request: pytest.FixtureRequest) -> Iterator[None]:
    backend = (
        request.getfixturevalue("backend")
        if "backend" in request.fixturenames
        else None
    )

    yield

    if backend is None:
        return
    for device in ROUTERS:
        try:
            routes = backend.list_routes(device)
        except Exception:
            continue
        for prefix in TEST_PREFIXES:
            if prefix in routes:
                try:
                    backend.delete_static_route(device, prefix)
                except Exception:
                    pass
