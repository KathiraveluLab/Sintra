import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from statistics import mean
from measurement_client.logger import logger

class RegionalLatencyPlotter:
    
    @staticmethod
    def plot_latency_trend(results: List[Dict], events: List[Dict], output_dir: Path) -> None:
        logger.info(f"Creating regional latency trend plot with {len(results)} results")
        
        plt.figure(figsize=(14, 8))
        
        regional_data = defaultdict(list)
        country_codes = set()
        
        for result in results:
            country = result.get("probe_country")
            country_code = result.get("probe_country_code")
            latency_stats = result.get("latency_stats", {})
            avg_latency = latency_stats.get("avg")
            
            region_name = country if country and country != "Unknown" else country_code
            
            if region_name and region_name.strip() and avg_latency is not None:
                regional_data[region_name].append(avg_latency)
                if country_code:
                    country_codes.add(country_code)
                logger.debug(f"Added latency {avg_latency}ms for region {region_name}")
        
        logger.info(f"Grouped data into {len(regional_data)} regions: {list(regional_data.keys())}")
        logger.info(f"Country codes found: {sorted(country_codes)}")
        
        if not regional_data:
            plt.text(0.5, 0.5, 'No regional latency data available\nEnsure measurements have probe country information', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Regional Latency Trend - No Data')
            logger.warning("No regional data found for latency plotting")
        else:
            regions = []
            median_latencies = []
            probe_counts = []
            
            for region_name, latencies in regional_data.items():
                if latencies:
                    regions.append(region_name)
                    median_lat = np.median(latencies)
                    median_latencies.append(median_lat)
                    probe_counts.append(len(latencies))
                    logger.info(f"Region {region_name}: {len(latencies)} probes, median latency: {median_lat:.2f}ms")
            
            if regions:
                sorted_data = sorted(zip(regions, median_latencies, probe_counts), key=lambda x: x[1])
                regions, median_latencies, probe_counts = zip(*sorted_data)
                
                x_pos = range(len(regions))
                colors = ['red' if lat > 200 else 'orange' if lat > 100 else 'green' 
                         for lat in median_latencies]
                
                plt.plot(x_pos, median_latencies, 'o-', linewidth=2, markersize=8, color='blue')
                
                for i, (lat, color, probe_count) in enumerate(zip(median_latencies, colors, probe_counts)):
                    plt.scatter(i, lat, color=color, s=150, zorder=5, edgecolors='black', linewidth=1)
                
                anomaly_regions = set()
                for event in events:
                    if event.get("anomaly") in ["latency_spike", "regional_high_latency"]:
                        region = event.get("probe_country") or event.get("region")
                        if region and region in regions:
                            anomaly_regions.add(region)
                
                if anomaly_regions:
                    for region in anomaly_regions:
                        idx = regions.index(region)
                        plt.scatter(idx, median_latencies[idx], marker='x', s=300, 
                                  color='red', linewidth=4, label='Anomaly Detected' if region == list(anomaly_regions)[0] else "")
                
                plt.xlabel('Region (sorted by latency)')
                plt.ylabel('Median Latency (ms)')
                plt.title(f'Regional Latency Trend ({len(regions)} regions)')
                plt.xticks(x_pos, regions, rotation=45, ha='right')
                plt.grid(True, alpha=0.3)
                
                plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='100ms threshold')
                plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='200ms threshold')
                
                for i, (lat, probe_count) in enumerate(zip(median_latencies, probe_counts)):
                    plt.annotate(f'{lat:.1f}ms\n({probe_count} probes)', (i, lat), textcoords="offset points", 
                               xytext=(0,15), ha='center', fontsize=8)
                
                plt.legend()
                logger.info(f"Successfully created regional latency trend plot with {len(regions)} regions")
            else:
                plt.text(0.5, 0.5, 'No valid regions with latency data', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
                plt.title('Regional Latency Trend - No Valid Data')
                logger.warning("No valid regions found with latency data")
        
        plt.tight_layout()
        plt.savefig(output_dir / "1_regional_latency_trend.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved regional latency trend plot to {output_dir / '1_regional_latency_trend.png'}")
