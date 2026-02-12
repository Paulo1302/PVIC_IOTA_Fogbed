"""
Orquestração de rede IOTA com Fogbed - VERSÃO CORRIGIDA
Corrige formato das chaves no gateway config
"""

import os
import shutil
import glob
import re
import subprocess
import time
import json
import atexit
import signal
import sys
from typing import List, Optional, TYPE_CHECKING

from fogbed import Container, FogbedExperiment
from fogbed_iota.utils import get_logger, validate_node_config

if TYPE_CHECKING:
    from fogbed_iota.accounts import AccountManager
    from fogbed_iota.smart_contracts import SmartContractManager

logger = get_logger('network')

WORK_DIR = "/tmp/fogbed_iota_workdir"
GENESIS_DIR = os.path.join(WORK_DIR, "genesis")
LIVE_DATA_DIR = os.path.join(WORK_DIR, "live_data")
DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")
MIN_IOTA_VERSION = "1.15.0"


class IotaNode(Container):
    """Container Fogbed que roda um iota-node."""

    def __init__(
        self,
        name: str,
        ip: str,
        role: str = "validator",
        port_offset: int = 0,
        image: str = DEFAULT_IMAGE,
        **kwargs
    ):
        valid, errors = validate_node_config(name, ip, role, port_offset)
        if not valid:
            raise ValueError(f"Invalid node config: {errors}")

        self.role = role
        self.ip_addr = ip
        self.port_offset = port_offset
        self.p2p_port = 2001 + (port_offset * 10)
        self.rpc_port = 9000
        self.metrics_port = 9184

        env = {
            "RUST_LOG": "info,iota_node=info",
            "NODE_TYPE": role,
        }

        logger.debug(f"Creating IotaNode {name} ({role}) @ {ip}")

        super().__init__(
            name=name,
            dimage=image,
            ip=ip,
            environment=env,
            privileged=True,
            dcmd="tail -f /dev/null",
            **kwargs
        )

    def get_config_command(self) -> str:
        return (
            "set -e; "
            "mkdir -p /var/log/iota; "
            "nohup iota-node --config-path /custom_config/validator.yaml "
            "> /var/log/iota/iota-node.log 2>&1 & "
            "echo $! > /var/log/iota/iota-node.pid"
        )


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
        self._generate_genesis()
        self._prepare_configs()
        self._inject_and_boot()
        self._wait_for_network_ready()
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

    def _ensure_iota_binary(self) -> str:
        if self._iota_binary_path:
            return self._iota_binary_path
        iota_path = shutil.which("iota")
        if iota_path and os.access(iota_path, os.X_OK):
            logger.info(f"✅ Found iota binary in PATH: {iota_path}")
            self._validate_binary_version(iota_path)
            self._iota_binary_path = iota_path
            return iota_path
        logger.warning("⚠️ iota binary not found in PATH")
        logger.info(f"Extracting binary from image: {self.image}")
        temp_bin_dir = "/tmp/fogbed_iota_bin"
        os.makedirs(temp_bin_dir, exist_ok=True)
        result = subprocess.run(["docker", "create", "--rm", self.image], capture_output=True, text=True, check=True)
        container_id = result.stdout.strip()
        iota_temp_path = f"{temp_bin_dir}/iota"
        subprocess.run(["docker", "cp", f"{container_id}:/usr/local/bin/iota", iota_temp_path], check=True, capture_output=True)
        subprocess.run(["docker", "rm", container_id], check=True, capture_output=True)
        os.chmod(iota_temp_path, 0o755)
        self._validate_binary_version(iota_temp_path)
        self._iota_binary_path = iota_temp_path
        return iota_temp_path

    def _validate_binary_version(self, binary_path: str) -> None:
        result = subprocess.run([binary_path, "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Binary test failed: {result.stderr}")
        version_match = re.search(r"v?(\d+\.\d+\.\d+)", result.stdout)
        if version_match:
            version = version_match.group(1)
            self._iota_version = version
            logger.info(f"✅ IOTA binary version: {version}")
            if self._compare_versions(version, MIN_IOTA_VERSION) < 0:
                raise RuntimeError(f"IOTA version {version} is below minimum required {MIN_IOTA_VERSION}.")
        else:
            logger.warning(f"⚠️  Could not parse version from: {result.stdout}")

    def _compare_versions(self, v1: str, v2: str) -> int:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
        return 0

    def _generate_genesis(self) -> None:
        validators = [n for n in self.nodes if n.role == "validator"]
        if not validators:
            raise RuntimeError("At least one validator required for genesis generation")
        
        iota_binary = self._ensure_iota_binary()
        logger.info(f"Generating genesis for {len(validators)} validators")
        
        cmd = [
            iota_binary, "genesis",
            "--working-dir", GENESIS_DIR,
            "--force", "--with-faucet",
            "--committee-size", str(len(validators)),
        ]
        logger.debug(f"Genesis command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        genesis_blob = os.path.join(GENESIS_DIR, "genesis.blob")
        if not os.path.exists(genesis_blob):
            raise RuntimeError(f"Genesis blob not created at {genesis_blob}")
        
        logger.info("✅ Genesis generated successfully")


    def _prepare_configs(self) -> None:
        logger.info("Preparing YAML configurations")
        
        # Busca recursiva para *.yaml e *.yml
        yaml_files = sorted(glob.glob(os.path.join(GENESIS_DIR, "**", "*.y*ml"), recursive=True))
        logger.debug(f"Found YAMLs: {[os.path.basename(f) for f in yaml_files]}")
        
        # Filtra apenas templates de validator (exclui client/configs)
        validator_yamls = []
        for f in yaml_files:
            base = os.path.basename(f).lower()
            if any(skip in base for skip in ["client", "iota_config", "fullnode"]):
                continue
            validator_yamls.append(f)
        
        validators = [n for n in self.nodes if n.role == "validator"]
        if not validator_yamls:
            raise RuntimeError(f"No validator templates found in {GENESIS_DIR}. Check genesis generation.")
        
        for i, node in enumerate(validators):
            template = validator_yamls[i % len(validator_yamls)]  # Rodízio seguro
            logger.debug(f"Using template {os.path.basename(template)} for {node.name}")
            
            node_dir = f"{LIVE_DATA_DIR}/{node.name}"
            os.makedirs(node_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{node_dir}/genesis.blob")
            self._patch_validator_yaml(template, f"{node_dir}/validator.yaml", node, validators)
        
        # Gateway usa o primeiro validator ou template genérico
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        if fullnodes:
            fullnode_yaml = next((f for f in yaml_files if "fullnode" in os.path.basename(f).lower()), validator_yamls[0])
            gateway = fullnodes[0]
            gw_dir = f"{LIVE_DATA_DIR}/{gateway.name}"
            os.makedirs(gw_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{gw_dir}/genesis.blob")
            self._create_gateway_config(fullnode_yaml, f"{gw_dir}/validator.yaml", gateway, validators)
        
        logger.info("✅ All configurations prepared")


    def _patch_validator_yaml(self, source: str, dest: str, node: IotaNode, all_validators: List[IotaNode]) -> None:
        logger.debug(f"Patching validator YAML: {source} → {dest}")
        with open(source, "r") as f:
            lines = f.readlines()
        new_lines: List[str] = []
        for line in lines:
            if "db-path:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}db-path: "/app/db"\n')
            elif "genesis-file-location:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}genesis-file-location: "/custom_config/genesis.blob"\n')
            elif "network-address:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f"{indent}network-address: /ip4/0.0.0.0/tcp/8080/http\n")
            elif "metrics-address:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}metrics-address: "0.0.0.0:9184"\n')

            elif "listen-address:" in line and "p2p" not in line.lower():
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}listen-address: "0.0.0.0:{node.p2p_port}"\n')
            elif "external-address:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}external-address: /ip4/{node.ip_addr}/tcp/{node.p2p_port}\n')
            elif any(k in line for k in ["pruning-period", "num-epochs-to-retain"]):
                continue
            else:
                new_lines.append(line)
        with open(dest, "w") as f:
            f.writelines(new_lines)
        logger.debug(f"✅ Validator YAML patched for {node.name}")

    def _create_gateway_config(
        self,
        source: str,
        dest: str,
        gateway: IotaNode,
        validators: List[IotaNode],
    ) -> None:
        """Gera YAML válido para o gateway (fullnode)."""
        logger.debug(f"Creating gateway(fullnode) config: {dest}")

        lines = [
            "---",
            'db-path: "/app/db"',
            "network-address: /ip4/0.0.0.0/tcp/8080/http",
            'metrics-address: "0.0.0.0:9184"',
            "",
            'json-rpc-address: "0.0.0.0:9000"',
            "",
            "genesis:",
            '  genesis-file-location: "/custom_config/genesis.blob"',
            "",
            "p2p-config:",
            f'  listen-address: "0.0.0.0:{gateway.p2p_port}"',
            f"  external-address: /ip4/{gateway.ip_addr}/tcp/{gateway.p2p_port}",
            "  seed-peers:",
        ]

        for v in validators:
            lines.append(f"    - address: /ip4/{v.ip_addr}/tcp/{v.p2p_port}")

        with open(dest, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


        logger.debug("✅ Gateway(fullnode) config created")

    def _inject_and_boot(self) -> None:
        logger.info("Injecting configs and booting nodes")
        validators = [n for n in self.nodes if n.role == "validator"]
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        logger.info(f"Starting {len(validators)} validators sequentially...")
        for i, node in enumerate(validators):
            self._inject_and_start_node(node)
            if i < len(validators) - 1:
                logger.debug(f"Waiting 8s before starting next validator...")
                time.sleep(8)
        if validators:
            logger.info("Waiting 15s for validator network to stabilize...")
            time.sleep(15)
        logger.info(f"Starting {len(fullnodes)} fullnodes...")
        for node in fullnodes:
            self._inject_and_start_node(node)
            self._wait_port_open(node, 9000, timeout=90)
        logger.info("✅ All nodes booted successfully")

    def _inject_and_start_node(self, node: IotaNode) -> None:
        src_dir = f"{LIVE_DATA_DIR}/{node.name}"
        if not os.path.exists(src_dir):
            raise RuntimeError(f"Config directory missing for {node.name}: {src_dir}")
        logger.info(f"Booting node: {node.name} (role={node.role}, ip={node.ip_addr})")
        node.cmd("mkdir -p /custom_config")
        cmd = f"docker cp {src_dir}/. mn.{node.name}:/custom_config/"
        rc = os.system(cmd)
        if rc != 0:
            raise RuntimeError(f"docker cp failed for {node.name} (exit code {rc})")
        logger.debug(f"Successfully copied {src_dir} to mn.{node.name}:/custom_config/")
        node.cmd("sh -lc 'ls -la /custom_config && echo --- && head -n 80 /custom_config/validator.yaml'")
        self._debug_runtime_ip(node)
        time.sleep(1)
        node.cmd(node.get_config_command())
        self._wait_node_process(node, timeout=30)

    def _wait_node_process(self, node: IotaNode, timeout: int = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = node.cmd("sh -lc 'test -f /var/log/iota/iota-node.pid && ps -p $(cat /var/log/iota/iota-node.pid) >/dev/null 2>&1 && echo OK || echo NOK'")
            if "OK" in out:
                logger.debug(f"✅ Process started on {node.name}")
                return
            time.sleep(1)
        tail = node.cmd("sh -lc 'tail -n 200 /var/log/iota/iota-node.log 2>/dev/null || true'")
        raise RuntimeError(f"iota-node failed to start on {node.name}. Last log:\n{tail}")

    def _wait_port_open(self, node: IotaNode, port: int, timeout: int = 90) -> None:
        deadline = time.time() + timeout
        check_tool = node.cmd("command -v ss >/dev/null 2>&1 && echo ss || echo netstat").strip()
        if check_tool == "ss":
            check_cmd = f"ss -lnt | grep -q ':{port}'"
        else:
            check_cmd = f"netstat -lnt | grep -q ':{port}'"
        logger.debug(f"Waiting for port {port} on {node.name} using {check_tool}")
        while time.time() < deadline:
            out = node.cmd(f"sh -lc '{check_cmd} && echo OK || echo NOK'")
            if "OK" in out:
                logger.debug(f"✅ Port {port} open on {node.name}")
                return
            time.sleep(2)
        tail = node.cmd("sh -lc 'tail -n 220 /var/log/iota/iota-node.log 2>/dev/null || true'")
        raise RuntimeError(f"Port {port} did not open on {node.name} within {timeout}s. Last log:\n{tail}")

    def _debug_runtime_ip(self, node: IotaNode) -> None:
        out = node.cmd("sh -lc \"ip -4 addr show | grep -oE '10\\.0\\.0\\.[0-9]+' | head -n1 || true\"").strip()
        logger.debug(f"Node {node.name} (role={node.role}, expected_ip={node.ip_addr}, runtime_ip={out})")

    def _wait_for_network_ready(self, timeout: int = 90) -> None:
        logger.info("Waiting for network consensus...")
        gateway = next((n for n in self.nodes if n.role == "fullnode"), None)
        if not gateway:
            logger.warning("No gateway found, skipping RPC health check")
            return
        deadline = time.time() + timeout
        rpc_url = f"http://{gateway.ip_addr}:{gateway.rpc_port}"
        while time.time() < deadline:
            try:
                result = gateway.cmd(f'curl -s -X POST {rpc_url} -H "Content-Type: application/json" -d \'{{' + '"jsonrpc":"2.0","method":"iota_getTotalTransactionBlocks","params":[],"id":1}}\' 2>/dev/null || echo FAIL')
                if "FAIL" not in result and "error" not in result.lower():
                    try:
                        data = json.loads(result)
                        if "result" in data:
                            logger.info(f"✅ RPC responding: {data}")
                            return
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.debug(f"RPC check failed: {e}")
            time.sleep(3)
        logger.warning(f"⚠️ RPC did not respond within {timeout}s, proceeding anyway...")

    def _configure_client(self) -> None:
        if not self.client_container:
            logger.debug("No client container to configure")
            return
        logger.info("📱 Configuring client container (genesis bank keystore)")
        rpc_node = next((n for n in self.nodes if n.role == "fullnode"), self.nodes[0] if self.nodes else None)
        if not rpc_node:
            raise RuntimeError("No nodes available for client configuration")
        self.client_container.cmd("mkdir -p /root/.iota/iota_config")
        host_keystore = os.path.join(GENESIS_DIR, "iota.keystore")
        if not os.path.exists(host_keystore):
            host_keystore = os.path.join(GENESIS_DIR, "benchmark.keystore")
        if not os.path.exists(host_keystore):
            logger.warning("⚠️ No genesis keystore found, client may not have funds")
        else:
            cmd_cp = f"docker cp {host_keystore} mn.{self.client_container.name}:/root/.iota/iota.keystore"
            rc = os.system(cmd_cp)
            if rc != 0:
                raise RuntimeError(f"Failed to copy keystore to client (rc={rc})")
            logger.debug("✅ Genesis keystore copied")
        rpc_url = f"http://{rpc_node.ip_addr}:{rpc_node.rpc_port}"
        yaml_content = f"""---
keystore:
  File: /root/.iota/iota.keystore
envs:
  - alias: fogbed
    rpc: "{rpc_url}"
    ws: ~
    basic_auth: ~
active_env: fogbed
"""
        self.client_container.cmd(f"cat > /root/.iota/iota_config/client.yaml << 'EOF'\n{yaml_content}\nEOF")
        validate_cmd = 'python3 -c "import yaml; yaml.safe_load(open(\'/root/.iota/iota_config/client.yaml\'))" 2>&1'
        validate_result = self.client_container.cmd(validate_cmd)
        if "error" in validate_result.lower() or "exception" in validate_result.lower():
            logger.error(f"❌ Generated client.yaml is invalid:\n{validate_result}")
            raise RuntimeError("Invalid client.yaml generated")
        logger.debug("✅ client.yaml validated")
        self.client_container.cmd("sh -lc 'iota client --client.config /root/.iota/iota_config/client.yaml envs 2>&1 || true'")
        logger.info(f"✅ Client configured (RPC: {rpc_url})")

    def _setup_smart_contract_env(self) -> None:
        if not self.client_container:
            logger.warning("No client container - skipping smart contract setup")
            return
        logger.info("Setting up smart contract environment")
        try:
            from fogbed_iota.accounts import AccountManager
            from fogbed_iota.smart_contracts import SmartContractManager
            self.account_manager = AccountManager(self.client_container)
            self.contract_manager = SmartContractManager(self.client_container, self.account_manager)
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
            logger.info(f"  - Config: /root/.iota/iota_config/client.yaml")
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

