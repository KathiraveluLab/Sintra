"""
Probe adapter translating active Mininet ping/traceroute telemetry into
the canonical Sintra `measurement_*_result.json` schema.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Dict, List, Optional

from event_manager.anomaly_utils import calculate_jitter, calculate_percentile


_RTT_RE = re.compile(r"time[=<]\s*([0-9]+(?:\.[0-9]+)?)\s*ms", re.IGNORECASE)
_SUMMARY_RE = re.compile(
    r"(\d+)\s+packets\s+transmitted,\s+(\d+)\s+(?:packets\s+)?received.*?([0-9]+(?:\.[0-9]+)?)%\s+packet\s+loss",
    re.IGNORECASE,
)


def parse_ping_output(stdout: str, requested_count: int = 5) -> Dict[str, Any]:
    """Parse Linux iputils-ping output into Sintra latency and loss metrics."""
    rtts = [float(m.group(1)) for m in _RTT_RE.finditer(stdout or "")]
    summary_match = _SUMMARY_RE.search(stdout or "")

    if summary_match:
        packets_sent = int(summary_match.group(1))
        packets_received = int(summary_match.group(2))
        packet_loss_pct = float(summary_match.group(3))
    else:
        packets_sent = max(requested_count, len(rtts))
        packets_received = len(rtts)
        packet_loss_pct = (
            ((packets_sent - packets_received) / packets_sent) * 100.0
            if packets_sent > 0
            else 100.0
        )

    return {
        "rtts": rtts,
        "avg": mean(rtts) if rtts else None,
        "min": min(rtts) if rtts else None,
        "max": max(rtts) if rtts else None,
        "median": median(rtts) if rtts else None,
        "p95": calculate_percentile(rtts, 95) if rtts else None,
        "p99": calculate_percentile(rtts, 99) if rtts else None,
        "jitter_ms": calculate_jitter(rtts),
        "packets_sent": packets_sent,
        "packets_received": packets_received,
        "packet_loss_percentage": round(packet_loss_pct, 2),
    }


def build_sintra_measurement_payload(
    measurement_id: str,
    probe_id: str,
    target_ip: str,
    ping_metrics: Dict[str, Any],
    source_ip: str = "10.0.0.1",
    probe_country: str = "Emulated-AS1",
    timestamp_epoch: Optional[float] = None,
) -> Dict[str, Any]:
    """Wrap parsed ping metrics in Sintra's canonical fetched-measurement JSON schema."""
    ts = time.time() if timestamp_epoch is None else timestamp_epoch
    ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "measurement_id": str(measurement_id),
        "measurement_type": "ping",
        "target": target_ip,
        "fetched_at": ts_iso,
        "results": [
            {
                "measurement_type": "ping",
                "measurement_id": str(measurement_id),
                "probe_id": str(probe_id),
                "probe_country": probe_country,
                "source_address": source_ip,
                "target_address": target_ip,
                "timestamp": ts_iso,
                "latency_stats": {
                    "rtts": ping_metrics["rtts"],
                    "avg": ping_metrics["avg"],
                    "min": ping_metrics["min"],
                    "max": ping_metrics["max"],
                    "median": ping_metrics["median"],
                    "p95": ping_metrics["p95"],
                    "p99": ping_metrics["p99"],
                },
                "samples": [
                    {
                        "timestamp": ts,
                        "avg_rtt": ping_metrics["avg"],
                        "min_rtt": ping_metrics["min"],
                        "max_rtt": ping_metrics["max"],
                        "packet_loss_percentage": ping_metrics["packet_loss_percentage"],
                    }
                ],
                "packet_loss_percentage": ping_metrics["packet_loss_percentage"],
                "packets_sent": ping_metrics["packets_sent"],
                "packets_received": ping_metrics["packets_received"],
            }
        ],
    }


def run_mininet_ping(
    host: Any,
    target_ip: str = "10.0.0.2",
    count: int = 5,
    interval_s: float = 0.2,
    timeout_s: int = 2,
) -> Dict[str, Any]:
    """Execute an active ICMP ping probe inside a Mininet host and return parsed metrics."""
    cmd = f"ping -c {count} -i {interval_s} -W {timeout_s} {target_ip}"
    stdout = host.cmd(cmd)
    return parse_ping_output(stdout, requested_count=count)
