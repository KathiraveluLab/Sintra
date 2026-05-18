"""
Unit tests for Sintra anomaly detection logic.

Tests the core detection methods in SintraEventManager with synthetic
measurement data to verify correct anomaly identification.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
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
        rtts = [] if avg_rtt is None else [avg_rtt] * 3  # 3 identical RTTs by default
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
            make_ping_result("probe_1", "8.8.8.8", None, packet_loss=100.0, rtts=[])
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "unreachable_host" in anomaly_types


# === Test: Jitter Spike Detection ===

class TestJitterSpikeDetection:
    def test_high_jitter_triggers_spike(self, event_manager):
        """RTTs with high variance should trigger jitter_spike but not latency_spike."""
        # RTTs: [10, 100, 10, 100, 10] -> stdev ~= 44ms > 15ms threshold
        # avg=46ms is well below latency_spike threshold of 250ms
        data = make_measurement_data("test_5", [
            make_ping_result("probe_1", "8.8.8.8", 46.0, rtts=[10, 100, 10, 100, 10])
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "jitter_spike" in anomaly_types
        assert "latency_spike" not in anomaly_types

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


# === Test: Correlated Routing Event ===

class TestCorrelatedRoutingEvent:
    def test_correlation_detects_spike_plus_route_change(self, event_manager):
        """When latency_spike and route_change occur on same probe+target, 
        a correlated_routing_event should be added."""
        # Simulate events that would be produced by detection
        fake_events = [
            {"anomaly": "latency_spike", "probe_id": "probe_1", "target": "8.8.8.8"},
            {"anomaly": "route_change", "probe_id": "probe_1", "target": "8.8.8.8"}
        ]
        correlated = event_manager._correlate_events(fake_events, "2026-01-01T00:00:00Z")
        anomaly_types = [e["anomaly"] for e in correlated]
        assert "correlated_routing_event" in anomaly_types
        correlated_event = next(
            e for e in correlated if e["anomaly"] == "correlated_routing_event"
        )
        assert correlated_event["description"] == (
            "Latency spike likely caused by route change detected on the same probe"
        )

    def test_no_correlation_without_both_types(self, event_manager):
        """If only latency_spike exists (no route_change), no correlation should be made."""
        fake_events = [
            {"anomaly": "latency_spike", "probe_id": "probe_1", "target": "8.8.8.8"},
            {"anomaly": "packet_loss", "probe_id": "probe_1", "target": "8.8.8.8"}
        ]
        correlated = event_manager._correlate_events(fake_events, "2026-01-01T00:00:00Z")
        assert len(correlated) == 0


# === Test: Per-Target Thresholds ===

class TestPerTargetThresholds:
    def test_custom_threshold_triggers_spike(self, event_manager):
        """A target with a lower custom threshold should trigger at lower latency."""
        # Set a custom threshold for this target
        event_manager.config["target_thresholds"] = {
            "10.0.0.1": {"latency_spike_ms": 100.0}
        }
        # 150ms is under global 250ms but above custom 100ms
        data = make_measurement_data("test_threshold", [
            make_ping_result("probe_1", "10.0.0.1", 150.0)
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "latency_spike" in anomaly_types

    def test_global_threshold_used_when_no_custom(self, event_manager):
        """A target without a custom threshold should use the global 250ms default."""
        event_manager.config["target_thresholds"] = {}
        # 200ms is under global 250ms — should NOT trigger
        data = make_measurement_data("test_global", [
            make_ping_result("probe_1", "10.0.0.1", 200.0)
        ])
        events = event_manager.analyze_measurement(data)
        anomaly_types = [e["anomaly"] for e in events]
        assert "latency_spike" not in anomaly_types


# === Test: Rolling Baseline ===

class TestRollingBaseline:
    def test_baseline_requires_minimum_samples(self, event_manager):
        """Baseline should return None until enough samples are stored.
        
        The baseline is computed from values stored *before* the current call,
        so it takes min_samples+1 calls before a baseline is returned.
        """
        # Calls 1-3: build up the stored samples (baseline reads before appending)
        for rtt in [100.0, 110.0, 120.0]:
            baseline = event_manager._get_and_update_baseline_rtt("p1", "8.8.8.8", rtt)
            assert baseline is None  # Not enough stored yet at read time

        # Call 4: now 3 samples are stored, baseline should be available
        baseline = event_manager._get_and_update_baseline_rtt("p1", "8.8.8.8", 130.0)
        assert baseline is not None
        assert abs(baseline - 110.0) < 1.0  # avg of [100, 110, 120] = 110

    def test_baseline_none_target_returns_none(self, event_manager):
        """If target_addr is None, baseline should return None without crashing."""
        baseline = event_manager._get_and_update_baseline_rtt("p1", None, 100.0)
        assert baseline is None


# === Test: Webhook Alert ===

class TestWebhookAlert:
    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_disabled_does_not_send(self, mock_post, event_manager):
        """When webhook is disabled, no HTTP request should be made."""
        event_manager.config["webhook"] = {"enabled": False, "url": "", "timeout_seconds": 10}
        event_manager.send_webhook_alert("test", [{"severity": "critical", "anomaly": "test"}])
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_sends_on_critical_events(self, mock_post, event_manager):
        """When webhook is enabled with critical events, POST should be called."""
        mock_post.return_value = MagicMock(status_code=200)
        event_manager.config["webhook"] = {
            "enabled": True,
            "url": "https://example.com/hook",
            "timeout_seconds": 5
        }
        events = [{"severity": "critical", "anomaly": "latency_spike",
                    "probe_id": "1", "target": "8.8.8.8"}]
        event_manager.send_webhook_alert("test_msm", events)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["total_anomalies"] == 1

    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_rejects_invalid_scheme(self, mock_post, event_manager):
        """Webhook with ftp:// or other invalid schemes should be rejected."""
        event_manager.config["webhook"] = {
            "enabled": True,
            "url": "ftp://example.com/hook",
            "timeout_seconds": 5
        }
        event_manager.send_webhook_alert("test", [{"severity": "critical", "anomaly": "test"}])
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_blocks_http_by_default(self, mock_post, event_manager):
        """Plain HTTP should be blocked unless allow_insecure_http is set."""
        event_manager.config["webhook"] = {
            "enabled": True,
            "url": "http://example.com/hook",
            "timeout_seconds": 5
        }
        event_manager.send_webhook_alert("test", [{"severity": "critical", "anomaly": "test"}])
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_allows_http_with_opt_in(self, mock_post, event_manager):
        """Plain HTTP should be allowed when allow_insecure_http is true."""
        mock_post.return_value = MagicMock(status_code=200)
        event_manager.config["webhook"] = {
            "enabled": True,
            "url": "http://example.com/hook",
            "timeout_seconds": 5,
            "allow_insecure_http": True
        }
        event_manager.send_webhook_alert("test", [{"severity": "critical", "anomaly": "test"}])
        mock_post.assert_called_once()

    @patch("event_manager.eventmanager.requests.post")
    def test_webhook_logs_non_2xx_response(self, mock_post, event_manager):
        """Webhook returning non-2xx should not raise but should log warning."""
        mock_post.return_value = MagicMock(status_code=500, text="Internal Server Error")
        event_manager.config["webhook"] = {
            "enabled": True,
            "url": "https://example.com/hook",
            "timeout_seconds": 5
        }
        # Should not raise
        event_manager.send_webhook_alert("test", [{"severity": "critical", "anomaly": "test"}])
        mock_post.assert_called_once()


# === Test: Outlier with None Values ===

class TestOutlierWithNone:
    def test_outlier_detection_with_none_latencies(self, event_manager):
        """Outlier detection should handle None values in latency lists gracefully."""
        data = make_measurement_data("test_none", [
            make_ping_result("probe_1", "8.8.8.8", None, packet_loss=100.0, rtts=[]),
            make_ping_result("probe_2", "8.8.8.8", 30.0),
            make_ping_result("probe_3", "8.8.8.8", 35.0),
            make_ping_result("probe_4", "8.8.8.8", 200.0),
        ])
        # Should not raise despite None in latencies
        events = event_manager.analyze_measurement(data)
        assert isinstance(events, list)


# === Test: Path Flapping Detection ===

class TestPathFlapping:
    def test_path_flapping_detected(self, event_manager):
        """Frequent route changes should trigger path_flapping.
        
        Path flapping triggers when route_history length exceeds
        path_flapping_window (default=3), so 4 runs are needed.
        """
        target = "8.8.8.8"
        
        # Run 4 analyses with alternating routes to trigger flapping
        routes = [
            ["1.1.1.1", "2.2.2.2", "8.8.8.8"],
            ["1.1.1.1", "3.3.3.3", "8.8.8.8"],
            ["1.1.1.1", "2.2.2.2", "8.8.8.8"],
            ["1.1.1.1", "3.3.3.3", "8.8.8.8"],
        ]
        
        events = []
        for route in routes:
            data = make_measurement_data("test_flap", [
                make_traceroute_result("probe_1", target, route)
            ])
            events = event_manager.analyze_measurement(data)
        
        anomaly_types = [e["anomaly"] for e in events]
        assert "path_flapping" in anomaly_types


# === Test: Full Pipeline Correlation ===

class TestFullPipelineCorrelation:
    def test_correlation_through_analyze_measurement(self, event_manager):
        """Full pipeline test: high latency + route change for same probe should
        produce a correlated_routing_event via analyze_measurement."""
        target = "8.8.8.8"
        
        # First run: establish baseline route
        data1 = make_measurement_data("test_corr", [
            make_ping_result("probe_1", target, 30.0),
            make_traceroute_result("probe_1", target, ["1.1.1.1", "2.2.2.2", "8.8.8.8"])
        ])
        event_manager.analyze_measurement(data1)
        
        # Second run: high latency + changed route
        data2 = make_measurement_data("test_corr", [
            make_ping_result("probe_1", target, 500.0),
            make_traceroute_result("probe_1", target, ["1.1.1.1", "3.3.3.3", "8.8.8.8"])
        ])
        events = event_manager.analyze_measurement(data2)
        anomaly_types = [e["anomaly"] for e in events]
        
        assert "latency_spike" in anomaly_types
        assert "route_change" in anomaly_types
        assert "correlated_routing_event" in anomaly_types
