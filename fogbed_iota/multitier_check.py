"""End-to-end verification of a running multi-tier IOTA topology.

Everything is executed **from inside the emulated network** (``docker exec mn.<node> ...``), so
each check really crosses the chained OVS switches instead of merely talking to a host-published
port. The command executor is injectable (``exec_fn``) so the logic is unit-testable without
Docker/Mininet.

Checks (names are stable, usable in tests / CI):

=====================  =========================================================================
``ip:<node>``          node kept its static 10.0.0.x address after attaching to its tier switch
``tc:<node>``          shaping is visible in the node's qdisc (diagnostic, *optional*)
``rtt:<src>-><dst>``   ICMP RTT from the edge host ≈ 2×Σdelay of the links on the path
``rpc:<src>->gw``      JSON-RPC ``iota_getChainIdentifier`` from the edge to the gateway (:9000)
``metrics:<src>->gw``  Prometheus ``/metrics`` from the edge to the gateway (:9184)
``tcp:<src>-><val>``   gRPC/TCP (:8080) reachability edge→validators and gateway→validators
``udp:<node>``         every node listens on its QUIC P2P UDP port (:8084)
``consensus``          gateway ``iota_getLatestCheckpointSequenceNumber`` strictly increases
``tx:pay-iota``        edge client sends a PTB (Move VM, L1) through the gateway; finalised
``tx:publish``         optional ``iota client publish`` of a Move package from the edge
=====================  =========================================================================
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from .topology import LinkProfile, TopologyValidationError

logger = logging.getLogger("fogbed_iota.multitier_check")

ExecFn = Callable[[str, str, int], Tuple[int, str]]

#: RTT acceptance window around the *configured* delay (netem + scheduler noise + processing).
RTT_LOWER_FACTOR = 0.85
RTT_LOWER_SLACK_MS = 2.0
RTT_UPPER_FACTOR = 1.35
RTT_UPPER_SLACK_MS = 25.0


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------
def docker_exec(container: str, command: str, timeout: int = 30) -> Tuple[int, str]:
    """Runs ``bash -c <command>`` in ``mn.<container>``; returns ``(returncode, stdout+stderr)``."""
    try:
        proc = subprocess.run(
            ["docker", "exec", f"mn.{container}", "bash", "-c", command],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except OSError as exc:
        return 127, f"cannot run docker: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


class DockerExecShell:
    """Minimal ``container``-like object (``.name`` + ``.cmd``) accepted by ``IotaCLI``."""

    def __init__(self, name: str, exec_fn: ExecFn = docker_exec) -> None:
        self.name = name
        self._exec = exec_fn

    def cmd(self, command: str) -> str:
        return self._exec(self.name, command, 120)[1]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    optional: bool = False  # optional failures never fail the report

    def line(self) -> str:
        mark = "✅" if self.ok else ("⚠️ " if self.optional else "❌")
        return f"{mark} {self.name:<34} {self.detail}"


@dataclass
class TopologyReport:
    results: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", optional: bool = False) -> CheckResult:
        res = CheckResult(name, bool(ok), detail, optional)
        self.results.append(res)
        logger.info(res.line())
        return res

    @property
    def ok(self) -> bool:
        return all(r.ok or r.optional for r in self.results)

    @property
    def failures(self) -> List[CheckResult]:
        return [r for r in self.results if not r.ok and not r.optional]

    def format(self) -> str:
        head = "Multi-tier topology verification: " + ("PASS" if self.ok else "FAIL")
        return "\n".join([head, *(r.line() for r in self.results)])

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "results": [r.__dict__.copy() for r in self.results]}

    def raise_for_failure(self) -> None:
        if not self.ok:
            raise TopologyValidationError(
                "multi-tier topology verification failed:\n" + "\n".join(r.line() for r in self.failures)
            )


# ---------------------------------------------------------------------------
# Pure parsing helpers (unit-tested)
# ---------------------------------------------------------------------------
_PING_RTT = re.compile(r"(?:rtt|round-trip)[^=]*=\s*([\d.]+)/([\d.]+)/([\d.]+)")
_PING_RECV = re.compile(r"(\d+)\s+(?:packets\s+)?received")


def parse_ping_avg_ms(output: str) -> Optional[float]:
    m = _PING_RTT.search(output or "")
    return float(m.group(2)) if m else None


def parse_ping_received(output: str) -> int:
    m = _PING_RECV.search(output or "")
    return int(m.group(1)) if m else 0


def rtt_window(expected_ms: float) -> Tuple[float, float]:
    """Acceptable ``(low, high)`` RTT for a configured ``expected_ms``."""
    return (
        max(0.0, expected_ms * RTT_LOWER_FACTOR - RTT_LOWER_SLACK_MS),
        expected_ms * RTT_UPPER_FACTOR + RTT_UPPER_SLACK_MS,
    )


def parse_jsonrpc_result(output: str) -> Any:
    """Returns ``result`` of a JSON-RPC response embedded in ``output`` (or ``None``)."""
    text = (output or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj.get("result") if isinstance(obj, dict) and "error" not in obj else None


def parse_checkpoint_seq(output: str) -> Optional[int]:
    res = parse_jsonrpc_result(output)
    try:
        return int(res)
    except (TypeError, ValueError):
        return None


def multiaddr_port(addr: str, proto: str) -> Optional[int]:
    m = re.search(rf"/{proto}/(\d+)", addr or "")
    return int(m.group(1)) if m else None


def hostport_port(addr: str) -> Optional[int]:
    m = re.search(r":(\d+)\s*$", addr or "")
    return int(m.group(1)) if m else None


def jsonrpc_curl(host: str, port: int, method: str, params: Optional[list] = None, timeout: int = 10) -> str:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []})
    return (
        f"curl -s -m {int(timeout)} -X POST http://{host}:{port} "
        f"-H 'Content-Type: application/json' -d {shlex.quote(payload)}"
    )


def node_ports(validator_yaml: Any) -> Dict[str, Optional[int]]:
    """Ports a node *really* listens on, read from its rendered ``validator.yaml``."""
    cfg = yaml.safe_load(Path(validator_yaml).read_text(encoding="utf-8")) or {}
    p2p = cfg.get("p2p-config") or {}
    return {
        "p2p": hostport_port(p2p.get("listen-address", "")),
        "network": multiaddr_port(cfg.get("network-address", ""), "tcp"),
        "rpc": hostport_port(cfg.get("json-rpc-address", "")),
        "metrics": hostport_port(cfg.get("metrics-address", "")),
        "grpc": 50051 if cfg.get("enable-grpc-api") else None,
    }


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------
def _poll(
    fn: Callable[[], Tuple[bool, str]],
    timeout: float,
    interval: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float] = time.monotonic,
) -> Tuple[bool, str]:
    deadline = clock() + timeout
    last = (False, "not attempted")
    while True:
        last = fn()
        if last[0] or clock() >= deadline:
            return last
        sleep(interval)


def validate_topology(
    net: Any,
    *,
    send_transaction: bool = True,
    publish_package_path: Optional[str] = None,
    progress_timeout: float = 90.0,
    ping_count: int = 6,
    exec_fn: ExecFn = docker_exec,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> TopologyReport:
    """Verifies the running topology of ``net`` (an ``IotaNetwork``) end to end."""
    report = TopologyReport()
    specs = net.node_specs
    gateways = [s for s in specs.values() if s.role == "fullnode"]
    validators = [s for s in specs.values() if s.role == "validator"]
    if not gateways or not validators:
        report.add("preconditions", False, "need at least one gateway (fullnode) and one validator")
        return report
    gw = gateways[0]
    arts = net.genesis_artifacts.nodes if net.genesis_artifacts else {}
    ports = {n: node_ports(a.validator_yaml) for n, a in arts.items()}

    client = net.client_container
    src_name = client.name if client is not None else gw.name
    src_tier = net.client_tier if client is not None else gw.tier
    if client is None:
        report.add("edge-host", True, f"no client container; edge-side checks run from gateway '{gw.name}'", optional=True)

    # -- ip:<node> and tc:<node> ---------------------------------------
    endpoints: List[Tuple[str, str, Optional[str]]] = [(s.name, s.ip, s.tier) for s in specs.values()]
    if client is not None:
        endpoints.append((client.name, client.ip, net.client_tier))
    for name, ip, _tier in endpoints:
        rc, out = exec_fn(name, "ip -4 -o addr show", 15)
        report.add(f"ip:{name}", rc == 0 and f"inet {ip}/" in out, f"expected {ip}")
        prof = net.effective_access_profile(name)
        if prof.is_shaped:
            rc, out = exec_fn(name, "tc qdisc show", 15)
            wanted = []
            if prof.delay is not None:
                wanted.append("delay")
            if prof.loss is not None:
                wanted.append("loss")
            if prof.bw is not None:
                wanted.append("htb")
            missing = [w for w in wanted if w not in out]
            report.add(f"tc:{name}", rc == 0 and not missing,
                       f"profile[{prof.describe()}]" + (f" missing {missing}" if missing else ""), optional=True)

    # -- rtt:<src>-><dst> (authoritative proof that per-link shaping is active) ----
    for dst in list(specs.values()):
        if dst.name == src_name:
            continue
        if net.topology is not None and src_tier is not None and dst.tier is not None:
            expected = net.topology.expected_rtt_ms(
                src_tier, dst.tier,
                src_access=net.effective_access_profile(src_name),
                dst_access=net.effective_access_profile(dst.name),
            )
        else:
            expected = 0.0
        low, high = rtt_window(expected)

        # Warm up ARP and switch MAC learning tables before measuring
        exec_fn(src_name, f"ping -c 1 -W 2 {dst.ip}", 5)

        def _measure_rtt(target_dst: Any = dst, exp_ms: float = expected, lo: float = low, hi: float = high) -> Tuple[bool, str]:
            rc, out = exec_fn(src_name, f"ping -c {int(ping_count)} -i 0.3 -W 3 {target_dst.ip}", 15 + 2 * ping_count)
            avg = parse_ping_avg_ms(out)
            ok = avg is not None and parse_ping_received(out) > 0 and lo <= avg <= hi
            detail = (f"avg={avg:.1f}ms" if avg is not None else "no reply") + f" expected≈{exp_ms:.0f}ms window[{lo:.0f},{hi:.0f}]"
            return ok, detail

        ok, detail = _poll(_measure_rtt, 15.0, 1.5, sleep, clock)
        report.add(f"rtt:{src_name}->{dst.name}", ok, detail)

    # -- rpc / metrics from the edge to the gateway ----------------------
    gp = ports.get(gw.name, {})
    rpc_port = gp.get("rpc") or 9000
    metrics_port = gp.get("metrics") or 9184

    def _rpc() -> Tuple[bool, str]:
        rc, out = exec_fn(src_name, jsonrpc_curl(gw.ip, rpc_port, "iota_getChainIdentifier"), 20)
        res = parse_jsonrpc_result(out)
        return res is not None, f"chainId={res}" if res is not None else f"no result ({out.strip()[:120]!r})"

    ok, detail = _poll(_rpc, 30, 3, sleep, clock)
    report.add(f"rpc:{src_name}->{gw.name}:{rpc_port}", ok, detail)

    def _metrics() -> Tuple[bool, str]:
        rc, out = exec_fn(src_name, f"curl -s -m 10 http://{gw.ip}:{metrics_port}/metrics | head -c 4000", 20)
        good = "# HELP" in out or "# TYPE" in out
        return good, "prometheus exposition ok" if good else f"no metrics ({out.strip()[:120]!r})"

    ok, detail = _poll(_metrics, 30, 3, sleep, clock)
    report.add(f"metrics:{src_name}->{gw.name}:{metrics_port}", ok, detail)

    # -- tcp (gRPC) to validators from the edge and from the gateway ---------
    for origin in dict.fromkeys([src_name, gw.name]):
        for v in validators:
            port = ports.get(v.name, {}).get("network") or 8080
            rc, out = exec_fn(origin, f"timeout 5 bash -c '</dev/tcp/{v.ip}/{port}'", 10)
            report.add(f"tcp:{origin}->{v.name}:{port}", rc == 0, "open" if rc == 0 else f"closed/filtered ({out.strip()[:80]!r})")

    # -- udp listeners (QUIC P2P) ---------------------------------------
    for s in specs.values():
        p2p = ports.get(s.name, {}).get("p2p") or 8084
        rc, out = exec_fn(s.name, "ss -uln", 10)
        report.add(f"udp:{s.name}:{p2p}", rc == 0 and f":{p2p}" in out, "listening" if f":{p2p}" in out else "not listening")

    # -- consensus liveness across the switches ---------------------------
    def _seq() -> Optional[int]:
        _rc, out = exec_fn(gw.name, jsonrpc_curl("127.0.0.1", rpc_port, "iota_getLatestCheckpointSequenceNumber"), 20)
        return parse_checkpoint_seq(out)

    first = _seq()
    if first is None:
        report.add("consensus", False, "gateway returned no checkpoint sequence number")
    else:
        state = {"last": first}

        def _advanced() -> Tuple[bool, str]:
            cur = _seq()
            if cur is not None:
                state["last"] = cur
            return state["last"] > first, f"checkpoint {first} -> {state['last']}"

        ok, detail = _poll(_advanced, progress_timeout, 3, sleep, clock)
        report.add("consensus", ok, detail)

    # -- L1 Move-VM transaction from the edge ------------------------------
    if send_transaction:
        _check_transaction(net, report, src_name, gw, rpc_port, exec_fn, sleep, clock)
    if publish_package_path:
        _check_publish(net, report, src_name, publish_package_path, exec_fn)
    return report


def _check_transaction(
    net: Any, report: TopologyReport, src: str, gw: Any, rpc_port: int, exec_fn: ExecFn,
    sleep: Callable[[float], None], clock: Callable[[], float] = time.monotonic,
) -> None:
    if net.client_container is None:
        report.add("tx:pay-iota", False, "no client container registered (set_client)")
        return
    if not net.client_provisioned:
        report.add("tx:pay-iota", False, "edge client was not provisioned (no funded keystore / client.yaml)")
        return
    try:
        from .client.cli import IotaCLI

        cli = IotaCLI(DockerExecShell(src, exec_fn), network="fogbed", client_config=net.client_config_path)
        address = cli.get_active_address()
        coins = cli.get_gas(address) if address else []
        if not coins:
            raw = DockerExecShell(src, exec_fn).cmd("iota client gas 2>&1 | tail -n 8")
            report.add("tx:pay-iota", False, f"no funded gas coins for {address}: {raw.strip()[:160]!r}")
            return
        recipient = net.client_recipient or address
        digest = cli.pay_iota(to=recipient, amount=1_000_000, gas_budget=10_000_000, input_coin=coins[0]["object_id"])
    except Exception as exc:  # noqa: BLE001 - report, never crash the verification
        report.add("tx:pay-iota", False, f"{type(exc).__name__}: {str(exc)[:200]}")
        return

    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "iota_getTransactionBlock",
                       "params": [digest, {"showEffects": True}]})

    def _finalised() -> Tuple[bool, str]:
        _rc, out = exec_fn(src, f"curl -s -m 10 -X POST http://{gw.ip}:{rpc_port} -H 'Content-Type: application/json' -d {shlex.quote(body)}", 20)
        res = parse_jsonrpc_result(out)
        status = ((res or {}).get("effects") or {}).get("status", {}).get("status") if isinstance(res, dict) else None
        return status == "success", f"digest={digest} status={status}"

    ok, detail = _poll(_finalised, 30, 2, sleep, clock)
    report.add("tx:pay-iota", ok, detail)


def _check_publish(net: Any, report: TopologyReport, src: str, path: str, exec_fn: ExecFn) -> None:
    try:
        from .client.cli import IotaCLI

        cli = IotaCLI(DockerExecShell(src, exec_fn), network="fogbed", client_config=net.client_config_path)
        parsed = cli.publish_package(path)
        status = ((parsed or {}).get("effects") or {}).get("status", {}).get("status") if isinstance(parsed, dict) else None
        report.add("tx:publish", status == "success", f"package={path} status={status}", optional=True)
    except Exception as exc:  # noqa: BLE001
        report.add("tx:publish", False, f"{type(exc).__name__}: {str(exc)[:200]}", optional=True)


__all__ = [
    "CheckResult",
    "DockerExecShell",
    "TopologyReport",
    "docker_exec",
    "hostport_port",
    "jsonrpc_curl",
    "multiaddr_port",
    "node_ports",
    "parse_checkpoint_seq",
    "parse_jsonrpc_result",
    "parse_ping_avg_ms",
    "parse_ping_received",
    "rtt_window",
    "validate_topology",
]
