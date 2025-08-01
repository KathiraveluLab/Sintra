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
        
        all_data = self._aggregate_measurement_data(json_files)
        
        if not all_data:
            logger.warning("No valid measurement data found after processing")
            logger.info("Check if measurement files contain valid ping results with country information")
            return
        
        logger.info(f"Generating measurement performance plots for {len(all_data)} countries...")
        
        self._plot_median_latency_by_country(all_data)
        self._plot_packet_loss_by_country(all_data)
        self._plot_jitter_by_country(all_data)
        
        logger.info(f"All measurement plots saved to: {self.output_dir}")
        logger.info("Measurement plots show actual network performance trends")
    
    def _aggregate_measurement_data(self, json_files: List[Path]) -> Dict[str, List[Dict]]:
        all_regional_data = defaultdict(list)
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                results = data.get("results", [])
                measurement_id = data.get("measurement_id", "unknown")
                
                logger.debug(f"Processing {json_file.name}: {len(results)} results")
                
                for result in results:
                    if result.get("measurement_type") != "ping":
                        continue
                    
                    country = result.get("probe_country")
                    if not country or country == "Unknown":
                        continue
                    
                    latency_stats = result.get("latency_stats", {})
                    avg_latency = latency_stats.get("avg")
                    rtts = latency_stats.get("rtts", [])
                    packet_loss = result.get("packet_loss_percentage", 0)
                    
                    if avg_latency is None or not rtts:
                        continue
                    
                    jitter = stdev(rtts) if len(rtts) > 1 else 0
                    
                    probe_data = {
                        "measurement_id": measurement_id,
                        "probe_id": result.get("probe_id"),
                        "avg_latency": avg_latency,
                        "packet_loss": packet_loss,
                        "jitter": jitter,
                        "rtts": rtts
                    }
                    
                    all_regional_data[country].append(probe_data)
                    
            except Exception as e:
                logger.error(f"Error processing {json_file}: {e}")
                continue
        
        filtered_data = self._filter_problematic_probes(all_regional_data)
        
        logger.info(f"Aggregated data from {len(filtered_data)} countries")
        for country, probes in filtered_data.items():
            logger.debug(f"  {country}: {len(probes)} probes")
        
        return filtered_data
    
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

def main():
    logger.info("Creating measurement performance plots...")
    plotter = MeasurementPlotter()
    plotter.process_all_measurement_files()

if __name__ == "__main__":
    main()
        # Add value labels for significant jitter
