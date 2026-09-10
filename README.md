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

## Layout

| Path | Contents |
| --- | --- |
| `topology/netqa.clab.yml` | Containerlab topology definition |
| `topology/configs/` | Per-router FRR configuration |
| `docker/` | Node image definitions |
| `inventory.yml` | Device inventory shared by all automation |
| `netqa/` | Python automation package |
| `scripts/lab.sh` | Lab lifecycle control |
| `scripts/build-images.sh` | Node image build |
| `scripts/collect.py` | State collection over SSH (Python) |
| `scripts/collect.sh` | State collection over SSH (Bash) |
