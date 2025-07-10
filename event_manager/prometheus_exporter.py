from flask import Flask, Response
import json
from pathlib import Path

app = Flask(__name__)

FETCHED_RESULTS_DIR = Path("measurement_client/results/fetched_measurements")
EVENT_RESULTS_DIR = Path("event_manager/results")

def collect_metrics():
    metrics = []
    # Measurement metrics
    for result_file in FETCHED_RESULTS_DIR.glob("measurement_*_result.json"):
        with open(result_file, "r") as f:
            data = json.load(f)
        measurement_id = data.get("measurement_id")
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            mtype = result.get("measurement_type")
            if mtype == "ping":
                loss = result.get("packet_loss_percentage") or 0
                latency = (result.get("latency_stats") or {}).get("avg") or 0
                metrics.append(f'sintra_ping_packet_loss{{measurement_id="{measurement_id}",probe_id="{probe_id}"}} {loss}')
                metrics.append(f'sintra_ping_latency_avg{{measurement_id="{measurement_id}",probe_id="{probe_id}"}} {latency}')
            elif mtype == "traceroute":
                hops = result.get("hops_count") or 0
                metrics.append(f'sintra_traceroute_hops{{measurement_id="{measurement_id}",probe_id="{probe_id}"}} {hops}')
    # Event metrics with zigzag transformation
    for event_file in EVENT_RESULTS_DIR.glob("*.json"):
        with open(event_file, "r") as f:
            data = json.load(f)
        measurement_id = data.get("measurement_id")
        events = data.get("events", [])
        probe_zigzag = {}
        for event in events:
            probe_id = event.get("probe_id")
            value = event.get("value", 0)
            # Zigzag: alternate sign for each event per probe
            count = probe_zigzag.get(probe_id, 0)
            zigzag_value = value if count % 2 == 0 else -value
            probe_zigzag[probe_id] = count + 1
            metrics.append(
                f'sintra_event_zigzag{{measurement_id="{measurement_id}",probe_id="{probe_id}",event="{event.get("event")}"}} {zigzag_value}'
            )
        metrics.append(f'sintra_events_total{{measurement_id="{measurement_id}"}} {len(events)}')
    # Event anomaly metrics (for visualization)
    for event_file in EVENT_RESULTS_DIR.glob("*.json"):
        with open(event_file, "r") as f:
            data = json.load(f)
        measurement_id = data.get("measurement_id")
        events = data.get("events", [])
        for idx, event in enumerate(events):
            probe_id = event.get("probe_id")
            event_type = event.get("event")
            value = event.get("value", 0)
            # Each anomaly is exported as a metric with labels for filtering in Grafana
            metrics.append(
                f'sintra_anomaly_event{{measurement_id="{measurement_id}",probe_id="{probe_id}",event="{event_type}",index="{idx}"}} {value}'
            )
        metrics.append(f'sintra_events_total{{measurement_id="{measurement_id}"}} {len(events)}')
    return "\n".join(metrics) + "\n"

@app.route("/metrics")
def metrics():
    return Response(collect_metrics(), mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
