import os
import json
from pathlib import Path
from measurement_client.logger import logger

class SintraEventManager:
    def __init__(self, fetched_results_dir="measurement_client/results/fetched_measurements", event_results_dir="event_manager/results"):
        self.fetched_results_dir = Path(fetched_results_dir)
        self.event_results_dir = Path(event_results_dir)
        self.event_results_dir.mkdir(parents=True, exist_ok=True)

    def analyze_all(self):
        # Analyze all fetched measurement results
        for result_file in self.fetched_results_dir.glob("measurement_*_result.json"):
            try:
                with open(result_file, "r") as f:
                    data = json.load(f)
                measurement_id = data.get("measurement_id")
                events = self.analyze_measurement(data)
                self.save_events(measurement_id, events)
                if events:
                    logger.info(f"Events for measurement {measurement_id} saved.")
                else:
                    logger.info(f"No anomalies found for measurement {measurement_id}.")
            except Exception as e:
                logger.error(f"Failed to analyze {result_file}: {e}")

    def analyze_measurement(self, data):
        # Analyze a single measurement's results and return detected events
        events = []
        for result in data.get("results", []):
            probe_id = result.get("probe_id")
            mtype = result.get("measurement_type")
            # Example event: high packet loss
            if mtype == "ping":
                loss = result.get("packet_loss_percentage")
                latency = result.get("latency_stats", {}).get("avg")
                if loss is not None and loss > 50:
                    events.append({
                        "probe_id": probe_id,
                        "event": "High packet loss",
                        "value": loss,
                        "threshold": 50
                    })
                if latency is not None and latency > 200:
                    events.append({
                        "probe_id": probe_id,
                        "event": "High latency",
                        "value": latency,
                        "threshold": 200
                    })
            elif mtype == "traceroute":
                hops = result.get("hops_count")
                if hops is not None and hops > 20:
                    events.append({
                        "probe_id": probe_id,
                        "event": "Excessive hops",
                        "value": hops,
                        "threshold": 20
                    })
        return events

    def save_events(self, measurement_id, events):
        # Save detected events to event_manager/results/<measurement_id>.json
        out_file = self.event_results_dir / f"{measurement_id}.json"
        with open(out_file, "w") as f:
            json.dump({"measurement_id": measurement_id, "events": events}, f, indent=2)

    def send_to_controller(self, measurement_id):
        # Stub for sending events to POX controller (to be implemented later)
        logger.info(f"Sending events for measurement {measurement_id} to POX controller (stub).")

