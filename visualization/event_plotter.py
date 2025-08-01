import json
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from pathlib import Path
from typing import Dict, List
from collections import defaultdict, Counter
from datetime import datetime
import numpy as np
from measurement_client.logger import logger

class EventPlotter:
    # This class helps us visualize network anomalies by creating charts and graphs
    
    def __init__(self, output_dir: str = "visualization/plots"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Set plotting style
        plt.style.use('default')
        sns.set_palette("husl")
        
        logger.info(f"EventPlotter initialized with output dir: {self.output_dir}")
    
    def process_all_event_files(self, events_dir: str = "event_manager/results"):
        # Go through all the event files and create helpful charts from them
        events_path = Path(events_dir)
        if not events_path.exists():
            logger.warning(f"Events directory not found: {events_dir}")
            logger.info("No anomaly plots generated - run 'sintra detect' first")
            return
        
        json_files = list(events_path.glob("*.json"))
        if not json_files:
            logger.warning(f"No event files found in {events_dir}")
            logger.info("No anomaly plots generated - run 'sintra detect' first")
            return
        
        logger.info(f"Processing {len(json_files)} event files...")
        
        # Aggregate all events
        all_events = self._aggregate_event_data(json_files)
        
        if not all_events:
            logger.info("No anomalies detected - no anomaly plots generated")
            logger.info("Network performance appears stable (this is good news!)")
            return
        
        logger.info(f"Found {len(all_events)} anomalies - generating anomaly analysis plots...")
        
        # Create anomaly detection plots
        self._plot_anomaly_counts_by_type(all_events)
        self._plot_anomaly_timeline(all_events)
        self._plot_region_impact_chart(all_events)
        
        logger.info(f"All event plots saved to: {self.output_dir}")
    
    def _aggregate_event_data(self, json_files: List[Path]) -> List[Dict]:
        # Collect all the event data from multiple files into one big list
        all_events = []
        
        for json_file in json_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                events = data.get("events", [])
                measurement_id = json_file.stem  # Extract measurement ID from filename
                
                logger.debug(f"Processing {json_file.name}: {len(events)} events")
                
                # Add measurement context to each event
                for event in events:
                    event["source_measurement"] = measurement_id
                    all_events.append(event)
                    
            except Exception as e:
                logger.error(f"Error processing {json_file}: {e}")
                continue
        
        logger.info(f"Total events aggregated: {len(all_events)}")
        return all_events
    
    def _plot_anomaly_counts_by_type(self, events: List[Dict]):
        # Create a bar chart showing how many times each type of problem occurred
        plt.figure(figsize=(12, 8))
        
        # Count anomaly types
        anomaly_types = [event.get("anomaly") or event.get("type", "unknown") 
                        for event in events]
        type_counts = Counter(anomaly_types)
        
        if not type_counts:
            plt.text(0.5, 0.5, 'No anomaly types found', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Anomaly Detection Summary - No Data')
        else:
            # Sort by count (most frequent first)
            sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
            types, counts = zip(*sorted_types)
            
            # Color mapping for different anomaly types
            color_map = {
                'latency_spike': '#ff4444',
                'packet_loss': '#ff8800', 
                'route_change': '#4488ff',
                'path_flapping': '#8844ff',
                'jitter_spike': '#ffcc00',
                'unreachable_host': '#cc0000',
                'regional_high_latency': '#ff6666',
                'regional_packet_loss': '#ffaa44',
                'regional_performance_outlier': '#ff00ff'
            }
            colors = [color_map.get(atype, '#888888') for atype in types]
            
            bars = plt.bar(range(len(types)), counts, color=colors, alpha=0.8)
            
            # Add value labels
            for bar, count in zip(bars, counts):
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                        str(count), ha='center', va='bottom', fontweight='bold', fontsize=11)
            
            plt.xlabel('Anomaly Type')
            plt.ylabel('Number of Detections')
            plt.title(f'Anomaly Detection Summary ({sum(counts)} total detections)')
            plt.xticks(range(len(types)), types, rotation=45, ha='right')
            
            # Add total count text
            plt.text(0.02, 0.98, f'Total Events: {sum(counts)}', 
                    transform=plt.gca().transAxes, fontsize=12, fontweight='bold',
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgray'))
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "event_anomaly_counts_by_type.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created anomaly counts by type plot")
    
    def _plot_anomaly_timeline(self, events: List[Dict]):
        # Create a timeline showing when network problems happened over time
        plt.figure(figsize=(15, 8))
        
        # Extract timestamps and types
        timeline_data = []
        for event in events:
            timestamp = event.get("timestamp") or event.get("detected_at")
            anomaly_type = event.get("anomaly") or event.get("type", "unknown")
            
            if timestamp:
                try:
                    # Handle different timestamp formats
                    if isinstance(timestamp, (int, float)):
                        dt = datetime.fromtimestamp(timestamp)
                    else:
                        dt = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00'))
                    
                    timeline_data.append({
                        'datetime': dt,
                        'type': anomaly_type,
                        'measurement': event.get("source_measurement", "unknown")
                    })
                except Exception as e:
                    continue
        
        if not timeline_data:
            plt.text(0.5, 0.5, 'No timestamp data available for timeline', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Anomaly Timeline - No Data')
        else:
            # Convert to DataFrame for easier plotting
            df = pd.DataFrame(timeline_data)
            
            # Group by type and plot
            anomaly_types = list(df['type'].unique())
            colors = plt.get_cmap('tab10')(np.linspace(0, 1, len(anomaly_types)))
            
            for i, atype in enumerate(anomaly_types):
                type_data = df[df['type'] == atype]
                plt.scatter(type_data['datetime'], [i] * len(type_data), 
                           label=f'{atype} ({len(type_data)})', 
                           alpha=0.7, s=60, color=colors[i])
            
            plt.xlabel('Time')
            plt.ylabel('Anomaly Type')
            plt.title(f'Anomaly Detection Timeline ({len(timeline_data)} events)')
            plt.yticks(range(len(anomaly_types)), anomaly_types)
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            
            # Format x-axis
            plt.xticks(rotation=45)
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "event_anomaly_timeline.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created anomaly timeline plot")
    
    def _plot_region_impact_chart(self, events: List[Dict]):
        """C. Region Impact Chart - Shows which regions had the most events."""
        plt.figure(figsize=(12, 8))
        
        # Extract region information
        region_impacts = defaultdict(lambda: defaultdict(int))
        total_by_region = defaultdict(int)
        
        for event in events:
            region = (event.get("probe_country") or 
                     event.get("region") or 
                     event.get("country") or "Unknown")
            anomaly_type = event.get("anomaly") or event.get("type", "unknown")
            
            region_impacts[region][anomaly_type] += 1
            total_by_region[region] += 1
        
        if not region_impacts:
            plt.text(0.5, 0.5, 'No regional data available', 
                    transform=plt.gca().transAxes, ha='center', va='center', fontsize=14)
            plt.title('Regional Impact Analysis - No Data')
        else:
            # Sort regions by total impact
            sorted_regions = sorted(total_by_region.items(), key=lambda x: x[1], reverse=True)
            regions, totals = zip(*sorted_regions[:15])  # Top 15 regions
            
            # Create stacked bar chart
            anomaly_types = list(set(atype for region_data in region_impacts.values() 
                                   for atype in region_data.keys()))
            colors = plt.cm.get_cmap('viridis')(np.linspace(0, 1, len(anomaly_types)))
            
            bottom = np.zeros(len(regions))
            for i, atype in enumerate(anomaly_types):
                values = [region_impacts[region][atype] for region in regions]
                plt.bar(regions, values, bottom=bottom, label=atype, 
                       color=colors[i], alpha=0.8)
                bottom += values
            
            # Add total labels
            for i, (region, total) in enumerate(zip(regions, totals)):
                plt.text(i, total + 0.5, str(total), ha='center', va='bottom', 
                        fontweight='bold', fontsize=10)
            
            plt.xlabel('Country/Region')
            plt.ylabel('Number of Anomalies')
            plt.title(f'Regional Impact Analysis (Top {len(regions)} regions)')
            plt.xticks(rotation=45, ha='right')
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            
            # Add summary text
            total_events = sum(totals)
            plt.text(0.02, 0.98, f'Total Events: {total_events}\nRegions Affected: {len(region_impacts)}', 
                    transform=plt.gca().transAxes, fontsize=11, fontweight='bold',
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue'))
        
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.output_dir / "event_region_impact_chart.png", dpi=300, bbox_inches='tight')
        plt.close()
        logger.info("Created regional impact chart")

def main():
    """Main function to create event analysis plots."""
    logger.info("Creating event detection analysis plots...")
    plotter = EventPlotter()
    plotter.process_all_event_files()

if __name__ == "__main__":
    main()
