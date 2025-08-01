import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict
import hashlib
from datetime import datetime
from measurement_client.logger import logger

class TraceroutePlotter:
    
    def __init__(self, output_dir: str = "visualization/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        plt.style.use('default')
        logger.info(f"TraceroutePlotter initialized with output dir: {self.output_dir}")
    
    def process_all_traceroute_files(self, results_dir: str = "measurement_client/results/fetched_measurements"):
        results_path = Path(results_dir)
        if not results_path.exists():
            logger.warning(f"Results directory not found: {results_dir}")
            return
        
        json_files = list(results_path.glob("measurement_*_result.json"))
        if not json_files:
            logger.warning(f"No measurement files found in {results_dir}")
            return
        
        logger.info(f"Processing {len(json_files)} files for traceroute analysis...")
        
        traceroute_data = self._extract_traceroute_data(json_files)
        
        if not traceroute_data:
            logger.warning("No traceroute data found - check if measurements contain traceroute results")
            return
        
        logger.info(f"Found traceroute data for {len(traceroute_data)} targets")
        
        self._plot_hop_count_over_time(traceroute_data)
        self._plot_route_change_timeline(traceroute_data)
        self._plot_path_stability_analysis(traceroute_data)
        
        logger.info(f"Traceroute analysis plots saved to: {self.output_dir}")
    
    def _extract_traceroute_data(self, json_files: List[Path]) -> Dict[str, List[Dict]]:
        traceroute_data = defaultdict(list)
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                measurement_id = data.get("measurement_id")
                target = data.get("target", "unknown")
                results = data.get("results", [])
                
                logger.debug(f"Processing {json_file.name} for target {target}")
                
                for result in results:
                    if result.get("measurement_type") != "traceroute":
                        continue
                    
                    probe_id = result.get("probe_id")
                    country = result.get("probe_country", "Unknown")
                    hops = result.get("hops", [])
                    hops_count = result.get("hops_count", 0)
                    timestamp = result.get("timestamp")
                    
                    if not hops or hops_count == 0:
                        continue
                    
                    route_hash = self._calculate_route_hash(hops)
                    hop_ips = self._extract_hop_ips(hops)
                    
                    traceroute_entry = {
                        "measurement_id": measurement_id,
                        "target": target,
                        "probe_id": probe_id,
                        "country": country,
                        "hops_count": hops_count,
                        "route_hash": route_hash,
                        "hop_ips": hop_ips,
                        "timestamp": timestamp,
                        "hops_raw": hops
                    }
                    
                    traceroute_data[target].append(traceroute_entry)
                    
            except Exception as e:
                logger.error(f"Error processing {json_file}: {e}")
                continue
        
        for target, entries in traceroute_data.items():
            entries.sort(key=lambda x: x["timestamp"] or 0)
            logger.info(f"Target {target}: {len(entries)} traceroute entries")
        
        return dict(traceroute_data)
    
    def _calculate_route_hash(self, hops: List[Dict]) -> str:
        hop_sequence = []
        for hop in hops:
            if isinstance(hop, dict):
                hop_responses = hop.get("result", [])
                for response in hop_responses:
                    if isinstance(response, dict) and response.get("from"):
                        hop_sequence.append(response["from"])
                        break
        
        route_string = "->".join(hop_sequence)
        return hashlib.md5(route_string.encode()).hexdigest()[:8]
    
    def _extract_hop_ips(self, hops: List[Dict]) -> List[str]:
        hop_ips = []
        for hop in hops:
            if isinstance(hop, dict):
                hop_responses = hop.get("result", [])
                for response in hop_responses:
                    if isinstance(response, dict) and response.get("from"):
                        hop_ips.append(response["from"])
                        break
                else:
                    hop_ips.append("*")
        return hop_ips
    
    def _plot_hop_count_over_time(self, traceroute_data: Dict[str, List[Dict]]):
        fig, axes = plt.subplots(len(traceroute_data), 1, figsize=(14, 6 * len(traceroute_data)))
        if len(traceroute_data) == 1:
            axes = [axes]
        
        for idx, (target, entries) in enumerate(traceroute_data.items()):
            ax = axes[idx]
            
            probe_data = defaultdict(list)
            for entry in entries:
                probe_id = entry["probe_id"]
                probe_data[probe_id].append(entry)
            
            colors = plt.get_cmap('viridis')(np.linspace(0, 1, len(probe_data)))
            
            for color, (probe_id, probe_entries) in zip(colors, probe_data.items()):
                timestamps = []
                hop_counts = []
                
                for entry in probe_entries:
                    if entry["timestamp"]:
                        timestamps.append(datetime.fromtimestamp(entry["timestamp"]))
                        hop_counts.append(entry["hops_count"])
                
                if timestamps and hop_counts:
                    country = probe_entries[0]["country"]
                    ax.plot(timestamps, hop_counts, 'o-', color=color, 
                           label=f'Probe {probe_id} ({country})', alpha=0.7, linewidth=2)
                    
                    hop_changes = []
                    for i in range(1, len(hop_counts)):
                        if abs(hop_counts[i] - hop_counts[i-1]) >= 3:
                            hop_changes.append((timestamps[i], hop_counts[i]))
                    
                    if hop_changes:
                        change_times, change_counts = zip(*hop_changes)
                        ax.scatter(change_times, change_counts, color='red', s=100, 
                                 marker='x', linewidth=3, zorder=5)
            
            ax.set_xlabel('Time')
            ax.set_ylabel('Hop Count')
            ax.set_title(f'Hop Count Over Time - Target: {target}')
            ax.grid(True, alpha=0.3)
            ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            
            if any(entry["hops_count"] for entry in entries):
                all_hop_counts = [entry["hops_count"] for entry in entries]
                ax.axhline(y=np.median(all_hop_counts), color='orange', linestyle='--', 
                          alpha=0.7, label=f'Median: {np.median(all_hop_counts):.1f}')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / "traceroute_hop_count_over_time.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created hop count over time plot")
    
    def _plot_route_change_timeline(self, traceroute_data: Dict[str, List[Dict]]):
        fig, axes = plt.subplots(len(traceroute_data), 1, figsize=(14, 6 * len(traceroute_data)))
        if len(traceroute_data) == 1:
            axes = [axes]
        
        for idx, (target, entries) in enumerate(traceroute_data.items()):
            ax = axes[idx]
            
            probe_data = defaultdict(list)
            for entry in entries:
                probe_id = entry["probe_id"]
                probe_data[probe_id].append(entry)
            
            y_offset = 0
            colors = plt.cm.get_cmap('Set3')(np.linspace(0, 1, len(probe_data)))
            
            for color, (probe_id, probe_entries) in zip(colors, probe_data.items()):
                timestamps = []
                route_ids = []
                route_hash_to_id = {}
                current_route_id = 0
                
                for entry in probe_entries:
                    if entry["timestamp"]:
                        timestamps.append(datetime.fromtimestamp(entry["timestamp"]))
                        route_hash = entry["route_hash"]
                        
                        if route_hash not in route_hash_to_id:
                            route_hash_to_id[route_hash] = current_route_id
                            current_route_id += 1
                        
                        route_ids.append(route_hash_to_id[route_hash] + y_offset)
                
                if timestamps and route_ids:
                    country = probe_entries[0]["country"]
                    ax.step(timestamps, route_ids, where='post', color=color, 
                           label=f'Probe {probe_id} ({country})', linewidth=2, alpha=0.8)
                    
                    route_changes = []
                    for i in range(1, len(route_ids)):
                        if route_ids[i] != route_ids[i-1]:
                            route_changes.append(timestamps[i])
                    
                    if route_changes:
                        for change_time in route_changes:
                            ax.axvline(x=change_time, color='red', alpha=0.5, linestyle='--')
                
                y_offset += current_route_id + 1
            
            ax.set_xlabel('Time')
            ax.set_ylabel('Route ID (per probe)')
            ax.set_title(f'Route Changes Over Time - Target: {target}')
            ax.grid(True, alpha=0.3)
            ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        plt.tight_layout()
        plt.savefig(self.output_dir / "traceroute_route_changes_timeline.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created route changes timeline plot")
    
    def _plot_path_stability_analysis(self, traceroute_data: Dict[str, List[Dict]]):
        plt.figure(figsize=(14, 8))
        
        targets = []
        stability_scores = []
        route_change_counts = []
        
        for target, entries in traceroute_data.items():
            probe_data = defaultdict(list)
            for entry in entries:
                probe_id = entry["probe_id"]
                probe_data[probe_id].append(entry)
            
            target_stability = []
            target_changes = 0
            
            for probe_id, probe_entries in probe_data.items():
                if len(probe_entries) > 1:
                    unique_routes = len(set(entry["route_hash"] for entry in probe_entries))
                    total_measurements = len(probe_entries)
                    stability = (1 - (unique_routes - 1) / total_measurements) * 100
                    target_stability.append(stability)
                    
                    route_changes = 0
                    for i in range(1, len(probe_entries)):
                        if probe_entries[i]["route_hash"] != probe_entries[i-1]["route_hash"]:
                            route_changes += 1
                    target_changes += route_changes
            
            if target_stability:
                targets.append(target)
                stability_scores.append(np.mean(target_stability))
                route_change_counts.append(target_changes)
        
        if targets:
            x_pos = range(len(targets))
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            
            colors_stability = ['green' if score > 80 else 'orange' if score > 60 else 'red' 
                               for score in stability_scores]
            
            bars1 = ax1.bar(x_pos, stability_scores, color=colors_stability, alpha=0.7)
            
            for bar, score in zip(bars1, stability_scores):
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                        f'{score:.1f}%', ha='center', va='bottom', fontweight='bold')
            
            ax1.set_xlabel('Target')
            ax1.set_ylabel('Path Stability Score (%)')
            ax1.set_title('Path Stability Analysis by Target')
            ax1.set_xticks(x_pos)
            ax1.set_xticklabels(targets, rotation=45, ha='right')
            ax1.axhline(y=80, color='green', linestyle='--', alpha=0.7, label='Stable (>80%)')
            ax1.axhline(y=60, color='orange', linestyle='--', alpha=0.7, label='Moderate (>60%)')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            colors_changes = ['red' if changes > 10 else 'orange' if changes > 5 else 'green' 
                             for changes in route_change_counts]
            
            bars2 = ax2.bar(x_pos, route_change_counts, color=colors_changes, alpha=0.7)
            
            for bar, changes in zip(bars2, route_change_counts):
                if changes > 0:
                    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                            str(changes), ha='center', va='bottom', fontweight='bold')
            
            ax2.set_xlabel('Target')
            ax2.set_ylabel('Total Route Changes')
            ax2.set_title('Route Change Count by Target')
            ax2.set_xticks(x_pos)
            ax2.set_xticklabels(targets, rotation=45, ha='right')
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            plt.savefig(self.output_dir / "traceroute_path_stability_analysis.png", dpi=300, bbox_inches='tight')
            plt.close()
            logger.info("Created path stability analysis plot")
        else:
            logger.warning("No valid data for path stability analysis")

def main():
    logger.info("Creating traceroute analysis plots...")
    plotter = TraceroutePlotter()
    plotter.process_all_traceroute_files()

if __name__ == "__main__":
    main()
