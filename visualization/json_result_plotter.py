import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
from statistics import median, mean, stdev
from measurement_client.logger import logger

class JSONResultPlotter:
    def __init__(self, output_dir: str = "visualization/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir = Path("measurement_client/results/fetched_measurements")
        plt.style.use('default')
        sns.set_palette("husl")
        logger.info(f"JSONResultPlotter initialized with output dir: {self.output_dir}")
    
    def auto_process_all_results(self) -> None:
        logger.info(f"Looking for measurement results in: {self.results_dir}")
        if not self.results_dir.exists():
            logger.error(f"Results directory not found: {self.results_dir}")
            logger.info("Please run measurements first using: python sintra.py measure && python sintra.py fetch")
            return
        json_files = list(self.results_dir.glob("measurement_*_result.json"))
        if not json_files:
            logger.warning(f"No measurement result files found in {self.results_dir}")
            logger.info("Please fetch measurement results first using: python sintra.py fetch")
            return
        logger.info(f"Found {len(json_files)} measurement files to process")
        for json_file in json_files:
            logger.debug(f"Processing: {json_file.name}")
            self.process_measurement_file(str(json_file))
        logger.info(f"All plots saved to: {self.output_dir}")
        plot_files = list(self.output_dir.glob("*.png"))
        logger.info(f"Generated {len(plot_files)} plots:")
        for plot_file in sorted(plot_files):
            logger.info(f"  - {plot_file.name}")

    def process_measurement_file(self, json_file_path: str) -> None:
        logger.debug(f"Processing measurement file: {json_file_path}")
        data = self._load_json_file(json_file_path)
        if not data:
            return
        results = data.get("results", [])
        if not results:
            logger.warning(f"No results found in {json_file_path}")
            return
        filtered_data = self._process_and_filter_results(results)
        if not filtered_data:
            logger.warning(f"No valid data after filtering in {json_file_path}")
            return
        regional_stats = self._compute_regional_statistics(filtered_data)
        measurement_id = Path(json_file_path).stem
        self._create_regional_plots(regional_stats, measurement_id)
    
    def _load_json_file(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error(f"Error loading JSON file {file_path}: {e}")
            return {}
    
    def _process_and_filter_results(self, results: List[Dict]) -> Dict[str, List[Dict]]:
        country_groups = {}
        for result in results:
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
                "probe_id": result.get("probe_id"),
                "avg_latency": avg_latency,
                "packet_loss": packet_loss,
                "jitter": jitter,
                "rtts": rtts
            }
            if country not in country_groups:
                country_groups[country] = []
            country_groups[country].append(probe_data)
        
        filtered_groups = {}
        for country, probes in country_groups.items():
            if len(probes) < 2:
                continue
            latencies = [p["avg_latency"] for p in probes]
            country_median_latency = median(latencies)
            filtered_probes = []
            for probe in probes:
                if probe["packet_loss"] >= 100:
                    logger.debug(f"Filtered probe {probe['probe_id']} in {country}: 100% packet loss")
                    continue
                if probe["avg_latency"] > 3 * country_median_latency:
                    logger.debug(f"Filtered probe {probe['probe_id']} in {country}: latency {probe['avg_latency']:.1f}ms > 3x median {country_median_latency:.1f}ms")
                    continue
                filtered_probes.append(probe)
            if len(filtered_probes) >= 2:
                filtered_groups[country] = filtered_probes
                logger.info(f"Country {country}: {len(filtered_probes)}/{len(probes)} probes after filtering")
        return filtered_groups
    
    def _compute_regional_statistics(self, filtered_data: Dict[str, List[Dict]]) -> Dict[str, Dict]:
        regional_stats = {}
        for country, probes in filtered_data.items():
            latencies = [p["avg_latency"] for p in probes]
            packet_losses = [p["packet_loss"] for p in probes]
            jitters = [p["jitter"] for p in probes]
            regional_stats[country] = {
                "median_latency": median(latencies),
                "avg_packet_loss": mean(packet_losses),
                "avg_jitter": mean(jitters),
                "probe_count": len(probes)
            }
            logger.info(f"Regional stats for {country}: "
                       f"median_latency={regional_stats[country]['median_latency']:.1f}ms, "
                       f"avg_packet_loss={regional_stats[country]['avg_packet_loss']:.1f}%, "
                       f"avg_jitter={regional_stats[country]['avg_jitter']:.1f}ms, "
                       f"probe_count={regional_stats[country]['probe_count']}")
        return regional_stats
    
    def _create_regional_plots(self, regional_stats: Dict[str, Dict], measurement_id: str) -> None:
        if not regional_stats:
            return
        countries = list(regional_stats.keys())
        median_latencies = [regional_stats[c]["median_latency"] for c in countries]
        avg_packet_losses = [regional_stats[c]["avg_packet_loss"] for c in countries]
        avg_jitters = [regional_stats[c]["avg_jitter"] for c in countries]
        probe_counts = [regional_stats[c]["probe_count"] for c in countries]
        self._plot_median_latency(countries, median_latencies, probe_counts, measurement_id)
        self._plot_packet_loss(countries, avg_packet_losses, probe_counts, measurement_id)
        self._plot_jitter(countries, avg_jitters, probe_counts, measurement_id)
    
    def _plot_median_latency(self, countries: List[str], latencies: List[float], 
                           probe_counts: List[int], measurement_id: str) -> None:
        plt.figure(figsize=(12, 8))
        sorted_data = sorted(zip(countries, latencies, probe_counts), key=lambda x: x[1])
        countries_sorted, latencies_sorted, probe_counts_sorted = zip(*sorted_data)
        colors = ['red' if lat > 200 else 'orange' if lat > 100 else 'green' 
                 for lat in latencies_sorted]
        bars = plt.bar(range(len(countries_sorted)), latencies_sorted, color=colors, alpha=0.7)
        for i, (bar, lat, count) in enumerate(zip(bars, latencies_sorted, probe_counts_sorted)):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 5,
                    f'{lat:.1f}ms\n({count} probes)', ha='center', va='bottom', fontsize=9)
        plt.xlabel('Country')
        plt.ylabel('Median Latency (ms)')
        plt.title(f'Median Latency by Country - {measurement_id}')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='100ms threshold')
        plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='200ms threshold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = self.output_dir / f"{measurement_id}_latency.png"
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved latency plot: {output_file}")
    
    def _plot_packet_loss(self, countries: List[str], packet_losses: List[float], 
                         probe_counts: List[int], measurement_id: str) -> None:
        plt.figure(figsize=(12, 8))
        sorted_data = sorted(zip(countries, packet_losses, probe_counts), key=lambda x: x[1], reverse=True)
        countries_sorted, losses_sorted, probe_counts_sorted = zip(*sorted_data)
        colors = ['red' if loss > 10 else 'orange' if loss > 5 else 'green' 
                 for loss in losses_sorted]
        bars = plt.bar(range(len(countries_sorted)), losses_sorted, color=colors, alpha=0.7)
        for i, (bar, loss, count) in enumerate(zip(bars, losses_sorted, probe_counts_sorted)):
            if loss > 0.1:
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                        f'{loss:.1f}%\n({count} probes)', ha='center', va='bottom', fontsize=9)
        plt.xlabel('Country')
        plt.ylabel('Average Packet Loss (%)')
        plt.title(f'Average Packet Loss by Country - {measurement_id}')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        plt.axhline(y=5, color='orange', linestyle='--', alpha=0.7, label='5% threshold')
        plt.axhline(y=10, color='red', linestyle='--', alpha=0.7, label='10% threshold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = self.output_dir / f"{measurement_id}_packet_loss.png"
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved packet loss plot: {output_file}")
    
    def _plot_jitter(self, countries: List[str], jitters: List[float], 
                    probe_counts: List[int], measurement_id: str) -> None:
        plt.figure(figsize=(12, 8))
        sorted_data = sorted(zip(countries, jitters, probe_counts), key=lambda x: x[1], reverse=True)
        countries_sorted, jitters_sorted, probe_counts_sorted = zip(*sorted_data)
        colors = ['red' if jitter > 50 else 'orange' if jitter > 20 else 'green' 
                 for jitter in jitters_sorted]
        bars = plt.bar(range(len(countries_sorted)), jitters_sorted, color=colors, alpha=0.7)
        for i, (bar, jitter, count) in enumerate(zip(bars, jitters_sorted, probe_counts_sorted)):
            if jitter > 1:
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        f'{jitter:.1f}ms\n({count} probes)', ha='center', va='bottom', fontsize=9)
        plt.xlabel('Country')
        plt.ylabel('Average Jitter (ms)')
        plt.title(f'Average Jitter by Country - {measurement_id}')
        plt.xticks(range(len(countries_sorted)), countries_sorted, rotation=45, ha='right')
        plt.axhline(y=20, color='orange', linestyle='--', alpha=0.7, label='20ms threshold')
        plt.axhline(y=50, color='red', linestyle='--', alpha=0.7, label='50ms threshold')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = self.output_dir / f"{measurement_id}_jitter.png"
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved jitter plot: {output_file}")


def process_all_measurement_files(input_dir: str = "measurement_client/results/fetched_measurements") -> None:
    input_path = Path(input_dir)
    if not input_path.exists():
        logger.error(f"Directory {input_dir} not found")
        return
    json_files = list(input_path.glob("measurement_*_result.json"))
    if not json_files:
        logger.warning(f"No measurement JSON files found in {input_dir}")
        return
    logger.info(f"Found {len(json_files)} measurement files to process")
    plotter = JSONResultPlotter()
    for json_file in json_files:
        logger.debug(f"Processing: {json_file.name}")
        plotter.process_measurement_file(str(json_file))
    logger.info(f"All plots saved to: {plotter.output_dir}")


def main():
    import sys
    if len(sys.argv) == 1:
        logger.info("Auto-processing all fetched measurement results...")
        plotter = JSONResultPlotter()
        plotter.auto_process_all_results()
        return
    if len(sys.argv) < 2:
        logger.info("Usage:")
        logger.info("  python json_result_plotter.py                              # Auto-process all fetched results")
        logger.info("  python json_result_plotter.py <path_to_json_file>           # Process single file")
        logger.info("  python json_result_plotter.py --all                        # Process all files in default directory")
        logger.info("  python json_result_plotter.py --all <directory_path>       # Process all files in specified directory")
        return
    if sys.argv[1] == "--all":
        if len(sys.argv) > 2:
            input_dir = sys.argv[2]
        else:
            input_dir = "measurement_client/results/fetched_measurements"
        process_all_measurement_files(input_dir)
    else:
        json_file_path = sys.argv[1]
        if not Path(json_file_path).exists():
            logger.error(f"File {json_file_path} not found")
            return
        plotter = JSONResultPlotter()
        plotter.process_measurement_file(json_file_path)
        logger.info(f"Plots saved to: {plotter.output_dir}")


if __name__ == "__main__":
    main()
