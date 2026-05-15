#!/usr/bin/env python3
"""
Master orchestrator for the distributed PVIC_IOTA_Fogbed deployment.

Flow:
1. Create the distributed Fogbed topology and allocate containers.
2. Start the experiment only to allocate the network and capture the assigned IPs.
3. Generate genesis/network artifacts centrally using the IOTA Docker image.
4. Ship the resulting files to each worker over SSH/SFTP.
5. Bootstrap the nodes remotely inside the already running containers.
"""

from __future__ import annotations

import argparse
import atexit
import importlib
import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import yaml

from fogbed import Container, FogbedDistributedExperiment


LOG = logging.getLogger("orquestrador_master")


def _configure_logging() -> None:
    if LOG.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)


@dataclass(frozen=True)
class WorkerEndpoint:
    """Physical worker reachable by both Fogbed and SSH."""

    ip: str
    fogbed_port: int = 5000
    ssh_port: int = 22
    username: str = field(default_factory=lambda: os.getenv("FOGBED_SSH_USER", "paulo"))
    password: Optional[str] = field(default_factory=lambda: os.getenv("FOGBED_SSH_PASSWORD"))
    key_filename: Optional[str] = field(default_factory=lambda: os.getenv("FOGBED_SSH_KEY"))
    remote_root: str = field(default_factory=lambda: os.getenv("FOGBED_REMOTE_ROOT", "/tmp/pvic_iota_fogbed"))


@dataclass
class NodeSpec:
    """Runtime metadata for a single IOTA node."""

    name: str
    role: str
    worker: WorkerEndpoint
    datacenter_name: str
    container: Container
    datacenter: object
    local_config_dir: Path
    remote_config_dir: str
    assigned_ip: Optional[str] = None


class RemoteWorkerSession:
    """Small SSH/SFTP helper around paramiko."""

    def __init__(self, endpoint: WorkerEndpoint) -> None:
        self.endpoint = endpoint
        try:
            self.paramiko = importlib.import_module("paramiko")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "paramiko is required for distributed orchestration. Install it with "
                "'pip install paramiko' or 'pip install -e .'"
            ) from exc
        self.client = self.paramiko.SSHClient()
        self.client.set_missing_host_key_policy(self.paramiko.AutoAddPolicy())

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
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if exit_status != 0:
            raise RuntimeError(
                f"SSH command failed on {self.endpoint.ip} (exit {exit_status}): {err.strip() or out.strip()}"
            )
        return out


class DistributedIotaMaster:
    """Orchestrates the two-step genesis and distributed boot sequence."""

    def __init__(
        self,
        image: str = "iota-fogbed-node:1.15.0",
        workers: Optional[Sequence[WorkerEndpoint]] = None,
        remote_volume_root: str = "/tmp/pvic_iota_fogbed/volumes",
        workspace_root: Optional[Path] = None,
    ) -> None:
        _configure_logging()
        self.image = image
        self.workers = list(
            workers
            or [
                WorkerEndpoint("192.168.1.10"),
                WorkerEndpoint("192.168.1.11"),
            ]
        )
        if len(self.workers) != 2:
            raise ValueError("This orchestrator expects exactly two workers.")

        self.remote_volume_root = remote_volume_root
        self.exp = FogbedDistributedExperiment()
        self._workspace_owner = None
        self.workspace_root = workspace_root or Path(tempfile.mkdtemp(prefix="pvic_iota_fogbed_"))
        self.genesis_dir = self.workspace_root / "genesis"
        self.nodes_dir = self.workspace_root / "nodes"
        self.generated_dir = self.workspace_root / "generated"
        self.sessions = [RemoteWorkerSession(worker) for worker in self.workers]
        self.node_specs: Dict[str, NodeSpec] = {}

        atexit.register(self.cleanup_workspace)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def cleanup_workspace(self) -> None:
        if self._workspace_owner is not None:
            return
        if self.workspace_root.exists():
            shutil.rmtree(self.workspace_root, ignore_errors=True)

    def connect_workers(self) -> None:
        for session in self.sessions:
            LOG.info("Connecting to worker %s", session.endpoint.ip)
            session.connect()
            session.mkdir_p(session.endpoint.remote_root)

    def prepare_remote_mounts(self) -> None:
        for session in self.sessions:
            session.mkdir_p(session.endpoint.remote_root)
            session.mkdir_p(self.remote_volume_root)
            for name in ("client", "device", "gateway"):
                session.mkdir_p(str(Path(self.remote_volume_root) / name))

    def _node_remote_dir(self, worker: WorkerEndpoint, node_name: str) -> str:
        return f"{self.remote_volume_root}/{node_name}"

    def _create_node(
        self,
        name: str,
        role: str,
        worker: WorkerEndpoint,
        delay: str,
        bw: int,
    ) -> NodeSpec:
        datacenter = self.exp.add_virtual_instance(f"dc-{name}")
        container = Container(
            name=name,
            dimage=self.image,
            ip=None,
            privileged=True,
            dcmd="wait",
            environment={
                "IOTA_CONFIG_DIR": "/iota/config",
                "IOTA_NODE_ROLE": role,
                "RUST_LOG": "info,iota=debug",
            },
            volumes=[f"{self._node_remote_dir(worker, name)}:/iota/config"],
            link_params={"delay": delay, "bw": bw},
        )
        self.exp.add_docker(container, datacenter)
        self.exp.get_worker(worker.ip).add(datacenter, reachable=True)
        node = NodeSpec(
            name=name,
            role=role,
            worker=worker,
            datacenter_name=datacenter.label,
            container=container,
            datacenter=datacenter,
            local_config_dir=self.generated_dir / name,
            remote_config_dir=self._node_remote_dir(worker, name),
        )
        self.node_specs[name] = node
        return node

    def build_topology(self) -> None:
        LOG.info("Building distributed Fogbed topology")
        for worker in self.workers:
            self.exp.add_worker(worker.ip, port=worker.fogbed_port)

        client = self._create_node("client", "validator", self.workers[0], delay="50ms", bw=10)
        device = self._create_node("device", "validator", self.workers[0], delay="50ms", bw=10)
        gateway = self._create_node("gateway", "fullnode", self.workers[1], delay="20ms", bw=50)

        # Local emulation on the first worker.
        self.exp.get_worker(self.workers[0].ip).add_link(
            client.datacenter,
            device.datacenter,
            delay="50ms",
            bw=10,
        )

        # Cross-worker connectivity is handled by FogbedDistributedExperiment tunnels.
        self.exp.add_tunnel(self.exp.get_worker(self.workers[0].ip), self.exp.get_worker(self.workers[1].ip))

        LOG.info(
            "Mapped nodes: %s",
            ", ".join(
                f"{node.name}@{node.worker.ip}" for node in (client, device, gateway)
            ),
        )

    # ------------------------------------------------------------------
    # Two-step genesis generation
    # ------------------------------------------------------------------
    def _run_docker(self, args: Sequence[str], cwd: Optional[Path] = None) -> None:
        LOG.info("Running: %s", " ".join(shlex.quote(part) for part in args))
        subprocess.run(list(args), cwd=str(cwd) if cwd else None, check=True)

    def _validator_nodes(self) -> List[NodeSpec]:
        return [self.node_specs["client"], self.node_specs["device"]]

    def _all_nodes(self) -> List[NodeSpec]:
        return [self.node_specs["client"], self.node_specs["device"], self.node_specs["gateway"]]

    def capture_ips(self) -> None:
        # Fogbed assigns the IPs when the containers are instantiated; we capture them
        # after exp.start() to make the workflow explicit and to log the runtime mapping.
        for node in self._all_nodes():
            node.assigned_ip = node.container.ip
            LOG.info("%s assigned IP %s", node.name, node.assigned_ip)

    def generate_genesis_artifacts(self) -> None:
        LOG.info("Generating central genesis artifacts")
        self.genesis_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        validator_ips = [node.assigned_ip for node in self._validator_nodes()]
        if any(ip is None for ip in validator_ips):
            raise RuntimeError("Missing validator IPs; capture_ips() must run after exp.start().")

        cmd = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/usr/local/bin/iota",
            "-v",
            f"{self.genesis_dir}:/work",
            self.image,
            "genesis",
            "--working-dir",
            "/work",
            "--force",
            "--committee-size",
            str(len(validator_ips)),
            "--benchmark-ips",
            *[ip for ip in validator_ips if ip is not None],
            "--chain-start-timestamp-ms",
            str(int(time.time() * 1000)),
            "--epoch-duration-ms",
            "86400000",
        ]
        self._run_docker(cmd)

        genesis_blob = self.genesis_dir / "genesis.blob"
        network_yaml = self.genesis_dir / "network.yaml"
        if not genesis_blob.exists():
            raise RuntimeError(f"genesis.blob not generated at {genesis_blob}")
        if not network_yaml.exists():
            raise RuntimeError(f"network.yaml not generated at {network_yaml}")

        self._patch_network_yaml(network_yaml, validator_ips)
        self._materialize_node_configs(genesis_blob, network_yaml)

    def _patch_network_yaml(self, path: Path, validator_ips: Sequence[str]) -> None:
        content = path.read_text(encoding="utf-8")
        data = None
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            data = None

        if isinstance(data, dict):
            if "validator_configs" in data:
                for index, cfg in enumerate(data["validator_configs"]):
                    if index >= len(validator_ips):
                        break
                    ip = validator_ips[index]
                    if isinstance(cfg, dict):
                        old = cfg.get("network-address")
                        if old:
                            cfg["network-address"] = f"/ip4/{ip}/tcp/8080/http"
                        p2p = cfg.get("p2p-config")
                        if isinstance(p2p, dict):
                            p2p["listen-address"] = "0.0.0.0:8080"
                            p2p["external-address"] = f"/ip4/{ip}/udp/8080/quic"
                path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
                return

            if "consensus" in data:
                consensus = data.setdefault("consensus", {})
                genesis = consensus.setdefault("genesis", {})
                genesis["validators"] = [{"address": f"{ip}:8080"} for ip in validator_ips]
                path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
                return

        # Fallback: textual patch for older genesis formats.
        lines = content.splitlines()
        patched: List[str] = []
        for line in lines:
            if "127.0.0.1" in line:
                replacement = line
                for ip in validator_ips:
                    if "127.0.0.1" in replacement:
                        replacement = replacement.replace("127.0.0.1", ip, 1)
                patched.append(replacement)
            else:
                patched.append(line)
        path.write_text("\n".join(patched) + "\n", encoding="utf-8")

    def _render_validator_config(
        self,
        self_ip: str,
        validator_ips: Sequence[str],
        rpc_port: int,
        is_gateway: bool = False,
    ) -> str:
        seed_peers = [
            {"address": f"/ip4/{ip}/udp/8080/quic"}
            for ip in validator_ips
            if ip != self_ip
        ]
        payload = {
            "node": {
                "db-path": "/var/lib/iota/mainnetdb",
                "grpc-bind-address": "0.0.0.0:9002",
                "rest-api-bind-address": f"0.0.0.0:{rpc_port}",
                "p2p-bind-address": "0.0.0.0:8080",
            },
            "consensus": {
                "authority-key-pair": {"path": "/iota/config/authority.key"},
                "network-key-pair": {"path": "/iota/config/network.key"},
                "genesis": {
                    "genesis-file-location": "/iota/config/genesis.blob",
                    "validators": [{"address": f"{ip}:8080"} for ip in validator_ips],
                },
                "p2p-config": {
                    "listen-address": "0.0.0.0:8080",
                    "external-address": f"/ip4/{self_ip}/udp/8080/quic",
                    "seed-peers": seed_peers,
                },
            },
        }
        if is_gateway:
            payload["node"]["rest-api-bind-address"] = "0.0.0.0:9000"
        return yaml.safe_dump(payload, sort_keys=False)

    def _materialize_node_configs(self, genesis_blob: Path, network_yaml: Path) -> None:
        validator_ips = [node.assigned_ip for node in self._validator_nodes()]
        validator_ips = [ip for ip in validator_ips if ip]

        for node in self._all_nodes():
            node_dir = node.local_config_dir
            node_dir.mkdir(parents=True, exist_ok=True)

            shutil.copy2(genesis_blob, node_dir / "genesis.blob")
            shutil.copy2(network_yaml, node_dir / "network.yaml")

            rpc_port = 9000 if node.role == "fullnode" else 9001
            config_name = "validator.yaml"
            (node_dir / config_name).write_text(
                self._render_validator_config(
                    self_ip=node.assigned_ip or "127.0.0.1",
                    validator_ips=validator_ips,
                    rpc_port=rpc_port,
                    is_gateway=node.role == "fullnode",
                ),
                encoding="utf-8",
            )

            # Keep a simple metadata file beside the configs to aid debugging.
            metadata = {
                "name": node.name,
                "role": node.role,
                "ip": node.assigned_ip,
                "worker": node.worker.ip,
            }
            (node_dir / "node.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

            # If keys were generated by the genesis command, ship them too.
            for key_name in ("authority.key", "network.key", "iota.keystore", "benchmark.keystore"):
                source = self.genesis_dir / key_name
                if source.exists():
                    shutil.copy2(source, node_dir / key_name)

    # ------------------------------------------------------------------
    # Distribution and boot
    # ------------------------------------------------------------------
    def _sync_node_configs(self) -> None:
        for session in self.sessions:
            session.connect()

        try:
            for node in self._all_nodes():
                session = next(s for s in self.sessions if s.endpoint.ip == node.worker.ip)
                session.mkdir_p(node.remote_config_dir)
                for file_name in ("genesis.blob", "network.yaml", "validator.yaml", "node.json"):
                    local_file = node.local_config_dir / file_name
                    if local_file.exists():
                        session.put_file(local_file, f"{node.remote_config_dir}/{file_name}")
                for key_name in ("authority.key", "network.key", "iota.keystore", "benchmark.keystore"):
                    local_file = node.local_config_dir / key_name
                    if local_file.exists():
                        session.put_file(local_file, f"{node.remote_config_dir}/{key_name}")
        finally:
            for session in self.sessions:
                session.close()

    def _boot_node(self, session: RemoteWorkerSession, node_name: str) -> None:
        container_name = f"mn.{node_name}"
        session.run(f"docker exec -d {shlex.quote(container_name)} /usr/local/bin/iota-entrypoint.sh start-node")

    def bootstrap_nodes(self) -> None:
        for session in self.sessions:
            session.connect()
        try:
            for node in self._all_nodes():
                session = next(s for s in self.sessions if s.endpoint.ip == node.worker.ip)
                self._boot_node(session, node.name)
            self._wait_for_gateway_rpc(self.sessions[1], "gateway")
        finally:
            for session in self.sessions:
                session.close()

    def _wait_for_gateway_rpc(self, session: RemoteWorkerSession, gateway_name: str, timeout: int = 180) -> None:
        deadline = time.time() + timeout
        container_name = f"mn.{gateway_name}"
        payload = (
            '{"jsonrpc":"2.0","method":"iota_getChainIdentifier","params":[],"id":1}'
        )
        curl_cmd = (
            f"docker exec {shlex.quote(container_name)} "
            f"curl -s -X POST http://127.0.0.1:9000 "
            f"-H 'Content-Type: application/json' "
            f"-d '{payload}'"
        )

        while time.time() < deadline:
            try:
                output = session.run(curl_cmd, timeout=30)
                if "\"result\"" in output and "\"error\"" not in output:
                    LOG.info("Gateway RPC is responding")
                    return
            except Exception:
                time.sleep(3)
                continue
            time.sleep(3)
        raise RuntimeError("Gateway RPC did not become ready in time")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            self.connect_workers()
            self.prepare_remote_mounts()
            self.build_topology()
            LOG.info("Starting Fogbed only to allocate network namespaces")
            self.exp.start()
            self.capture_ips()
            self.generate_genesis_artifacts()
            self._sync_node_configs()
            self.bootstrap_nodes()
            LOG.info("Distributed deployment is up")
        except Exception:
            try:
                self.exp.stop()
            finally:
                raise


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PVIC_IOTA_Fogbed distributed master orchestrator")
    parser.add_argument("--image", default="iota-fogbed-node:1.15.0", help="Docker image to use")
    parser.add_argument("--worker-1", default="192.168.1.10", help="First Fogbed worker IP")
    parser.add_argument("--worker-2", default="192.168.1.11", help="Second Fogbed worker IP")
    parser.add_argument("--ssh-user", default=os.getenv("FOGBED_SSH_USER", "paulo"), help="SSH username")
    parser.add_argument("--ssh-password", default=os.getenv("FOGBED_SSH_PASSWORD"), help="SSH password")
    parser.add_argument("--ssh-key", default=os.getenv("FOGBED_SSH_KEY"), help="SSH private key")
    parser.add_argument("--remote-root", default=os.getenv("FOGBED_REMOTE_ROOT", "/tmp/pvic_iota_fogbed"))
    parser.add_argument("--fogbed-port", type=int, default=5000, help="Remote Fogbed API port")
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    workers = [
        WorkerEndpoint(
            ip=args.worker_1,
            fogbed_port=args.fogbed_port,
            username=args.ssh_user,
            password=args.ssh_password,
            key_filename=args.ssh_key,
            remote_root=args.remote_root,
        ),
        WorkerEndpoint(
            ip=args.worker_2,
            fogbed_port=args.fogbed_port,
            username=args.ssh_user,
            password=args.ssh_password,
            key_filename=args.ssh_key,
            remote_root=args.remote_root,
        ),
    ]

    orchestrator = DistributedIotaMaster(image=args.image, workers=workers, remote_volume_root=args.remote_root)
    orchestrator.run()


if __name__ == "__main__":
    main()
