import os
import re
import json
import time
import tempfile
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse
from measurement_client.logger import logger
from .anomaly_types import ANOMALY_TYPES
from .anomaly_utils import (
    calculate_jitter,
    is_outlier,
    geo_anomaly_check,
    calculate_distance_km,
    calculate_jaccard_similarity,
)


class SintraEventManager:
    """
    Sintra Event Manager for detecting network anomalies from RIPE Atlas measurements.
    
    This class processes measurement results and detects various types of network
    anomalies including latency spikes, packet loss, jitter spikes, routing changes,
    and path flapping. It also manages adaptive baselines for latency and traceroute hops.
    """
    
    def __init__(self, 
                 fetched_results_dir: str = "measurement_client/results/fetched_measurements",
                 event_results_dir: str = "event_manager/results", 
                 baseline_dir: str = "event_manager/baseline",
                 config_path: Optional[str] = None):

        self.fetched_results_dir = Path(fetched_results_dir)
        self.event_results_dir = Path(event_results_dir)
        self.baseline_dir = Path(baseline_dir)
        
        # Create directories if they don't exist
        self._ensure_directories()
        
        # Load configuration with default thresholds
        self.config = self._load_config(config_path)
        
        # Route history for path flapping detection
        self.route_history: Dict[str, List[List[str]]] = {}
        
        # Closed-loop controller hysteresis & cooldown state (keyed by target)
        self._last_controller_dispatch: Dict[str, float] = {}
        self._consecutive_anomaly_counts: Dict[str, int] = {}
        
        logger.info(f"SintraEventManager initialized with results dir: {self.fetched_results_dir}")

    def _ensure_directories(self) -> None:
        try:
            self.event_results_dir.mkdir(parents=True, exist_ok=True)
            self.baseline_dir.mkdir(parents=True, exist_ok=True)
            logger.debug("Directories created/verified successfully")
        except OSError as e:
            logger.error(f"Failed to create directories: {e}")
            raise

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        default_config = {
            "thresholds": {
                "latency_spike_ms": 250.0,
                "latency_spike_multiplier": 2.0,
                "packet_loss_percentage": 10.0,
                "jitter_spike_ms": 15.0,
                "outlier_factor": 2.0,
                "geo_anomaly_margin_ms": 50.0,
                "path_flapping_window": 3,
                "route_change_jaccard_threshold": 1.0
            },
            "target_thresholds": {},
            "target_coordinates": {},
            "detection": {
                "enable_outlier_detection": True,
                "enable_geo_anomaly_detection": True,
                "enable_adaptive_baseline": True
            },
            "controller": {
                "enabled": False,
                "url": "http://127.0.0.1:8080/sintra/events",
                "timeout_seconds": 5,
                "cooldown_seconds": 15.0,
                "min_consecutive_anomalies": 1,
                "min_severity": "warning",
                "allow_insecure_http": False
            }
        }
        
        if config_path and Path(config_path).exists():
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                for section, values in user_config.items():
                    if section in default_config:
                        default_config[section].update(values)
                    else:
                        default_config[section] = values
                logger.info(f"Configuration loaded from {config_path}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load config from {config_path}: {e}. Using defaults.")
        else:
            logger.info("Using default configuration")
            
        return default_config

    def analyze_all(self) -> None:
        logger.info("Starting analysis of all measurement results")
        
        result_files = list(self.fetched_results_dir.glob("measurement_*_result.json"))
        if not result_files:
            logger.warning(f"No measurement result files found in {self.fetched_results_dir}")
            return
            
        processed_count = 0
        error_count = 0
        all_results = []  # Collect (measurement_id, events) for post-analysis webhook dispatch
        
        for result_file in result_files:
            try:
                measurement_id, events = self._analyze_single_file(result_file)
                processed_count += 1
                if measurement_id and events:
                    all_results.append((measurement_id, events))
                logger.debug(f"Processed {result_file.name}: {len(events)} events detected")
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to analyze {result_file.name}: {e}")
                
        logger.info(f"Analysis complete: {processed_count} files processed, {error_count} errors")
        
        # Send webhook alerts and SDN controller notifications after analysis completes
        for measurement_id, events in all_results:
            self.send_webhook_alert(measurement_id, events)
            self.send_to_controller(measurement_id, events)

    def _analyze_single_file(self, result_file: Path) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """Analyze a single measurement file. Returns (measurement_id, events)."""
        try:
            with open(result_file, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to read/parse {result_file}: {e}")
            raise
            
        measurement_id = data.get("measurement_id")
        if not measurement_id:
            logger.warning(f"No measurement_id found in {result_file}")
            return None, []
            
        measurement_id = str(measurement_id)
        events = self.analyze_measurement(data)
        self.save_events(measurement_id, events)
        
        if events:
            logger.info(f"Events for measurement {measurement_id} saved: {len(events)} anomalies")
        else:
            logger.debug(f"No anomalies found for measurement {measurement_id}")
            
        return measurement_id, events

    def analyze_measurement(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        events = []
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Initialize data collectors
        probe_data = self._collect_probe_data(data)
        
        # Run different anomaly detection methods
        events.extend(self._detect_outlier_anomalies(probe_data, timestamp))
        events.extend(self._detect_threshold_anomalies(probe_data, timestamp))
        events.extend(self._detect_geo_anomalies(probe_data, timestamp))
        events.extend(self._detect_routing_anomalies(probe_data, timestamp))
        
        # Cross-correlate ping and traceroute anomalies using a snapshot
        # to avoid coupling with future changes in _correlate_events return semantics
        events.extend(self._correlate_events(list(events), timestamp))
        
        logger.debug(f"Detected {len(events)} total anomalies for measurement {data.get('measurement_id')}")
        return events

    def _collect_probe_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        probe_data = {
            'latencies': {},
            'distances': {},
            'losses': {},
            'jitters': {},
            'targets': {},
            'countries': {},
            'traceroute_hops': {},
            'baseline_rtts': {},
            'baseline_hops': {},
            'route_histories': {}
        }
        
        default_target_lat = data.get("target_latitude")
        default_target_lon = data.get("target_longitude")
        
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            if not probe_id:
                continue
            # Normalize probe_id to string to prevent silent key mismatches
            # (RIPE Atlas may return probe IDs as int or str)
            probe_id = str(probe_id)
                
            target_addr = result.get("target_address") or result.get("target") or data.get("target")
            probe_data['targets'][probe_id] = target_addr
            if result.get("probe_country"):
                probe_data['countries'][probe_id] = result.get("probe_country")
            
            measurement_type = result.get("measurement_type")
            
            if measurement_type == "ping":
                self._process_ping_data(
                    result, probe_id, target_addr, probe_data,
                    default_target_lat=default_target_lat,
                    default_target_lon=default_target_lon
                )
            elif measurement_type == "traceroute":
                self._process_traceroute_data(result, probe_id, target_addr, probe_data)
                
        return probe_data

    def _process_ping_data(self, result: Dict[str, Any], probe_id: str, 
                          target_addr: str, probe_data: Dict[str, Any],
                          default_target_lat: Optional[float] = None,
                          default_target_lon: Optional[float] = None) -> None:
        latency_stats = result.get("latency_stats", {})
        latency = latency_stats.get("avg")
        loss = result.get("packet_loss_percentage")
        rtts = latency_stats.get("rtts", [])
        
        probe_data['latencies'][probe_id] = latency
        probe_data['losses'][probe_id] = loss
        probe_data['jitters'][probe_id] = calculate_jitter(rtts)
        
        distance_km = result.get("distance_km")
        if distance_km is None:
            probe_lat = result.get("probe_latitude")
            probe_lon = result.get("probe_longitude")
            target_lat = result.get("target_latitude", default_target_lat)
            target_lon = result.get("target_longitude", default_target_lon)
            if target_lat is None or target_lon is None:
                target_coords = self.config.get("target_coordinates", {}).get(target_addr, {})
                if isinstance(target_coords, dict):
                    target_lat = target_coords.get("latitude", target_lat)
                    target_lon = target_coords.get("longitude", target_lon)
            distance_km = calculate_distance_km(probe_lat, probe_lon, target_lat, target_lon)
        probe_data['distances'][probe_id] = distance_km
        
        if self.config["detection"]["enable_adaptive_baseline"]:
            baseline_rtt = self._get_and_update_baseline_rtt(probe_id, target_addr, latency)
            probe_data['baseline_rtts'][probe_id] = baseline_rtt

    @staticmethod
    def _extract_hop_ips(hops: List[Any]) -> List[str]:
        """Extract hop IP sequence from either simplified or RIPE Atlas traceroute hop records.
        
        Supports:
        - Simplified format: [{"ip": "1.2.3.4"}, ...]
        - RIPE Atlas format: [{"hop": 1, "result": [{"from": "1.2.3.4", "rtt": 1.2}, ...]}, ...]
        - Plain IP strings: ["1.2.3.4", ...]
        """
        hop_ips: List[str] = []
        for hop in hops or []:
            if isinstance(hop, str):
                if hop and hop != "*":
                    hop_ips.append(hop)
            elif isinstance(hop, dict):
                if hop.get("ip"):
                    hop_ips.append(str(hop["ip"]))
                elif hop.get("from"):
                    hop_ips.append(str(hop["from"]))
                elif isinstance(hop.get("result"), list):
                    for response in hop["result"]:
                        if isinstance(response, dict) and response.get("from"):
                            hop_ips.append(str(response["from"]))
                            break
        return hop_ips

    def _process_traceroute_data(self, result: Dict[str, Any], probe_id: str,
                                target_addr: str, probe_data: Dict[str, Any]) -> None:
        samples = result.get("traceroute_samples")
        sample_hop_sequences: List[List[str]] = []
        if isinstance(samples, list) and samples:
            for sample in samples:
                if isinstance(sample, dict):
                    seq = self._extract_hop_ips(sample.get("hops", []))
                    if seq:
                        sample_hop_sequences.append(seq)
        
        if not sample_hop_sequences:
            hop_ips = self._extract_hop_ips(result.get("hops", []))
            if hop_ips:
                sample_hop_sequences.append(hop_ips)
        
        if not sample_hop_sequences:
            probe_data['traceroute_hops'][probe_id] = []
            probe_data['baseline_hops'][probe_id] = None
            return
        
        previous_hops = None
        for seq in sample_hop_sequences:
            previous_hops = self._get_and_update_baseline_hops(probe_id, target_addr, seq)
        
        probe_data['traceroute_hops'][probe_id] = sample_hop_sequences[-1]
        probe_data['baseline_hops'][probe_id] = previous_hops
        route_key = f"{probe_id}_{target_addr}"
        probe_data['route_histories'][probe_id] = list(self.route_history.get(route_key, []))

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        """Sanitize a value for safe use in filenames.
        
        Removes path separators, special chars, and consecutive dots
        to prevent path traversal or ambiguous filenames.
        """
        sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', str(value))
        # Collapse consecutive dots to prevent path-traversal-looking names
        sanitized = re.sub(r'\.{2,}', '.', sanitized)
        return sanitized.strip('.')

    def _get_and_update_baseline_rtt(self, probe_id: str, target_addr: str, 
                                    current_rtt: Optional[float]) -> Optional[float]:
        """Get baseline RTT using a rolling average of the last N measurements.
        
        Stores the last 10 RTT values per probe-target pair and uses their
        average as the baseline. This smooths out temporary spikes and dips,
        giving a more stable and realistic picture of normal latency.
        
        The baseline is computed from values stored *before* the current RTT
        is appended, so min_samples + 1 total calls are needed before a
        baseline is returned (e.g., 4 calls when min_samples=3).
        
        Note: Spike values are still stored in the rolling window, which may
        drag the baseline upward during sustained anomalies. The window size
        (default 10) limits this drift, and values age out as new data arrives.
        """
        if target_addr is None:
            logger.debug(f"Skipping baseline RTT for probe {probe_id}: target_addr is None")
            return None

        safe_probe = self._sanitize_filename(probe_id)
        safe_target = self._sanitize_filename(target_addr)
        baseline_file = self.baseline_dir / f"ping_{safe_probe}_{safe_target}.json"
        baseline_rtt = None
        rolling_window_size = 10
        min_samples = 3  # Require at least 3 samples for a reliable baseline
        
        try:
            rtts = []
            if baseline_file.exists():
                with open(baseline_file, "r") as bf:
                    baseline_data = json.load(bf)
                    rtts = baseline_data.get("rtts", [])
                    # Fallback: migrate from old single-value format
                    if not rtts and baseline_data.get("avg_rtt") is not None:
                        rtts = [baseline_data["avg_rtt"]]
                    
                    # Only use baseline if we have enough samples
                    if len(rtts) >= min_samples:
                        baseline_rtt = sum(rtts) / len(rtts)
            
            if current_rtt is not None:
                rtts.append(current_rtt)
                # Keep only the last N values
                if len(rtts) > rolling_window_size:
                    rtts = rtts[-rolling_window_size:]
                
                # Write atomically via temp file to prevent corruption on interruption
                baseline_data = {
                    "rtts": rtts,
                    "avg_rtt": sum(rtts) / len(rtts)  # Kept for external readers/debugging
                }
                fd, tmp_path = tempfile.mkstemp(dir=str(self.baseline_dir), suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as bf:
                        json.dump(baseline_data, bf)
                    os.replace(tmp_path, str(baseline_file))
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass
                    raise
                    
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to handle baseline RTT for {probe_id}->{target_addr}: {e}")
            
        return baseline_rtt

    def _get_and_update_baseline_hops(self, probe_id: str, target_addr: str,
                                     current_hops: List[str]) -> Optional[List[str]]:
        """Get previous traceroute hops and persist current hops and route history."""
        if target_addr is None:
            logger.debug(f"Skipping baseline hops for probe {probe_id}: target_addr is None")
            return None

        safe_probe = self._sanitize_filename(probe_id)
        safe_target = self._sanitize_filename(target_addr)
        baseline_file = self.baseline_dir / f"traceroute_{safe_probe}_{safe_target}.json"
        route_key = f"{probe_id}_{target_addr}"
        previous_hops = None
        flapping_window = max(int(self.config["thresholds"].get("path_flapping_window", 3)), 1)
        max_history = max(flapping_window * 3, 10)
        history: List[List[str]] = list(self.route_history.get(route_key, []))
        
        try:
            if baseline_file.exists():
                with open(baseline_file, "r") as bf:
                    baseline_data = json.load(bf)
                    previous_hops = baseline_data.get("hop_ips")
                    disk_history = baseline_data.get("route_history")
                    if isinstance(disk_history, list) and disk_history:
                        history = disk_history
                    elif previous_hops and not history:
                        history = [previous_hops]
            
            if current_hops:
                history.append(list(current_hops))
                if len(history) > max_history:
                    history = history[-max_history:]
                self.route_history[route_key] = history
            
            # Write atomically via temp file to prevent corruption on interruption
            fd, tmp_path = tempfile.mkstemp(dir=str(self.baseline_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as bf:
                    json.dump({"hop_ips": current_hops, "route_history": history}, bf)
                os.replace(tmp_path, str(baseline_file))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass
                raise
                
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to handle baseline hops for {probe_id}->{target_addr}: {e}")
            
        return previous_hops

    def _detect_outlier_anomalies(self, probe_data: Dict[str, Any], 
                                 timestamp: str) -> List[Dict[str, Any]]:
        events = []
        
        if not self.config["detection"]["enable_outlier_detection"]:
            return events
            
        outlier_factor = self.config["thresholds"]["outlier_factor"]
        
        for probe_id, latency in probe_data['latencies'].items():
            # Filter None from population to avoid arithmetic errors in is_outlier
            valid_latencies = [v for v in probe_data['latencies'].values() if v is not None]
            if latency is not None and is_outlier(latency, valid_latencies, outlier_factor):
                events.append(self._create_event(
                    timestamp, "outlier_probe_latency", probe_id,
                    probe_data['targets'][probe_id], "ping_rtt_ms",
                    latency, None, "ms", "warning",
                    probe_country=probe_data['countries'].get(probe_id)
                ))
        
        for probe_id, loss in probe_data['losses'].items():
            valid_losses = [v for v in probe_data['losses'].values() if v is not None]
            if (loss is not None and loss > 5.0 and 
                is_outlier(loss, valid_losses, outlier_factor)):
                events.append(self._create_event(
                    timestamp, "outlier_probe_loss", probe_id,
                    probe_data['targets'][probe_id], "ping_loss_pct",
                    loss, None, "%", "warning",
                    probe_country=probe_data['countries'].get(probe_id)
                ))
        
        return events

    def _detect_threshold_anomalies(self, probe_data: Dict[str, Any],
                                   timestamp: str) -> List[Dict[str, Any]]:
        events = []
        thresholds = self.config["thresholds"]
        target_thresholds = self.config.get("target_thresholds", {})
        
        for probe_id in probe_data['targets']:
            target_addr = probe_data['targets'][probe_id]
            probe_country = probe_data['countries'].get(probe_id)
            
            # Use per-target threshold if configured, otherwise fall back to global
            target_config = target_thresholds.get(target_addr, {})
            latency_threshold = target_config.get(
                "latency_spike_ms", thresholds["latency_spike_ms"]
            )
            
            # Latency spike detection (emit at most one per probe — take highest violation)
            latency = probe_data['latencies'].get(probe_id)
            if latency is not None:
                spike_event = None
                
                # Static threshold (per-target or global)
                if latency > latency_threshold:
                    spike_event = self._create_event(
                        timestamp, "latency_spike", probe_id, target_addr,
                        "ping_rtt_ms", latency, latency_threshold,
                        "ms", "warning", probe_country=probe_country
                    )
                
                # Multiplier-based threshold (overrides static if also triggered)
                baseline_rtt = probe_data['baseline_rtts'].get(probe_id)
                multiplier_threshold = (
                    baseline_rtt * thresholds["latency_spike_multiplier"]
                    if baseline_rtt is not None else None
                )
                if (multiplier_threshold is not None and
                    latency > multiplier_threshold):
                    spike_event = self._create_event(
                        timestamp, "latency_spike", probe_id, target_addr,
                        "ping_rtt_ms", latency, multiplier_threshold,
                        "ms", "warning", probe_country=probe_country
                    )
                
                if spike_event:
                    events.append(spike_event)
            
            # Packet loss detection
            loss = probe_data['losses'].get(probe_id)
            if loss is not None and loss > thresholds["packet_loss_percentage"]:
                events.append(self._create_event(
                    timestamp, "packet_loss", probe_id, target_addr,
                    "ping_loss_pct", loss, thresholds["packet_loss_percentage"],
                    "%", "warning", probe_country=probe_country
                ))
            
            # Unreachable host detection
            if loss is not None and loss == 100.0:
                events.append(self._create_event(
                    timestamp, "unreachable_host", probe_id, target_addr,
                    "reachability", 0, 1, "reachable_flag", "critical",
                    probe_country=probe_country
                ))
            
            # Jitter spike detection
            jitter = probe_data['jitters'].get(probe_id)
            if jitter is not None and jitter > thresholds["jitter_spike_ms"]:
                events.append(self._create_event(
                    timestamp, "jitter_spike", probe_id, target_addr,
                    "ping_jitter_ms", jitter, thresholds["jitter_spike_ms"],
                    "ms", "warning", probe_country=probe_country
                ))
        
        return events

    def _detect_geo_anomalies(self, probe_data: Dict[str, Any],
                             timestamp: str) -> List[Dict[str, Any]]:
        """Detect geographic anomalies where a distant probe outperforms a closer probe.
        
        Compares probes measuring the same target using great-circle distance (km)
        and average RTT (ms). Emits at most one geo_anomaly event per distant
        outperforming probe, recording the strongest margin violation.
        """
        events = []
        if not self.config["detection"].get("enable_geo_anomaly_detection", True):
            return events
        
        margin_ms = self.config["thresholds"].get("geo_anomaly_margin_ms", 50.0)
        
        # Group probes with valid distance and latency by target
        probes_by_target: Dict[Any, List[Tuple[str, float, float]]] = {}
        for probe_id, lat in probe_data['latencies'].items():
            dist = probe_data['distances'].get(probe_id)
            if lat is not None and dist is not None:
                target_addr = probe_data['targets'].get(probe_id)
                probes_by_target.setdefault(target_addr, []).append((probe_id, float(dist), float(lat)))
        
        for target_addr, entries in probes_by_target.items():
            if len(entries) < 2:
                continue
            for pid1, dist1, lat1 in entries:
                best_violation = None
                for pid2, dist2, lat2 in entries:
                    if pid1 == pid2:
                        continue
                    if geo_anomaly_check(dist1, lat1, dist2, lat2, margin=margin_ms):
                        diff = lat2 - lat1
                        if best_violation is None or diff > best_violation[0]:
                            best_violation = (diff, pid2, dist2, lat2)
                if best_violation is not None:
                    diff, near_pid, near_dist, near_lat = best_violation
                    event = self._create_event(
                        timestamp, "geo_anomaly", pid1, target_addr,
                        "geo_latency_diff_ms", round(diff, 2), margin_ms,
                        "ms", "warning",
                        probe_country=probe_data['countries'].get(pid1)
                    )
                    event.update({
                        "far_probe_distance_km": round(dist1, 2),
                        "far_probe_rtt_ms": round(lat1, 2),
                        "near_probe_id": near_pid,
                        "near_probe_distance_km": round(near_dist, 2),
                        "near_probe_rtt_ms": round(near_lat, 2),
                    })
                    events.append(event)
        
        return events

    def _detect_routing_anomalies(self, probe_data: Dict[str, Any],
                                 timestamp: str) -> List[Dict[str, Any]]:
        events = []
        thresholds = self.config["thresholds"]
        jaccard_threshold = float(thresholds.get("route_change_jaccard_threshold", 1.0))
        flapping_window = int(thresholds.get("path_flapping_window", 3))
        
        for probe_id in probe_data['targets']:
            target_addr = probe_data['targets'][probe_id]
            probe_country = probe_data['countries'].get(probe_id)
            
            # Route change detection using hop sequence comparison + Jaccard similarity
            current_hops = probe_data['traceroute_hops'].get(probe_id)
            previous_hops = probe_data['baseline_hops'].get(probe_id)
            
            if previous_hops and current_hops:
                jaccard_sim = calculate_jaccard_similarity(previous_hops, current_hops)
                route_changed = (
                    (previous_hops != current_hops)
                    if jaccard_threshold >= 1.0
                    else (jaccard_sim < jaccard_threshold)
                )
                if route_changed:
                    event = self._create_event(
                        timestamp, "route_change", probe_id, target_addr,
                        "traceroute_hops", round(jaccard_sim, 4), jaccard_threshold,
                        "jaccard_similarity", "warning", probe_country=probe_country
                    )
                    event.update({
                        "previous_hops": previous_hops,
                        "current_hops": current_hops,
                        "jaccard_similarity": round(jaccard_sim, 4),
                        "hop_count_delta": len(current_hops) - len(previous_hops),
                    })
                    events.append(event)
            
            # Path flapping detection over persisted + in-memory route history
            if current_hops:
                route_key = f"{probe_id}_{target_addr}"
                history = probe_data.get('route_histories', {}).get(
                    probe_id, self.route_history.get(route_key, [])
                )
                if len(history) >= flapping_window:
                    recent_routes = history[-flapping_window:]
                    transitions = sum(
                        1 for i in range(1, len(recent_routes))
                        if recent_routes[i] != recent_routes[i - 1]
                    )
                    if transitions >= 2:
                        event = self._create_event(
                            timestamp, "path_flapping", probe_id, target_addr,
                            "traceroute_hops", transitions, 2, "route_changes",
                            "warning", probe_country=probe_country
                        )
                        event["routes"] = recent_routes
                        events.append(event)
        
        return events

    def _correlate_events(self, events: List[Dict[str, Any]], 
                         timestamp: str) -> List[Dict[str, Any]]:
        """Cross-correlate ping and traceroute anomalies from the same probe.
        
        If a latency spike is detected at the same time as a route change from
        the same probe to the same target, adds a 'correlated_routing_event'
        alongside the existing events to flag the probable root cause.
        The original latency_spike and route_change events are kept as-is.
        """
        correlated = []
        
        # Group events by (probe_id, target) using tuple keys to avoid
        # string concatenation collisions. Defensive: skip correlated events
        # in case this function is ever called iteratively/idempotently.
        groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for event in events:
            if event.get("anomaly") == "correlated_routing_event":
                continue
            key = (str(event.get('probe_id', '')), str(event.get('target', '')))
            if key not in groups:
                groups[key] = {"anomalies": [], "event_refs": [], 
                              "probe_id": key[0], "target": key[1],
                              "probe_country": event.get("probe_country")}
            groups[key]["anomalies"].append(event.get("anomaly"))
            groups[key]["event_refs"].append(event)
            if not groups[key].get("probe_country") and event.get("probe_country"):
                groups[key]["probe_country"] = event.get("probe_country")
        
        # Check for latency_spike + route_change in the same group
        for key, group in groups.items():
            anomaly_types = set(group["anomalies"])
            if "latency_spike" in anomaly_types and "route_change" in anomaly_types:
                probe_id = group["probe_id"]
                target = group["target"]
                
                correlated_event = self._create_event(
                    timestamp, "correlated_routing_event", probe_id, target,
                    "correlation", None, None, "", "warning",
                    probe_country=group.get("probe_country")
                )
                correlated_event["description"] = (
                    "Latency spike likely caused by route change detected on the same probe"
                )
                correlated_event["correlated_anomalies"] = ["latency_spike", "route_change"]
                correlated.append(correlated_event)
                logger.debug(f"Correlated latency_spike + route_change for probe {probe_id} -> {target}")
        
        return correlated

    def _create_event(self, timestamp: str, anomaly: str, probe_id: str,
                     target: str, metric: str, value: Any, threshold: Any,
                     units: str, severity: str,
                     probe_country: Optional[str] = None) -> Dict[str, Any]:
        event = {
            "timestamp": timestamp,
            "anomaly": anomaly,
            "probe_id": probe_id,
            "target": target,
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "units": units,
            "severity": severity
        }
        if probe_country is not None:
            event["probe_country"] = probe_country
        return event

    def save_events(self, measurement_id: str, events: List[Dict[str, Any]]) -> None:

        try:
            # Create analysis summary
            analysis = self._create_analysis_summary(events)
            
            output_data = {
                "measurement_id": measurement_id,
                "analysis_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "events": events,
                "analysis": analysis
            }
            
            out_file = self.event_results_dir / f"{measurement_id}.json"
            with open(out_file, "w") as f:
                json.dump(output_data, f, indent=2)
                
            logger.debug(f"Events saved to {out_file}")
            
        except IOError as e:
            logger.error(f"Failed to save events for measurement {measurement_id}: {e}")

    def _create_analysis_summary(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a summary analysis of the events."""
        probe_analysis = {}
        anomaly_summary = {}
        
        for event in events:
            probe_id = event.get("probe_id")
            anomaly = event.get("anomaly")
            target = event.get("target")
            
            if probe_id:
                if probe_id not in probe_analysis:
                    probe_analysis[probe_id] = {"target": target, "anomalies": []}
                probe_analysis[probe_id]["anomalies"].append(anomaly)
            
            anomaly_summary[anomaly] = anomaly_summary.get(anomaly, 0) + 1
        
        for probe_id, info in probe_analysis.items():
            info["anomaly_count"] = len(info["anomalies"])
        
        return {
            "per_probe": probe_analysis,
            "anomaly_summary": anomaly_summary,
            "total_anomalies": len(events),
            "unique_probes_affected": len(probe_analysis)
        }

    def show_alerts_summary(self) -> None:
        logger.info("=== Alerts Summary ===")
        
        total_measurements = 0
        total_anomalies = 0
        global_anomaly_counts = {}
        
        for result_file in self.event_results_dir.glob("*.json"):
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
                
                measurement_id = data.get("measurement_id")
                events = data.get("events", [])
                total_measurements += 1
                total_anomalies += len(events)
                
                logger.info(f"Measurement {measurement_id}: {len(events)} anomalies detected")
                
                # Count anomaly types
                for event in events:
                    anomaly = event.get("anomaly")
                    global_anomaly_counts[anomaly] = global_anomaly_counts.get(anomaly, 0) + 1
                    
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to read summary from {result_file}: {e}")
        
        logger.info(f"\nGlobal Summary:")
        logger.info(f"  Total measurements analyzed: {total_measurements}")
        logger.info(f"  Total anomalies detected: {total_anomalies}")
        logger.info(f"  Anomaly breakdown:")
        
        for anomaly, count in sorted(global_anomaly_counts.items()):
            description = ANOMALY_TYPES.get(anomaly, {}).get("description", "Unknown anomaly type")
            logger.info(f"    {anomaly}: {count} events - {description}")

    def send_to_controller(
        self,
        measurement_id: str,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Dispatch detected anomalies to an SDN controller (e.g., POX northbound REST API).
        
        Applies per-target consecutive-window hysteresis and cooldown damping to
        prevent route oscillation during transient spikes. Critical reachability
        failures ('unreachable_host') bypass cooldown for immediate failover.
        """
        controller_cfg = self.config.get("controller", {})
        if not controller_cfg.get("enabled", False):
            logger.debug("SDN controller dispatch is disabled")
            return {"sent": False, "reason": "disabled"}

        controller_url = controller_cfg.get("url", "").strip()
        if not controller_url:
            logger.warning("Controller URL is not configured")
            return {"sent": False, "reason": "missing_url"}

        parsed = urlparse(controller_url)
        if parsed.scheme not in ("https", "http"):
            logger.error(f"Invalid controller URL scheme '{parsed.scheme}': {controller_url}")
            return {"sent": False, "reason": "invalid_scheme"}

        is_loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if parsed.scheme == "http" and not is_loopback and not controller_cfg.get("allow_insecure_http", False):
            logger.error(
                "Non-loopback controller URL uses plain HTTP and insecure delivery is disabled. "
                "Use https:// or set controller.allow_insecure_http=true to opt in."
            )
            return {"sent": False, "reason": "insecure_http_blocked"}

        # Load events from disk if not passed directly
        if events is None:
            event_file = self.event_results_dir / f"{measurement_id}.json"
            if not event_file.exists():
                logger.warning(f"No event file found for measurement {measurement_id}: {event_file}")
                return {"sent": False, "reason": "no_event_file"}
            try:
                with open(event_file, "r") as f:
                    events = json.load(f).get("events", [])
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to read events for controller dispatch: {e}")
                return {"sent": False, "reason": "read_error"}

        min_severity = str(controller_cfg.get("min_severity", "warning")).lower()
        allowed_severities = {"critical"} if min_severity == "critical" else {"critical", "warning"}
        eligible_events = [e for e in events if e.get("severity") in allowed_severities]

        if not eligible_events:
            # Clean measurement round resets consecutive anomaly counters
            self._consecutive_anomaly_counts.clear()
            logger.debug(f"No controller-actionable events for measurement {measurement_id}")
            return {"sent": False, "reason": "no_eligible_events"}

        # Group eligible events by target for hysteresis and cooldown evaluation
        by_target: Dict[str, List[Dict[str, Any]]] = {}
        for event in eligible_events:
            target = str(event.get("target") or "unknown")
            by_target.setdefault(target, []).append(event)

        # Reset counters for targets absent from current anomalies
        for tracked_target in list(self._consecutive_anomaly_counts.keys()):
            if tracked_target not in by_target:
                self._consecutive_anomaly_counts[tracked_target] = 0

        min_consecutive = max(int(controller_cfg.get("min_consecutive_anomalies", 1)), 1)
        cooldown_seconds = max(float(controller_cfg.get("cooldown_seconds", 15.0)), 0.0)
        now = time.monotonic()

        dispatched_events: List[Dict[str, Any]] = []
        dispatched_targets: List[str] = []
        suppressed_targets: Dict[str, str] = {}

        for target, target_events in by_target.items():
            count = self._consecutive_anomaly_counts.get(target, 0) + 1
            self._consecutive_anomaly_counts[target] = count

            has_critical_outage = any(
                e.get("anomaly") == "unreachable_host" or e.get("severity") == "critical"
                for e in target_events
            )

            if not has_critical_outage and count < min_consecutive:
                suppressed_targets[target] = f"hysteresis_pending ({count}/{min_consecutive})"
                continue

            last_sent = self._last_controller_dispatch.get(target)
            if not has_critical_outage and last_sent is not None and (now - last_sent) < cooldown_seconds:
                remaining = round(cooldown_seconds - (now - last_sent), 2)
                suppressed_targets[target] = f"cooldown_active ({remaining}s remaining)"
                continue

            dispatched_targets.append(target)
            dispatched_events.extend(target_events)

        if not dispatched_events:
            logger.info(
                f"Controller dispatch suppressed for measurement {measurement_id}: {suppressed_targets}"
            )
            return {
                "sent": False,
                "reason": "suppressed_by_damping",
                "suppressed_targets": suppressed_targets,
            }

        reroute_triggers = {
            "latency_spike", "packet_loss", "unreachable_host", "jitter_spike",
            "path_flapping", "correlated_routing_event", "geo_anomaly", "route_change",
        }
        action = (
            "reroute"
            if any(e.get("anomaly") in reroute_triggers for e in dispatched_events)
            else "monitor"
        )

        payload = {
            "measurement_id": str(measurement_id),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "action": action,
            "targets": dispatched_targets,
            "total_anomalies": len(dispatched_events),
            "anomalies": [
                {
                    "type": e.get("anomaly"),
                    "probe_id": e.get("probe_id"),
                    "probe_country": e.get("probe_country"),
                    "target": e.get("target"),
                    "severity": e.get("severity"),
                    "metric": e.get("metric"),
                    "value": e.get("value"),
                    "threshold": e.get("threshold"),
                    "units": e.get("units", ""),
                }
                for e in dispatched_events
            ],
        }

        timeout = controller_cfg.get("timeout_seconds", 5)
        t0 = time.perf_counter()
        try:
            response = requests.post(
                controller_url,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )
            dispatch_ms = round((time.perf_counter() - t0) * 1000.0, 3)

            if response.status_code < 300:
                for target in dispatched_targets:
                    self._last_controller_dispatch[target] = now
                    self._consecutive_anomaly_counts[target] = 0
                try:
                    resp_body = response.json()
                except ValueError:
                    resp_body = response.text[:200]
                logger.info(
                    f"Controller notified for measurement {measurement_id} "
                    f"(action={action}, targets={dispatched_targets}, {dispatch_ms:.2f}ms)"
                )
                return {
                    "sent": True,
                    "status_code": response.status_code,
                    "action": action,
                    "dispatched_targets": dispatched_targets,
                    "suppressed_targets": suppressed_targets,
                    "dispatch_latency_ms": dispatch_ms,
                    "response": resp_body,
                }

            logger.warning(
                f"Controller returned status {response.status_code} for measurement {measurement_id}: "
                f"{response.text[:200]}"
            )
            return {
                "sent": False,
                "reason": f"http_{response.status_code}",
                "status_code": response.status_code,
                "dispatch_latency_ms": dispatch_ms,
            }

        except requests.RequestException as e:
            dispatch_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            logger.error(f"Failed to notify SDN controller for measurement {measurement_id}: {e}")
            return {
                "sent": False,
                "reason": "request_exception",
                "error": str(e),
                "dispatch_latency_ms": dispatch_ms,
            }

    def send_webhook_alert(self, measurement_id: str, events: List[Dict[str, Any]]) -> None:
        """Send alert notifications to a configured webhook URL.
        
        Sends a POST request with JSON payload containing measurement ID,
        anomaly types, severity, and affected probes. Only events with
        'critical' or 'warning' severity are included in the payload;
        info-level events are filtered out.
        
        Compatible with Slack, Microsoft Teams, Discord, PagerDuty, or
        any custom endpoint.
        
        Note: This runs synchronously. For high-throughput batch analysis,
        consider running detection and alerting in separate steps.
        """
        webhook_config = self.config.get("webhook", {})
        
        if not webhook_config.get("enabled", False):
            logger.debug("Webhook alerts are disabled")
            return
        
        webhook_url = webhook_config.get("url", "")
        if not webhook_url:
            logger.warning("Webhook URL is not configured")
            return
        
        # Validate URL scheme and reject insecure HTTP unless explicitly allowed
        parsed = urlparse(webhook_url)
        if parsed.scheme not in ("https", "http"):
            logger.error(f"Invalid webhook URL scheme '{parsed.scheme}': {webhook_url}. Must be https:// or http://")
            return
        if parsed.scheme == "http":
            if not webhook_config.get("allow_insecure_http", False):
                logger.error(
                    "Webhook URL uses plain HTTP and insecure delivery is disabled. "
                    "Use https:// or set webhook.allow_insecure_http=true to opt in."
                )
                return
            logger.warning("Webhook URL uses plain HTTP; alert payloads will be sent unencrypted")
        
        timeout = webhook_config.get("timeout_seconds", 10)
        
        # Filter for critical/warning events worth alerting on
        alert_events = [e for e in events if e.get("severity") in ("critical", "warning")]
        if not alert_events:
            logger.debug(f"No alertable events for measurement {measurement_id}")
            return
        
        # Build payload
        payload = {
            "measurement_id": measurement_id,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "total_anomalies": len(alert_events),
            "anomalies": []
        }
        
        for event in alert_events:
            payload["anomalies"].append({
                "type": event.get("anomaly"),
                "probe_id": event.get("probe_id"),
                "target": event.get("target"),
                "severity": event.get("severity"),
                "value": event.get("value"),
                "threshold": event.get("threshold"),
                "units": event.get("units", "")
            })
        
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code < 300:
                logger.info(f"Webhook alert sent for measurement {measurement_id}: {len(alert_events)} anomalies")
            else:
                logger.warning(
                    f"Webhook returned status {response.status_code} for measurement {measurement_id}: "
                    f"{response.text[:200]}"
                )
                
        except requests.RequestException as e:
            logger.error(f"Failed to send webhook alert for measurement {measurement_id}: {e}")

