"""
Adaptive multi-path SDN routing engine and northbound REST server for Sintra.

This module is pure Python (no POX or Mininet runtime dependency) so the
composite path-cost model, Dijkstra solver, policy behaviors (static,
threshold, sintra), penalty decay, cooldown hysteresis, and HTTP northbound
interface can be unit-tested on any OS and wrapped directly by POX on Linux.
"""

from __future__ import annotations

import heapq
import json
import math
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple


# Canonical 6-switch, 3-disjoint-path interdomain topology shared by
# Mininet (topology.py) and POX (pox_sintra_controller.py).
# Each entry: (u_dpid, v_dpid, u_port, v_port, one_way_delay_ms, bw_mbps)
DEFAULT_TOPOLOGY_LINKS: List[Tuple[int, int, int, int, float, float]] = [
    # Path A: s1 -> s2 -> s5 (baseline RTT = 20 ms)
    (1, 2, 2, 1, 5.0, 100.0),
    (2, 5, 2, 2, 5.0, 100.0),
    # Path B: s1 -> s3 -> s5 (baseline RTT = 36 ms)
    (1, 3, 3, 1, 9.0, 100.0),
    (3, 5, 2, 3, 9.0, 100.0),
    # Path C: s1 -> s4 -> s6 -> s5 (baseline RTT = 54 ms)
    (1, 4, 4, 1, 9.0, 100.0),
    (4, 6, 2, 1, 9.0, 100.0),
    (6, 5, 2, 4, 9.0, 100.0),
]

# Host IP -> (attached_switch_dpid, switch_port, host_mac)
DEFAULT_HOST_ATTACHMENT: Dict[str, Tuple[int, int, str]] = {
    "10.0.0.1": (1, 1, "00:00:00:00:00:01"),
    "10.0.0.2": (5, 1, "00:00:00:00:00:02"),
}

PATH_NAMES: Dict[Tuple[int, ...], str] = {
    (1, 2, 5): "Path A (s1-s2-s5)",
    (1, 3, 5): "Path B (s1-s3-s5)",
    (1, 4, 6, 5): "Path C (s1-s4-s6-s5)",
}


@dataclass
class LinkMetrics:
    """Dynamic performance metrics and anomaly penalty for an undirected switch link."""

    base_rtt_ms: float
    rtt_ms: float
    loss_pct: float = 0.0
    jitter_ms: float = 0.0
    anomaly_penalty: float = 0.0
    last_penalty_time: float = field(default_factory=time.monotonic)
    bw_mbps: float = 100.0

    def effective_penalty(self, now: float, decay_half_life_s: float) -> float:
        """Compute exponentially decayed anomaly penalty at timestamp `now`."""
        if self.anomaly_penalty <= 0.0:
            return 0.0
        if decay_half_life_s <= 0.0:
            return self.anomaly_penalty
        elapsed = max(0.0, now - self.last_penalty_time)
        decayed = self.anomaly_penalty * math.pow(0.5, elapsed / decay_half_life_s)
        return 0.0 if decayed < 0.01 else decayed


class AdaptivePathEngine:
    """Weighted Dijkstra path solver with Sintra anomaly penalties and hysteresis.

    Supported policies (matching experimental baselines):
      - "static": Never reroutes (shortest-hop BGP-like baseline).
      - "threshold": Reroutes only on 'unreachable_host' or static latency_spike (>250 ms).
      - "sintra": Full multi-anomaly adaptive rerouting (latency, loss, jitter,
        flapping, correlation, geo anomalies) with penalty decay and cooldown damping.
    """

    ANOMALY_PENALTIES: Dict[str, float] = {
        "unreachable_host": 5000.0,
        "packet_loss": 400.0,
        "correlated_routing_event": 350.0,
        "path_flapping": 300.0,
        "latency_spike": 250.0,
        "jitter_spike": 220.0,
        "geo_anomaly": 180.0,
        "route_change": 120.0,
        "outlier_probe_latency": 80.0,
        "outlier_probe_loss": 100.0,
    }

    def __init__(
        self,
        src_dpid: int = 1,
        dst_dpid: int = 5,
        policy: str = "sintra",
        cooldown_seconds: float = 10.0,
        penalty_decay_half_life_s: float = 45.0,
        w_rtt: float = 1.0,
        w_loss: float = 20.0,
        w_jitter: float = 5.0,
        links: Optional[List[Tuple[int, int, int, int, float, float]]] = None,
    ) -> None:
        if policy not in ("static", "threshold", "sintra"):
            raise ValueError(f"Unsupported policy '{policy}'. Use static, threshold, or sintra.")
        self.src_dpid = src_dpid
        self.dst_dpid = dst_dpid
        self.policy = policy
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.penalty_decay_half_life_s = max(0.0, float(penalty_decay_half_life_s))
        self.w_rtt = float(w_rtt)
        self.w_loss = float(w_loss)
        self.w_jitter = float(w_jitter)

        self._lock = threading.RLock()
        self._link_defs = list(links) if links is not None else list(DEFAULT_TOPOLOGY_LINKS)
        self.port_map: Dict[Tuple[int, int], int] = {}
        self.adjacency: Dict[int, List[int]] = {}
        self.link_metrics: Dict[Tuple[int, int], LinkMetrics] = {}

        self.active_path: List[int] = []
        self.last_switchover_time: Optional[float] = None
        self.switchover_count: int = 0
        self.events_received: int = 0
        self.switchover_history: List[Dict[str, Any]] = []

        self._build_graph()
        self.active_path = self.compute_best_path(self.src_dpid, self.dst_dpid)

    @staticmethod
    def _edge_key(u: int, v: int) -> Tuple[int, int]:
        return (u, v) if u < v else (v, u)

    def _build_graph(self) -> None:
        self.port_map.clear()
        self.adjacency.clear()
        self.link_metrics.clear()
        for u, v, u_port, v_port, one_way_delay_ms, bw_mbps in self._link_defs:
            self.port_map[(u, v)] = u_port
            self.port_map[(v, u)] = v_port
            self.adjacency.setdefault(u, []).append(v)
            self.adjacency.setdefault(v, []).append(u)
            rtt_ms = 2.0 * float(one_way_delay_ms)
            self.link_metrics[self._edge_key(u, v)] = LinkMetrics(
                base_rtt_ms=rtt_ms,
                rtt_ms=rtt_ms,
                bw_mbps=bw_mbps,
            )

    def reset(self, policy: Optional[str] = None) -> Dict[str, Any]:
        """Reset all penalties, metrics, and history to initial clean state."""
        with self._lock:
            if policy is not None:
                if policy not in ("static", "threshold", "sintra"):
                    raise ValueError(f"Unsupported policy '{policy}'")
                self.policy = policy
            self._build_graph()
            self.active_path = self.compute_best_path(self.src_dpid, self.dst_dpid)
            self.last_switchover_time = None
            self.switchover_count = 0
            self.events_received = 0
            self.switchover_history.clear()
            return self.get_status()

    def set_policy(self, policy: str) -> Dict[str, Any]:
        """Switch active control policy without tearing down topology."""
        if policy not in ("static", "threshold", "sintra"):
            raise ValueError(f"Unsupported policy '{policy}'")
        with self._lock:
            self.policy = policy
            return self.get_status()

    def link_cost(self, u: int, v: int, now: Optional[float] = None) -> float:
        """Compute composite routing cost for edge (u, v)."""
        ts = time.monotonic() if now is None else now
        m = self.link_metrics[self._edge_key(u, v)]
        penalty = m.effective_penalty(ts, self.penalty_decay_half_life_s)
        return (
            self.w_rtt * m.rtt_ms
            + self.w_loss * m.loss_pct
            + self.w_jitter * m.jitter_ms
            + penalty
        )

    def compute_best_path(
        self,
        src: Optional[int] = None,
        dst: Optional[int] = None,
        now: Optional[float] = None,
    ) -> List[int]:
        """Compute minimum-cost path between src and dst using Dijkstra's algorithm."""
        src_node = self.src_dpid if src is None else src
        dst_node = self.dst_dpid if dst is None else dst
        ts = time.monotonic() if now is None else now

        with self._lock:
            if src_node not in self.adjacency or dst_node not in self.adjacency:
                return []
            dist: Dict[int, float] = {src_node: 0.0}
            prev: Dict[int, Optional[int]] = {src_node: None}
            pq: List[Tuple[float, int]] = [(0.0, src_node)]

            while pq:
                cur_cost, node = heapq.heappop(pq)
                if cur_cost > dist.get(node, float("inf")):
                    continue
                if node == dst_node:
                    break
                for nxt in sorted(self.adjacency.get(node, [])):
                    step_cost = self.link_cost(node, nxt, now=ts)
                    cand = cur_cost + step_cost
                    if cand < dist.get(nxt, float("inf")):
                        dist[nxt] = cand
                        prev[nxt] = node
                        heapq.heappush(pq, (cand, nxt))

            if dst_node not in prev:
                return []
            path: List[int] = []
            cur: Optional[int] = dst_node
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            path.reverse()
            return path

    def path_cost(self, path: List[int], now: Optional[float] = None) -> float:
        """Total composite cost along an explicit switch path."""
        ts = time.monotonic() if now is None else now
        with self._lock:
            if len(path) < 2:
                return 0.0
            return sum(self.link_cost(path[i], path[i + 1], now=ts) for i in range(len(path) - 1))

    def get_path_ports(self, path: List[int]) -> List[Tuple[int, int, int]]:
        """Return [(dpid, in_port, out_port), ...] for switch-to-switch hops along path."""
        with self._lock:
            if len(path) < 2:
                return []
            hops: List[Tuple[int, int, int]] = []
            for idx, dpid in enumerate(path):
                in_port = self.port_map[(dpid, path[idx - 1])] if idx > 0 else 1
                out_port = self.port_map[(dpid, path[idx + 1])] if idx < len(path) - 1 else 1
                hops.append((dpid, in_port, out_port))
            return hops

    def _is_actionable_under_policy(self, anomalies: List[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
        """Filter incoming anomalies according to the active control policy."""
        if self.policy == "static":
            return False, []
        if self.policy == "threshold":
            # Static threshold-only policy reacts solely to unreachable_host or >250ms RTT spike
            matched = []
            for a in anomalies:
                atype = a.get("type") or a.get("anomaly")
                val = a.get("value")
                if atype == "unreachable_host":
                    matched.append(a)
                elif atype == "latency_spike" and isinstance(val, (int, float)) and val > 250.0:
                    matched.append(a)
            return bool(matched), matched
        # Full Sintra policy reacts to all recognized anomalies
        matched = [a for a in anomalies if (a.get("type") or a.get("anomaly")) in self.ANOMALY_PENALTIES]
        return bool(matched), matched

    def handle_sintra_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a Sintra anomaly payload, update active path penalties, and decide rerouting."""
        t0 = time.perf_counter()
        now = time.monotonic()

        with self._lock:
            self.events_received += 1
            anomalies = payload.get("anomalies", [])
            old_path = list(self.active_path)

            actionable, matched = self._is_actionable_under_policy(anomalies)
            if not actionable:
                compute_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                return {
                    "rerouted": False,
                    "reason": f"ignored_by_{self.policy}_policy",
                    "policy": self.policy,
                    "old_path": old_path,
                    "active_path": old_path,
                    "active_path_name": PATH_NAMES.get(tuple(old_path), str(old_path)),
                    "compute_time_ms": compute_ms,
                }

            has_critical = any(
                (a.get("type") or a.get("anomaly")) == "unreachable_host"
                or a.get("severity") == "critical"
                for a in matched
            )

            # Enforce controller-side cooldown unless critical outage occurred
            if (
                not has_critical
                and self.last_switchover_time is not None
                and (now - self.last_switchover_time) < self.cooldown_seconds
            ):
                remaining = round(self.cooldown_seconds - (now - self.last_switchover_time), 2)
                compute_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                return {
                    "rerouted": False,
                    "reason": f"controller_cooldown ({remaining}s remaining)",
                    "policy": self.policy,
                    "old_path": old_path,
                    "active_path": old_path,
                    "active_path_name": PATH_NAMES.get(tuple(old_path), str(old_path)),
                    "compute_time_ms": compute_ms,
                }

            # Apply penalty proportional to strongest anomaly onto edges of currently active path
            strongest_penalty = 0.0
            trigger_types: List[str] = []
            for a in matched:
                atype = str(a.get("type") or a.get("anomaly"))
                trigger_types.append(atype)
                base_p = self.ANOMALY_PENALTIES.get(atype, 100.0)
                val = a.get("value")
                if atype == "latency_spike" and isinstance(val, (int, float)):
                    base_p = max(base_p, float(val))
                elif atype == "packet_loss" and isinstance(val, (int, float)):
                    base_p = max(base_p, float(val) * self.w_loss)
                elif atype == "jitter_spike" and isinstance(val, (int, float)):
                    base_p = max(base_p, float(val) * self.w_jitter + 150.0)
                strongest_penalty = max(strongest_penalty, base_p)

            # Penalize the bottleneck transit edges along old_path
            if len(old_path) >= 2:
                per_edge = strongest_penalty / max(len(old_path) - 1, 1)
                for i in range(len(old_path) - 1):
                    ek = self._edge_key(old_path[i], old_path[i + 1])
                    m = self.link_metrics[ek]
                    current_decayed = m.effective_penalty(now, self.penalty_decay_half_life_s)
                    m.anomaly_penalty = current_decayed + per_edge
                    m.last_penalty_time = now

            new_path = self.compute_best_path(self.src_dpid, self.dst_dpid, now=now)
            rerouted = bool(new_path) and new_path != old_path
            compute_ms = round((time.perf_counter() - t0) * 1000.0, 3)

            if rerouted:
                self.active_path = new_path
                self.last_switchover_time = now
                self.switchover_count += 1
                record = {
                    "timestamp": time.time(),
                    "measurement_id": payload.get("measurement_id"),
                    "old_path": old_path,
                    "new_path": new_path,
                    "old_path_name": PATH_NAMES.get(tuple(old_path), str(old_path)),
                    "new_path_name": PATH_NAMES.get(tuple(new_path), str(new_path)),
                    "triggers": sorted(set(trigger_types)),
                    "applied_penalty": round(strongest_penalty, 2),
                    "compute_time_ms": compute_ms,
                }
                self.switchover_history.append(record)

            return {
                "rerouted": rerouted,
                "reason": "path_switched" if rerouted else "current_path_still_optimal",
                "policy": self.policy,
                "old_path": old_path,
                "active_path": list(self.active_path),
                "active_path_name": PATH_NAMES.get(tuple(self.active_path), str(self.active_path)),
                "triggers": sorted(set(trigger_types)),
                "applied_penalty": round(strongest_penalty, 2),
                "compute_time_ms": compute_ms,
                "switchover_count": self.switchover_count,
            }

    def get_status(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of controller state and link costs."""
        now = time.monotonic()
        with self._lock:
            links_snapshot = {}
            for ek, m in sorted(self.link_metrics.items()):
                links_snapshot[f"s{ek[0]}-s{ek[1]}"] = {
                    "base_rtt_ms": m.base_rtt_ms,
                    "rtt_ms": m.rtt_ms,
                    "loss_pct": m.loss_pct,
                    "jitter_ms": m.jitter_ms,
                    "effective_penalty": round(m.effective_penalty(now, self.penalty_decay_half_life_s), 2),
                    "total_cost": round(self.link_cost(ek[0], ek[1], now=now), 2),
                }
            return {
                "policy": self.policy,
                "active_path": list(self.active_path),
                "active_path_name": PATH_NAMES.get(tuple(self.active_path), str(self.active_path)),
                "switchover_count": self.switchover_count,
                "events_received": self.events_received,
                "cooldown_seconds": self.cooldown_seconds,
                "links": links_snapshot,
                "switchover_history": list(self.switchover_history),
            }


class NorthboundRESTServer:
    """Lightweight HTTP/JSON northbound interface connecting Sintra to an SDN controller."""

    def __init__(
        self,
        engine: AdaptivePathEngine,
        host: str = "127.0.0.1",
        port: int = 8080,
        on_reroute: Optional[Callable[[List[int], List[int], Dict[str, Any]], float]] = None,
    ) -> None:
        self.engine = engine
        self.host = host
        self.port = port
        self.on_reroute = on_reroute
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def _make_handler(self):
        engine = self.engine
        on_reroute = self.on_reroute

        class SintraNorthboundHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return  # Silence default stderr access logs during tests/experiments

            def _send_json(self, status_code: int, body: Dict[str, Any]) -> None:
                raw = json.dumps(body).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _read_json(self) -> Optional[Dict[str, Any]]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return None

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/sintra/status":
                    self._send_json(200, engine.get_status())
                elif self.path == "/health":
                    self._send_json(200, {"status": "ok", "policy": engine.policy})
                else:
                    self._send_json(404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                data = self._read_json()
                if data is None:
                    self._send_json(400, {"error": "invalid_json"})
                    return

                if self.path == "/sintra/events":
                    decision = engine.handle_sintra_event(data)
                    rule_ms = 0.0
                    if decision.get("rerouted") and on_reroute is not None:
                        rule_ms = float(
                            on_reroute(decision["old_path"], decision["active_path"], decision)
                        )
                    decision["rule_install_time_ms"] = round(rule_ms, 3)
                    self._send_json(200, decision)
                elif self.path == "/sintra/reset":
                    policy = data.get("policy")
                    prev_path = list(engine.active_path)
                    try:
                        status = engine.reset(policy=policy)
                    except ValueError as exc:
                        self._send_json(400, {"error": str(exc)})
                        return
                    if on_reroute is not None:
                        on_reroute(prev_path, status["active_path"], {"reason": "reset"})
                    self._send_json(200, status)
                elif self.path == "/sintra/policy":
                    policy = data.get("policy")
                    if not policy:
                        self._send_json(400, {"error": "missing_policy"})
                        return
                    try:
                        status = engine.set_policy(str(policy))
                    except ValueError as exc:
                        self._send_json(400, {"error": str(exc)})
                        return
                    self._send_json(200, status)
                else:
                    self._send_json(404, {"error": "not_found"})

        return SintraNorthboundHandler

    def start(self) -> Tuple[str, int]:
        """Start the REST server on a background daemon thread and return (host, bound_port)."""
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._make_handler())
        bound_host, bound_port = self._httpd.server_address[:2]
        self.port = int(bound_port)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="sintra-northbound-rest",
            daemon=True,
        )
        self._thread.start()
        return str(bound_host), self.port

    def stop(self) -> None:
        """Cleanly shut down the REST server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
