"""Distributed and Local IOTA Network Orchestration for Fogbed.

Supports:
1. Local Mininet/Containernet emulation using standard FogbedExperiment
   (e.g., examples/01_basic_network.py). No SSH/paramiko required.
2. Distributed multi-host orchestration using FogbedDistributedExperiment and SSH sessions.
   Requires `paramiko` (lazy loaded on demand).

Both modes use the two-step genesis pipeline adhering strictly to IOTA release v1.33.1.
"""

from __future__ import annotations

import atexit
import ipaddress
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml

_FOGBED_IMPORT_ERROR: Optional[BaseException] = None
try:
    from fogbed import Container, FogbedExperiment, FogbedDistributedExperiment
except (ImportError, AttributeError) as _exc:
    # Lets the package be imported (unit tests, tooling) outside the Fogbed/Containernet
    # environment. Creating a *real* experiment without Fogbed is refused in IotaNetwork.__init__.
    _FOGBED_IMPORT_ERROR = _exc

    class Container:  # type: ignore
        pass

    class FogbedExperiment:  # type: ignore
        pass

    class FogbedDistributedExperiment:  # type: ignore
        pass

from .genesis import (
    Committee,
    CommitteeSpec,
    GenesisArtifacts,
    GenesisBuilder,
    ToolRunner,
    load_release,
    prepare_committee,
)
from .genesis.errors import GenesisError, NodeStartError
from .topology import (
    LinkProfile,
    TierRef,
    TopologyError,
    TopologySpec,
    three_tier_topology,
    tier_name,
)

logger = logging.getLogger("fogbed_iota.network")

WORK_DIR = "/tmp/fogbed_iota_workdir"
DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")


def _patch_mininet_containernet_intf_quirk() -> None:
    """Silences benign Mininet quirk where empty TTY output from docker exec
    causes false-positive 'Error setting <intf> up: ' warnings."""
    try:
        from mininet.link import Intf  # type: ignore
        from mininet.log import error  # type: ignore

        def patched_isUp(self: Any, setUp: bool = False) -> bool:
            if setUp:
                cmdOutput = self.ifconfig("up")
                if cmdOutput and cmdOutput.strip():
                    error(f"Error setting {self.name} up: {cmdOutput} ")
                    return False
                return True
            return "UP" in self.ifconfig()

        Intf.isUp = patched_isUp
    except Exception:
        pass


_patch_mininet_containernet_intf_quirk()


def _configure_logging(level: str = "INFO") -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] [%(name)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))


@dataclass(frozen=True)
class WorkerEndpoint:
    """Physical worker accessible by Fogbed and SSH."""
    ip: str
    fogbed_port: int = 5000
    ssh_port: int = 22
    username: str = field(default_factory=lambda: os.getenv("FOGBED_SSH_USER", "paulo"))
    password: Optional[str] = field(default_factory=lambda: os.getenv("FOGBED_SSH_PASSWORD"))
    key_filename: Optional[str] = field(default_factory=lambda: os.getenv("FOGBED_SSH_KEY"))
    remote_root: str = field(default_factory=lambda: os.getenv("FOGBED_REMOTE_ROOT", "/tmp/pvic_iota_fogbed"))


class RemoteWorkerSession:
    """SSH/SFTP wrapper around paramiko, lazily loaded only when distributed mode is used."""

    def __init__(self, endpoint: WorkerEndpoint) -> None:
        try:
            import paramiko  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The 'paramiko' library is required for distributed multi-worker orchestration.\n"
                "Please install it in your environment: pip install paramiko"
            ) from exc

        import paramiko
        self.endpoint = endpoint
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self) -> None:
        self.client.connect(
            hostname=self.endpoint.ip,
            port=self.endpoint.ssh_port,
            username=self.endpoint.username,
            password=self.endpoint.password,
            key_filename=self.endpoint.key_filename,
            allow_agent=True,
            look_for_keys=True,
            timeout=15,
        )

    def close(self) -> None:
        self.client.close()

    def mkdir_p(self, remote_path: str) -> None:
        self.run(f"mkdir -p {shlex.quote(remote_path)}")

    def put_file(self, local_path: Path, remote_path: str) -> None:
        with self.client.open_sftp() as sftp:
            sftp.put(str(local_path), remote_path)

    def run(self, command: str, timeout: int = 60) -> str:
        _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if exit_status != 0:
            raise RuntimeError(
                f"SSH command failed on {self.endpoint.ip} (exit {exit_status}): "
                f"{err.strip() or out.strip()}"
            )
        return out


@dataclass
class NodeSpec:
    """Runtime metadata for a node in the IOTA network."""
    name: str
    role: str  # "validator" or "fullnode"
    ip: str
    container: Container
    port_offset: int = 0
    p2p_port: int = 8084
    rpc_port: int = 9000
    metrics_port: int = 9184
    grpc_port: int = 50051
    worker: Optional[WorkerEndpoint] = None
    datacenter_name: str = "cloud"
    local_config_dir: Optional[Path] = None
    remote_config_dir: Optional[str] = None
    assigned_ip: Optional[str] = None
    tier: Optional[str] = None  # None == classic single-switch topology
    link_params: Dict[str, Any] = field(default_factory=dict)  # node access link (TCLink params)


class IotaNode(Container):
    """Fogbed container specialized for running an IOTA v1.33.1 node."""

    def __init__(
        self,
        name: str,
        ip: str,
        role: str = "validator",
        port_offset: int = 0,
        image: str = DEFAULT_IMAGE,
        port_bindings: Optional[Dict[int, int]] = None,
        **kwargs: Any,
    ):
        self.role = role
        self.ip_addr = ip
        self.port_offset = port_offset
        self.p2p_port = 8084
        self.rpc_port = 9000
        self.metrics_port = 9184
        self.grpc_port = 50051

        env = {
            "IOTA_CONFIG_DIR": "/custom_config",
            "IOTA_NODE_ROLE": role,
            "RUST_LOG": "info,iota=debug",
            "RUST_BACKTRACE": "1",
        }

        super().__init__(
            name=name,
            dimage=image,
            ip=ip,
            environment=env,
            privileged=True,
            dcmd="tail -f /dev/null",
            port_bindings=port_bindings or {},
            **kwargs,
        )


class IotaNetwork:
    """Unified Orchestrator for IOTA networks on Fogbed (Local & Distributed)."""

    def __init__(
        self,
        experiment: Optional[Union[FogbedExperiment, FogbedDistributedExperiment]] = None,
        image: str = DEFAULT_IMAGE,
        log_level: str = "INFO",
        auto_cleanup: bool = True,
        workers: Optional[Sequence[WorkerEndpoint]] = None,
        remote_volume_root: str = "/tmp/pvic_iota_fogbed/volumes",
        workspace_root: Optional[Path] = None,
        readiness_timeout: Optional[int] = None,
    ):
        _configure_logging(log_level)
        self.image = image
        self.auto_cleanup = auto_cleanup
        self.release = load_release()

        if experiment is None and _FOGBED_IMPORT_ERROR is not None:
            raise ImportError(
                f"Fogbed/Containernet could not be imported ({_FOGBED_IMPORT_ERROR}). Run inside the Fogbed "
                "environment, e.g. `sudo PYTHONPATH=$(pwd) /opt/fogbed/venv/bin/python3 <script>`, "
                "or pass an already-created experiment."
            ) from _FOGBED_IMPORT_ERROR

        # Determine mode: distributed if FogbedDistributedExperiment or workers supplied
        self.is_distributed = isinstance(experiment, FogbedDistributedExperiment) or bool(workers)

        if experiment is not None:
            self.exp = experiment
        else:
            self.exp = FogbedDistributedExperiment() if self.is_distributed else FogbedExperiment()

        self.workers = list(workers) if workers else []
        self.remote_volume_root = remote_volume_root
        self._workspace_owner = workspace_root is None
        self.workspace_root = workspace_root or Path(tempfile.mkdtemp(prefix="iota_fogbed_"))
        self.genesis_dir = self.workspace_root / "genesis"
        self.generated_dir = self.workspace_root / "generated"

        self.node_specs: Dict[str, NodeSpec] = {}
        self.client_container: Optional[Container] = None

        # Multi-tier state (all inert unless add_tier()/use_three_tier_topology() is called)
        self.readiness_timeout = readiness_timeout
        self.topology: Optional[TopologySpec] = None
        self.client_tier: Optional[str] = None
        self._client_link = LinkProfile()
        self.tier_switches: Dict[str, str] = {}
        self.client_provisioned = False
        self.client_config_path = "/app/config/client.yaml"
        self.client_recipient: Optional[str] = None
        self._topology_built = False
        self._cleanup_registered = False

        self.account_manager = None
        self.contract_manager = None
        self.genesis_artifacts: Optional[GenesisArtifacts] = None

        self.sessions: List[RemoteWorkerSession] = []
        if self.is_distributed and self.workers:
            self.sessions = [RemoteWorkerSession(w) for w in self.workers]

        if self.auto_cleanup:
            self._register_cleanup_handlers()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _register_cleanup_handlers(self) -> None:
        if self._cleanup_registered:
            return
        atexit.register(self._cleanup_on_exit)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self._cleanup_registered = True

    def _signal_handler(self, signum: int, frame: Any) -> None:
        logger.info(f"\n⚠️ Received signal {signum}, cleaning up...")
        self.stop()

    def _cleanup_on_exit(self) -> None:
        if self.auto_cleanup:
            self.cleanup_workspace()

    def cleanup_workspace(self) -> None:
        if self._workspace_owner and self.workspace_root.exists():
            shutil.rmtree(self.workspace_root, ignore_errors=True)

    def __enter__(self) -> "IotaNetwork":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def stop(self) -> None:
        logger.info("🛑 Stopping IOTA Network...")
        if self.is_distributed and self.sessions:
            for session in self.sessions:
                try:
                    session.connect()
                    for name in self.node_specs:
                        session.run(f"docker exec mn.{name} pkill -9 iota-node 2>/dev/null || true")
                except Exception as exc:
                    logger.debug("Failed remote stop: %s", exc)
                finally:
                    session.close()
        else:
            for spec in self.node_specs.values():
                try:
                    subprocess.run(
                        ["docker", "exec", f"mn.{spec.name}", "pkill", "-9", "iota-node"],
                        capture_output=True,
                        check=False,
                    )
                except Exception as exc:
                    logger.debug("Failed to stop node %s: %s", spec.name, exc)

        if self.auto_cleanup:
            self.cleanup_workspace()
        logger.info("✅ IOTA Network stopped")

    # ------------------------------------------------------------------
    # Node registration
    # ------------------------------------------------------------------
    def _register_endpoint(self, name: str, ip: str, ignore_client: bool = False) -> None:
        """Rejects bad/duplicate names and IPs up front (Fogbed would only fail later, at add_docker)."""
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError as exc:
            raise TopologyError(f"invalid IP {ip!r} for node {name!r}: {exc}") from exc
        if addr.version != 4:
            raise TopologyError(f"node {name!r}: only IPv4 is supported, got {ip!r}")

        names = set(self.node_specs)
        ips = {s.ip for s in self.node_specs.values()}
        if self.client_container is not None and not ignore_client:
            names.add(getattr(self.client_container, "name", ""))
            ips.add(getattr(self.client_container, "ip", ""))
        if name in names:
            raise TopologyError(f"duplicate node name {name!r}")
        if ip in ips:
            raise TopologyError(f"duplicate IP {ip} (node {name!r})")
        if addr not in ipaddress.ip_network("10.0.0.0/8"):
            logger.warning(
                "node %s uses %s outside Mininet's 10.0.0.0/8: it will not be reachable by the other nodes", name, ip
            )

    def add_validator(
        self,
        name: str,
        ip: str,
        tier: Optional[TierRef] = None,
        link_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> IotaNode:
        """Registers a validator node with static IP.

        ``tier`` (e.g. ``"cloud"``) places the node on that tier's switch when a multi-tier topology
        is declared; ``link_params`` (``delay``/``bw``/``loss``/...) shapes this node's access link.
        """
        logger.info(f"Adding validator: {name} @ {ip}")
        self._register_endpoint(name, ip)
        profile = LinkProfile.from_params(link_params)
        tname = tier_name(tier)
        worker = self.workers[0] if (self.is_distributed and self.workers) else None
        container = IotaNode(
            name=name, ip=ip, role="validator", port_offset=len(self.node_specs), image=self.image,
            link_params=profile.to_params(), **kwargs,
        )
        spec = NodeSpec(
            name=name,
            role="validator",
            ip=ip,
            container=container,
            port_offset=len(self.node_specs),
            worker=worker,
            datacenter_name=tname or "cloud",
            local_config_dir=self.generated_dir / name,
            remote_config_dir=f"{self.remote_volume_root}/{name}" if worker else None,
            assigned_ip=ip,
            tier=tname,
            link_params=profile.to_params(),
        )
        self.node_specs[name] = spec
        return container

    def add_gateway(
        self,
        name: str,
        ip: str,
        port_bindings: Optional[Dict[int, int]] = None,
        bind_host_ports: bool = True,
        tier: Optional[TierRef] = None,
        link_params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> IotaNode:
        """Registers a gateway (fullnode) node with static IP (see ``add_validator`` for tier/link_params)."""
        logger.info(f"Adding gateway (fullnode): {name} @ {ip}")
        self._register_endpoint(name, ip)
        profile = LinkProfile.from_params(link_params)
        tname = tier_name(tier)
        worker = self.workers[1] if (self.is_distributed and len(self.workers) > 1) else (self.workers[0] if self.workers else None)
        
        bindings: Dict[int, int] = {}
        if port_bindings is not None:
            bindings = port_bindings
        elif bind_host_ports and not self.is_distributed:
            bindings = {9000: 9000, 9184: 9184}

        container = IotaNode(
            name=name,
            ip=ip,
            role="fullnode",
            port_offset=len(self.node_specs),
            image=self.image,
            port_bindings=bindings,
            link_params=profile.to_params(),
            **kwargs,
        )
        spec = NodeSpec(
            name=name,
            role="fullnode",
            ip=ip,
            container=container,
            port_offset=len(self.node_specs),
            worker=worker,
            datacenter_name=tname or "cloud",
            local_config_dir=self.generated_dir / name,
            remote_config_dir=f"{self.remote_volume_root}/{name}" if worker else None,
            assigned_ip=ip,
            tier=tname,
            link_params=profile.to_params(),
        )
        self.node_specs[name] = spec
        return container

    def set_client(
        self,
        container: Container,
        tier: Optional[TierRef] = None,
        link_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Registers a client container for user interactions / smart contracts.

        In a multi-tier topology the client normally lives on the ``edge`` tier.
        """
        logger.info(f"Setting client container: {container.name}")
        self._register_endpoint(container.name, getattr(container, "ip", ""), ignore_client=True)
        existing = getattr(container, "link_params", None) or {}
        self._client_link = LinkProfile.from_params(link_params).merged_over(LinkProfile.from_params(existing))
        container.link_params = self._client_link.to_params()
        self.client_tier = tier_name(tier)
        self.client_container = container

    # ------------------------------------------------------------------
    # Multi-tier topology declaration (Edge / Fog / Cloud)
    # ------------------------------------------------------------------
    def _topology_or_new(self) -> TopologySpec:
        if self.topology is None:
            self.topology = TopologySpec()
        return self.topology

    def add_tier(
        self,
        name: TierRef,
        access_link: Union[LinkProfile, Dict[str, Any], None] = None,
        resource_model: Any = None,
    ) -> None:
        """Declares a tier (== one Fogbed VirtualInstance == one OVS switch).

        ``access_link`` is the default host<->switch link of every node on that tier
        (a node's own ``link_params`` override it field by field).
        """
        self._topology_or_new().add_tier(name, access_link, resource_model)

    def connect_tiers(self, a: TierRef, b: TierRef, **link_params: Any) -> None:
        """Links two tier switches with a shaped link: ``delay='20ms', bw=50, loss=1`` ..."""
        self._topology_or_new().connect(a, b, link_params)

    def use_three_tier_topology(
        self,
        edge_fog: Union[LinkProfile, Dict[str, Any], None] = None,
        fog_cloud: Union[LinkProfile, Dict[str, Any], None] = None,
        edge_access: Union[LinkProfile, Dict[str, Any], None] = None,
        fog_access: Union[LinkProfile, Dict[str, Any], None] = None,
        cloud_access: Union[LinkProfile, Dict[str, Any], None] = None,
    ) -> TopologySpec:
        """Declares ``edge — fog — cloud`` (a loop-free chain of three switches)."""
        if self.topology is not None:
            raise TopologyError("a topology is already declared; use add_tier()/connect_tiers() to extend it")
        self.topology = three_tier_topology(edge_fog, fog_cloud, edge_access, fog_access, cloud_access)
        return self.topology

    def effective_access_profile(self, node_name: str) -> LinkProfile:
        """Access link actually applied to ``node_name``: node ``link_params`` over its tier default."""
        spec = self.node_specs.get(node_name)
        if spec is not None:
            tier, own = spec.tier, LinkProfile.from_params(spec.link_params)
        elif self.client_container is not None and getattr(self.client_container, "name", None) == node_name:
            tier, own = self.client_tier, self._client_link
        else:
            raise TopologyError(f"unknown node {node_name!r}")
        base = LinkProfile()
        if self.topology is not None and tier in self.topology.tiers:
            base = self.topology.tiers[tier].access_link
        return own.merged_over(base)

    def describe_topology(self) -> Dict[str, Any]:
        """Human/JSON friendly view: tiers → switch → nodes (+ inter-tier links)."""
        tiers: Dict[str, Any] = {}
        members: List[Any] = [(s.name, s.ip, s.role, s.tier) for s in self.node_specs.values()]
        if self.client_container is not None:
            members.append((self.client_container.name, getattr(self.client_container, "ip", None), "client", self.client_tier))
        for name, ip, role, tier in members:
            key = tier or "(single-switch)"
            entry = tiers.setdefault(key, {"switch": self.tier_switches.get(tier) if tier else None, "nodes": []})
            entry["nodes"].append({"name": name, "ip": ip, "role": role, "access": self.effective_access_profile(name).to_params()})
        return {
            "mode": "multi-tier" if self.topology is not None else "single-switch",
            "tiers": tiers,
            "links": self.topology.describe()["links"] if self.topology is not None else [],
        }

    # ------------------------------------------------------------------
    # Topology Wiring
    # ------------------------------------------------------------------
    def _validate_tier_assignments(self) -> None:
        assert self.topology is not None
        self.topology.validate()
        declared = sorted(self.topology.tiers)
        for spec in self.node_specs.values():
            if spec.tier is None:
                raise TopologyError(f"node {spec.name!r} has no tier; pass tier=... (declared: {declared})")
            if spec.tier not in self.topology.tiers:
                raise TopologyError(f"node {spec.name!r}: unknown tier {spec.tier!r} (declared: {declared})")
        if self.client_container is not None:
            if self.client_tier is None:
                raise TopologyError(f"client has no tier; pass set_client(..., tier=...) (declared: {declared})")
            if self.client_tier not in self.topology.tiers:
                raise TopologyError(f"client: unknown tier {self.client_tier!r} (declared: {declared})")

    def _apply_access_profiles(self) -> None:
        """Merges tier access links into each container's ``link_params`` (before add_docker)."""
        for spec in self.node_specs.values():
            spec.container.link_params = self.effective_access_profile(spec.name).to_params()
        if self.client_container is not None:
            self.client_container.link_params = self.effective_access_profile(self.client_container.name).to_params()

    def _get_or_create_instance(self, name: str, resource_model: Any = None) -> Any:
        try:
            dc = self.exp.get_virtual_instance(name)
        except Exception:
            dc = None
        return dc if dc is not None else self.exp.add_virtual_instance(name, resource_model)

    def _attach_local_multitier(self) -> None:
        """One switch per tier, chained by shaped TCLinks (local FogbedExperiment only)."""
        assert self.topology is not None
        if getattr(getattr(self.exp, "net", None), "is_running", False):
            raise TopologyError(
                "attach_to_experiment() must run BEFORE exp.start(): inter-tier links cannot be added "
                "to a running Mininet"
            )
        self._apply_access_profiles()

        instances: Dict[str, Any] = {}
        for tname, tspec in self.topology.tiers.items():
            instances[tname] = self._get_or_create_instance(tname, tspec.resource_model)
            self.tier_switches[tname] = instances[tname].switch

        for spec in self.node_specs.values():
            self.exp.add_docker(spec.container, datacenter=instances[spec.tier])
        if self.client_container is not None:
            self.exp.add_docker(self.client_container, datacenter=instances[self.client_tier])

        for link in self.topology.links:
            self.exp.add_link(instances[link.a], instances[link.b], **link.profile.to_params())
            logger.info(
                "link %s(%s) <-> %s(%s): %s", link.a, self.tier_switches[link.a],
                link.b, self.tier_switches[link.b], link.profile.describe(),
            )

    def attach_to_experiment(self, datacenter_name: str = "cloud") -> None:
        """Wires every node into the Fogbed experiment.

        * no tiers declared → classic single switch (``datacenter_name``), behaviour unchanged;
        * tiers declared    → one switch per tier, chained by shaped inter-tier links.
        """
        if self._topology_built:
            return

        if self.topology is None:
            assigned = {s.tier for s in self.node_specs.values() if s.tier}
            if self.client_tier:
                assigned.add(self.client_tier)
            if assigned:
                raise TopologyError(
                    f"nodes were assigned to tiers {sorted(assigned)} but none is declared: call "
                    "use_three_tier_topology() or add_tier()/connect_tiers() first"
                )
        else:
            self._validate_tier_assignments()

        if self.topology is not None and self.is_distributed:
            if self.topology.links:
                logger.warning(
                    "FogbedDistributedExperiment has no add_link(): inter-tier link shaping is NOT applied; "
                    "only per-node access-link shaping is. Use the local FogbedExperiment for full multi-tier."
                )
            self._apply_access_profiles()

        if self.topology is not None and not self.is_distributed:
            self._attach_local_multitier()
            self._topology_built = True
            logger.info("✅ All nodes attached to experiment (multi-tier: %s)", self.tier_switches)
        else:
            self._attach_legacy(datacenter_name)

    def _attach_legacy(self, datacenter_name: str) -> None:
        if self.is_distributed:
            for worker in self.workers:
                self.exp.add_worker(worker.ip, port=worker.fogbed_port)

            for spec in self.node_specs.values():
                dc = self.exp.add_virtual_instance(f"dc-{spec.name}")
                self.exp.add_docker(spec.container, dc)
                if spec.worker:
                    self.exp.get_worker(spec.worker.ip).add(dc, reachable=True)
            if len(self.workers) >= 2:
                self.exp.add_tunnel(self.exp.get_worker(self.workers[0].ip), self.exp.get_worker(self.workers[1].ip))
        else:
            # Local FogbedExperiment
            try:
                dc = self.exp.get_virtual_instance(datacenter_name)
            except Exception:
                dc = None
            if dc is None:
                dc = self.exp.add_virtual_instance(datacenter_name)

            for spec in self.node_specs.values():
                self.exp.add_docker(spec.container, datacenter=dc)

            if self.client_container:
                self.exp.add_docker(self.client_container, datacenter=dc)

        self._topology_built = True
        logger.info("✅ All nodes attached to experiment")

    # ------------------------------------------------------------------
    # Two-step Genesis Execution
    # ------------------------------------------------------------------
    def generate_genesis_artifacts(self) -> None:
        """Executes Step 1 (committee prep) and Step 2 (genesis build) deterministically."""
        validators = [s for s in self.node_specs.values() if s.role == "validator"]
        gateways = [s for s in self.node_specs.values() if s.role == "fullnode"]

        if not validators:
            raise GenesisError("At least one validator is required to generate genesis.")

        val_tuples = [(v.name, v.ip) for v in validators]
        gw_tuples = [(g.name, g.ip) for g in gateways]

        spec = CommitteeSpec(
            network_name="fogbed-iota",
            validators=val_tuples,
            gateways=gw_tuples,
            subnet=None,  # Accept any valid non-loopback IP
        )

        tools = ToolRunner(image=self.image)
        logger.info("Step 1: Preparing deterministic committee state...")
        committee = prepare_committee(
            state_dir=self.genesis_dir,
            spec=spec,
            tools=tools,
            force=True,
        )

        logger.info("Step 2: Building genesis.blob and node configurations...")
        builder = GenesisBuilder(tools=tools)
        self.genesis_artifacts = builder.build(
            committee=committee,
            output_dir=self.generated_dir,
            container_config_dir="/custom_config",
        )

    def _sync_and_boot_local(self) -> None:
        """Injects artifacts and boots nodes in local Fogbed containers."""
        if not self.genesis_artifacts:
            raise GenesisError("Genesis artifacts not generated.")

        for name, spec in self.node_specs.items():
            node_art = self.genesis_artifacts.nodes.get(name)
            if not node_art:
                continue

            logger.info(f"Injecting configuration into mn.{name}...")
            # Ensure target config directory exists
            subprocess.run(["docker", "exec", f"mn.{name}", "mkdir", "-p", "/custom_config"], check=True)

            # Copy validator.yaml and genesis.blob into container
            subprocess.run(
                ["docker", "cp", f"{node_art.validator_yaml}", f"mn.{name}:/custom_config/validator.yaml"],
                check=True,
            )
            subprocess.run(
                ["docker", "cp", f"{node_art.genesis_blob}", f"mn.{name}:/custom_config/genesis.blob"],
                check=True,
            )

            # Boot iota-node using the container entrypoint
            logger.info(f"Starting iota-node inside mn.{name}...")
            boot_cmd = (
                "set -e; "
                "mkdir -p /var/log/iota; "
                "nohup /usr/local/bin/iota-node --config-path /custom_config/validator.yaml "
                "> /var/log/iota/iota-node.log 2>&1 & "
                "echo $! > /var/log/iota/iota-node.pid"
            )
            subprocess.run(["docker", "exec", "-d", f"mn.{name}", "bash", "-c", boot_cmd], check=True)

    def _sync_and_boot_distributed(self) -> None:
        """Ships files to remote workers and boots nodes via SSH."""
        if not self.genesis_artifacts:
            raise GenesisError("Genesis artifacts not generated.")

        for session in self.sessions:
            session.connect()

        try:
            for name, spec in self.node_specs.items():
                if not spec.worker:
                    continue
                node_art = self.genesis_artifacts.nodes.get(name)
                if not node_art:
                    continue

                session = next(s for s in self.sessions if s.endpoint.ip == spec.worker.ip)
                session.mkdir_p(spec.remote_config_dir)
                session.put_file(node_art.validator_yaml, f"{spec.remote_config_dir}/validator.yaml")
                session.put_file(node_art.genesis_blob, f"{spec.remote_config_dir}/genesis.blob")

                boot_cmd = f"docker exec -d mn.{name} /usr/local/bin/iota-entrypoint.sh start-node"
                session.run(boot_cmd)
        finally:
            for session in self.sessions:
                session.close()

    def _wait_for_readiness(self, timeout: Optional[int] = None) -> None:
        """Polls gateway RPC until chain identifier is available."""
        if timeout is None:
            # shaped multi-tier links slow down checkpoint sync => give the gateway longer by default
            timeout = self.readiness_timeout or (240 if self.topology is not None else 120)
        gateways = [s for s in self.node_specs.values() if s.role == "fullnode"]
        target = gateways[0] if gateways else next(iter(self.node_specs.values()), None)
        if target is None:
            return

        logger.info(f"Waiting for RPC on {target.name} ({target.ip}:9000)...")
        deadline = time.time() + timeout
        payload = json.dumps({"jsonrpc": "2.0", "method": "iota_getChainIdentifier", "params": [], "id": 1})
        check_cmd = [
            "docker", "exec", f"mn.{target.name}",
            "curl", "-s", "-X", "POST", "http://127.0.0.1:9000",
            "-H", "Content-Type: application/json",
            "-d", payload,
        ]

        while time.time() < deadline:
            res = subprocess.run(check_cmd, capture_output=True, text=True)
            if '"result"' in res.stdout:
                logger.info(f"✅ Node {target.name} RPC is ready!")
                return
            time.sleep(2)

        # Failure diagnosis: fetch tail of log
        tail_res = subprocess.run(["docker", "exec", f"mn.{target.name}", "tail", "-n", "30", "/var/log/iota/iota-node.log"], capture_output=True, text=True)
        raise NodeStartError(
            f"Node {target.name} failed to expose RPC within {timeout}s",
            hint=f"Check logs:\n{tail_res.stdout or tail_res.stderr}",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Main startup sequence."""
        logger.info("=" * 60)
        logger.info(f"Starting IOTA Network (Release {self.release.tag})")
        logger.info("=" * 60)

        # 1. Generate artifacts using the two-step genesis
        self.generate_genesis_artifacts()

        # 2. Inject configs and boot
        if self.is_distributed:
            self._sync_and_boot_distributed()
        else:
            self._sync_and_boot_local()

        # 3. Wait for readiness
        self._wait_for_readiness()
        logger.info("✅ IOTA Network is running and verified!")

        # 4. Give the (edge) client a client.yaml pointing at the gateway + the funded keystore
        if self.client_container is not None and not self.is_distributed:
            try:
                self.provision_client()
            except Exception as exc:  # the network is up; a client problem must not tear it down
                logger.warning("edge client provisioning failed: %s", exc)

    def run(self) -> None:
        self.start()

    # ------------------------------------------------------------------
    # Edge client provisioning + end-to-end verification
    # ------------------------------------------------------------------
    @staticmethod
    def _keystore_addresses(path: Path) -> List[str]:
        """Addresses stored in an IOTA v2 file keystore (``{"version":2,"keys":[{"address":...}]}``)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        keys = data.get("keys", []) if isinstance(data, dict) else []
        return [k["address"] for k in keys if isinstance(k, dict) and k.get("address")]

    def provision_client(self) -> bool:
        """Installs ``client.yaml`` (RPC = gateway) and the *funded* genesis keystore in the client.

        ``iota-localnet genesis --from-config`` writes no keystore and its ``client.yaml`` targets
        127.0.0.1 / public networks, so neither is usable from the edge. The funded keys are those of
        ``benchmark.keystore`` (same addresses as the genesis ``accounts``).
        """
        client = self.client_container
        if client is None:
            return False
        if self.is_distributed:
            logger.warning("client provisioning is only implemented for the local (non-distributed) mode")
            return False
        gateways = [s for s in self.node_specs.values() if s.role == "fullnode"]
        keystore = self.genesis_artifacts.iota_keystore if self.genesis_artifacts else None
        if not gateways or keystore is None or not Path(keystore).is_file():
            logger.warning("cannot provision client: needs a gateway and the funded genesis keystore")
            return False

        gw = gateways[0]
        addresses = self._keystore_addresses(Path(keystore))
        self.client_recipient = addresses[1] if len(addresses) > 1 else (addresses[0] if addresses else None)

        name = f"mn.{client.name}"
        env = subprocess.run(["docker", "exec", name, "printenv", "IOTA_CONFIG_DIR"], capture_output=True, text=True)
        cfg_dir = (env.stdout or "").strip() or "/iota/config"  # image default; the CLI reads $IOTA_CONFIG_DIR

        cfg = {
            "keystore": {"File": f"{cfg_dir}/iota.keystore"},
            "envs": [{
                "alias": "fogbed", "rpc": f"http://{gw.ip}:9000", "graphql": None, "ws": None,
                "grpc": f"http://{gw.ip}:{getattr(gw, 'grpc_port', 50051)}", "basic_auth": None, "faucet": None,
            }],
            "active_env": "fogbed",
            "active_address": addresses[0] if addresses else None,
        }
        staging = self.workspace_root / "client_provision"
        staging.mkdir(parents=True, exist_ok=True)
        cfg_file = staging / "client.yaml"
        cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

        subprocess.run(["docker", "exec", name, "mkdir", "-p", cfg_dir, "/app/config"], check=True)
        subprocess.run(["docker", "cp", str(keystore), f"{name}:{cfg_dir}/iota.keystore"], check=True)
        subprocess.run(["docker", "cp", str(cfg_file), f"{name}:{cfg_dir}/client.yaml"], check=True)
        subprocess.run(["docker", "cp", str(cfg_file), f"{name}:/app/config/client.yaml"], check=True)

        self.client_config_path = f"{cfg_dir}/client.yaml"
        self.client_provisioned = True
        logger.info("✅ Edge client %s provisioned: rpc=http://%s:9000 active=%s", client.name, gw.ip, cfg["active_address"])
        return True

    def validate_topology(self, **kwargs: Any) -> Any:
        """Runs the cross-tier verification (see ``fogbed_iota.multitier_check``); returns a report."""
        from .multitier_check import validate_topology as _validate

        return _validate(self, **kwargs)

    def get_rpc_url(self, host: bool = False) -> Optional[str]:
        gateways = [s for s in self.node_specs.values() if s.role == "fullnode"]
        if gateways:
            ip = "localhost" if host else gateways[0].ip
            return f"http://{ip}:9000"
        return None

    def get_metrics_url(self, host: bool = False) -> Optional[str]:
        gateways = [s for s in self.node_specs.values() if s.role == "fullnode"]
        if gateways:
            ip = "localhost" if host else gateways[0].ip
            return f"http://{ip}:9184/metrics"
        return None


DistributedIotaMaster = IotaNetwork

__all__ = [
    "IotaNetwork",
    "IotaNode",
    "NodeSpec",
    "WorkerEndpoint",
    "RemoteWorkerSession",
    "DistributedIotaMaster",
]
