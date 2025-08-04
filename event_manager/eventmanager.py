import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from measurement_client.logger import logger
from .anomaly_types import ANOMALY_TYPES
from .anomaly_utils import calculate_jitter, is_outlier, geo_anomaly_check


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
                "path_flapping_window": 3
            },
            "detection": {
                "enable_outlier_detection": True,
                "enable_geo_anomaly_detection": True,
                "enable_adaptive_baseline": True
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
        
        for result_file in result_files:
            try:
                events = self._analyze_single_file(result_file)
                processed_count += 1
                logger.debug(f"Processed {result_file.name}: {len(events)} events detected")
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to analyze {result_file.name}: {e}")
                
        logger.info(f"Analysis complete: {processed_count} files processed, {error_count} errors")

    def _analyze_single_file(self, result_file: Path) -> List[Dict[str, Any]]:
        try:
            with open(result_file, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to read/parse {result_file}: {e}")
            raise
            
        measurement_id = data.get("measurement_id")
        if not measurement_id:
            logger.warning(f"No measurement_id found in {result_file}")
            return []
            
        events = self.analyze_measurement(data)
        self.save_events(measurement_id, events)
        
        if events:
            logger.info(f"Events for measurement {measurement_id} saved: {len(events)} anomalies")
        else:
            logger.debug(f"No anomalies found for measurement {measurement_id}")
            
        return events

    def analyze_measurement(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        events = []
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Initialize data collectors
        probe_data = self._collect_probe_data(data)
        
        # Run different anomaly detection methods
        events.extend(self._detect_outlier_anomalies(probe_data, timestamp))
        events.extend(self._detect_threshold_anomalies(probe_data, timestamp))
        events.extend(self._detect_routing_anomalies(probe_data, timestamp))
        
        logger.debug(f"Detected {len(events)} total anomalies for measurement {data.get('measurement_id')}")
        return events

    def _collect_probe_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        probe_data = {
            'latencies': {},
            'distances': {},
            'losses': {},
            'jitters': {},
            'targets': {},
            'traceroute_hops': {},
            'baseline_rtts': {},
            'baseline_hops': {}
        }
        
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            if not probe_id:
                continue
                
            target_addr = result.get("target_address") or result.get("target")
            probe_data['targets'][probe_id] = target_addr
            
            measurement_type = result.get("measurement_type")
            
            if measurement_type == "ping":
                self._process_ping_data(result, probe_id, target_addr, probe_data)
            elif measurement_type == "traceroute":
                self._process_traceroute_data(result, probe_id, target_addr, probe_data)
                
        return probe_data

    def _process_ping_data(self, result: Dict[str, Any], probe_id: str, 
                          target_addr: str, probe_data: Dict[str, Any]) -> None:
        latency_stats = result.get("latency_stats", {})
        latency = latency_stats.get("avg")
        loss = result.get("packet_loss_percentage")
        rtts = latency_stats.get("rtts", [])
        
        probe_data['latencies'][probe_id] = latency
        probe_data['losses'][probe_id] = loss
        probe_data['jitters'][probe_id] = calculate_jitter(rtts)
        probe_data['distances'][probe_id] = result.get("distance_km")
        
        if self.config["detection"]["enable_adaptive_baseline"]:
            baseline_rtt = self._get_and_update_baseline_rtt(probe_id, target_addr, latency)
            probe_data['baseline_rtts'][probe_id] = baseline_rtt

    def _process_traceroute_data(self, result: Dict[str, Any], probe_id: str,
                                target_addr: str, probe_data: Dict[str, Any]) -> None:
        hops = result.get("hops", [])
        hop_ips = [h.get("ip") for h in hops if h.get("ip")]
        
        probe_data['traceroute_hops'][probe_id] = hop_ips
        
        previous_hops = self._get_and_update_baseline_hops(probe_id, target_addr, hop_ips)
        probe_data['baseline_hops'][probe_id] = previous_hops

    def _get_and_update_baseline_rtt(self, probe_id: str, target_addr: str, 
                                    current_rtt: Optional[float]) -> Optional[float]:
        baseline_file = self.baseline_dir / f"ping_{probe_id}_{target_addr}.json"
        baseline_rtt = None
        
        try:
            if baseline_file.exists():
                with open(baseline_file, "r") as bf:
                    baseline_data = json.load(bf)
                    baseline_rtt = baseline_data.get("avg_rtt")
            
            if current_rtt is not None:
                with open(baseline_file, "w") as bf:
                    json.dump({"avg_rtt": current_rtt}, bf)
                    
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to handle baseline RTT for {probe_id}->{target_addr}: {e}")
            
        return baseline_rtt

    def _get_and_update_baseline_hops(self, probe_id: str, target_addr: str,
                                     current_hops: List[str]) -> Optional[List[str]]:
        baseline_file = self.baseline_dir / f"traceroute_{probe_id}_{target_addr}.json"
        previous_hops = None
        
        try:
            if baseline_file.exists():
                with open(baseline_file, "r") as bf:
                    baseline_data = json.load(bf)
                    previous_hops = baseline_data.get("hop_ips")
            
            with open(baseline_file, "w") as bf:
                json.dump({"hop_ips": current_hops}, bf)
                
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
            if latency and is_outlier(latency, probe_data['latencies'].values(), outlier_factor):
                events.append(self._create_event(
                    timestamp, "outlier_probe_latency", probe_id,
                    probe_data['targets'][probe_id], "ping_rtt_ms",
                    latency, None, "ms", "warning"
                ))
        
        for probe_id, loss in probe_data['losses'].items():
            if (loss and loss > 5.0 and 
                is_outlier(loss, probe_data['losses'].values(), outlier_factor)):
                events.append(self._create_event(
                    timestamp, "outlier_probe_loss", probe_id,
                    probe_data['targets'][probe_id], "ping_loss_pct",
                    loss, None, "%", "warning"
                ))
        
        return events

    def _detect_threshold_anomalies(self, probe_data: Dict[str, Any],
                                   timestamp: str) -> List[Dict[str, Any]]:
        events = []
        thresholds = self.config["thresholds"]
        
        for probe_id in probe_data['targets']:
            target_addr = probe_data['targets'][probe_id]
            
            # Latency spike detection
            latency = probe_data['latencies'].get(probe_id)
            if latency:
                # Static threshold
                if latency > thresholds["latency_spike_ms"]:
                    events.append(self._create_event(
                        timestamp, "latency_spike", probe_id, target_addr,
                        "ping_rtt_ms", latency, thresholds["latency_spike_ms"],
                        "ms", "warning"
                    ))
                
                baseline_rtt = probe_data['baseline_rtts'].get(probe_id)
                if (baseline_rtt and 
                    latency > baseline_rtt * thresholds["latency_spike_multiplier"]):
                    events.append(self._create_event(
                        timestamp, "latency_spike", probe_id, target_addr,
                        "ping_rtt_ms", latency, baseline_rtt * thresholds["latency_spike_multiplier"],
                        "ms", "warning"
                    ))
            
            # Packet loss detection
            loss = probe_data['losses'].get(probe_id)
            if loss and loss > thresholds["packet_loss_percentage"]:
                events.append(self._create_event(
                    timestamp, "packet_loss", probe_id, target_addr,
                    "ping_loss_pct", loss, thresholds["packet_loss_percentage"],
                    "%", "warning"
                ))
            
            # Unreachable host detection
            if loss and loss == 100.0:
                events.append(self._create_event(
                    timestamp, "unreachable_host", probe_id, target_addr,
                    "reachability", 0, 1, "reachable_flag", "critical"
                ))
            
            # Jitter spike detection
            jitter = probe_data['jitters'].get(probe_id)
            if jitter and jitter > thresholds["jitter_spike_ms"]:
                events.append(self._create_event(
                    timestamp, "jitter_spike", probe_id, target_addr,
                    "ping_jitter_ms", jitter, thresholds["jitter_spike_ms"],
                    "ms", "warning"
                ))
        
        return events

    def _detect_routing_anomalies(self, probe_data: Dict[str, Any],
                                 timestamp: str) -> List[Dict[str, Any]]:
        events = []
        
        for probe_id in probe_data['targets']:
            target_addr = probe_data['targets'][probe_id]
            
            # Route change detection
            current_hops = probe_data['traceroute_hops'].get(probe_id)
            previous_hops = probe_data['baseline_hops'].get(probe_id)
            
            if previous_hops and current_hops and previous_hops != current_hops:
                event = self._create_event(
                    timestamp, "route_change", probe_id, target_addr,
                    "traceroute_hops", None, None, "", "warning"
                )
                event.update({
                    "previous_hops": previous_hops,
                    "current_hops": current_hops
                })
                events.append(event)
            
            # Path flapping detection
            if current_hops:
                route_key = f"{probe_id}_{target_addr}"
                self.route_history.setdefault(route_key, [])
                self.route_history[route_key].append(current_hops)
                
                flapping_window = self.config["thresholds"]["path_flapping_window"]
                if len(self.route_history[route_key]) > flapping_window:
                    recent_routes = self.route_history[route_key][-flapping_window:]
                    unique_routes = set(tuple(r) for r in recent_routes)
                    
                    if len(unique_routes) > 1:
                        event = self._create_event(
                            timestamp, "path_flapping", probe_id, target_addr,
                            "traceroute_hops", None, None, "", "warning"
                        )
                        event["routes"] = recent_routes
                        events.append(event)
        
        return events

    def _create_event(self, timestamp: str, anomaly: str, probe_id: str,
                     target: str, metric: str, value: Any, threshold: Any,
                     units: str, severity: str) -> Dict[str, Any]:
        return {
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

    def save_events(self, measurement_id: str, events: List[Dict[str, Any]]) -> None:

        try:
            # Create analysis summary
            analysis = self._create_analysis_summary(events)
            
            output_data = {
                "measurement_id": measurement_id,
                "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
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

    def send_to_controller(self, measurement_id: str) -> None:
        """
        Send events to POX controller (to be implemented).
        """
        logger.info(f"Sending events for measurement {measurement_id} to POX controller (placeholder)")

