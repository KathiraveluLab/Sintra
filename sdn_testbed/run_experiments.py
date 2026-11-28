"""
Automated closed-loop SDN experiment runner for Sintra (Mininet + POX).

Compares three control policies across controlled impairment scenarios:
  - static:    Shortest-hop BGP-like baseline (never reroutes)
  - threshold: Static threshold-only rerouting (>250 ms RTT or 100% outage)
  - sintra:    Full Sintra multi-anomaly engine + hysteresis/cooldown damping

Modes:
  --mode mininet   (Ubuntu/Linux + root + POX running): real OpenFlow 1.0 + tc netem + iperf3 UDP
  --mode simulate  (Any OS, CI/smoke testing): exercises real SintraEventManager + HTTP REST +
                   AdaptivePathEngine loop with synthetic link telemetry (clearly tagged as simulation).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import tempfile
import time
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional

import requests

from event_manager.anomaly_utils import calculate_jitter, calculate_percentile
from event_manager.eventmanager import SintraEventManager
from sdn_testbed.path_engine import AdaptivePathEngine, NorthboundRESTServer, PATH_NAMES
from sdn_testbed.probe_adapter import build_sintra_measurement_payload, run_mininet_ping
from sdn_testbed.topology import (
    ImpairmentController,
    MININET_AVAILABLE,
    create_sintra_network,
    load_ripe_atlas_trace,
)


SCENARIOS: Dict[str, Dict[str, Any]] = {
    "latency_spike": {
        "label": "Latency Spike (+270 ms on Path A)",
        "extra_rtt_ms": 270.0,
        "jitter_ms": 0.0,
        "loss_pct": 0.0,
    },
    "moderate_degradation": {
        "label": "Moderate Degradation (+160 ms on Path A)",
        "extra_rtt_ms": 160.0,
        "jitter_ms": 0.0,
        "loss_pct": 0.0,
    },
    "packet_loss": {
        "label": "Packet Loss (15% on Path A)",
        "extra_rtt_ms": 0.0,
        "jitter_ms": 0.0,
        "loss_pct": 15.0,
    },
    "jitter_spike": {
        "label": "Jitter Spike (50 ms +/- 40 ms on Path A)",
        "extra_rtt_ms": 50.0,
        "jitter_ms": 40.0,
        "loss_pct": 0.0,
    },
    "link_outage": {
        "label": "Link Outage (100% Loss on Path A)",
        "extra_rtt_ms": 0.0,
        "jitter_ms": 0.0,
        "loss_pct": 100.0,
    },
}

POLICIES = ("static", "threshold", "sintra")


def _make_event_manager(
    tmp_dir: Path,
    controller_url: str,
    cooldown_s: float,
    min_consecutive: int,
) -> SintraEventManager:
    em = SintraEventManager(
        fetched_results_dir=str(tmp_dir / "fetched"),
        event_results_dir=str(tmp_dir / "events"),
        baseline_dir=str(tmp_dir / "baseline"),
    )
    em.config["controller"] = {
        "enabled": True,
        "url": controller_url,
        "timeout_seconds": 5,
        "cooldown_seconds": cooldown_s,
        "min_consecutive_anomalies": min_consecutive,
        "min_severity": "warning",
        "allow_insecure_http": True,
    }
    return em


def _simulate_probe_metrics(
    active_path: List[int],
    scenario: Dict[str, Any],
    impaired: bool,
    rng: random.Random,
) -> Dict[str, Any]:
    """Generate synthetic RTT/loss sample for CI smoke testing (--mode simulate only)."""
    path_base_rtt = {
        (1, 2, 5): 20.0,
        (1, 3, 5): 36.0,
        (1, 4, 6, 5): 54.0,
    }.get(tuple(active_path), 20.0)

    on_impaired_path = impaired and tuple(active_path) == (1, 2, 5)
    extra_rtt = scenario["extra_rtt_ms"] if on_impaired_path else 0.0
    jitter = scenario["jitter_ms"] if on_impaired_path else 1.5
    loss_pct = scenario["loss_pct"] if on_impaired_path else 0.0

    packets_sent = 5
    if loss_pct >= 100.0:
        return {
            "rtts": [],
            "avg": None,
            "min": None,
            "max": None,
            "median": None,
            "p95": None,
            "p99": None,
            "jitter_ms": 0.0,
            "packets_sent": packets_sent,
            "packets_received": 0,
            "packet_loss_percentage": 100.0,
        }

    rtts: List[float] = []
    for _ in range(packets_sent):
        if loss_pct > 0.0 and rng.random() * 100.0 < loss_pct:
            continue
        sample_rtt = max(1.0, path_base_rtt + extra_rtt + rng.gauss(0.0, max(jitter, 0.5)))
        rtts.append(round(sample_rtt, 2))

    # Guarantee deterministic loss representation for smoke verification if requested loss > 0
    if loss_pct > 0.0 and len(rtts) == packets_sent:
        rtts.pop()

    actual_loss = round(((packets_sent - len(rtts)) / packets_sent) * 100.0, 2)
    return {
        "rtts": rtts,
        "avg": round(mean(rtts), 2) if rtts else None,
        "min": min(rtts) if rtts else None,
        "max": max(rtts) if rtts else None,
        "median": round(median(rtts), 2) if rtts else None,
        "p95": round(calculate_percentile(rtts, 95), 2) if rtts else None,
        "p99": round(calculate_percentile(rtts, 99), 2) if rtts else None,
        "jitter_ms": round(calculate_jitter(rtts), 2),
        "packets_sent": packets_sent,
        "packets_received": len(rtts),
        "packet_loss_percentage": actual_loss,
    }


def run_single_trial(
    mode: str,
    scenario_name: str,
    policy: str,
    trial_idx: int,
    rest_base_url: str,
    rounds: int = 18,
    impair_start: int = 5,
    impair_end: int = 13,
    cooldown_s: float = 2.0,
    probe_interval_s: float = 0.0,
    mininet_net: Any = None,
    impairment_ctl: Optional[ImpairmentController] = None,
    ripe_trace: Optional[List[Dict[str, float]]] = None,
) -> Dict[str, Any]:
    """Execute one closed-loop trial and return per-round telemetry + summary stats."""
    scenario = SCENARIOS[scenario_name]
    requests.post(f"{rest_base_url}/sintra/reset", json={"policy": policy}, timeout=5)
    if impairment_ctl is not None:
        impairment_ctl.reset_path_a()

    rng = random.Random(1000 + trial_idx * 31 + hash((scenario_name, policy)) % 997)
    records: List[Dict[str, Any]] = []
    detect_times_ms: List[float] = []
    dispatch_times_ms: List[float] = []
    compute_times_ms: List[float] = []
    rule_times_ms: List[float] = []

    with tempfile.TemporaryDirectory() as td:
        em = _make_event_manager(
            Path(td),
            controller_url=f"{rest_base_url}/sintra/events",
            cooldown_s=cooldown_s,
            min_consecutive=1,
        )

        h1 = mininet_net.get("h1") if mininet_net is not None else None
        impairment_active = False

        for step in range(rounds):
            should_impair = impair_start <= step < impair_end
            if mode == "mininet" and impairment_ctl is not None:
                if ripe_trace and should_impair:
                    sample = ripe_trace[(step - impair_start) % len(ripe_trace)]
                    impairment_ctl.inject_path_a_impairment(
                        extra_rtt_ms=max(0.0, sample["rtt_ms"] - 20.0),
                        loss_pct=sample["loss_pct"],
                    )
                    impairment_active = True
                elif should_impair and not impairment_active:
                    impairment_ctl.inject_path_a_impairment(
                        extra_rtt_ms=scenario["extra_rtt_ms"],
                        jitter_ms=scenario["jitter_ms"],
                        loss_pct=scenario["loss_pct"],
                    )
                    impairment_active = True
                elif not should_impair and impairment_active:
                    impairment_ctl.reset_path_a()
                    impairment_active = False

            status_before = requests.get(f"{rest_base_url}/sintra/status", timeout=5).json()
            active_path = status_before["active_path"]

            if mode == "mininet":
                ping_metrics = run_mininet_ping(h1, target_ip="10.0.0.2", count=5, interval_s=0.2)
            else:
                ping_metrics = _simulate_probe_metrics(active_path, scenario, should_impair, rng)

            msm_id = f"{scenario_name}_{policy}_t{trial_idx}_s{step}"
            payload = build_sintra_measurement_payload(
                measurement_id=msm_id,
                probe_id="mininet_h1",
                target_ip="10.0.0.2",
                ping_metrics=ping_metrics,
            )

            t_det = time.perf_counter()
            events = em.analyze_measurement(payload)
            det_ms = (time.perf_counter() - t_det) * 1000.0
            detect_times_ms.append(det_ms)

            ctrl_res = em.send_to_controller(msm_id, events)
            rerouted = False
            if ctrl_res.get("sent"):
                dispatch_times_ms.append(float(ctrl_res.get("dispatch_latency_ms", 0.0)))
                resp = ctrl_res.get("response") or {}
                if isinstance(resp, dict):
                    compute_times_ms.append(float(resp.get("compute_time_ms", 0.0)))
                    rule_times_ms.append(float(resp.get("rule_install_time_ms", 0.0)))
                    rerouted = bool(resp.get("rerouted", False))

            status_after = requests.get(f"{rest_base_url}/sintra/status", timeout=5).json()

            records.append({
                "mode": mode,
                "scenario": scenario_name,
                "policy": policy,
                "trial": trial_idx,
                "step": step,
                "impaired": should_impair,
                "active_path": status_after["active_path_name"],
                "avg_rtt_ms": ping_metrics["avg"],
                "p95_rtt_ms": ping_metrics["p95"],
                "jitter_ms": ping_metrics["jitter_ms"],
                "packet_loss_pct": ping_metrics["packet_loss_percentage"],
                "anomalies": ",".join(sorted({e["anomaly"] for e in events})),
                "rerouted": rerouted,
                "detect_ms": round(det_ms, 3),
            })

            if probe_interval_s > 0.0:
                time.sleep(probe_interval_s)

        if impairment_ctl is not None:
            impairment_ctl.reset_path_a()

        final_status = requests.get(f"{rest_base_url}/sintra/status", timeout=5).json()

    impair_rtts = [r["avg_rtt_ms"] for r in records if r["impaired"] and r["avg_rtt_ms"] is not None]
    impair_loss = [r["packet_loss_pct"] for r in records if r["impaired"]]
    impair_jitter = [r["jitter_ms"] for r in records if r["impaired"]]

    return {
        "mode": mode,
        "scenario": scenario_name,
        "policy": policy,
        "trial": trial_idx,
        "switchover_count": final_status["switchover_count"],
        "mean_impaired_rtt_ms": round(mean(impair_rtts), 2) if impair_rtts else None,
        "p95_impaired_rtt_ms": round(calculate_percentile(impair_rtts, 95), 2) if impair_rtts else None,
        "mean_impaired_loss_pct": round(mean(impair_loss), 2) if impair_loss else 0.0,
        "mean_impaired_jitter_ms": round(mean(impair_jitter), 2) if impair_jitter else 0.0,
        "mean_detect_ms": round(mean(detect_times_ms), 3) if detect_times_ms else 0.0,
        "mean_dispatch_ms": round(mean(dispatch_times_ms), 3) if dispatch_times_ms else 0.0,
        "mean_compute_ms": round(mean(compute_times_ms), 3) if compute_times_ms else 0.0,
        "mean_rule_install_ms": round(mean(rule_times_ms), 3) if rule_times_ms else 0.0,
        "records": records,
    }


def plot_experiment_results(all_records: List[Dict[str, Any]], output_dir: Path, mode: str) -> List[Path]:
    """Generate publication-grade comparison figures from collected trial records."""
    os.environ["MPLBACKEND"] = "Agg"
    import matplotlib.pyplot as plt
    from statistics import stdev

    output_dir.mkdir(parents=True, exist_ok=True)
    generated: List[Path] = []
    tag = "Mininet + POX" if mode == "mininet" else "Simulated Control-Loop Smoke Test"
    policy_styles = {
        "static": ("#d62728", "--", "s", 6.5, 3, "Static Shortest-Path (BGP-like)"),
        "threshold": ("#ff7f0e", "-.", "^", 7.5, 4, "Threshold-Only (>250ms / Outage)"),
        "sintra": ("#1f77b4", "-", "o", 5.5, 5, "Sintra Closed-Loop Adaptive"),
    }

    scenarios_present = sorted({r["scenario"] for r in all_records})
    for scen in scenarios_present:
        fig, ax = plt.subplots(figsize=(9.8, 6.0))
        scen_rows = [r for r in all_records if r["scenario"] == scen]
        impaired_steps = sorted({int(r["step"]) for r in scen_rows if str(r["impaired"]).lower() == "true"})
        if impaired_steps:
            ax.axvspan(min(impaired_steps), max(impaired_steps), color="red", alpha=0.10, label="Impairment Window")

        max_step = 0
        for pol in POLICIES:
            color, ls, marker, msize, zord, label = policy_styles[pol]
            pol_rows = [r for r in scen_rows if r["policy"] == pol]
            by_step: Dict[int, List[float]] = {}
            for r in pol_rows:
                raw_val = r["packet_loss_pct"] if scen in ("packet_loss", "link_outage") else r["avg_rtt_ms"]
                if raw_val not in (None, "", "None"):
                    step_i = int(r["step"])
                    max_step = max(max_step, step_i)
                    by_step.setdefault(step_i, []).append(float(raw_val))
            if by_step:
                xs = sorted(by_step.keys())
                ys = [mean(by_step[s]) for s in xs]
                sds = [stdev(by_step[s]) if len(by_step[s]) > 1 else 0.0 for s in xs]
                ax.plot(
                    xs, ys, color=color, linestyle=ls, linewidth=2.6,
                    marker=marker, markersize=msize, zorder=zord, label=label,
                )
                if any(sd > 0.0 for sd in sds):
                    low = [max(0.0, y - sd) for y, sd in zip(ys, sds)]
                    high = [y + sd for y, sd in zip(ys, sds)]
                    ax.fill_between(xs, low, high, color=color, alpha=0.14, zorder=zord - 1)

        ylabel = "Packet Loss (%)" if scen in ("packet_loss", "link_outage") else "Average RTT (ms)"
        ax.set_xlabel("Probe Interval Step", fontsize=15, fontweight="bold", labelpad=8)
        ax.set_ylabel(ylabel, fontsize=15, fontweight="bold", labelpad=8)
        ax.set_xticks(range(0, max_step + 1, 2))
        ax.tick_params(labelsize=13)
        ax.grid(True, alpha=0.35)

        # Place legend cleanly OUTSIDE above the axes so it never covers any curve
        ax.legend(
            fontsize=12.5,
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            ncol=2,
            frameon=True,
            facecolor="white",
            framealpha=0.95,
        )
        fig.suptitle(
            f"{SCENARIOS[scen]['label']} ({tag})",
            fontsize=17,
            fontweight="bold",
            y=1.03,
        )
        fig.tight_layout()
        out_path = output_dir / f"sdn_{mode}_{scen}.png"
        fig.savefig(out_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        generated.append(out_path)

    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="Sintra Mininet + POX Closed-Loop Experiment Runner")
    parser.add_argument("--mode", choices=["mininet", "simulate"], default="mininet")
    parser.add_argument("--rest-url", default="http://127.0.0.1:8080")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6633)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=18)
    parser.add_argument("--cooldown", type=float, default=2.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--scenarios", nargs="+", default=list(SCENARIOS.keys()), choices=list(SCENARIOS.keys()))
    parser.add_argument("--ripe-trace", type=str, default=None, help="Optional Sintra RIPE Atlas JSON file for trace replay")
    parser.add_argument("--output-dir", default="sdn_testbed/results")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ripe_trace = load_ripe_atlas_trace(args.ripe_trace) if args.ripe_trace else None

    sim_server: Optional[NorthboundRESTServer] = None
    mininet_net: Any = None
    impairment_ctl: Optional[ImpairmentController] = None
    rest_url = args.rest_url.rstrip("/")

    if args.mode == "simulate":
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=args.cooldown)
        sim_server = NorthboundRESTServer(engine=engine, host="127.0.0.1", port=0)
        host, port = sim_server.start()
        rest_url = f"http://{host}:{port}"
        probe_interval = 0.0
    else:
        if not MININET_AVAILABLE:
            raise SystemExit("Mininet is not available. Run on Ubuntu/Linux with Mininet installed, or use --mode simulate.")
        mininet_net = create_sintra_network(args.controller_ip, args.controller_port)
        mininet_net.start()
        time.sleep(2.0)  # Wait for OVS switches to connect to POX
        impairment_ctl = ImpairmentController(mininet_net)
        probe_interval = args.interval

    all_summaries: List[Dict[str, Any]] = []
    all_records: List[Dict[str, Any]] = []

    try:
        for scenario_name in args.scenarios:
            for policy in POLICIES:
                for trial in range(1, args.trials + 1):
                    res = run_single_trial(
                        mode=args.mode,
                        scenario_name=scenario_name,
                        policy=policy,
                        trial_idx=trial,
                        rest_base_url=rest_url,
                        rounds=args.rounds,
                        cooldown_s=args.cooldown,
                        probe_interval_s=probe_interval,
                        mininet_net=mininet_net,
                        impairment_ctl=impairment_ctl,
                        ripe_trace=ripe_trace,
                    )
                    all_records.extend(res["records"])
                    summary = {k: v for k, v in res.items() if k != "records"}
                    all_summaries.append(summary)
                    print(
                        f"[{args.mode}] {scenario_name:20s} | {policy:9s} | trial {trial} | "
                        f"impaired_rtt={summary['mean_impaired_rtt_ms']}ms | "
                        f"loss={summary['mean_impaired_loss_pct']}% | "
                        f"switches={summary['switchover_count']}"
                    )
    finally:
        if mininet_net is not None:
            mininet_net.stop()
        if sim_server is not None:
            sim_server.stop()

    # Save raw CSV & JSON summary
    csv_path = out_dir / f"sdn_{args.mode}_records.csv"
    if all_records:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_records[0].keys()))
            writer.writeheader()
            writer.writerows(all_records)

    summary_path = out_dir / f"sdn_{args.mode}_summary.json"
    summary_path.write_text(json.dumps(all_summaries, indent=2), encoding="utf-8")
    plots = plot_experiment_results(all_records, out_dir / "plots", args.mode)
    print(f"Saved CSV ({csv_path}), summary ({summary_path}), and {len(plots)} plot(s).")


if __name__ == "__main__":
    main()
