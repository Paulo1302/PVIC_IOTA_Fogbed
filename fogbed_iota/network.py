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

try:
    from fogbed import Container, FogbedExperiment, FogbedDistributedExperiment
except (ImportError, AttributeError):
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
    worker: Optional[WorkerEndpoint] = None
    datacenter_name: str = "cloud"
    local_config_dir: Optional[Path] = None
    remote_config_dir: Optional[str] = None
    assigned_ip: Optional[str] = None


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
    ):
        _configure_logging(log_level)
        self.image = image
        self.auto_cleanup = auto_cleanup
        self.release = load_release()

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
    def add_validator(self, name: str, ip: str) -> IotaNode:
        """Registers a validator node with static IP."""
        logger.info(f"Adding validator: {name} @ {ip}")
        worker = self.workers[0] if (self.is_distributed and self.workers) else None
        container = IotaNode(name=name, ip=ip, role="validator", port_offset=len(self.node_specs), image=self.image)
        spec = NodeSpec(
            name=name,
            role="validator",
            ip=ip,
            container=container,
            port_offset=len(self.node_specs),
            worker=worker,
            datacenter_name="cloud",
            local_config_dir=self.generated_dir / name,
            remote_config_dir=f"{self.remote_volume_root}/{name}" if worker else None,
            assigned_ip=ip,
        )
        self.node_specs[name] = spec
        return container

    def add_gateway(
        self,
        name: str,
        ip: str,
        port_bindings: Optional[Dict[int, int]] = None,
        bind_host_ports: bool = True,
        **kwargs: Any,
    ) -> IotaNode:
        """Registers a gateway (fullnode) node with static IP."""
        logger.info(f"Adding gateway (fullnode): {name} @ {ip}")
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
            **kwargs,
        )
        spec = NodeSpec(
            name=name,
            role="fullnode",
            ip=ip,
            container=container,
            port_offset=len(self.node_specs),
            worker=worker,
            datacenter_name="cloud",
            local_config_dir=self.generated_dir / name,
            remote_config_dir=f"{self.remote_volume_root}/{name}" if worker else None,
            assigned_ip=ip,
        )
        self.node_specs[name] = spec
        return container

    def set_client(self, container: Container) -> None:
        """Registers a client container for user interactions / smart contracts."""
        logger.info(f"Setting client container: {container.name}")
        self.client_container = container

    # ------------------------------------------------------------------
    # Topology Wiring
    # ------------------------------------------------------------------
    def attach_to_experiment(self, datacenter_name: str = "cloud") -> None:
        if self._topology_built:
            return

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

    def _wait_for_readiness(self, timeout: int = 120) -> None:
        """Polls gateway RPC until chain identifier is available."""
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

    def run(self) -> None:
        self.start()

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
