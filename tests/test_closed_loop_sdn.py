"""
Unit and live-loopback integration tests for Sintra's closed-loop SDN control plane:
  - SintraEventManager.send_to_controller() hysteresis, cooldown, critical bypass, URL hygiene
  - AdaptivePathEngine weighted Dijkstra solver, policies (static / threshold / sintra), decay
  - NorthboundRESTServer live HTTP closed loop with SintraEventManager
  - Mininet probe_adapter ping parser, RIPE trace loader, and `sintra monitor` CLI
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

import sintra
from event_manager.eventmanager import SintraEventManager
from sdn_testbed.path_engine import AdaptivePathEngine, NorthboundRESTServer
from sdn_testbed.probe_adapter import build_sintra_measurement_payload, parse_ping_output
from sdn_testbed.topology import load_ripe_atlas_trace


@pytest.fixture
def em(tmp_path):
    return SintraEventManager(
        fetched_results_dir=str(tmp_path / "fetched"),
        event_results_dir=str(tmp_path / "events"),
        baseline_dir=str(tmp_path / "baseline"),
    )


def _sample_warning_event(target="10.0.0.2", anomaly="latency_spike", value=320.0):
    return {
        "timestamp": "2026-11-27T18:00:00Z",
        "anomaly": anomaly,
        "probe_id": "mininet_h1",
        "probe_country": "Emulated-AS1",
        "target": target,
        "metric": "ping_rtt_ms",
        "value": value,
        "threshold": 250.0,
        "units": "ms",
        "severity": "warning",
    }


def _sample_critical_outage(target="10.0.0.2"):
    return {
        "timestamp": "2026-11-27T18:00:00Z",
        "anomaly": "unreachable_host",
        "probe_id": "mininet_h1",
        "probe_country": "Emulated-AS1",
        "target": target,
        "metric": "reachability",
        "value": 0,
        "threshold": 1,
        "units": "reachable_flag",
        "severity": "critical",
    }


# === Test: SintraEventManager.send_to_controller() ===

class TestSendToController:
    @patch("event_manager.eventmanager.requests.post")
    def test_disabled_by_default_does_not_post(self, mock_post, em):
        res = em.send_to_controller("msm_1", [_sample_warning_event()])
        assert res["sent"] is False
        assert res["reason"] == "disabled"
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_non_loopback_http_blocked_unless_opt_in(self, mock_post, em):
        em.config["controller"] = {
            "enabled": True,
            "url": "http://192.0.2.10:8080/sintra/events",
            "allow_insecure_http": False,
        }
        res = em.send_to_controller("msm_2", [_sample_warning_event()])
        assert res["sent"] is False
        assert res["reason"] == "insecure_http_blocked"
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_hysteresis_requires_consecutive_anomalies(self, mock_post, em):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"rerouted": True})
        em.config["controller"] = {
            "enabled": True,
            "url": "http://127.0.0.1:8080/sintra/events",
            "min_consecutive_anomalies": 2,
            "cooldown_seconds": 0.0,
        }
        # Round 1: suppressed by hysteresis
        r1 = em.send_to_controller("msm_h1", [_sample_warning_event()])
        assert r1["sent"] is False
        assert r1["reason"] == "suppressed_by_damping"
        mock_post.assert_not_called()

        # Round 2: consecutive count reaches 2 -> dispatches
        r2 = em.send_to_controller("msm_h2", [_sample_warning_event()])
        assert r2["sent"] is True
        assert r2["action"] == "reroute"
        mock_post.assert_called_once()

    @patch("event_manager.eventmanager.requests.post")
    def test_clean_round_resets_hysteresis(self, mock_post, em):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"rerouted": True})
        em.config["controller"] = {
            "enabled": True,
            "url": "http://127.0.0.1:8080/sintra/events",
            "min_consecutive_anomalies": 2,
            "cooldown_seconds": 0.0,
        }
        em.send_to_controller("m1", [_sample_warning_event()])
        # Clean round resets consecutive count back to 0
        em.send_to_controller("m2", [])
        # Next single warning should again be suppressed (1/2)
        r3 = em.send_to_controller("m3", [_sample_warning_event()])
        assert r3["sent"] is False
        mock_post.assert_not_called()

    @patch("event_manager.eventmanager.requests.post")
    def test_cooldown_damps_warning_but_critical_outage_bypasses(self, mock_post, em):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"rerouted": True})
        em.config["controller"] = {
            "enabled": True,
            "url": "http://127.0.0.1:8080/sintra/events",
            "min_consecutive_anomalies": 1,
            "cooldown_seconds": 60.0,
        }
        r1 = em.send_to_controller("m1", [_sample_warning_event()])
        assert r1["sent"] is True

        # Immediate second warning is suppressed by 60s cooldown
        r2 = em.send_to_controller("m2", [_sample_warning_event()])
        assert r2["sent"] is False
        assert r2["reason"] == "suppressed_by_damping"

        # Critical unreachable_host bypasses cooldown immediately
        r3 = em.send_to_controller("m3", [_sample_critical_outage()])
        assert r3["sent"] is True
        assert mock_post.call_count == 2

    @patch("event_manager.eventmanager.requests.post")
    def test_loads_events_from_disk_when_omitted(self, mock_post, em):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"rerouted": True})
        em.config["controller"] = {
            "enabled": True,
            "url": "http://127.0.0.1:8080/sintra/events",
            "cooldown_seconds": 0.0,
        }
        em.save_events("disk_42", [_sample_warning_event()])
        res = em.send_to_controller("disk_42")
        assert res["sent"] is True
        mock_post.assert_called_once()


# === Test: AdaptivePathEngine ===

class TestAdaptivePathEngine:
    def test_default_shortest_path_is_path_a(self):
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0)
        assert engine.active_path == [1, 2, 5]
        # Verify deterministic port mapping for all 3 paths
        assert engine.get_path_ports([1, 2, 5]) == [(1, 1, 2), (2, 1, 2), (5, 2, 1)]
        assert engine.get_path_ports([1, 3, 5]) == [(1, 1, 3), (3, 1, 2), (5, 3, 1)]
        assert engine.get_path_ports([1, 4, 6, 5]) == [(1, 1, 4), (4, 1, 2), (6, 1, 2), (5, 4, 1)]

    def test_sintra_policy_cascades_path_a_to_b_to_c(self):
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0)
        d1 = engine.handle_sintra_event({"anomalies": [{"type": "latency_spike", "value": 300.0}]})
        assert d1["rerouted"] is True
        assert d1["active_path"] == [1, 3, 5]

        d2 = engine.handle_sintra_event({"anomalies": [{"type": "packet_loss", "value": 20.0}]})
        assert d2["rerouted"] is True
        assert d2["active_path"] == [1, 4, 6, 5]
        assert engine.switchover_count == 2

    def test_static_policy_never_reroutes(self):
        engine = AdaptivePathEngine(policy="static", cooldown_seconds=0.0)
        d = engine.handle_sintra_event({"anomalies": [{"type": "unreachable_host", "severity": "critical"}]})
        assert d["rerouted"] is False
        assert engine.active_path == [1, 2, 5]

    def test_threshold_policy_ignores_jitter_and_moderate_spike(self):
        engine = AdaptivePathEngine(policy="threshold", cooldown_seconds=0.0)
        # Jitter spike ignored by threshold-only policy
        d_jit = engine.handle_sintra_event({"anomalies": [{"type": "jitter_spike", "value": 45.0}]})
        assert d_jit["rerouted"] is False
        assert engine.active_path == [1, 2, 5]

        # Moderate latency spike (180ms <= 250ms) ignored by threshold-only policy
        d_mod = engine.handle_sintra_event({"anomalies": [{"type": "latency_spike", "value": 180.0}]})
        assert d_mod["rerouted"] is False

        # >250ms static spike triggers threshold-only reroute
        d_hi = engine.handle_sintra_event({"anomalies": [{"type": "latency_spike", "value": 290.0}]})
        assert d_hi["rerouted"] is True
        assert d_hi["active_path"] == [1, 3, 5]

    def test_sintra_policy_reacts_to_jitter_spike(self):
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0)
        d = engine.handle_sintra_event({"anomalies": [{"type": "jitter_spike", "value": 45.0}]})
        assert d["rerouted"] is True
        assert d["active_path"] == [1, 3, 5]

    def test_penalty_exponential_decay_allows_eventual_recovery(self):
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0, penalty_decay_half_life_s=1.0)
        engine.handle_sintra_event({"anomalies": [{"type": "latency_spike", "value": 260.0}]})
        assert engine.active_path == [1, 3, 5]
        # Evaluate path cost far in the future after penalty decays to ~0
        future = time.monotonic() + 30.0
        assert engine.compute_best_path(now=future) == [1, 2, 5]


# === Test: Live Local HTTP Closed Loop ===

class TestLiveClosedLoopREST:
    def test_end_to_end_event_manager_to_rest_controller(self, em):
        reroute_calls = []
        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0)

        def _fake_of_install(old_path, new_path, decision):
            reroute_calls.append((old_path, new_path))
            return 1.25

        server = NorthboundRESTServer(engine=engine, host="127.0.0.1", port=0, on_reroute=_fake_of_install)
        host, port = server.start()
        base_url = f"http://{host}:{port}"

        try:
            em.config["controller"] = {
                "enabled": True,
                "url": f"{base_url}/sintra/events",
                "cooldown_seconds": 0.0,
                "min_consecutive_anomalies": 1,
            }

            # Feed a degraded ping sample through SintraEventManager -> real HTTP POST -> controller
            ping_metrics = {
                "rtts": [280.0, 290.0, 310.0],
                "avg": 293.33,
                "min": 280.0,
                "max": 310.0,
                "median": 290.0,
                "p95": 308.0,
                "p99": 309.6,
                "jitter_ms": 15.28,
                "packets_sent": 3,
                "packets_received": 3,
                "packet_loss_percentage": 0.0,
            }
            payload = build_sintra_measurement_payload("live_loop_1", "h1", "10.0.0.2", ping_metrics)
            events = em.analyze_measurement(payload)
            assert any(e["anomaly"] == "latency_spike" for e in events)

            dispatch = em.send_to_controller("live_loop_1", events)
            assert dispatch["sent"] is True
            assert dispatch["response"]["rerouted"] is True
            assert dispatch["response"]["active_path"] == [1, 3, 5]
            assert dispatch["response"]["rule_install_time_ms"] == 1.25
            assert reroute_calls == [([1, 2, 5], [1, 3, 5])]

            # Verify GET /sintra/status and POST /sintra/reset
            status = requests.get(f"{base_url}/sintra/status", timeout=5).json()
            assert status["active_path"] == [1, 3, 5]
            assert status["switchover_count"] == 1

            reset_status = requests.post(f"{base_url}/sintra/reset", json={"policy": "threshold"}, timeout=5).json()
            assert reset_status["active_path"] == [1, 2, 5]
            assert reset_status["policy"] == "threshold"
            assert reset_status["switchover_count"] == 0
        finally:
            server.stop()


# === Test: Ping Parser, RIPE Trace Loader, and `sintra monitor` CLI ===

class TestProbeAdapterAndMonitorCLI:
    def test_parse_ping_output_healthy_and_loss(self):
        sample = """
PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=20.1 ms
64 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=21.5 ms
64 bytes from 10.0.0.2: icmp_seq=4 ttl=64 time=19.9 ms

--- 10.0.0.2 ping statistics ---
4 packets transmitted, 3 received, 25% packet loss, time 602ms
"""
        parsed = parse_ping_output(sample, requested_count=4)
        assert parsed["packets_sent"] == 4
        assert parsed["packets_received"] == 3
        assert parsed["packet_loss_percentage"] == 25.0
        assert abs(parsed["avg"] - 20.5) < 0.01
        assert parsed["p95"] is not None

    def test_parse_ping_output_total_outage(self):
        sample = """
PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.

--- 10.0.0.2 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4050ms
"""
        parsed = parse_ping_output(sample, requested_count=5)
        assert parsed["avg"] is None
        assert parsed["packet_loss_percentage"] == 100.0

    def test_load_ripe_atlas_trace(self, tmp_path):
        trace_file = tmp_path / "measurement_123_result.json"
        trace_file.write_text(json.dumps({
            "measurement_id": 123,
            "results": [{
                "measurement_type": "ping",
                "samples": [
                    {"timestamp": 1000, "avg_rtt": 140.5, "packet_loss_percentage": 0.0},
                    {"timestamp": 1300, "avg_rtt": 310.2, "packet_loss_percentage": 10.0},
                ],
            }],
        }), encoding="utf-8")
        trace = load_ripe_atlas_trace(str(trace_file))
        assert len(trace) == 2
        assert trace[1]["rtt_ms"] == 310.2
        assert trace[1]["loss_pct"] == 10.0

    def test_sintra_monitor_cli_single_iteration_with_controller(self, tmp_path):
        fetched_dir = tmp_path / "fetched"
        fetched_dir.mkdir()
        ping_metrics = {
            "rtts": [350.0, 360.0, 355.0],
            "avg": 355.0,
            "min": 350.0,
            "max": 360.0,
            "median": 355.0,
            "p95": 359.5,
            "p99": 359.9,
            "jitter_ms": 5.0,
            "packets_sent": 3,
            "packets_received": 3,
            "packet_loss_percentage": 0.0,
        }
        payload = build_sintra_measurement_payload("mon_1", "h1", "10.0.0.2", ping_metrics)
        (fetched_dir / "measurement_mon_1_result.json").write_text(json.dumps(payload), encoding="utf-8")

        engine = AdaptivePathEngine(policy="sintra", cooldown_seconds=0.0)
        server = NorthboundRESTServer(engine=engine, host="127.0.0.1", port=0)
        host, port = server.start()
        try:
            parser = sintra.create_parser()
            args = parser.parse_args([
                "monitor",
                "--results-dir", str(fetched_dir),
                "--interval", "0.05",
                "--iterations", "1",
                "--controller-url", f"http://{host}:{port}/sintra/events",
            ])
            sintra.handle_monitor_command(args)
            status = requests.get(f"http://{host}:{port}/sintra/status", timeout=5).json()
            assert status["active_path"] == [1, 3, 5]
            assert status["switchover_count"] == 1
        finally:
            server.stop()
