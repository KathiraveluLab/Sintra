"""
Mininet multi-path interdomain topology and dynamic `tc netem` impairment controller.

Matches DEFAULT_TOPOLOGY_LINKS and DEFAULT_HOST_ATTACHMENT from path_engine.py:
  - Path A (primary, 20 ms RTT):  h1 -- s1 -- s2 -- s5 -- h2
  - Path B (alternate, 36 ms RTT): h1 -- s1 -- s3 -- s5 -- h2
  - Path C (backup, 54 ms RTT):    h1 -- s1 -- s4 -- s6 -- s5 -- h2
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sdn_testbed.path_engine import DEFAULT_HOST_ATTACHMENT, DEFAULT_TOPOLOGY_LINKS

try:
    from mininet.topo import Topo
    from mininet.net import Mininet
    from mininet.node import OVSKernelSwitch, RemoteController
    from mininet.link import TCLink
    MININET_AVAILABLE = True
except ImportError:
    MININET_AVAILABLE = False
    Topo = object
    Mininet = None
    OVSKernelSwitch = None
    RemoteController = None
    TCLink = None


class SintraInterdomainTopo(Topo):
    """6-switch, 3-disjoint-path interdomain topology with deterministic port numbering."""

    def build(self) -> None:
        # Hosts
        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

        # Switches s1..s6 (explicit OpenFlow 1.0 DPIDs 1..6)
        switches = {
            dpid: self.addSwitch(f"s{dpid}", dpid=f"{dpid:016x}", protocols="OpenFlow10")
            for dpid in range(1, 7)
        }

        # Attach hosts to edge switches s1 (port 1) and s5 (port 1)
        self.addLink(h1, switches[1], port1=0, port2=1)
        self.addLink(h2, switches[5], port1=0, port2=1)

        # Interdomain switch-to-switch links with baseline propagation delays
        for u, v, u_port, v_port, one_way_delay_ms, bw_mbps in DEFAULT_TOPOLOGY_LINKS:
            self.addLink(
                switches[u],
                switches[v],
                port1=u_port,
                port2=v_port,
                bw=bw_mbps,
                delay=f"{one_way_delay_ms}ms",
                use_htb=True,
            )


def create_sintra_network(controller_ip: str = "127.0.0.1", controller_port: int = 6633) -> Any:
    """Instantiate a Mininet network connected to an external POX OpenFlow 1.0 controller."""
    if not MININET_AVAILABLE:
        raise RuntimeError("Mininet is not installed on this host. Run on Ubuntu/Linux with Mininet.")
    topo = SintraInterdomainTopo()
    net = Mininet(
        topo=topo,
        switch=OVSKernelSwitch,
        link=TCLink,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=True,
    )
    net.addController(
        "c0",
        controller=RemoteController,
        ip=controller_ip,
        port=controller_port,
    )
    return net


class ImpairmentController:
    """Dynamically injects and clears `tc netem` latency, jitter, and loss on Mininet links."""

    # Bottleneck interfaces along Path A (s2 <-> s5, both directions)
    PATH_A_INTFS: Tuple[Tuple[str, str, float], ...] = (
        ("s2", "s2-eth2", 5.0),
        ("s5", "s5-eth2", 5.0),
    )

    def __init__(self, net: Any) -> None:
        self.net = net

    def _find_netem_parent(self, node: Any, intf: str) -> Optional[str]:
        """Find existing netem qdisc parent handle (Mininet TCLink attaches netem under HTB)."""
        out = node.cmd(f"tc qdisc show dev {intf}")
        match = re.search(r"qdisc netem \S+ parent (\S+)", out)
        return match.group(1) if match else None

    def set_link_impairment(
        self,
        switch_name: str,
        intf: str,
        delay_ms: float,
        jitter_ms: float = 0.0,
        loss_pct: float = 0.0,
    ) -> str:
        """Apply `tc netem` parameters cleanly to a single switch interface."""
        node = self.net.get(switch_name)
        parent = self._find_netem_parent(node, intf)
        netem_args = [f"delay {delay_ms:.1f}ms"]
        if jitter_ms > 0.0:
            netem_args.append(f"{jitter_ms:.1f}ms distribution normal")
        if loss_pct > 0.0:
            netem_args.append(f"loss {min(loss_pct, 100.0):.2f}%")
        params = " ".join(netem_args)

        if parent:
            cmd = f"tc qdisc change dev {intf} parent {parent} netem {params}"
        else:
            cmd = f"tc qdisc replace dev {intf} root netem {params}"
        return node.cmd(cmd)

    def inject_path_a_impairment(
        self,
        extra_rtt_ms: float = 0.0,
        jitter_ms: float = 0.0,
        loss_pct: float = 0.0,
    ) -> None:
        """Inject symmetric impairment across Path A's transit link s2-s5."""
        half_extra = extra_rtt_ms / 2.0
        half_jitter = jitter_ms / 2.0
        # Split packet loss symmetrically so round-trip effective loss matches loss_pct
        if loss_pct >= 100.0:
            one_way_loss = 100.0
        elif loss_pct > 0.0:
            one_way_loss = (1.0 - (1.0 - loss_pct / 100.0) ** 0.5) * 100.0
        else:
            one_way_loss = 0.0

        for sw, intf, base_delay in self.PATH_A_INTFS:
            self.set_link_impairment(
                sw,
                intf,
                delay_ms=base_delay + half_extra,
                jitter_ms=half_jitter,
                loss_pct=one_way_loss,
            )

    def reset_path_a(self) -> None:
        """Restore Path A (s2-s5) to its clean 5ms one-way baseline (20 ms total RTT)."""
        for sw, intf, base_delay in self.PATH_A_INTFS:
            self.set_link_impairment(sw, intf, delay_ms=base_delay, jitter_ms=0.0, loss_pct=0.0)


def load_ripe_atlas_trace(json_path: str) -> List[Dict[str, float]]:
    """Extract an ordered (rtt_ms, loss_pct) replay series from a Sintra RIPE Atlas JSON file."""
    path = Path(json_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    trace: List[Dict[str, float]] = []
    for result in data.get("results", []):
        if result.get("measurement_type") != "ping":
            continue
        samples = result.get("samples") or []
        if samples:
            for sample in samples:
                rtt = sample.get("avg_rtt")
                loss = float(sample.get("packet_loss_percentage", 0.0) or 0.0)
                if rtt is not None or loss >= 100.0:
                    trace.append({"rtt_ms": float(rtt or 0.0), "loss_pct": loss})
        else:
            stats = result.get("latency_stats", {})
            for rtt in stats.get("rtts", []):
                if rtt is not None:
                    trace.append({
                        "rtt_ms": float(rtt),
                        "loss_pct": float(result.get("packet_loss_percentage", 0.0) or 0.0),
                    })
    return trace
