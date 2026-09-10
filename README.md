# netqa-verify

Automated verification of a simulated multi-node network topology, built with
Containerlab, FRRouting and pytest.

## Topology

```
   h1 ──────────── r1 ═══════════════ r2 ──────────── h2
10.0.1.10       10.0.1.1           10.0.2.1       10.0.2.10
                10.0.12.1 ──────── 10.0.12.2
              lo 10.255.255.1     lo 10.255.255.2
```

| Node | Role | Image |
| --- | --- | --- |
| `r1`, `r2` | FRRouting routers, OSPF area 0 | `netqa/frr:10.7.1` |
| `h1`, `h2` | End hosts on separate subnets | `netqa/host:latest` |

Both images are built locally from `docker/`, layering an SSH daemon onto the
upstream FRR and netshoot images so the devices can be driven the same way a
physical switch would be. Management addresses are pinned on a dedicated
`172.100.100.0/24` network so the inventory stays stable across redeployments.

`h1` and `h2` sit on different subnets and can only reach each other if OSPF has
converged and both routers have installed the far-side route, so end-to-end
reachability is a meaningful assertion rather than a formality.

## Requirements

Containerlab manipulates container network namespaces directly, so the Docker
daemon must run in the same kernel. On Windows this means native Docker Engine
inside a WSL2 distribution; Docker Desktop's WSL integration will not work, as
its daemon runs in a separate VM.

- WSL2 with Ubuntu, `[automount] options = "metadata"` set in `/etc/wsl.conf`
- Native Docker Engine installed inside the distribution
- Containerlab

## Usage

Build the node images once, then manage the lab lifecycle:

```bash
./scripts/build-images.sh   # build netqa/frr and netqa/host
./scripts/lab.sh deploy     # bring the topology up
./scripts/lab.sh wait       # block until the data plane converges
./scripts/lab.sh status     # node and OSPF neighbour state
./scripts/lab.sh destroy    # tear down
```

## Collecting device state

The same operations are implemented twice, over SSH, against the inventory in
`inventory.yml`.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

PYTHONPATH=. ./.venv/bin/python scripts/collect.py          # Python, netmiko
PYTHONPATH=. ./.venv/bin/python scripts/collect.py --json   # machine-readable
./scripts/collect.sh                                        # Bash, sshpass
```

Router state is read through `vtysh`, which supports native JSON output, so the
Python layer parses structured data rather than scraping CLI text.

Lab credentials are `admin` / `admin`. They are intentionally trivial and are
suitable only for a disposable local topology.

## Interfaces

Every device operation is reachable through two independent paths, which lets
one interface be validated against the other rather than against itself.

| Path | Transport | Entry point |
| --- | --- | --- |
| CLI | SSH (netmiko) | `netqa.cli.CliDevice` |
| API | Docker exec, over HTTP | `netqa.api` service, `netqa.client.ApiClient` |

```bash
./scripts/serve.sh          # http://127.0.0.1:8000, docs at /docs
```

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service and transport status |
| `GET` | `/devices` | Inventory listing |
| `GET` | `/devices/{name}/interfaces` | Interface state |
| `GET` | `/devices/{name}/addresses` | Configured addresses |
| `GET` | `/devices/{name}/routes` | Routing table, optional `?protocol=` filter |
| `GET` | `/devices/{name}/ospf/neighbors` | OSPF adjacencies |
| `POST` | `/devices/{name}/routes` | Add a static route |
| `DELETE` | `/devices/{name}/routes/{prefix}` | Remove a static route |
| `GET` | `/devices/{name}/ping/{destination}` | Reachability check |

A route written through the API is observable over SSH and vice versa, so the
two paths can be asserted equivalent.

## Tests

Both interfaces implement the same `RouteManager` abstract base class, so every
assertion can be executed through either one. Tests requesting the `backend`
fixture are parametrised across both automatically.

```bash
./.venv/bin/pytest                    # everything, both backends
./.venv/bin/pytest --backend cli      # SSH path only
./.venv/bin/pytest -m parity          # by marker
./.venv/bin/pytest --redeploy         # rebuild the lab first
./.venv/bin/pytest --destroy-lab      # tear down afterwards
```

| Marker | Scope |
| --- | --- |
| `functional` | Core behaviour of the running topology |
| `parity` | Identical assertions through every backend |
| `regression` | Re-checks core paths after configuration change |
| `performance` | Timing characteristics |
| `security` | Traffic filtering behaves as intended |

Fixtures are layered by cost. The lab is brought up once per session and reused
if already running; API service startup is session scoped; static routes created
during a test are removed at function scope, with a session-wide sweep as a
backstop.

Timing-sensitive assertions poll through `netqa.wait.wait_until` rather than
sleeping for a fixed period. Protocol adjacency reaching `Full` does not imply
the data plane is forwarding, so readiness is defined as observable end-to-end
reachability.

## Layout

| Path | Contents |
| --- | --- |
| `topology/netqa.clab.yml` | Containerlab topology definition |
| `topology/configs/` | Per-router FRR configuration |
| `docker/` | Node image definitions |
| `inventory.yml` | Device inventory shared by all automation |
| `netqa/inventory.py` | Device inventory model |
| `netqa/transport.py` | SSH and Docker transports |
| `netqa/cli.py` | Device operations over a transport |
| `netqa/api.py` | FastAPI service |
| `netqa/client.py` | HTTP client SDK |
| `netqa/backends.py` | `RouteManager` abstraction and backends |
| `netqa/wait.py` | Polling helpers for timing-sensitive assertions |
| `tests/` | pytest suite and fixtures |
| `scripts/lab.sh` | Lab lifecycle control |
| `scripts/build-images.sh` | Node image build |
| `scripts/collect.py` | State collection over SSH (Python) |
| `scripts/collect.sh` | State collection over SSH (Bash) |
| `scripts/serve.sh` | Run the API service |
