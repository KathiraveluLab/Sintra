"""
Unit tests for Sintra anomaly detection logic.

Tests the core detection methods in SintraEventManager with synthetic
measurement data to verify correct anomaly identification.
"""
import pytest
from pathlib import Path
from event_manager.eventmanager import SintraEventManager


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temporary directories for test isolation."""
    fetched_dir = tmp_path / "fetched"
    events_dir = tmp_path / "events"
    baseline_dir = tmp_path / "baseline"
    fetched_dir.mkdir()
    events_dir.mkdir()
    baseline_dir.mkdir()
    return fetched_dir, events_dir, baseline_dir


@pytest.fixture
def event_manager(temp_dirs):
    """Create an EventManager with temporary directories."""
    fetched_dir, events_dir, baseline_dir = temp_dirs
    return SintraEventManager(
        fetched_results_dir=str(fetched_dir),
        event_results_dir=str(events_dir),
        baseline_dir=str(baseline_dir)
    )


def make_ping_result(probe_id, target, avg_rtt, packet_loss=0.0, rtts=None):
    """Helper to create a synthetic ping measurement result."""
    if rtts is None:
        rtts = [avg_rtt] * 3  # 3 identical RTTs by default
    return {
        "probe_id": probe_id,
        "measurement_type": "ping",
        "target_address": target,
        "latency_stats": {
            "avg": avg_rtt if rtts else None,
            "min": min(rtts) if rtts else None,
            "max": max(rtts) if rtts else None,
            "rtts": rtts
        },
        "packet_loss_percentage": packet_loss,
        "packets_sent": max(len(rtts), 3),  # at least 3 packets sent
        "packets_received": len(rtts)
    }


def make_traceroute_result(probe_id, target, hop_ips):
    """Helper to create a synthetic traceroute measurement result."""
    return {
        "probe_id": probe_id,
        "measurement_type": "traceroute",
        "target_address": target,
        "hops": [{"ip": ip} for ip in hop_ips],
        "hops_count": len(hop_ips)
    }


def make_measurement_data(measurement_id, results):
    """Wrap results into a measurement data structure."""
    return {
        "measurement_id": measurement_id,
        "results": results
    }


# === Test: Latency Spike Detection ===

class TestLatencySpikeDetection:
    def test_high_latency_triggers_spike(self, event_manager):
        """500ms latency should trigger a latency_spike (threshold=250ms)."""
        data = make_measurement_data("test_1", [
            make_ping_result("probe_1", "8.8.8.8", 500.0)
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "latency_spike" in anomaly_types

    def test_normal_latency_no_spike(self, event_manager):
        """50ms latency should NOT trigger a latency_spike."""
        data = make_measurement_data("test_2", [
            make_ping_result("probe_1", "8.8.8.8", 50.0)
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "latency_spike" not in anomaly_types


# === Test: Packet Loss Detection ===

class TestPacketLossDetection:
    def test_high_packet_loss_triggers_alert(self, event_manager):
        """25% packet loss should trigger a packet_loss event (threshold=10%)."""
        data = make_measurement_data("test_3", [
            make_ping_result("probe_1", "8.8.8.8", 100.0, packet_loss=25.0)
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "packet_loss" in anomaly_types

    def test_unreachable_host_on_total_loss(self, event_manager):
        """100% packet loss should trigger unreachable_host."""
        data = make_measurement_data("test_4", [
            make_ping_result("probe_1", "8.8.8.8", 0, packet_loss=100.0, rtts=[])
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "unreachable_host" in anomaly_types


# === Test: Jitter Spike Detection ===

class TestJitterSpikeDetection:
    def test_high_jitter_triggers_spike(self, event_manager):
        """RTTs with high variance should trigger jitter_spike."""
        # RTTs: [10, 100, 10, 100, 10] → stdev ≈ 44ms > 15ms threshold
        data = make_measurement_data("test_5", [
            make_ping_result("probe_1", "8.8.8.8", 46.0, rtts=[10, 100, 10, 100, 10])
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "jitter_spike" in anomaly_types

    def test_stable_rtts_no_jitter(self, event_manager):
        """Stable RTTs should NOT trigger jitter_spike."""
        data = make_measurement_data("test_6", [
            make_ping_result("probe_1", "8.8.8.8", 50.0, rtts=[49, 50, 51, 50, 49])
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "jitter_spike" not in anomaly_types


# === Test: Route Change Detection ===

class TestRouteChangeDetection:
    def test_route_change_detected(self, event_manager):
        """Changed traceroute hops should trigger route_change on second run."""
        target = "8.8.8.8"
        
        # First run: establish baseline
        data1 = make_measurement_data("test_7", [
            make_traceroute_result("probe_1", target, ["1.1.1.1", "2.2.2.2", "8.8.8.8"])
        ])
        event_manager.analyze_measurement(data1)
        
        # Second run: different route
        data2 = make_measurement_data("test_7", [
            make_traceroute_result("probe_1", target, ["1.1.1.1", "3.3.3.3", "8.8.8.8"])
        ])
        events = event_manager.analyze_measurement(data2)
        anomaly_types = [e["anomaly"] for e in events]
        assert "route_change" in anomaly_types


# === Test: No False Positives ===

class TestNoFalsePositives:
    def test_normal_data_no_anomalies(self, event_manager):
        """Normal, healthy measurement data should produce zero anomalies."""
        data = make_measurement_data("test_8", [
            make_ping_result("probe_1", "8.8.8.8", 30.0, packet_loss=0.0, rtts=[28, 30, 32]),
            make_ping_result("probe_2", "8.8.8.8", 35.0, packet_loss=0.0, rtts=[33, 35, 37]),
            make_ping_result("probe_3", "8.8.8.8", 25.0, packet_loss=0.0, rtts=[23, 25, 27]),
        ])
        events = event_manager.analyze_measurement(data)
        assert len(events) == 0


# === Test: Outlier Detection ===

class TestOutlierDetection:
    def test_outlier_probe_detected(self, event_manager):
        """One probe with much higher latency than others should be flagged as outlier."""
        data = make_measurement_data("test_9", [
            make_ping_result("probe_1", "8.8.8.8", 30.0),
            make_ping_result("probe_2", "8.8.8.8", 35.0),
            make_ping_result("probe_3", "8.8.8.8", 25.0),
            make_ping_result("probe_4", "8.8.8.8", 200.0),  # outlier: >2x average
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "outlier_probe_latency" in anomaly_types
        
        # Verify it's probe_4 that's flagged
        outlier_events = [e for e in events if e["anomaly"] == "outlier_probe_latency"]
        assert any(e["probe_id"] == "probe_4" for e in outlier_events)


# === Test: Probe ID Type Consistency (Bug #3) ===

class TestProbeIdConsistency:
    def test_integer_probe_ids_handled(self, event_manager):
        """Probe IDs as integers should work the same as strings."""
        data = make_measurement_data("test_10", [
            make_ping_result(12345, "8.8.8.8", 500.0)  # integer probe_id
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "latency_spike" in anomaly_types
        # Verify probe_id is normalized to string on the specific event
        latency_spike_event = next(e for e in events if e["anomaly"] == "latency_spike")
        assert latency_spike_event["probe_id"] == "12345"
