import json
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from measurement_client.logger import logger
from statistics import stdev, mean
from collections import defaultdict

class SintraPlotter:
    """Regional measurement analysis plotter for each measurement."""
    
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
        """Generate regional plots for each measurement in its own directory."""
        logger.info("Generating regional analysis plots for each measurement...")
        
        result_files = list(self.results_dir.glob("measurement_*_result.json"))
        
        if not result_files:
            logger.warning(f"No measurement result files found in {self.results_dir}")
            return
        
        processed_count = 0
        for result_file in result_files:
            try:
                measurement_id = self._extract_measurement_id(result_file.name)
                if measurement_id:
                    self._create_regional_plots_for_measurement(measurement_id)
                    processed_count += 1
            except Exception as e:
                logger.error(f"Failed to plot {result_file.name}: {e}")
        
        logger.info(f"Regional plot generation complete: {processed_count} measurements processed")

    def _extract_measurement_id(self, filename: str) -> Optional[str]:
        """Extract measurement ID from filename like 'measurement_12345_result.json'."""
        try:
            parts = filename.split('_')
            if len(parts) >= 3 and parts[0] == 'measurement' and parts[-1] == 'result.json':
                return parts[1]
            return None
        except Exception as e:
            logger.error(f"Failed to extract measurement ID from {filename}: {e}")
            return None

    def _create_regional_plots_for_measurement(self, measurement_id: str) -> None:
        """Create region-based plots for a specific measurement in its own directory."""
        logger.info(f"Generating regional plots for measurement {measurement_id}")
        
        # Create measurement-specific directory
        measurement_dir = self.output_dir / f"measurement_{measurement_id}"
        measurement_dir.mkdir(parents=True, exist_ok=True)
        
        # Load measurement and event data
        measurement_data = self._load_measurement_data(measurement_id)
        event_data = self._load_event_data(measurement_id)
        
        if not measurement_data:
            logger.warning(f"No measurement data found for {measurement_id}")
            return
        
        results = measurement_data.get("results", [])
        events = event_data.get("events", []) if event_data else []
        
        if not results:
            logger.warning(f"No results in measurement {measurement_id}")
            return
        
        # Filter for ping results only for regional analysis
        ping_results = [r for r in results if r.get("measurement_type") == "ping"]
        
        if not ping_results:
            logger.warning(f"No ping results found for measurement {measurement_id}")
            return
        
        logger.info(f"Processing {len(ping_results)} ping results for regional analysis")
        
        # Import plotters locally to avoid circular imports
        from .regional_latency_plotter import RegionalLatencyPlotter
        from .regional_metrics_plotter import RegionalMetricsPlotter
        from .anomaly_summary_plotter import AnomalySummaryPlotter
        
        # Create regional plots
        RegionalLatencyPlotter.plot_latency_trend(ping_results, events, measurement_dir)
        RegionalMetricsPlotter.plot_packet_loss(ping_results, measurement_dir)
        RegionalMetricsPlotter.plot_jitter(ping_results, measurement_dir)
        RegionalMetricsPlotter.plot_per_probe_distribution(ping_results, measurement_dir)
        AnomalySummaryPlotter.plot_anomaly_summary(events, measurement_dir)
        
        logger.info(f"Regional plots saved in directory: {measurement_dir}")

    def _plot_regional_packet_loss(self, results: List[Dict], output_dir: Path) -> None:
        """Regional Packet Loss - Bar chart showing average packet loss per region."""
        plt.figure(figsize=(12, 8))
        
        # Group packet loss by country
        regional_losses = defaultdict(list)
        for result in results:
            if result.get("measurement_type") == "ping":
                country = result.get("probe_country")
                loss = result.get("packet_loss_percentage", 0)
                if country:
                    regional_losses[country].append(loss)
        
        if not regional_losses:
            plt.text(0.5, 0.5, 'No regional packet loss data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Regional Packet Loss')
        else:
            regions = []
            avg_losses = []
            for country, losses in regional_losses.items():
                if losses:
                    regions.append(country)
                    avg_losses.append(mean(losses))
            
            if regions:
                # Sort by packet loss (highest first)
                sorted_data = sorted(zip(regions, avg_losses), key=lambda x: x[1], reverse=True)
                regions, avg_losses = zip(*sorted_data)
                
                # Color coding: Red >10%, Yellow 5-10%, Green <5%
                colors = ['red' if loss > 10 else 'orange' if loss > 5 else 'green' 
                         for loss in avg_losses]
                
                bars = plt.bar(range(len(regions)), avg_losses, color=colors, alpha=0.7)
                
                # Add value labels
                for bar, loss in zip(bars, avg_losses):
                    if loss > 0.1:
                        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                                f'{loss:.1f}%', ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Region')
                plt.ylabel('Average Packet Loss (%)')
                plt.title('Regional Packet Loss Comparison')
                plt.xticks(range(len(regions)), regions, rotation=45, ha='right')
                
                # Add threshold lines
                plt.axhline(y=5, color='orange', linestyle='--', alpha=0.7, label='5% threshold')
                plt.axhline(y=10, color='red', linestyle='--', alpha=0.7, label='10% threshold')
                plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "2_regional_packet_loss.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_regional_jitter(self, results: List[Dict], output_dir: Path) -> None:
        """Regional Jitter - Bar chart showing average jitter per region."""
        plt.figure(figsize=(12, 8))
        
        # Calculate jitter by country
        regional_jitters = defaultdict(list)
        for result in results:
            if result.get("measurement_type") == "ping":
                country = result.get("probe_country")
                latency_stats = result.get("latency_stats", {})
                rtts = latency_stats.get("rtts", [])
                if country and len(rtts) > 1:
                    jitter = stdev(rtts)
                    regional_jitters[country].append(jitter)
        
        if not regional_jitters:
            plt.text(0.5, 0.5, 'No regional jitter data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Regional Jitter Analysis')
        else:
            regions = []
            avg_jitters = []
            for country, jitters in regional_jitters.items():
                if jitters:
                    regions.append(country)
                    avg_jitters.append(mean(jitters))
            
            if regions:
                # Sort by jitter (highest first)
                sorted_data = sorted(zip(regions, avg_jitters), key=lambda x: x[1], reverse=True)
                regions, avg_jitters = zip(*sorted_data)
                
                # Color coding for jitter
                colors = ['red' if jitter > 50 else 'orange' if jitter > 20 else 'green' 
                         for jitter in avg_jitters]
                
                bars = plt.bar(range(len(regions)), avg_jitters, color=colors, alpha=0.7)
                
                # Add value labels
                for bar, jitter in zip(bars, avg_jitters):
                    if jitter > 1:
                        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                                f'{jitter:.1f}ms', ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Region')
                plt.ylabel('Average Jitter (ms)')
                plt.title('Regional Jitter Analysis')
                plt.xticks(range(len(regions)), regions, rotation=45, ha='right')
                
                # Add threshold lines
                plt.axhline(y=20, color='orange', linestyle='--', alpha=0.7, label='20ms threshold')
                plt.axhline(y=50, color='red', linestyle='--', alpha=0.7, label='50ms threshold')
                plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "3_regional_jitter.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_per_probe_latency_distribution(self, results: List[Dict], output_dir: Path) -> None:
        """Per-Probe Latency Distribution - Box plot grouped by region."""
        plt.figure(figsize=(14, 8))
        
        # Group latencies by country and probe
        regional_probe_data = defaultdict(lambda: defaultdict(list))
        for result in results:
            if result.get("measurement_type") == "ping":
                country = result.get("probe_country")
                probe_id = result.get("probe_id")
                latency_stats = result.get("latency_stats", {})
                rtts = latency_stats.get("rtts", [])
                if country and probe_id and rtts:
                    regional_probe_data[country][probe_id].extend(rtts)
        
        if not regional_probe_data:
            plt.text(0.5, 0.5, 'No probe latency data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Per-Probe Latency Distribution')
        else:
            # Prepare data for box plot
            all_data = []
            labels = []
            colors = []
            
            for country, probes in regional_probe_data.items():
                for probe_id, rtts in probes.items():
                    if rtts:
                        all_data.append(rtts)
                        labels.append(f'{country}\nProbe {probe_id}')
                        median_rtt = np.median(rtts)
                        if median_rtt > 200:
                            colors.append('red')
                        elif median_rtt > 100:
                            colors.append('orange')
                        else:
                            colors.append('green')
            
            if all_data:
                box_plot = plt.boxplot(all_data, patch_artist=True)
                
                # Color the boxes
                for patch, color in zip(box_plot['boxes'], colors):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)
                
                plt.ylabel('Latency (ms)')
                plt.title('Per-Probe Latency Distribution (Grouped by Region)')
                plt.xticks(range(1, len(labels) + 1), labels, rotation=45, ha='right')
                
                # Add threshold lines
                plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='100ms threshold')
                plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='200ms threshold')
                plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "4_per_probe_latency_distribution.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _plot_anomaly_type_summary(self, events: List[Dict], output_dir: Path) -> None:
        """Anomaly Type Summary - Bar chart showing count of each anomaly type."""
        plt.figure(figsize=(12, 6))
        
        if not events:
            plt.text(0.5, 0.5, 'No anomalies detected', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Anomaly Type Summary')
        else:
            # Count anomalies by type
            anomaly_counts = defaultdict(int)
            for event in events:
                anomaly_type = event.get("anomaly") or event.get("type")
                if anomaly_type:
                    anomaly_counts[anomaly_type] += 1
            
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
                    'regional_high_latency': 'crimson',
                    'regional_packet_loss': 'darkorange',
                    'regional_performance_outlier': 'magenta'
                }
                colors = [color_map.get(atype, 'gray') for atype in anomaly_types]
                
                bars = plt.bar(anomaly_types, counts, color=colors, alpha=0.7)
                
                # Add value labels
                for bar, count in zip(bars, counts):
                    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                            str(count), ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Anomaly Type')
                plt.ylabel('Number of Events')
                plt.title(f'Anomaly Type Summary ({sum(counts)} total events)')
                plt.xticks(rotation=45, ha='right')
            else:
                plt.text(0.5, 0.5, 'No valid anomaly data found', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
                plt.title('Anomaly Type Summary')
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "5_anomaly_type_summary.png", dpi=300, bbox_inches='tight')
        plt.close()

    def _load_measurement_data(self, measurement_id: str) -> Optional[Dict]:
        """Load measurement data from results directory."""
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
        """Load event data from events directory."""
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
        """Extract ping data for plotting."""
        ping_data = {
            "probe_ids": [],
            "latencies": [],
            "packet_losses": [],
            "all_rtts": [],
            "countries": [],
            "jitters": []
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
