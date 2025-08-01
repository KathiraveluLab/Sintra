import json
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
from statistics import median, mean, stdev
from collections import defaultdict
import pandas as pd
from measurement_client.logger import logger

class MeasurementPlotter:
    
    def __init__(self, output_dir: str = "visualization/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        plt.style.use('default')
        sns.set_palette("husl")
        logger.info(f"MeasurementPlotter initialized with output dir: {self.output_dir}")
        
    def process_all_measurement_files(self, results_dir: str = "measurement_client/results/fetched_measurements"):
        results_path = Path(results_dir)
        if not results_path.exists():
            logger.warning(f"Results directory not found: {results_dir}")
            logger.info("No measurement plots generated - run 'sintra fetch' first")
            return
        
        json_files = list(results_path.glob("measurement_*_result.json"))
        if not json_files:
            logger.warning(f"No measurement files found in {results_dir}")
            logger.info("No measurement plots generated - run 'sintra fetch' first")
            return
        
        logger.info(f"Processing {len(json_files)} measurement files...")
        
        ping_data = self._aggregate_measurement_data(json_files, "ping")
        traceroute_data = self._aggregate_measurement_data(json_files, "traceroute")
        
        plot_count = 0
        
        if ping_data:
            logger.info(f"Generating ping performance plots for {len(ping_data)} countries...")
            self._plot_median_latency_by_country(ping_data)
            self._plot_packet_loss_by_country(ping_data)
            self._plot_jitter_by_country(ping_data)
            plot_count += 3
        else:
            logger.warning("No valid ping data found")
        
        if traceroute_data:
            logger.info(f"Generating traceroute plots for {len(traceroute_data)} countries...")
            self._plot_traceroute_hops_by_country(traceroute_data)
            self._plot_traceroute_path_analysis(traceroute_data)
            plot_count += 2
            
            try:
                from visualization.traceroute_plotter import TraceroutePlotter
                traceroute_plotter = TraceroutePlotter(str(self.output_dir))
                traceroute_plotter.process_all_traceroute_files(results_dir)
                plot_count += 3
                logger.info("Traceroute timeline analysis completed")
            except ImportError as e:
                logger.warning(f"Could not import TraceroutePlotter: {e}")
            except Exception as e:
                logger.warning(f"Error in traceroute timeline analysis: {e}")
        else:
            logger.warning("No valid traceroute data found")
        
        if plot_count > 0:
            logger.info(f"All {plot_count} measurement plots saved to: {self.output_dir}")
            logger.info("Measurement plots show actual network performance trends")
        else:
            logger.warning("No measurement plots generated - no valid data found")
    
    def _aggregate_measurement_data(self, json_files: List[Path], measurement_type: str = "ping") -> Dict[str, List[Dict]]:
        all_regional_data = defaultdict(list)
        total_processed = 0
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                results = data.get("results", [])
                measurement_id = data.get("measurement_id", "unknown")
                
                logger.debug(f"Processing {json_file.name}: {len(results)} total results")
                
                processed_count = 0
                for result in results:
                    result_type = result.get("measurement_type")
                    if result_type != measurement_type:
                        continue
                    
                    country = result.get("probe_country")
                    if not country or country == "Unknown":
                        continue
                    
                    if measurement_type == "ping":
                        probe_data = self._extract_ping_data(result, measurement_id)
                    elif measurement_type == "traceroute":
                        probe_data = self._extract_traceroute_data(result, measurement_id)
                    else:
                        continue
                    
                    if probe_data:
                        all_regional_data[country].append(probe_data)
                        processed_count += 1
                
                logger.info(f"File {json_file.name}: processed {processed_count} {measurement_type} results")
                total_processed += processed_count
                    
            except Exception as e:
                logger.error(f"Error processing {json_file}: {e}")
                continue
        
        logger.info(f"Total {measurement_type} results processed: {total_processed}")
        
        if measurement_type == "ping":
            filtered_data = self._filter_problematic_probes(all_regional_data)
        else:
            filtered_data = self._filter_problematic_traceroutes(all_regional_data)
        
        logger.info(f"Aggregated {measurement_type} data from {len(filtered_data)} countries")
        for country, probes in filtered_data.items():
            logger.info(f"  {country}: {len(probes)} {measurement_type} probes")
        
        return filtered_data
    
    def _extract_ping_data(self, result: Dict, measurement_id: str) -> Dict:
        latency_stats = result.get("latency_stats", {})
        avg_latency = latency_stats.get("avg")
        rtts = latency_stats.get("rtts", [])
        packet_loss = result.get("packet_loss_percentage", 0)
        
        if avg_latency is None or not rtts:
            return {}
        
        jitter = stdev(rtts) if len(rtts) > 1 else 0
        
        return {
            "measurement_id": measurement_id,
            "probe_id": result.get("probe_id"),
            "avg_latency": avg_latency,
            "packet_loss": packet_loss,
            "jitter": jitter,
            "rtts": rtts
        }
    
    def _extract_traceroute_data(self, result: Dict, measurement_id: str) -> Dict:
        hops = result.get("hops", [])
        hops_count = result.get("hops_count", 0)
        
        logger.debug(f"Traceroute data - probe {result.get('probe_id')}: hops={len(hops)}, hops_count={hops_count}")
        
        # Try alternative field names
        if not hops and not hops_count:
            hops = result.get("result", [])  # Alternative field name
            hops_count = len(hops) if hops else 0
            logger.debug(f"Alternative traceroute data - probe {result.get('probe_id')}: result={len(hops)}")
        
        if not hops or hops_count == 0:
            logger.debug(f"Skipping traceroute probe {result.get('probe_id')}: no hops data")
            return {}
        
        responding_hops = 0
        unique_ips = set()
        
        for hop in hops:
            if isinstance(hop, dict):
                hop_responses = hop.get("result", [])
                if not hop_responses:
                    continue
                    
                has_response = False
                for response in hop_responses:
                    if isinstance(response, dict) and response.get("from"):
                        has_response = True
                        unique_ips.add(response.get("from"))
                        break
                        
                if has_response:
                    responding_hops += 1
        
        logger.debug(f"Traceroute probe {result.get('probe_id')}: {responding_hops}/{hops_count} responding hops, {len(unique_ips)} unique IPs")
        
        return {
            "measurement_id": measurement_id,
            "probe_id": result.get("probe_id"),
            "hops_count": hops_count,
            "responding_hops": responding_hops,
            "non_responding_hops": hops_count - responding_hops,
            "unique_ips": len(unique_ips),
            "path_completeness": (responding_hops / hops_count * 100) if hops_count > 0 else 0
        }
    
    def _filter_problematic_probes(self, regional_data: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        filtered_data = {}
        
        for country, probes in regional_data.items():
            if len(probes) < 2:
                continue
            
            latencies = [p["avg_latency"] for p in probes]
            country_median_latency = median(latencies)
            
            good_probes = []
            for probe in probes:
                if probe["packet_loss"] >= 100:
                    continue
                
                if probe["avg_latency"] > 3 * country_median_latency:
                    continue
                
                good_probes.append(probe)
            
            if len(good_probes) >= 2:
                filtered_data[country] = good_probes
                logger.info(f"{country}: kept {len(good_probes)}/{len(probes)} probes after filtering")
        
        return filtered_data
    
    def _filter_problematic_traceroutes(self, regional_data: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        filtered_data = {}
        
        logger.info(f"Filtering traceroute data from {len(regional_data)} countries")
        
        for country, probes in regional_data.items():
            if len(probes) < 1:  # Allow single probe for traceroute
                logger.debug(f"Skipping {country}: only {len(probes)} probes")
                continue
            
            good_probes = []
            for probe in probes:
                # More lenient filtering for traceroute
                if probe["hops_count"] == 0:
                    logger.debug(f"Filtered probe {probe['probe_id']} in {country}: 0 hops")
                    continue
                
                if probe["path_completeness"] < 10:  # Lower threshold
                    logger.debug(f"Filtered probe {probe['probe_id']} in {country}: low completeness {probe['path_completeness']:.1f}%")
                    continue
                
                if probe["hops_count"] > 64:  # Higher threshold
                    logger.debug(f"Filtered probe {probe['probe_id']} in {country}: too many hops {probe['hops_count']}")
                    continue
                
                good_probes.append(probe)
            
            if len(good_probes) >= 1:
                filtered_data[country] = good_probes
                logger.info(f"{country}: kept {len(good_probes)}/{len(probes)} traceroute probes after filtering")
        
        return filtered_data
    
    def _plot_median_latency_by_country(self, regional_data: Dict[str, List[Dict]]):
        plt.figure(figsize=(14, 8))
        
        countries = []
        median_latencies = []
        probe_counts = []
        
        for country, probes in regional_data.items():
            latencies = [p["avg_latency"] for p in probes]
            countries.append(country)
            median_latencies.append(median(latencies))
            probe_counts.append(len(probes))
        
        sorted_data = sorted(zip(countries, median_latencies, probe_counts), key=lambda x: x[1])
        countries_sorted, latencies_sorted, counts_sorted = zip(*sorted_data)
        
        colors = ['green' if lat < 50 else 'orange' if lat < 100 else 'red' 
                 for lat in latencies_sorted]
        
        bars = plt.bar(range(len(countries_sorted)), latencies_sorted, color=colors, alpha=0.7)
        
        for i, (bar, lat, count) in enumerate(zip(bars, latencies_sorted, counts_sorted)):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                    f'{lat:.1f}ms\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        plt.xlabel('Country')
        plt.ylabel('Median Latency (ms)')
        plt.title('Network Performance: Median Latency by Country')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        
        plt.axhline(y=50, color='green', linestyle='--', alpha=0.7, label='Good (<50ms)')
        plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='Fair (<100ms)')
        plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='Poor (>200ms)')
        plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "measurement_median_latency_by_country.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created median latency by country plot")
    
    def _plot_packet_loss_by_country(self, regional_data: Dict[str, List[Dict]]):
        plt.figure(figsize=(14, 8))
        
        countries = []
        avg_packet_losses = []
        probe_counts = []
        
        for country, probes in regional_data.items():
            packet_losses = [p["packet_loss"] for p in probes]
            countries.append(country)
            avg_packet_losses.append(mean(packet_losses))
            probe_counts.append(len(probes))
        
        sorted_data = sorted(zip(countries, avg_packet_losses, probe_counts), key=lambda x: x[1], reverse=True)
        countries_sorted, losses_sorted, counts_sorted = zip(*sorted_data)
        
        colors = ['red' if loss > 5 else 'orange' if loss > 1 else 'green' 
                 for loss in losses_sorted]
        
        bars = plt.bar(range(len(countries_sorted)), losses_sorted, color=colors, alpha=0.7)
        
        for i, (bar, loss, count) in enumerate(zip(bars, losses_sorted, counts_sorted)):
            if loss > 0.1:
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                        f'{loss:.1f}%\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        plt.xlabel('Country')
        plt.ylabel('Average Packet Loss (%)')
        plt.title('Network Reliability: Average Packet Loss by Country')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        
        plt.axhline(y=1, color='orange', linestyle='--', alpha=0.7, label='Acceptable (1%)')
        plt.axhline(y=5, color='red', linestyle='--', alpha=0.7, label='Poor (5%)')
        plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "measurement_packet_loss_by_country.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created packet loss by country plot")
    
    def _plot_jitter_by_country(self, regional_data: Dict[str, List[Dict]]):
        plt.figure(figsize=(14, 8))
        
        countries = []
        avg_jitters = []
        probe_counts = []
        
        for country, probes in regional_data.items():
            jitters = [p["jitter"] for p in probes]
            countries.append(country)
            avg_jitters.append(mean(jitters))
            probe_counts.append(len(probes))
        
        sorted_data = sorted(zip(countries, avg_jitters, probe_counts), key=lambda x: x[1], reverse=True)
        countries_sorted, jitters_sorted, counts_sorted = zip(*sorted_data)
        
        colors = ['red' if jitter > 20 else 'orange' if jitter > 10 else 'green' 
                 for jitter in jitters_sorted]
        
        bars = plt.bar(range(len(countries_sorted)), jitters_sorted, color=colors, alpha=0.7)
        
        # Add value labels for significant jitter
        for i, (bar, jitter, count) in enumerate(zip(bars, jitters_sorted, counts_sorted)):
            if jitter > 1:  # Only show label if there's measurable jitter
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                        f'{jitter:.1f}ms\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        plt.xlabel('Country')
        plt.ylabel('Average Jitter (ms)')
        plt.title('Network Stability: Average Jitter by Country')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        
        # Add stability threshold lines
        plt.axhline(y=10, color='orange', linestyle='--', alpha=0.7, label='Noticeable (10ms)')
        plt.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Problematic (20ms)')
        plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "measurement_jitter_by_country.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created jitter by country plot")
    
    def _plot_traceroute_hops_by_country(self, regional_data: Dict[str, List[Dict]]):
        plt.figure(figsize=(14, 8))
        
        countries = []
        median_hops = []
        probe_counts = []
        
        for country, probes in regional_data.items():
            hop_counts = [p["hops_count"] for p in probes]
            countries.append(country)
            median_hops.append(median(hop_counts))
            probe_counts.append(len(probes))
        
        sorted_data = sorted(zip(countries, median_hops, probe_counts), key=lambda x: x[1])
        countries_sorted, hops_sorted, counts_sorted = zip(*sorted_data)
        
        colors = ['green' if hops < 10 else 'orange' if hops < 20 else 'red' 
                 for hops in hops_sorted]
        
        bars = plt.bar(range(len(countries_sorted)), hops_sorted, color=colors, alpha=0.7)
        
        for i, (bar, hops, count) in enumerate(zip(bars, hops_sorted, counts_sorted)):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                    f'{hops:.1f}\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        plt.xlabel('Country')
        plt.ylabel('Median Hop Count')
        plt.title('Network Path Length: Median Traceroute Hops by Country')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        
        plt.axhline(y=10, color='orange', linestyle='--', alpha=0.7, label='Short path (<10 hops)')
        plt.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Long path (>20 hops)')
        plt.legend()
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "measurement_traceroute_hops_by_country.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created traceroute hops by country plot")
    
    def _plot_traceroute_path_analysis(self, regional_data: Dict[str, List[Dict]]):
        countries = []
        avg_completeness = []
        avg_unique_ips = []
        probe_counts = []
        
        for country, probes in regional_data.items():
            completeness_values = [p["path_completeness"] for p in probes]
            unique_ip_values = [p["unique_ips"] for p in probes]
            
            countries.append(country)
            avg_completeness.append(mean(completeness_values))
            avg_unique_ips.append(mean(unique_ip_values))
            probe_counts.append(len(probes))
        
        sorted_data = sorted(zip(countries, avg_completeness, avg_unique_ips, probe_counts), 
                           key=lambda x: x[1], reverse=True)
        countries_sorted, completeness_sorted, unique_ips_sorted, counts_sorted = zip(*sorted_data)
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12))
        
        colors_completeness = ['green' if comp > 80 else 'orange' if comp > 60 else 'red' 
                              for comp in completeness_sorted]
        
        bars1 = ax1.bar(range(len(countries_sorted)), completeness_sorted, 
                       color=colors_completeness, alpha=0.7)
        
        for i, (bar, comp, count) in enumerate(zip(bars1, completeness_sorted, counts_sorted)):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{comp:.1f}%\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        ax1.set_xlabel('Country')
        ax1.set_ylabel('Average Path Completeness (%)')
        ax1.set_title('Traceroute Path Completeness by Country')
        ax1.set_xticks(range(len(countries_sorted)))
        ax1.set_xticklabels(countries_sorted, rotation=45, ha='right')
        ax1.axhline(y=80, color='green', linestyle='--', alpha=0.7, label='Good (>80%)')
        ax1.axhline(y=60, color='orange', linestyle='--', alpha=0.7, label='Fair (>60%)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        colors_ips = ['green' if ips > 5 else 'orange' if ips > 3 else 'red' 
                     for ips in unique_ips_sorted]
        
        bars2 = ax2.bar(range(len(countries_sorted)), unique_ips_sorted, 
                       color=colors_ips, alpha=0.7)
        
        for i, (bar, ips, count) in enumerate(zip(bars2, unique_ips_sorted, counts_sorted)):
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                    f'{ips:.1f}\n({count} probes)', ha='center', va='bottom', fontsize=9)
        
        ax2.set_xlabel('Country')
        ax2.set_ylabel('Average Unique IPs in Path')
        ax2.set_title('Path Diversity: Unique IPs per Traceroute by Country')
        ax2.set_xticks(range(len(countries_sorted)))
        ax2.set_xticklabels(countries_sorted, rotation=45, ha='right')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(self.output_dir / "measurement_traceroute_path_analysis_by_country.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created traceroute path analysis by country plot")

def main():
    logger.info("Creating measurement performance plots...")
    plotter = MeasurementPlotter()
    plotter.process_all_measurement_files()

if __name__ == "__main__":
    main()
