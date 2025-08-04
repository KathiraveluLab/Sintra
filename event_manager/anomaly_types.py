ANOMALY_TYPES = {
    "latency_spike": {
        "description": "RTT (Round Trip Time) exceeds a threshold (e.g., > 250 ms) or spikes suddenly",
        "measurement_type": "ping",
        "latency_related": True
    },
    "packet_loss": {
        "description": "% of lost packets > threshold (e.g., 5–10%)",
        "measurement_type": "ping",
        "latency_related": False
    },
    "unreachable_host": {
        "description": "100% packet loss, host not reachable, no ping replies",
        "measurement_type": "ping, traceroute",
        "latency_related": False
    },
    "route_change": {
        "description": "Traceroute path is different than baseline path (hop IPs or count changed)",
        "measurement_type": "traceroute",
        "latency_related": False
    },
    "path_flapping": {
        "description": "Route changes frequently (e.g., unstable topology)",
        "measurement_type": "traceroute",
        "latency_related": False
    },
    "geo_anomaly": {
        "description": "Far probe suddenly has better latency than near one (suspicious routing)",
        "measurement_type": "ping",
        "latency_related": True
    },
    "jitter_spike": {
        "description": "High variation in RTTs (instability, not necessarily high latency)",
        "measurement_type": "ping",
        "latency_related": True
    },
    "outlier_probe_latency": {
        "description": "Only some probes report high delay (not the majority)",
        "measurement_type": "ping",
        "latency_related": True
    },
    "outlier_probe_loss": {
        "description": "Only some probes report high loss (not the majority)",
        "measurement_type": "ping",
        "latency_related": False
    }
}
