import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List
from collections import defaultdict
from measurement_client.logger import logger

class AnomalySummaryPlotter:
    
    @staticmethod
    def plot_anomaly_summary(events: List[Dict], output_dir: Path) -> None:
        plt.figure(figsize=(12, 6))
        
        if not events:
            plt.text(0.5, 0.5, 'No anomalies detected', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Anomaly Type Summary')
            logger.info("No anomalies detected for summary plot")
        else:
            anomaly_counts = defaultdict(int)
            for event in events:
                anomaly_type = event.get("anomaly") or event.get("type")
                if anomaly_type:
                    anomaly_counts[anomaly_type] += 1
            
            if anomaly_counts:
                anomaly_types = list(anomaly_counts.keys())
                counts = list(anomaly_counts.values())
                
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
                
                for bar, count in zip(bars, counts):
                    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                            str(count), ha='center', va='bottom', fontweight='bold')
                
                plt.xlabel('Anomaly Type')
                plt.ylabel('Number of Events')
                plt.title(f'Anomaly Type Summary ({sum(counts)} total events)')
                plt.xticks(rotation=45, ha='right')
                logger.info(f"Created anomaly summary plot with {sum(counts)} total events")
            else:
                plt.text(0.5, 0.5, 'No valid anomaly data found', 
                        transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
                plt.title('Anomaly Type Summary')
                logger.warning("No valid anomaly data found for summary plot")
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        output_file = output_dir / "5_anomaly_type_summary.png"
        plt.savefig(output_file, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved anomaly summary plot: {output_file}")
