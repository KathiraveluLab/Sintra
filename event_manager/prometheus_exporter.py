from flask import Flask, Response
import json
from pathlib import Path
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

FETCHED_RESULTS_DIR = Path("measurement_client/results/fetched_measurements")
EVENT_RESULTS_DIR = Path("event_manager/results")

def collect_metrics():
    metrics = []
    
    # Measurement metrics - focus on key indicators
    try:
        for result_file in FETCHED_RESULTS_DIR.glob("measurement_*_result.json"):
            with open(result_file, "r") as f:
                data = json.load(f)
            
            measurement_id = data.get("measurement_id")
            results = data.get("results", [])
            
            # Summary metrics
            metrics.append(f'sintra_measurement_total_results{{measurement_id="{measurement_id}"}} {len(results)}')
            metrics.append(f'sintra_measurement_total_probes{{measurement_id="{measurement_id}"}} {data.get("summary", {}).get("total_probes", 0)}')
            
            # Per-probe metrics
            for result in results:
                probe_id = result.get("probe_id")
                mtype = result.get("measurement_type")
                source = result.get("source_address", "unknown")
                target = result.get("target_address", "unknown")
                
                if mtype == "ping":
                    loss = result.get("packet_loss_percentage", 0)
                    latency_stats = result.get("latency_stats", {})
                    avg_latency = latency_stats.get("avg", 0)
                    min_latency = latency_stats.get("min", 0)
                    max_latency = latency_stats.get("max", 0)
                    median_latency = latency_stats.get("median", 0)
                    
                    # Key ping metrics with target info
                    metrics.append(f'sintra_ping_packet_loss_percent{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {loss}')
                    metrics.append(f'sintra_ping_latency_avg_ms{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {avg_latency}')
                    metrics.append(f'sintra_ping_latency_min_ms{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {min_latency}')
                    metrics.append(f'sintra_ping_latency_max_ms{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {max_latency}')
                    metrics.append(f'sintra_ping_latency_median_ms{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {median_latency}')
                    
                elif mtype == "traceroute":
                    hops = result.get("hops_count", 0)
                    metrics.append(f'sintra_traceroute_hops{{measurement_id="{measurement_id}",probe_id="{probe_id}",source="{source}",target="{target}"}} {hops}')
    
    except Exception as e:
        logging.error(f"Error processing measurement files: {e}")
        metrics.append(f'sintra_exporter_errors{{type="measurement_processing"}} 1')
    
    # Event metrics - simplified
    try:
        for event_file in EVENT_RESULTS_DIR.glob("*.json"):
            with open(event_file, "r") as f:
                data = json.load(f)
            
            measurement_id = data.get("measurement_id")
            events = data.get("events", [])
            
            # Event summary
            metrics.append(f'sintra_events_total{{measurement_id="{measurement_id}"}} {len(events)}')
            
            # Event types count
            event_types = {}
            for event in events:
                event_type = event.get("event", "unknown")
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            for event_type, count in event_types.items():
                metrics.append(f'sintra_events_by_type{{measurement_id="{measurement_id}",event_type="{event_type}"}} {count}')
    
    except Exception as e:
        logging.error(f"Error processing event files: {e}")
        metrics.append(f'sintra_exporter_errors{{type="event_processing"}} 1')
    
    # Add timestamp for monitoring freshness
    import time
    metrics.append(f'sintra_exporter_last_scrape_timestamp {int(time.time())}')
    
    return "\n".join(metrics) + "\n"

@app.route("/metrics")
def metrics():
    return Response(collect_metrics(), mimetype="text/plain")

@app.route("/health")
def health():
    return {"status": "healthy", "service": "sintra-prometheus-exporter"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
