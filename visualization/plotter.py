import json
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from measurement_client.logger import logger
from statistics import stdev

class SintraPlotter:
    # visualizing measurement results and detected anomalies.
    
    def __init__(self, 
                 events_dir: str = "event_manager/results",
                 results_dir: str = "measurement_client/results/fetched_measurements",
                 output_dir: str = "visualization/plots"):
        
        self.events_dir = Path(events_dir)
        self.results_dir = Path(results_dir)
        self.output_dir = Path(output_dir)
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        plt.style.use('default')
        sns.set_palette("husl")
        
        logger.info(f"SintraPlotter initialized with output dir: {self.output_dir}")

    def plot_all_measurements(self) -> None:
        logger.info("Generating plots for all measurements...")
        
        result_files = list(self.results_dir.glob("measurement_*_result.json"))
        
        if not result_files:
            logger.warning(f"No measurement result files found in {self.results_dir}")
            return
        
        processed_count = 0
        for result_file in result_files:
            try:
                measurement_id = self._extract_measurement_id(result_file.name)
                if measurement_id:
                    self._create_measurement_plots(measurement_id)
                    processed_count += 1
            except Exception as e:
                logger.error(f"Failed to plot {result_file.name}: {e}")
        
        logger.info(f"Plot generation complete: {processed_count} measurements processed")

    def _extract_measurement_id(self, filename: str) -> Optional[str]:
        # Extract measurement ID from filename like 'measurement_12345_result.json'.
        try:
            parts = filename.split('_')
            if len(parts) >= 3 and parts[0] == 'measurement' and parts[-1] == 'result.json':
                return parts[1]
            return None
        except Exception as e:
            logger.error(f"Failed to extract measurement ID from {filename}: {e}")
            return None

    def _create_measurement_plots(self, measurement_id: str) -> None:
        # Create individual plots for a specific measurement in its own directory.
        logger.info(f"Generating plots for measurement {measurement_id}")
        
        # Create measurement-specific directory
        measurement_dir = self.output_dir / f"measurement_{measurement_id}"
        measurement_dir.mkdir(parents=True, exist_ok=True)
        
        measurement_data = self._load_measurement_data(measurement_id)
        event_data = self._load_event_data(measurement_id)
        
        if not measurement_data:
            logger.warning(f"No measurement data found for {measurement_id}")
            return
        
        # Extract basic info
        results = measurement_data.get("results", [])
        if not results:
            logger.warning(f"No results in measurement {measurement_id}")
            return
        
        measurement_type = results[0].get("measurement_type", "unknown")
        
        if measurement_type == "ping":
            self._create_ping_plots(measurement_id, results, event_data or {}, measurement_dir)
        elif measurement_type == "traceroute":
            self._create_traceroute_plots(measurement_id, results, event_data or {}, measurement_dir)
        
        # Always create anomaly summary
        self._create_anomaly_summary_plot(measurement_id, event_data or {}, measurement_dir)
        
        logger.info(f"Plots saved in directory: {measurement_dir}")

    def _create_ping_plots(self, measurement_id: str, results: List[Dict], event_data: Dict, output_dir: Path) -> None:
        
        # Extract ping data
        ping_data = self._extract_ping_data(results)
        anomaly_events = event_data.get("events", []) if event_data else []
        
        # Latency Over Time (Per Probe)
        self._plot_latency_over_time(ping_data, anomaly_events, output_dir)
        
        # Latency Distribution (Per Probe) - Box plot
        self._plot_latency_distribution_boxplot(ping_data, output_dir)
        
        # Average Latency Across Probes - Bar chart
        self._plot_average_latency_per_probe(ping_data, output_dir)
        
        # Packet Loss (%) Per Probe - Bar chart
        self._plot_packet_loss_per_probe(ping_data, output_dir)
        
        # Jitter Per Probe - Bar chart
        self._plot_jitter_per_probe(ping_data, output_dir)

    def _create_traceroute_plots(self, measurement_id: str, results: List[Dict], event_data: Dict, output_dir: Path) -> None:
        
        # Extract traceroute data
        traceroute_data = self._extract_traceroute_data(results)
        
        # Hop Count Distribution
        self._plot_hop_count_distribution(traceroute_data, output_dir)
        
        # Route Stability Analysis
        self._plot_route_stability(traceroute_data, event_data, output_dir)
        
        # Probe Distribution by Country
        self._plot_probe_country_distribution(traceroute_data, output_dir)
        
        # Path Visualization (simplified)
        self._plot_path_analysis(traceroute_data, output_dir)

    def _plot_path_analysis(self, traceroute_data: Dict, output_dir: Path) -> None:
        # Path analysis visualization for traceroute data.
        plt.figure(figsize=(12, 8))
        
        routes = traceroute_data.get("routes", [])
        
        if not routes or not any(routes):
            plt.text(0.5, 0.5, 'No route data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=12)
            plt.title('Path Analysis')
        else:
            # Count unique paths
            path_counts = {}
            for route in routes:
                if route:
                    path_key = tuple(route)
                    path_counts[path_key] = path_counts.get(path_key, 0) + 1
            
            # Plot path frequency
            if path_counts:
                paths = list(range(1, len(path_counts) + 1))
                frequencies = list(path_counts.values())
                
                plt.bar(paths, frequencies, alpha=0.7, color='lightblue')
                plt.xlabel('Path ID')
                plt.ylabel('Frequency')
                plt.title(f'Path Analysis ({len(path_counts)} unique paths)')
                plt.grid(True, alpha=0.3)
            else:
                plt.text(0.5, 0.5, 'No valid path data', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=12)
                plt.title('Path Analysis')
        
        plt.tight_layout()
        plt.savefig(output_dir / "4_path_analysis.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_latency_over_time(self, ping_data: Dict, anomaly_events: List[Dict], output_dir: Path) -> None:
        # Latency Over Time (Per Probe) Line plot with anomaly highlights.
        plt.figure(figsize=(12, 8))
        
        # Group RTTs by probe
        probe_rtts = {}
        for i, probe_id in enumerate(ping_data.get("probe_ids", [])):
            if probe_id not in probe_rtts:
                probe_rtts[probe_id] = []
            
            if i < len(ping_data.get("all_rtts", [])):
                rtts = ping_data["all_rtts"][i]
                probe_rtts[probe_id].extend(rtts)
        
        # Plot lines for each probe
        if probe_rtts:
            colors = plt.cm.get_cmap('tab10')(np.linspace(0, 1, len(probe_rtts)))
            for (probe_id, rtts), color in zip(probe_rtts.items(), colors):
                if rtts:
                    x_values = range(len(rtts))
                    plt.plot(x_values, rtts, label=f'Probe {probe_id}', alpha=0.7, color=color)
        
        # Highlight anomalies
        anomaly_marked = False
        latency_anomalies = [e for e in anomaly_events if e.get("anomaly") == "latency_spike"]
        for anomaly in latency_anomalies:
            probe_id = anomaly.get("probe_id")
            value = anomaly.get("value")
            if probe_id in probe_rtts and value and not anomaly_marked:
                plt.scatter([], [], color='red', s=100, marker='o', label='Latency Spike')
                anomaly_marked = True
        
        plt.xlabel('Ping Sequence')
        plt.ylabel('RTT (ms)')
        plt.title('Latency Over Time (Per Probe)')
        
        # Only add legend if there are items to show
        if probe_rtts or anomaly_marked:
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "1_latency_over_time.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_latency_distribution_boxplot(self, ping_data: Dict, output_dir: Path) -> None:
        # Latency Distribution (Per Probe) -Box plot.
        plt.figure(figsize=(12, 8))
        
        probe_rtts = {}
        for i, probe_id in enumerate(ping_data.get("probe_ids", [])):
            if i < len(ping_data.get("all_rtts", [])):
                rtts = ping_data["all_rtts"][i]
                if rtts:
                    probe_rtts[str(probe_id)] = rtts
        
        if probe_rtts:
            data_for_boxplot = []
            labels = []
            for probe_id, rtts in probe_rtts.items():
                data_for_boxplot.append(rtts)
                labels.append(f'Probe {probe_id}')
            
            box_plot = plt.boxplot(data_for_boxplot, patch_artist=True)
            plt.xticks(range(1, len(labels) + 1), labels)
            
            for patch, rtts in zip(box_plot['boxes'], data_for_boxplot):
                median_rtt = np.median(rtts)
                if median_rtt > 200:
                    patch.set_facecolor('red')
                elif median_rtt > 100:
                    patch.set_facecolor('orange')
                else:
                    patch.set_facecolor('lightgreen')
        
        plt.ylabel('RTT (ms)')
        plt.title('Latency Distribution (Per Probe)')
        plt.xticks(rotation=45, ha='right')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "2_latency_distribution_boxplot.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_average_latency_per_probe(self, ping_data: Dict, output_dir: Path) -> None:
        # Average Latency Across Probes - Bar chart.
        plt.figure(figsize=(12, 8))
        
        probe_ids = ping_data.get("probe_ids", [])
        latencies = ping_data.get("latencies", [])
        
        if probe_ids and latencies:
            colors = ['red' if lat > 200 else 'orange' if lat > 100 else 'green' for lat in latencies]
            bars = plt.bar(range(len(probe_ids)), latencies, color=colors, alpha=0.7)
            
            for bar, latency in zip(bars, latencies):
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                        f'{latency:.1f}ms', ha='center', va='bottom')
            
            plt.xlabel('Probe ID')
            plt.ylabel('Average RTT (ms)')
            plt.title('Average Latency Across Probes')
            plt.xticks(range(len(probe_ids)), [f'Probe {pid}' for pid in probe_ids], rotation=45, ha='right')
            
            plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='100ms threshold')
            plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='200ms threshold')
            plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "3_average_latency_per_probe.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_packet_loss_per_probe(self, ping_data: Dict, output_dir: Path) -> None:
        # Packet Loss (%) Per Probe - Bar chart.
        plt.figure(figsize=(12, 8))
        
        probe_ids = ping_data.get("probe_ids", [])
        packet_losses = ping_data.get("packet_losses", [])
        
        if probe_ids and packet_losses:
            colors = ['red' if loss > 10 else 'orange' if loss > 5 else 'green' for loss in packet_losses]
            bars = plt.bar(range(len(probe_ids)), packet_losses, color=colors, alpha=0.7)
            
            for bar, loss in zip(bars, packet_losses):
                if loss > 0:
                    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                            f'{loss:.1f}%', ha='center', va='bottom')
            
            plt.xlabel('Probe ID')
            plt.ylabel('Packet Loss (%)')
            plt.title('Packet Loss (%) Per Probe')
            plt.xticks(range(len(probe_ids)), [f'Probe {pid}' for pid in probe_ids], rotation=45, ha='right')
            
            plt.axhline(y=5, color='orange', linestyle='--', alpha=0.7, label='5% warning threshold')
            plt.axhline(y=10, color='red', linestyle='--', alpha=0.7, label='10% critical threshold')
            plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "4_packet_loss_per_probe.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_jitter_per_probe(self, ping_data: Dict, output_dir: Path) -> None:
        # Jitter Per Probe - Bar chart.
        plt.figure(figsize=(12, 8))
        
        probe_ids = ping_data.get("probe_ids", [])
        jitters = ping_data.get("jitters", [])
        
        if probe_ids and jitters:
            colors = ['red' if jitter > 50 else 'orange' if jitter > 20 else 'green' for jitter in jitters]
            bars = plt.bar(range(len(probe_ids)), jitters, color=colors, alpha=0.7)
            
            for bar, jitter in zip(bars, jitters):
                if jitter > 1:
                    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                            f'{jitter:.1f}ms', ha='center', va='bottom')
            
            plt.xlabel('Probe ID')
            plt.ylabel('Jitter (ms)')
            plt.title('Jitter Per Probe')
            plt.xticks(range(len(probe_ids)), [f'Probe {pid}' for pid in probe_ids], rotation=45, ha='right')
            
            plt.axhline(y=20, color='orange', linestyle='--', alpha=0.7, label='20ms warning threshold')
            plt.axhline(y=50, color='red', linestyle='--', alpha=0.7, label='50ms critical threshold')
            plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "5_jitter_per_probe.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_hop_count_distribution(self, traceroute_data: Dict, output_dir: Path) -> None:
        # Hop count distribution for traceroute.
        plt.figure(figsize=(10, 6))
        
        hop_counts = traceroute_data.get("hop_counts", [])
        
        if hop_counts:
            plt.hist(hop_counts, bins=range(min(hop_counts), max(hop_counts) + 2), 
                    alpha=0.7, color='lightblue', edgecolor='black')
            plt.xlabel('Number of Hops')
            plt.ylabel('Number of Probes')
            plt.title('Hop Count Distribution')
            plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(output_dir / "1_hop_count_distribution.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_route_stability(self, traceroute_data: Dict, event_data: Dict, output_dir: Path) -> None:
        # Route stability analysis.
        plt.figure(figsize=(10, 6))
        
        routes = traceroute_data.get("routes", [])
        unique_routes = len(set(tuple(route) for route in routes if route))
        total_probes = len(routes)
        
        if total_probes > 0:
            stable_routes = total_probes - unique_routes + 1 if unique_routes > 0 else total_probes
            unstable_routes = unique_routes - 1 if unique_routes > 1 else 0
            
            plt.pie([stable_routes, unstable_routes], 
                   labels=['Stable Routes', 'Route Variations'],
                   colors=['green', 'orange'],
                   autopct='%1.1f%%')
            plt.title('Route Stability Analysis')
        
        plt.tight_layout()
        plt.savefig(output_dir / "2_route_stability.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _load_measurement_data(self, measurement_id: str) -> Optional[Dict]:
        result_file = self.results_dir / f"measurement_{measurement_id}_result.json"
        
        try:
            if result_file.exists():
                with open(result_file, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"Measurement result file not found: {result_file}")
                return None
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load measurement data from {result_file}: {e}")
            return None

    def _load_event_data(self, measurement_id: str) -> Optional[Dict]:
        # Load event data from events directory.
        # Try multiple possible event file patterns
        possible_files = [
            self.events_dir / f"{measurement_id}.json",
            self.events_dir / f"measurement_{measurement_id}.json",
            self.events_dir / f"measurement_{measurement_id}_events.json"
        ]
        
        for event_file in possible_files:
            try:
                if event_file.exists():
                    with open(event_file, 'r') as f:
                        data = json.load(f)
                        logger.info(f"Loaded event data from {event_file}")
                        return data
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load event data from {event_file}: {e}")
                continue
        
        logger.info(f"No event file found for measurement {measurement_id}")
        return None

    def _extract_ping_data(self, results: List[Dict]) -> Dict[str, Any]:
        ping_data = {
            "probe_ids": [],
            "latencies": [],
            "packet_losses": [],
            "jitters": [],
            "all_rtts": [],
            "countries": []
        }
        
        for result in results:
            if result.get("measurement_type") == "ping":
                latency_stats = result.get("latency_stats", {})
                latency = latency_stats.get("avg")
                loss = result.get("packet_loss_percentage", 0)
                rtts = latency_stats.get("rtts", [])
                
                if latency is not None:
                    ping_data["probe_ids"].append(result.get("probe_id"))
                    ping_data["latencies"].append(latency)
                    ping_data["packet_losses"].append(loss)
                    ping_data["all_rtts"].append(rtts)
                    ping_data["countries"].append(result.get("probe_country"))
                    
                    jitter = stdev(rtts) if len(rtts) > 1 else 0
                    ping_data["jitters"].append(jitter)
        
        return ping_data

    def _extract_traceroute_data(self, results: List[Dict]) -> Dict[str, Any]:
        # Extract traceroute data for plotting.
        traceroute_data = {
            "probe_ids": [],
            "hop_counts": [],
            "routes": [],
            "countries": []
        }
        
        for result in results:
            if result.get("measurement_type") == "traceroute":
                hops_count = result.get("hops_count", 0)
                hops = result.get("hops", [])
                country = result.get("probe_country")
                probe_id = result.get("probe_id")
                
                # Only add if we have valid data
                if probe_id is not None:
                    traceroute_data["probe_ids"].append(probe_id)
                    traceroute_data["hop_counts"].append(hops_count)
                    traceroute_data["countries"].append(country)
                    
                    # Extract route (IP addresses)
                    route = []
                    if isinstance(hops, list):
                        for hop in hops:
                            if isinstance(hop, dict) and hop.get("ip"):
                                route.append(hop.get("ip"))
                    traceroute_data["routes"].append(route)
        
        logger.info(f"Extracted traceroute data: {len(traceroute_data['probe_ids'])} probes, countries: {set(traceroute_data['countries'])}")
        return traceroute_data

    def _plot_probe_country_distribution(self, data: Dict, output_dir: Path) -> None:
        # Probe distribution by country.
        plt.figure(figsize=(12, 6))
        
        countries = data.get("countries", [])
        logger.info(f"Countries data: {countries}")
        
        # Filter out None and empty values
        valid_countries = [country for country in countries if country and str(country).strip() and str(country) != 'None']
        logger.info(f"Valid countries: {valid_countries}")
        
        if valid_countries:
            country_counts = {}
            for country in valid_countries:
                country_counts[country] = country_counts.get(country, 0) + 1
            
            if country_counts:
                countries_list = list(country_counts.keys())
                counts = list(country_counts.values())
                
                plt.bar(countries_list, counts, alpha=0.7, color='lightcoral')
                plt.xlabel('Country')
                plt.ylabel('Number of Probes')
                plt.title('Probe Distribution by Country')
                plt.xticks(rotation=45, ha='right')
            else:
                plt.text(0.5, 0.5, 'No valid country data available', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=12)
                plt.title('Probe Distribution by Country')
        else:
            plt.text(0.5, 0.5, 'No country data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=12)
            plt.title('Probe Distribution by Country')
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "3_probe_country_distribution.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _create_anomaly_summary_plot(self, measurement_id: str, event_data: Dict, output_dir: Path) -> None:
        # Anomaly Summary - Bar chart.
        plt.figure(figsize=(10, 6))
        
        # Debug: log what we have in event_data
        logger.info(f"Event data keys for measurement {measurement_id}: {list(event_data.keys()) if event_data else 'No event data'}")
        
        if not event_data or not event_data.get("events"):
            plt.text(0.5, 0.5, 'No anomalies detected', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Anomaly Summary')
            logger.info(f"No events found for measurement {measurement_id}")
        else:
            events = event_data["events"]
            logger.info(f"Found {len(events)} events for measurement {measurement_id}")
            
            if len(events) == 0:
                plt.text(0.5, 0.5, 'No anomalies detected', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
                plt.title('Anomaly Summary')
                logger.info(f"Empty events list for measurement {measurement_id}")
            else:
                anomaly_counts = {}
                
                for event in events:
                    anomaly_type = event.get("anomaly")
                    if anomaly_type:
                        anomaly_counts[anomaly_type] = anomaly_counts.get(anomaly_type, 0) + 1
                
                logger.info(f"Anomaly counts for measurement {measurement_id}: {anomaly_counts}")
                
                if anomaly_counts:
                    anomaly_types = list(anomaly_counts.keys())
                    counts = list(anomaly_counts.values())
                    
                    # Color mapping for different anomaly types
                    color_map = {
                        'latency_spike': 'red',
                        'packet_loss': 'orange',
                        'route_change': 'blue',
                        'path_flapping': 'purple',
                        'jitter_spike': 'yellow',
                        'unreachable_host': 'darkred',
                        'outlier_probe_latency': 'pink',
                        'outlier_probe_loss': 'brown'
                    }
                    colors = [color_map.get(atype, 'gray') for atype in anomaly_types]
                    
                    bars = plt.bar(anomaly_types, counts, color=colors, alpha=0.7)
                    
                    # Add value labels
                    for bar, count in zip(bars, counts):
                        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                                str(count), ha='center', va='bottom')
                    
                    plt.xlabel('Anomaly Type')
                    plt.ylabel('Number of Events')
                    plt.title(f'Anomaly Summary ({sum(counts)} total events)')
                    plt.xticks(rotation=45, ha='right')
                else:
                    plt.text(0.5, 0.5, 'No valid anomaly data found', 
                            transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
                    plt.title('Anomaly Summary')
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "anomaly_summary.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_severity_distribution(self, ax, all_events):
        # Plot distribution of anomaly severities.
        severities = [e.get("severity") for e in all_events if e.get("severity")]
        
        if not severities:
            ax.text(0.5, 0.5, 'No severity data available',
                   transform=ax.transAxes, ha='center', va='center')
            ax.set_title('Severity Distribution')
            return
        
        severity_counts = {}
        for severity in severities:
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        colors = {'warning': 'orange', 'critical': 'red', 'info': 'blue'}
        
        for severity, count in severity_counts.items():
            color = colors.get(severity, 'gray')
            ax.bar(severity, count, alpha=0.7, color=color)
        
        ax.set_xlabel('Severity Level')
        ax.set_ylabel('Number of Events')
        ax.set_title('Anomaly Severity Distribution')

    def _plot_measurement_anomaly_stats(self, ax, measurements_with_anomalies):
        # Plot measurement anomaly statistics.
        total_measurements = len(list(self.results_dir.glob("measurement_*_result.json")))
        measurements_clean = total_measurements - measurements_with_anomalies
        
        labels = ['Clean Measurements', 'Measurements with Anomalies']
        values = [measurements_clean, measurements_with_anomalies]
        colors = ['green', 'red']
        
        wedges, texts, autotexts = ax.pie(values, labels=labels, colors=colors,
                                         autopct='%1.1f%%', startangle=90)
        ax.set_title('Measurements Overview')

    def _plot_top_affected_probes(self, ax, all_events):
        # Plot top probes affected by anomalies.
        probe_counts = {}
        for event in all_events:
            probe_id = event.get("probe_id")
            if probe_id:
                probe_counts[probe_id] = probe_counts.get(probe_id, 0) + 1
        
        if not probe_counts:
            ax.text(0.5, 0.5, 'No probe data available',
                   transform=ax.transAxes, ha='center', va='center')
            ax.set_title('Top Affected Probes')
            return
        
        # Get top 10 probes
        top_probes = sorted(probe_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        if top_probes:
            probes, counts = zip(*top_probes)
            ax.barh(probes, counts, alpha=0.7, color='coral')
            ax.set_xlabel('Number of Anomalies')
            ax.set_title('Top 10 Affected Probes')

    def _plot_country_distribution(self, ax, all_probe_data):
        # Plot probe distribution by country.
        countries = [data.get("country") for data in all_probe_data.values() 
                    if data.get("country")]
        
        if not countries:
            ax.text(0.5, 0.5, 'No country data available',
                   transform=ax.transAxes, ha='center', va='center')
            ax.set_title('Country Distribution')
            return
        
        country_counts = {}
        for country in countries:
            country_counts[country] = country_counts.get(country, 0) + 1
        
        # Get top countries
        top_countries = sorted(country_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        if top_countries:
            countries_list, counts = zip(*top_countries)
            ax.bar(countries_list, counts, alpha=0.7, color='skyblue')
            ax.set_xlabel('Country')
            ax.set_ylabel('Number of Probes')
            ax.set_title('Top Countries by Probe Count')
            plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    def _plot_probes_per_measurement(self, ax):
        # Plot number of probes per measurement.
        probe_counts = []
        
        for result_file in self.results_dir.glob("measurement_*_result.json"):
            try:
                with open(result_file, 'r') as f:
                    data = json.load(f)
                
                unique_probes = len(set(r.get("probe_id") for r in data.get("results", []) 
                                      if r.get("probe_id")))
                probe_counts.append(unique_probes)
                
            except (json.JSONDecodeError, IOError):
                continue
        
        if not probe_counts:
            ax.text(0.5, 0.5, 'No probe count data available',
                   transform=ax.transAxes, ha='center', va='center')
            ax.set_title('Probes per Measurement')
            return
        
        ax.hist(probe_counts, bins=10, alpha=0.7, color='lightgreen', edgecolor='black')
        ax.set_xlabel('Number of Probes')
        ax.set_ylabel('Number of Measurements')
        ax.set_title('Probes per Measurement Distribution')
        ax.grid(True, alpha=0.3)
        ax.set_title('Probes per Measurement Distribution')
        ax.grid(True, alpha=0.3)
