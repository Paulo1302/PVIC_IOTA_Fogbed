"""
Orquestração de rede IOTA com Fogbed - VERSÃO CORRIGIDA
Corrige formato das chaves no gateway config
"""

import os
import shutil
import subprocess
import time
import json
import atexit
import signal
import sys
from typing import List, Optional, TYPE_CHECKING

from fogbed import Container, FogbedExperiment
from fogbed_iota.utils import get_logger

# Importando submódulos refatorados
from fogbed_iota.models.iota_node import IotaNode
from fogbed_iota.utils.genesis import ensure_iota_binary, generate_genesis
from fogbed_iota.utils.config import prepare_configs
from fogbed_iota.utils.lifecycle import inject_and_boot, wait_for_network_ready

if TYPE_CHECKING:
    from fogbed_iota.accounts import AccountManager
    from fogbed_iota.contracts import SmartContractManager

logger = get_logger('network')

WORK_DIR = "/tmp/fogbed_iota_workdir"
GENESIS_DIR = os.path.join(WORK_DIR, "genesis")
LIVE_DATA_DIR = os.path.join(WORK_DIR, "live_data")
DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")


class IotaNetwork:
    """Orquestrador principal da rede IOTA."""

    def __init__(
        self,
        experiment: FogbedExperiment,
        image: str = DEFAULT_IMAGE,
        log_level: str = "INFO",
        auto_cleanup: bool = True
    ):
        logger.info(f"Initializing IotaNetwork with image: {image}")
        self.exp = experiment
        self.image = image
        self.auto_cleanup = auto_cleanup
        self.nodes: List[IotaNode] = []
        self.client_container: Optional[Container] = None
        self._iota_binary_path: Optional[str] = None
        self._iota_version: Optional[str] = None
        self._cleanup_registered = False
        self.account_manager: Optional["AccountManager"] = None
        self.contract_manager: Optional["SmartContractManager"] = None

        if self.auto_cleanup:
            self._register_cleanup_handlers()

    def _register_cleanup_handlers(self) -> None:
        if self._cleanup_registered:
            return
        atexit.register(self._cleanup_on_exit)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        self._cleanup_registered = True
        logger.debug("✅ Cleanup handlers registered")

    def _signal_handler(self, signum, frame):
        logger.info(f"\n⚠️  Received signal {signum}, cleaning up...")
        self.stop()
        sys.exit(0)

    def _cleanup_on_exit(self) -> None:
        if self.auto_cleanup:
            logger.info("🧹 Auto-cleanup on exit...")
            self._cleanup_work_dir()

    def stop(self) -> None:
        logger.info("🛑 Stopping IOTA Network...")
        for node in self.nodes:
            try:
                node.cmd("pkill -9 iota-node 2>/dev/null || true")
                logger.debug(f"Stopped {node.name}")
            except Exception as e:
                logger.warning(f"Failed to stop {node.name}: {e}")
        if self.auto_cleanup:
            self._cleanup_work_dir()
        logger.info("✅ IOTA Network stopped")

    def _cleanup_work_dir(self) -> None:
        if os.path.exists(WORK_DIR):
            try:
                shutil.rmtree(WORK_DIR)
                logger.info(f"✅ Cleaned up work directory: {WORK_DIR}")
            except Exception as e:
                logger.warning(f"Failed to cleanup {WORK_DIR}: {e}")
        if self._iota_binary_path and "/tmp/" in self._iota_binary_path:
            try:
                temp_dir = os.path.dirname(self._iota_binary_path)
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.debug(f"Cleaned up temp binary: {temp_dir}")
            except Exception as e:
                logger.debug(f"Failed to cleanup temp binary: {e}")

    def add_validator(self, name: str, ip: str) -> IotaNode:
        logger.info(f"Adding validator: {name} @ {ip}")
        node = IotaNode(name=name, ip=ip, role="validator", port_offset=len(self.nodes), image=self.image)
        self.nodes.append(node)
        logger.debug(f"✅ Validator {name} added (P2P: {node.p2p_port})")
        return node

    def add_gateway(self, name: str, ip: str) -> IotaNode:
        logger.info(f"Adding gateway (fullnode): {name} @ {ip}")
        node = IotaNode(name=name, ip=ip, role="fullnode", port_offset=len(self.nodes), image=self.image)
        self.nodes.append(node)
        logger.debug(f"✅ Gateway {name} added (RPC: {node.rpc_port})")
        return node

    def set_client(self, container: Container) -> None:
        logger.info(f"Setting client container: {container.name}")
        self.client_container = container

    def attach_to_experiment(self, datacenter_name: str = "cloud") -> None:
        logger.info(f"Attaching nodes to datacenter: {datacenter_name}")
        try:
            cloud = self.exp.get_virtual_instance(datacenter_name)
        except Exception:
            cloud = None
        if cloud is None:
            logger.debug(f"Creating virtual instance: {datacenter_name}")
            cloud = self.exp.add_virtual_instance(datacenter_name)
        for node in self.nodes:
            self.exp.add_docker(node, datacenter=cloud)
            logger.debug(f"✅ Node {node.name} attached")
        if self.client_container:
            self.exp.add_docker(self.client_container, datacenter=cloud)
            logger.debug(f"✅ Client {self.client_container.name} attached")
        logger.info(f"✅ All nodes attached to {datacenter_name}")

    def start(self) -> None:
        logger.info("=" * 60)
        logger.info("Starting IOTA Network Initialization")
        logger.info("=" * 60)
        self._cleanup()
        
        self._iota_binary_path = ensure_iota_binary(self.image, self._iota_binary_path)
        
        validators = [n for n in self.nodes if n.role == "validator"]
        generate_genesis(validators, GENESIS_DIR, self._iota_binary_path)
        
        prepare_configs(self.nodes, GENESIS_DIR, LIVE_DATA_DIR)
        
        inject_and_boot(self.nodes, LIVE_DATA_DIR)
        
        wait_for_network_ready(self.nodes)
        
        self._configure_client()
        self._setup_smart_contract_env()
        
        logger.info("=" * 60)
        logger.info("✅ IOTA Network Successfully Started!")
        logger.info("=" * 60)
        self._print_network_summary()

    def _cleanup(self) -> None:
        logger.debug(f"Cleaning up work directory: {WORK_DIR}")
        if os.path.exists(WORK_DIR):
            shutil.rmtree(WORK_DIR)
        os.makedirs(GENESIS_DIR, exist_ok=True)
        os.makedirs(LIVE_DATA_DIR, exist_ok=True)
        logger.info("✅ Work directories ready")

    def _configure_client(self) -> None:
        if not self.client_container:
            logger.debug("No client container to configure")
            return
        logger.info("📱 Configuring client container (genesis bank keystore)")
        rpc_node = next((n for n in self.nodes if n.role == "fullnode"), self.nodes[0] if self.nodes else None)
        if not rpc_node:
            raise RuntimeError("No nodes available for client configuration")
        self.client_container.cmd("mkdir -p /app/config /root/.iota /root/.iota/iota_config")
        benchmark_keystore = os.path.join(GENESIS_DIR, "benchmark.keystore")
        default_keystore = os.path.join(GENESIS_DIR, "iota.keystore")
        host_keystore = benchmark_keystore if os.path.exists(benchmark_keystore) else default_keystore
        if not os.path.exists(host_keystore):
            logger.warning("⚠️ No genesis keystore found, client may not have funds")
        else:
            cmd_cp = f"docker cp {host_keystore} mn.{self.client_container.name}:/app/config/iota.keystore"
            rc = os.system(cmd_cp)
            if rc != 0:
                raise RuntimeError(f"Failed to copy keystore to client (rc={rc})")
            self.client_container.cmd("cp -f /app/config/iota.keystore /root/.iota/iota.keystore")
            logger.debug(f"✅ Genesis keystore copied from {os.path.basename(host_keystore)}")
        rpc_url = f"http://{rpc_node.ip_addr}:{rpc_node.rpc_port}"
        yaml_content = f"""---
keystore:
  File: /app/config/iota.keystore
envs:
  - alias: localnet
    rpc: "{rpc_url}"
    ws: ~
    basic_auth: ~
    faucet: ~
active_env: localnet
"""
        self.client_container.cmd(f"cat > /app/config/client.yaml << 'EOF'\n{yaml_content}\nEOF")
        self.client_container.cmd("cp -f /app/config/client.yaml /root/.iota/iota_config/client.yaml")
        validate_cmd = 'python3 -c "import yaml; yaml.safe_load(open(\'/app/config/client.yaml\'))" 2>&1'
        validate_result = self.client_container.cmd(validate_cmd)
        if "error" in validate_result.lower() or "exception" in validate_result.lower():
            logger.error(f"❌ Generated client.yaml is invalid:\n{validate_result}")
            raise RuntimeError("Invalid client.yaml generated")
        logger.debug("✅ client.yaml validated")
        self.client_container.cmd("sh -lc 'iota client --client.config /app/config/client.yaml envs 2>&1 || true'")
        logger.info(f"✅ Client configured (RPC: {rpc_url})")

    def _setup_smart_contract_env(self) -> None:
        if not self.client_container:
            logger.warning("No client container - skipping smart contract setup")
            return
        logger.info("Setting up smart contract environment")
        try:
            from fogbed_iota.client.cli import IotaCLI
            from fogbed_iota.accounts import AccountManager
            from fogbed_iota.contracts import SmartContractManager
            
            cli = IotaCLI(self.client_container)
            self.account_manager = AccountManager(self.client_container)
            self.contract_manager = SmartContractManager(cli, self.account_manager)
            
            logger.info("✅ SmartContractManager created with IotaCLI integration")
        except ImportError as e:
            raise RuntimeError(f"Smart contract modules missing: {e}")
        self.client_container.cmd("mkdir -p /contracts /contracts/examples")
        logger.info("✅ Smart contract environment ready")

    def _print_network_summary(self) -> None:
        validators = [n for n in self.nodes if n.role == "validator"]
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        logger.info("")
        logger.info("📊 Network Summary:")
        logger.info(f" Validators: {len(validators)}")
        for v in validators:
            logger.info(f"  - {v.name}: {v.ip_addr} (P2P: tcp/{v.p2p_port})")
        for gw in fullnodes:
            logger.info(f" Gateway: {gw.name}")
            logger.info(f"  - Address: {gw.ip_addr}")
            logger.info(f"  - RPC: http://{gw.ip_addr}:{gw.rpc_port}")
            logger.info(f"  - Metrics: http://{gw.ip_addr}:{gw.metrics_port}/metrics")
        if self.client_container:
            logger.info(f" Client: {self.client_container.name}")
            logger.info(f"  - Config: /app/config/client.yaml")
        logger.info("")

    def get_rpc_url(self) -> Optional[str]:
        gateway = next((n for n in self.nodes if n.role == "fullnode"), None)
        if gateway:
            return f"http://{gateway.ip_addr}:{gateway.rpc_port}"
        return None

    def get_metrics_url(self) -> Optional[str]:
        gateway = next((n for n in self.nodes if n.role == "fullnode"), None)
        if gateway:
            return f"http://{gateway.ip_addr}:{gateway.metrics_port}/metrics"
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    @classmethod
    def create_network(cls, experiment: FogbedExperiment, validators: int = 4, gateways: int = 1, image: str = DEFAULT_IMAGE) -> "IotaNetwork":
        net = cls(experiment, image=image, auto_cleanup=True)
        for i in range(1, validators + 1):
            net.add_validator(f"validator{i}", f"10.0.0.{i}")
        for i in range(gateways):
            net.add_gateway(f"gateway{i+1}", f"10.0.0.{100+i}")
        return net
