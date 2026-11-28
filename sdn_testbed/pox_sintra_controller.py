"""
POX OpenFlow 1.0 controller for Sintra closed-loop adaptive rerouting.

Run on Linux / Ubuntu VM with POX (gar-experimental Python 3 branch):
    PYTHONPATH=/path/to/Sintra python3 /path/to/pox/pox.py \
        log.level --INFO \
        sdn_testbed.pox_sintra_controller \
        --rest_port=8080 --policy=sintra --cooldown=10
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from sdn_testbed.path_engine import (
    AdaptivePathEngine,
    DEFAULT_HOST_ATTACHMENT,
    NorthboundRESTServer,
    PATH_NAMES,
)

try:
    from pox.core import core
    import pox.openflow.libopenflow_01 as of
    from pox.lib.addresses import IPAddr, EthAddr
    POX_AVAILABLE = True
except ImportError:  # Allows importing/type-checking outside POX runtime
    POX_AVAILABLE = False
    core = None
    of = None
    IPAddr = None
    EthAddr = None


class SintraPOXController:
    """OpenFlow 1.0 reactive/proactive path controller driven by Sintra anomaly events."""

    FLOW_PRIORITY_DATA = 200
    FLOW_PRIORITY_ARP = 150

    def __init__(
        self,
        rest_host: str = "127.0.0.1",
        rest_port: int = 8080,
        policy: str = "sintra",
        cooldown: float = 10.0,
        decay_half_life: float = 45.0,
    ) -> None:
        self.log = core.getLogger("sintra.pox") if POX_AVAILABLE else None
        self.connections: Dict[int, Any] = {}
        self.engine = AdaptivePathEngine(
            src_dpid=1,
            dst_dpid=5,
            policy=policy,
            cooldown_seconds=cooldown,
            penalty_decay_half_life_s=decay_half_life,
        )
        self.rest_server = NorthboundRESTServer(
            engine=self.engine,
            host=rest_host,
            port=rest_port,
            on_reroute=self._handle_reroute_callback,
        )

        if POX_AVAILABLE:
            core.openflow.addListeners(self)
        host, bound_port = self.rest_server.start()
        if self.log:
            self.log.info(
                f"SintraPOXController started: policy={policy}, "
                f"REST=http://{host}:{bound_port}/sintra/events, "
                f"initial_path={self.engine.active_path}"
            )

    def _handle_reroute_callback(
        self,
        old_path: List[int],
        new_path: List[int],
        decision: Dict[str, Any],
    ) -> float:
        """Install OpenFlow rules on POX's recoco event loop (thread-safe) and return install time (ms)."""
        if not POX_AVAILABLE:
            return 0.0
        done = threading.Event()
        elapsed_holder: List[float] = [0.0]

        def _do_install() -> None:
            t0 = time.perf_counter()
            try:
                self._install_bidirectional_path(new_path, old_path=old_path)
            finally:
                elapsed_holder[0] = (time.perf_counter() - t0) * 1000.0
                done.set()

        core.callLater(_do_install)
        done.wait(timeout=2.0)
        elapsed_ms = elapsed_holder[0]
        if self.log:
            self.log.info(
                f"Rerouted active flow: {old_path} -> {new_path} "
                f"({PATH_NAMES.get(tuple(new_path), new_path)}) in {elapsed_ms:.2f} ms"
            )
        return elapsed_ms

    def _handle_ConnectionUp(self, event: Any) -> None:  # noqa: N802
        dpid = int(event.dpid)
        self.connections[dpid] = event.connection
        if self.log:
            self.log.info(f"Switch s{dpid} connected ({len(self.connections)} total)")
        # Re-install active path rules once relevant switches are connected
        self._install_bidirectional_path(self.engine.active_path)

    def _handle_ConnectionDown(self, event: Any) -> None:  # noqa: N802
        dpid = int(event.dpid)
        self.connections.pop(dpid, None)
        if self.log:
            self.log.warning(f"Switch s{dpid} disconnected")

    def _send_flow_mod(
        self,
        dpid: int,
        dl_type: int,
        nw_src: str,
        nw_dst: str,
        out_port: int,
        priority: int,
    ) -> None:
        conn = self.connections.get(dpid)
        if conn is None or not POX_AVAILABLE:
            return
        msg = of.ofp_flow_mod()
        msg.priority = priority
        msg.command = of.OFPFC_MODIFY_STRICT
        msg.match.dl_type = dl_type
        msg.match.nw_src = IPAddr(nw_src)
        msg.match.nw_dst = IPAddr(nw_dst)
        msg.actions.append(of.ofp_action_output(port=out_port))
        # Send as ADD (overwrites matching rule cleanly in OpenFlow 1.0)
        msg.command = of.OFPFC_ADD
        conn.send(msg)

    def _delete_flows_for_pair(self, dpid: int, nw_src: str, nw_dst: str) -> None:
        conn = self.connections.get(dpid)
        if conn is None or not POX_AVAILABLE:
            return
        for dl_type in (0x0800, 0x0806):
            msg = of.ofp_flow_mod()
            msg.command = of.OFPFC_DELETE
            msg.match.dl_type = dl_type
            msg.match.nw_src = IPAddr(nw_src)
            msg.match.nw_dst = IPAddr(nw_dst)
            conn.send(msg)

    def _install_bidirectional_path(
        self,
        path: List[int],
        old_path: List[int] = None,
    ) -> None:
        """Make-before-break OpenFlow 1.0 path installation for h1 <-> h2 (IPv4 + ARP).

        Installs downstream transit switches first before flipping edge switch s1/s5
        so in-flight packets encounter valid forwarding rules with minimal drop.
        """
        if not POX_AVAILABLE or len(path) < 2:
            return

        h1_ip, h2_ip = "10.0.0.1", "10.0.0.2"
        hops = self.engine.get_path_ports(path)
        if not hops:
            return

        # Make-before-break: program downstream switches first (destination -> source)
        for dpid, in_port, out_port in reversed(hops):
            # Forward h1 -> h2 (IPv4 + ARP)
            self._send_flow_mod(dpid, 0x0800, h1_ip, h2_ip, out_port, self.FLOW_PRIORITY_DATA)
            self._send_flow_mod(dpid, 0x0806, h1_ip, h2_ip, out_port, self.FLOW_PRIORITY_ARP)

        # Reverse direction h2 -> h1 (source -> destination)
        for dpid, in_port, out_port in hops:
            self._send_flow_mod(dpid, 0x0800, h2_ip, h1_ip, in_port, self.FLOW_PRIORITY_DATA)
            self._send_flow_mod(dpid, 0x0806, h2_ip, h1_ip, in_port, self.FLOW_PRIORITY_ARP)

        # Clean up unused transit switches from previous path
        if old_path:
            removed = set(old_path) - set(path)
            for dpid in removed:
                self._delete_flows_for_pair(dpid, h1_ip, h2_ip)
                self._delete_flows_for_pair(dpid, h2_ip, h1_ip)


def launch(
    rest_host: str = "127.0.0.1",
    rest_port: str = "8080",
    policy: str = "sintra",
    cooldown: str = "10.0",
    decay_half_life: str = "45.0",
) -> None:
    """POX module entry point."""
    if not POX_AVAILABLE:
        raise RuntimeError("This module must be launched inside the POX runtime (pox.py).")
    core.registerNew(
        SintraPOXController,
        rest_host=rest_host,
        rest_port=int(rest_port),
        policy=policy,
        cooldown=float(cooldown),
        decay_half_life=float(decay_half_life),
    )
