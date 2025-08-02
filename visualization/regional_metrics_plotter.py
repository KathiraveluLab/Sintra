import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from statistics import mean, stdev
from measurement_client.logger import logger

class RegionalMetricsPlotter:
    
    @staticmethod
    def plot_packet_loss(results: List[Dict], output_dir: Path) -> None:
        plt.figure(figsize=(12, 8))
        
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
            logger.warning("No regional packet loss data found")
        else:
            regions = []
            avg_losses = []
            for country, losses in regional_losses.items():
                if losses:
                    regions.append(country)
                    avg_losses.append(mean(losses))
            
            if regions:
                sorted_data = sorted(zip(regions, avg_losses), key=lambda x: x[1], reverse=True)
                regions, avg_losses = zip(*sorted_data)
                
                colors = ['red' if loss > 10 else 'orange' if loss > 5 else 'green' 
                         for loss in avg_losses]
                
                bars = plt.bar(range(len(regions)), avg_losses, color=colors, alpha=0.7)
                
                for bar, loss in zip(bars, avg_losses):
                    if loss > 0.1:
                        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.2,
                                f'{loss:.1f}%', ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Region')
                plt.ylabel('Average Packet Loss (%)')
                plt.title('Regional Packet Loss Comparison')
                plt.xticks(range(len(regions)), regions, rotation=45, ha='right')
                
                plt.axhline(y=5, color='orange', linestyle='--', alpha=0.7, label='5% threshold')
                plt.axhline(y=10, color='red', linestyle='--', alpha=0.7, label='10% threshold')
                plt.legend()
                logger.info(f"Created packet loss plot for {len(regions)} regions")
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "2_regional_packet_loss.png", dpi=300, bbox_inches='tight')
        plt.close()

    @staticmethod
    def plot_jitter(results: List[Dict], output_dir: Path) -> None:
        plt.figure(figsize=(12, 8))
        
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
            logger.warning("No regional jitter data found")
        else:
            regions = []
            avg_jitters = []
            for country, jitters in regional_jitters.items():
                if jitters:
                    regions.append(country)
                    avg_jitters.append(mean(jitters))
            
            if regions:
                sorted_data = sorted(zip(regions, avg_jitters), key=lambda x: x[1], reverse=True)
                regions, avg_jitters = zip(*sorted_data)
                
                colors = ['red' if jitter > 50 else 'orange' if jitter > 20 else 'green' 
                         for jitter in avg_jitters]
                
                bars = plt.bar(range(len(regions)), avg_jitters, color=colors, alpha=0.7)
                
                for bar, jitter in zip(bars, avg_jitters):
                    if jitter > 1:
                        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                                f'{jitter:.1f}ms', ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Region')
                plt.ylabel('Average Jitter (ms)')
                plt.title('Regional Jitter Analysis')
                plt.xticks(range(len(regions)), regions, rotation=45, ha='right')
                
                plt.axhline(y=20, color='orange', linestyle='--', alpha=0.7, label='20ms threshold')
                plt.axhline(y=50, color='red', linestyle='--', alpha=0.7, label='50ms threshold')
                plt.legend()
                logger.info(f"Created jitter plot for {len(regions)} regions")
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "3_regional_jitter.png", dpi=300, bbox_inches='tight')
        plt.close()

    @staticmethod
    def plot_per_probe_distribution(results: List[Dict], output_dir: Path) -> None:
        plt.figure(figsize=(14, 8))
        
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
            logger.warning("No probe latency data found")
        else:
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
                
                for patch, color in zip(box_plot['boxes'], colors):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.7)
                
                plt.ylabel('Latency (ms)')
                plt.title('Per-Probe Latency Distribution (Grouped by Region)')
                plt.xticks(range(1, len(labels) + 1), labels, rotation=45, ha='right')
                
                plt.axhline(y=100, color='orange', linestyle='--', alpha=0.7, label='100ms threshold')
                plt.axhline(y=200, color='red', linestyle='--', alpha=0.7, label='200ms threshold')
                plt.legend()
                logger.info(f"Created distribution plot for {len(all_data)} probes")
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "4_per_probe_latency_distribution.png", dpi=300, bbox_inches='tight')
        plt.close()

    @staticmethod
    def plot_traceroute_path_diversity(results: List[Dict], output_dir: Path) -> None:
        plt.figure(figsize=(12, 8))
        
        regional_traceroute_data = defaultdict(list)
        logger.info(f"Processing {len(results)} results for traceroute path diversity")
        
        for result in results:
            result_type = result.get("measurement_type")
            if result_type != "traceroute":
                continue
                
            country = result.get("probe_country")
            hops_count = result.get("hops_count", 0)
            
            # Try alternative field names
            if hops_count == 0:
                hops = result.get("hops", []) or result.get("result", [])
                hops_count = len(hops) if hops else 0
            
            logger.debug(f"Traceroute result: country={country}, hops_count={hops_count}")
            
            if country and country != "Unknown" and hops_count > 0:
                regional_traceroute_data[country].append(hops_count)
        
        logger.info(f"Found traceroute data for {len(regional_traceroute_data)} countries")
        
        if not regional_traceroute_data:
            plt.text(0.5, 0.5, 'No regional traceroute data available\nCheck if measurements contain traceroute results', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Regional Traceroute Path Diversity - No Data')
            logger.warning("No regional traceroute data found")
        else:
            regions = []
            avg_hops = []
            probe_counts = []
            
            for country, hop_counts in regional_traceroute_data.items():
                if hop_counts:
                    regions.append(country)
                    avg_hops.append(mean(hop_counts))
                    probe_counts.append(len(hop_counts))
            
            if regions:
                sorted_data = sorted(zip(regions, avg_hops, probe_counts), key=lambda x: x[1], reverse=True)
                regions, avg_hops, probe_counts = zip(*sorted_data)
                
                colors = ['red' if hops > 20 else 'orange' if hops > 15 else 'green' 
                         for hops in avg_hops]
                
                bars = plt.bar(range(len(regions)), avg_hops, color=colors, alpha=0.7)
                
                for i, (bar, hops, count) in enumerate(zip(bars, avg_hops, probe_counts)):
                    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                            f'{hops:.1f}\n({count} probes)', ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Region')
                plt.ylabel('Average Hop Count')
                plt.title('Regional Traceroute Path Length Analysis')
                plt.xticks(range(len(regions)), regions, rotation=45, ha='right')
                
                plt.axhline(y=15, color='orange', linestyle='--', alpha=0.7, label='15 hops threshold')
                plt.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='20 hops threshold')
                plt.legend()
                logger.info(f"Created traceroute path diversity plot for {len(regions)} regions")
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_dir / "5_regional_traceroute_path_diversity.png", dpi=300, bbox_inches='tight')
        plt.close()
