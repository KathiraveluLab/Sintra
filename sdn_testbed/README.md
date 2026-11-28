# Sintra Closed-Loop SDN Testbed (Mininet + POX)

This package closes the control loop between `SintraEventManager` and an OpenFlow 1.0 **POX** SDN controller over a multi-path **Mininet** interdomain topology.

## Topology (`topology.py`)

Six OpenFlow switches (`s1`–`s6`) connect `h1` (`10.0.0.1`) and `h2` (`10.0.0.2`) across three disjoint interdomain paths:

| Path | Switch Sequence | Baseline RTT | Role |
|---|---|---|---|
| **Path A** | `s1 -> s2 -> s5` | 20 ms | Default shortest-hop (BGP-like) path |
| **Path B** | `s1 -> s3 -> s5` | 36 ms | Alternate low-latency path |
| **Path C** | `s1 -> s4 -> s6 -> s5` | 54 ms | Backup multi-hop path |

## Components

- `path_engine.py`: Weighted Dijkstra path solver (`AdaptivePathEngine`), three selectable control policies (`static`, `threshold`, `sintra`), exponential penalty decay, cooldown hysteresis, and `NorthboundRESTServer` (`POST /sintra/events`, `GET /sintra/status`, `POST /sintra/reset`, `POST /sintra/policy`).
- `pox_sintra_controller.py`: POX OpenFlow 1.0 controller wrapping `AdaptivePathEngine` + `NorthboundRESTServer` with thread-safe make-before-break `ofp_flow_mod` programming.
- `topology.py`: Mininet `SintraInterdomainTopo`, dynamic `tc netem` `ImpairmentController`, and `load_ripe_atlas_trace()` for RIPE Atlas trace replay.
- `probe_adapter.py`: Translates Linux `ping` output from Mininet hosts into Sintra's canonical `measurement_*_result.json` format.
- `run_experiments.py`: Automated harness comparing `static` vs. `threshold` vs. `sintra` across latency spike, moderate degradation, packet loss, jitter spike, and link outage scenarios, producing CSV logs, JSON summaries, and Matplotlib figures.

## Quick Start on Ubuntu 22.04 / 24.04 VM

```bash
bash sdn_testbed/setup_ubuntu.sh
```

**Terminal 1 — Start the POX controller:**
```bash
PYTHONPATH=$(pwd) python3 ~/pox/pox.py \
    log.level --INFO \
    sdn_testbed.pox_sintra_controller \
    --rest_port=8080 --policy=sintra --cooldown=5
```

**Terminal 2 — Run the automated Mininet experiments:**
```bash
sudo .venv/bin/python -m sdn_testbed.run_experiments --mode mininet --trials 5
```

To replay an actual RIPE Atlas measurement JSON fetched by Sintra onto Path A:
```bash
sudo .venv/bin/python -m sdn_testbed.run_experiments \
    --mode mininet --trials 5 \
    --ripe-trace measurement_client/results/fetched_measurements/measurement_<ID>_result.json
```

## Smoke Testing the Control-Loop Pipeline Without Mininet (Windows / CI)

```bash
.venv/bin/python -m sdn_testbed.run_experiments --mode simulate --trials 1 --scenarios latency_spike jitter_spike
```

> **Note:** `--mode simulate` exercises the real `SintraEventManager`, HTTP REST dispatch, `NorthboundRESTServer`, and `AdaptivePathEngine` with synthetic telemetry solely for pipeline verification. For paper evaluation results, run `--mode mininet` on Linux with Open vSwitch and POX.
