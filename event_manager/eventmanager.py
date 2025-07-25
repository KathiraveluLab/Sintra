import os
import json
from pathlib import Path
from datetime import datetime
from measurement_client.logger import logger
from .anomaly_types import ANOMALY_TYPES
from .anomaly_utils import calculate_jitter, is_outlier, geo_anomaly_check

class SintraEventManager:
    def __init__(self, fetched_results_dir="measurement_client/results/fetched_measurements", event_results_dir="event_manager/results", baseline_dir="event_manager/baseline"):
        self.fetched_results_dir = Path(fetched_results_dir)
        self.event_results_dir = Path(event_results_dir)
        self.baseline_dir = Path(baseline_dir)
        self.event_results_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.route_history = {}  # For path flapping

    def analyze_all(self):
        # Analyze all fetched measurement results
        for result_file in self.fetched_results_dir.glob("measurement_*_result.json"):
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
                measurement_id = data.get("measurement_id")
                events = self.analyze_measurement(data)
                self.save_events(measurement_id, events)
                if events:
                    logger.info(f"Events for measurement {measurement_id} saved.")
                else:
                    logger.info(f"No anomalies found for measurement {measurement_id}.")
            except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
                logger.error(f"Failed to analyze {result_file}: {e}")

    def analyze_measurement(self, data):
        # Analyze a single measurement's results and return detected events
        events = []
        timestamp = datetime.utcnow().isoformat() + "Z"
        probe_latencies = {}
        probe_distances = {}
        probe_losses = {}
        probe_jitters = {}
        probe_targets = {}
        traceroute_hops = {}

        # Map probe_id to target address for all results
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            target_addr = result.get("target_address") if "target_address" in result else result.get("target")
            probe_targets[probe_id] = target_addr
            mtype = result.get("measurement_type")
            if mtype == "ping":
                latency = result.get("latency_stats", {}).get("avg")
                loss = result.get("packet_loss_percentage")
                rtts = result.get("latency_stats", {}).get("rtts", [])
                probe_latencies[probe_id] = latency
                probe_losses[probe_id] = loss
                probe_jitters[probe_id] = calculate_jitter(rtts)
                probe_distances[probe_id] = result.get("distance_km", None)
            elif mtype == "traceroute":
                hops = result.get("hops", [])
                hop_ips = [h.get("ip") for h in hops if h.get("ip")]
                traceroute_hops[probe_id] = hop_ips

        # Outlier detection (latency/loss)
        if probe_latencies:
            for probe_id, latency in probe_latencies.items():
                if is_outlier(latency, probe_latencies.values()):
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "outlier_probe_latency",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "ping_rtt_ms",
                        "value": latency,
                        "threshold": None,
                        "units": "ms",
                        "severity": "warning"
                    })
        if probe_losses:
            for probe_id, loss in probe_losses.items():
                if is_outlier(loss, probe_losses.values()) and loss > 5.0:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "outlier_probe_loss",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "ping_loss_pct",
                        "value": loss,
                        "threshold": None,
                        "units": "%",
                        "severity": "warning"
                    })

        # Geo-anomaly: far probe has better latency than near probe
        for pid1, lat1 in probe_latencies.items():
            for pid2, lat2 in probe_latencies.items():
                if pid1 != pid2 and geo_anomaly_check(probe_distances.get(pid1), lat1, probe_distances.get(pid2), lat2):
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "geo_anomaly",
                        "probe_id": pid1,
                        "target": probe_targets[pid1],
                        "metric": "ping_rtt_ms",
                        "value": lat1,
                        "threshold": lat2,
                        "units": "ms",
                        "severity": "warning"
                    })

        # Jitter spike detection
        for probe_id, jitter in probe_jitters.items():
            if jitter > 15.0:
                events.append({
                    "timestamp": timestamp,
                    "anomaly": "jitter_spike",
                    "probe_id": probe_id,
                    "target": probe_targets[probe_id],
                    "metric": "ping_jitter_ms",
                    "value": jitter,
                    "threshold": 15.0,
                    "units": "ms",
                    "severity": "warning"
                })

        # Main anomaly detection per probe
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            target = result.get("target_address")
            mtype = result.get("measurement_type")
            # --- Latency Spike ---
            if mtype == "ping":
                latency = result.get("latency_stats", {}).get("avg")
                loss = result.get("packet_loss_percentage")
                baseline_file = self.baseline_dir / f"ping_{probe_id}_{target}.json"
                baseline_rtt = None
                if baseline_file.exists():
                    with open(baseline_file, "r") as bf:
                        baseline_rtt = json.load(bf).get("avg_rtt")
                # Save current RTT as new baseline
                if latency is not None:
                    with open(baseline_file, "w") as bf:
                        json.dump({"avg_rtt": latency}, bf)
                # Static threshold
                if latency is not None and latency > 250:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "latency_spike",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "ping_rtt_ms",
                        "value": latency,
                        "threshold": 250.0,
                        "units": "ms",
                        "severity": "warning"
                    })
                # Adaptive threshold (2x baseline)
                if latency is not None and baseline_rtt is not None and latency > 2 * baseline_rtt:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "latency_spike",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "ping_rtt_ms",
                        "value": latency,
                        "threshold": 2 * baseline_rtt,
                        "units": "ms",
                        "severity": "warning"
                    })
                # --- High Packet Loss ---
                if loss is not None and loss > 10.0:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "packet_loss",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "ping_loss_pct",
                        "value": loss,
                        "threshold": 10.0,
                        "units": "%",
                        "severity": "warning"
                    })
                # --- Unreachable Host ---
                if loss is not None and loss == 100.0:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "unreachable_host",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "reachability",
                        "value": 0,
                        "threshold": 1,
                        "units": "reachable_flag",
                        "severity": "critical"
                    })
            # --- Traceroute Route Change ---
            elif mtype == "traceroute":
                hops = result.get("hops", [])
                hop_ips = [h.get("ip") for h in hops if h.get("ip")]
                baseline_file = self.baseline_dir / f"traceroute_{probe_id}_{target}.json"
                previous_hops = None
                if baseline_file.exists():
                    with open(baseline_file, "r") as bf:
                        previous_hops = json.load(bf).get("hop_ips")
                # Save current hops as baseline
                with open(baseline_file, "w") as bf:
                    json.dump({"hop_ips": hop_ips}, bf)
                # Route change detection
                if previous_hops and hop_ips and previous_hops != hop_ips:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "route_change",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "traceroute_hops",
                        "previous_hops": previous_hops,
                        "current_hops": hop_ips,
                        "severity": "warning"
                    })
                # Path flapping detection (track history)
                route_key = f"{probe_id}_{target}"
                self.route_history.setdefault(route_key, [])
                self.route_history[route_key].append(hop_ips)
                if len(self.route_history[route_key]) > 3:
                    recent_routes = self.route_history[route_key][-3:]
                    if len(set(tuple(r) for r in recent_routes)) > 1:
                        events.append({
                            "timestamp": timestamp,
                            "anomaly": "path_flapping",
                            "probe_id": probe_id,
                            "target": probe_targets[probe_id],
                            "metric": "traceroute_hops",
                            "routes": recent_routes,
                            "severity": "warning"
                        })
                # Unreachable host via traceroute (destination not reached)
                if hop_ips and hop_ips[-1] != target:
                    events.append({
                        "timestamp": timestamp,
                        "anomaly": "unreachable_host",
                        "probe_id": probe_id,
                        "target": probe_targets[probe_id],
                        "metric": "reachability",
                        "value": 0,
                        "threshold": 1,
                        "units": "reachable_flag",
                        "severity": "critical"
                    })
        return events

    def save_events(self, measurement_id, events):
        # Save detected events to event_manager/results/<measurement_id>.json
        out_file = self.event_results_dir / f"{measurement_id}.json"
        with open(out_file, "w") as f:
            json.dump({"measurement_id": measurement_id, "events": events}, f, indent=2)

    def send_to_controller(self, measurement_id):
        # sending events to POX controller (to be implemented later)
        logger.info(f"Sending events for measurement {measurement_id} to POX controller (stub).")

    def show_alerts_summary(self):
        # Print a summary of all alerts/anomalies found
        for result_file in self.event_results_dir.glob("*.json"):
            with open(result_file, "r") as f:
                data = json.load(f)
            measurement_id = data.get("measurement_id")
            events = data.get("events", [])
            logger.info(f"Measurement {measurement_id}: {len(events)} anomalies detected.")
            # Print per-anomaly summary using ANOMALY_TYPES
            anomaly_counts = {}
            for event in events:
                anomaly = event.get("anomaly")
                anomaly_counts[anomaly] = anomaly_counts.get(anomaly, 0) + 1
            for anomaly, count in anomaly_counts.items():
                desc = ANOMALY_TYPES.get(anomaly, {}).get("description", "")
                logger.info(f"  {anomaly}: {count} events - {desc}")

