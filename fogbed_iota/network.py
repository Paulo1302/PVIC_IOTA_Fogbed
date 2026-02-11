# fogbed_iota/network.py

"""
Orquestração de rede IOTA com Fogbed

Gerencia validadores, fullnodes/gateway e container cliente (IOTA CLI).
"""

import os
import shutil
import glob
import re
import subprocess
import time
from typing import List, Optional, TYPE_CHECKING

from fogbed import Container, FogbedExperiment

from fogbed_iota.utils import (
    get_logger,
    validate_node_config,
)

if TYPE_CHECKING:
    from fogbed_iota.accounts import AccountManager
    from fogbed_iota.smart_contracts import SmartContractManager

logger = get_logger("network")

WORK_DIR = "/tmp/fogbed_iota_workdir"
GENESIS_DIR = os.path.join(WORK_DIR, "genesis")
LIVE_DATA_DIR = os.path.join(WORK_DIR, "live_data")
DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")


class IotaNode(Container):
    """
    Container Fogbed que roda um iota-node.
    """

    def __init__(
        self,
        name: str,
        ip: str,
        role: str = "validator",
        port_offset: int = 0,
        image: str = DEFAULT_IMAGE,
    ):
        valid, errors = validate_node_config(name, ip, role, port_offset)
        if not valid:
            raise ValueError(f"Invalid node config: {errors}")

        self.role = role
        self.ip_addr = ip
        self.port_offset = port_offset

        # Portas (P2P muda por nó; RPC/metrics padronizados)
        self.p2p_port = 2001 + (port_offset * 10)
        self.rpc_port = 9000
        self.metrics_port = 9184

        env = {
            "RUST_LOG": "info,iota_node=info",
            "NODE_TYPE": role,
        }

        logger.debug(f"Creating IotaNode: {name} ({role}) @ {ip}")

        super().__init__(
            name=name,
            dimage=image,
            ip=ip,
            environment=env,
            privileged=True,
            dcmd="tail -f /dev/null",
        )

    def get_config_command(self) -> str:
        """
        Sobe iota-node em background + log + pid.
        """
        return (
            "set -e; "
            "mkdir -p /var/log/iota; "
            "nohup iota-node --config-path /custom_config/validator.yaml "
            "> /var/log/iota/iota-node.log 2>&1 & "
            "echo $! > /var/log/iota/iota-node.pid"
        )


class IotaNetwork:
    """
    Orquestrador principal da rede IOTA.
    """

    def __init__(self, experiment: FogbedExperiment, image: str = DEFAULT_IMAGE):
        logger.info(f"Initializing IotaNetwork with image: {image}")
        self.exp = experiment
        self.image = image

        self.nodes: List[IotaNode] = []
        self.client_container: Optional[Container] = None

        self._iota_binary_path: Optional[str] = None

        self.account_manager: Optional["AccountManager"] = None
        self.contract_manager: Optional["SmartContractManager"] = None

    # ---------- Topologia ----------

    def add_validator(self, name: str, ip: str) -> IotaNode:
        logger.info(f"Adding validator: {name} @ {ip}")
        node = IotaNode(
            name=name,
            ip=ip,
            role="validator",
            port_offset=len(self.nodes),
            image=self.image,
        )
        self.nodes.append(node)
        logger.debug(f"✅ Validator {name} added (P2P: {node.p2p_port})")
        return node

    def add_gateway(self, name: str, ip: str) -> IotaNode:
        logger.info(f"Adding gateway (fullnode): {name} @ {ip}")
        node = IotaNode(
            name=name,
            ip=ip,
            role="fullnode",
            port_offset=len(self.nodes),
            image=self.image,
        )
        self.nodes.append(node)
        logger.debug(f"✅ Gateway {name} added (RPC: {node.rpc_port})")
        return node

    def set_client(self, container: Container) -> None:
        logger.info(f"Setting client container: {container.name}")
        self.client_container = container

    # ---------- Lifecycle ----------

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
        self._configure_client()
        self._setup_smart_contract_env()

        logger.info("=" * 60)
        logger.info("✅ IOTA Network Successfully Started!")
        logger.info("=" * 60)
        self._print_network_summary()

    # ---------- Helpers (process/ports) ----------

    def _wait_node_process(self, node: IotaNode, timeout: int = 25) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = node.cmd(
                "sh -lc \""
                "test -f /var/log/iota/iota-node.pid && "
                "ps -p $(cat /var/log/iota/iota-node.pid) >/dev/null 2>&1 "
                "&& echo OK || echo NOK\""
            )
            if "OK" in out:
                return
            time.sleep(1)

        tail = node.cmd("sh -lc \"tail -n 200 /var/log/iota/iota-node.log 2>/dev/null || true\"")
        raise RuntimeError(f"iota-node failed to start on {node.name}. Last log:\n{tail}")

    def _wait_port_open(self, node: IotaNode, port: int, timeout: int = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            out = node.cmd(
                f"sh -lc \""
                f"(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null) "
                f"| grep -q ':{port} ' && echo OK || echo NOK\""
            )
            if "OK" in out:
                return
            time.sleep(1)

        tail = node.cmd("sh -lc \"tail -n 220 /var/log/iota/iota-node.log 2>/dev/null || true\"")
        raise RuntimeError(f"Port {port} did not open on {node.name}. Last log:\n{tail}")

    def _debug_runtime_ip(self, node: IotaNode) -> None:
        out = node.cmd(
            "sh -lc \"ip -4 addr show | grep -oE '10\\.0\\.0\\.[0-9]+' | head -n1 || true\""
        ).strip()
        logger.info(f"Node {node.name}: role={node.role}, expected_ip={node.ip_addr}, runtime_ip={out}")

    # ---------- Internals ----------

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
            logger.info(f"✅ Found iota binary: {iota_path}")
            self._iota_binary_path = iota_path
            return iota_path

        logger.warning("⚠️ iota binary not found in PATH")
        logger.info(f"📦 Extracting binary from image: {self.image}")

        temp_bin_dir = "/tmp/fogbed_iota_bin"
        os.makedirs(temp_bin_dir, exist_ok=True)

        result = subprocess.run(
            ["docker", "create", "--rm", self.image],
            capture_output=True,
            text=True,
            check=True,
        )
        container_id = result.stdout.strip()

        iota_temp_path = f"{temp_bin_dir}/iota"
        subprocess.run(
            ["docker", "cp", f"{container_id}:/usr/local/bin/iota", iota_temp_path],
            check=True,
            capture_output=True,
        )
        subprocess.run(["docker", "rm", container_id], check=True, capture_output=True)

        os.chmod(iota_temp_path, 0o755)

        test_result = subprocess.run([iota_temp_path, "--version"], capture_output=True, text=True)
        if test_result.returncode != 0:
            raise RuntimeError(f"Binary test failed: {test_result.stderr}")

        self._iota_binary_path = iota_temp_path
        return iota_temp_path

    def _generate_genesis(self) -> None:
        validators = [n for n in self.nodes if n.role == "validator"]
        ips = [n.ip_addr for n in validators]
        if not ips:
            raise RuntimeError("At least one validator required for genesis generation")

        iota_binary = self._ensure_iota_binary()

        logger.info(f"📊 Generating genesis for {len(validators)} validators")
        cmd = [iota_binary, "genesis", "--working-dir", GENESIS_DIR, "--force"]
        for ip in ips:
            cmd.extend(["--benchmark-ips", ip])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("⚠️ Primary genesis command failed, trying alternative...")
            cmd_alt = [iota_binary, "genesis", "--working-dir", GENESIS_DIR, "--force", "--with-faucet"]
            result = subprocess.run(cmd_alt, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Genesis stdout:\n{result.stdout}")
                logger.error(f"Genesis stderr:\n{result.stderr}")
                raise RuntimeError(f"Genesis generation failed: {result.stderr}")

        genesis_blob = os.path.join(GENESIS_DIR, "genesis.blob")
        if not os.path.exists(genesis_blob):
            raise RuntimeError(f"Genesis blob not created at {genesis_blob}")

        logger.info("✅ Genesis generated successfully")

    def _prepare_configs(self) -> None:
        logger.info("⚙️ Preparing YAML configurations")

        yaml_files = sorted(glob.glob(f"{GENESIS_DIR}/*.yaml"))
        validator_yamls = [f for f in yaml_files if "fullnode" not in f]
        validators = [n for n in self.nodes if n.role == "validator"]

        # ---- validadores ----
        for i, node in enumerate(validators):
            if i >= len(validator_yamls):
                logger.warning(f"⚠️ Not enough YAML templates for {node.name}")
                break

            node_dir = f"{LIVE_DATA_DIR}/{node.name}"
            os.makedirs(node_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{node_dir}/genesis.blob")

            self._patch_validator_yaml(
                validator_yamls[i],
                f"{node_dir}/validator.yaml",
                node,
            )

        # ---- gateway/fullnode ----
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        fullnode_yaml = f"{GENESIS_DIR}/fullnode.yaml"
        if fullnodes and os.path.exists(fullnode_yaml):
            gateway = fullnodes[0]
            gw_dir = f"{LIVE_DATA_DIR}/{gateway.name}"
            os.makedirs(gw_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{gw_dir}/genesis.blob")

            # mantém o nome validator.yaml, mas o conteúdo é de gateway
            self._create_gateway_config(
                fullnode_yaml,
                f"{gw_dir}/validator.yaml",
                gateway,
                validators,
            )

        logger.info("✅ All configurations prepared")

    def _patch_validator_yaml(self, source: str, dest: str, node: IotaNode) -> None:
        logger.debug(f"Patching YAML: {source} → {dest}")

        with open(source, "r") as f:
            lines = f.readlines()

        new_lines: List[str] = []
        for line in lines:
            if "db-path:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                # simplifica: /app/db (consensus fica por conta do template)
                new_lines.append(f'{indent}db-path: "/app/db"\n')
            elif "genesis-file-location:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}genesis-file-location: "/custom_config/genesis.blob"\n')
            elif "network-address:" in line:
                new_lines.append("network-address: /ip4/0.0.0.0/tcp/8080/http\n")
            elif "metrics-address:" in line:
                new_lines.append('metrics-address: "0.0.0.0:9184"\n')
            elif "listen-address:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}listen-address: "0.0.0.0:{node.p2p_port}"\n')
            elif "external-address:" in line:
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}external-address: /ip4/{node.ip_addr}/udp/{node.p2p_port}\n')
            elif any(k in line for k in ["pruning-period", "num-epochs-to-retain"]):
                continue
            else:
                new_lines.append(line)

        with open(dest, "w") as f:
            f.writelines(new_lines)

        logger.debug("✅ YAML patched successfully")

    def _create_gateway_config(
        self,
        source: str,
        dest: str,
        gateway: IotaNode,
        validators: List[IotaNode],
    ) -> None:
        logger.debug(f"Creating gateway config: {dest}")

        keys = {}
        with open(source, "r") as f:
            content = f.read()

        for k in ["authority-key-pair", "protocol-key-pair", "account-key-pair", "network-key-pair"]:
            m = re.search(rf"{k}:\s*\n\s*value:\s*(.+)", content)
            if m:
                keys[k] = m.group(1).strip()

        # Compat RPC: versões diferentes aceitam chaves diferentes;
        # colocamos as duas (não costuma quebrar).
        config = f"""---
authority-key-pair:
  value: {keys.get('authority-key-pair', '')}
protocol-key-pair:
  value: {keys.get('protocol-key-pair', '')}
account-key-pair:
  value: {keys.get('account-key-pair', '')}
network-key-pair:
  value: {keys.get('network-key-pair', '')}

db-path: "/app/db"
network-address: /ip4/0.0.0.0/tcp/8080/http

# ---- JSON-RPC ----
json-rpc-address: "0.0.0.0:9000"
rpc-address: "0.0.0.0:9000"
enable-json-rpc: true
enable-rest-api: true

metrics-address: "0.0.0.0:9184"

p2p-config:
  listen-address: "0.0.0.0:{gateway.p2p_port}"
  external-address: /ip4/{gateway.ip_addr}/udp/{gateway.p2p_port}
  seed-peers:
"""

        for v in validators:
            config += f"    - address: /ip4/{v.ip_addr}/udp/{v.p2p_port}\n"

        config += """genesis:
  genesis-file-location: "/custom_config/genesis.blob"
"""

        with open(dest, "w") as f:
            f.write(config)

        logger.debug("✅ Gateway config created")

    def _inject_and_boot(self) -> None:
        logger.info("🚀 Injecting configs and booting nodes")

        for node in self.nodes:
            src_dir = f"{LIVE_DATA_DIR}/{node.name}"
            if not os.path.exists(src_dir):
                raise RuntimeError(f"Config directory missing for {node.name}: {src_dir}")

            logger.info(f"Booting node: {node.name} (role={node.role}, ip={node.ip_addr})")

            node.cmd("mkdir -p /custom_config")
            cmd = f"docker cp {src_dir}/. mn.{node.name}:/custom_config/"
            rc = os.system(cmd)
            if rc != 0:
                raise RuntimeError(f"docker cp failed for {node.name}")

            # debug: mostra as primeiras linhas do YAML que foi aplicado
            node.cmd("sh -lc \"ls -la /custom_config; echo '---'; sed -n '1,80p' /custom_config/validator.yaml\"")
            self._debug_runtime_ip(node)

            time.sleep(1)
            node.cmd(node.get_config_command())

            self._wait_node_process(node, timeout=25)

            # gateway precisa abrir 9000
            if node.role == "fullnode":
                self._wait_port_open(node, 9000, timeout=90)

        logger.info("✅ All nodes booted successfully")

    def _configure_client(self) -> None:
        """Configura container cliente com client.yaml + injeta keystore do genesis (bank)."""
        if not self.client_container:
            logger.debug("No client container to configure")
            return

        logger.info("📱 Configuring client container (genesis bank keystore)")

        rpc_node = next((n for n in self.nodes if n.role == "fullnode"), self.nodes[0] if self.nodes else None)
        if not rpc_node:
            raise RuntimeError("No nodes available for client configuration")

        # 1) padroniza config dir do CLI dentro do container
        self.client_container.cmd("mkdir -p /app/config")

        # 2) injeta keystore gerado no genesis
        host_bank = os.path.join(GENESIS_DIR, "benchmark.keystore")
        if not os.path.exists(host_bank):
            raise RuntimeError(f"benchmark.keystore not found at {host_bank}")

        # Nota: container real no Docker chama mn.<name>
        # para o client, normalmente: mn.client
        cmd_cp = f"docker cp {host_bank} mn.{self.client_container.name}:/app/config/iota.keystore"
        rc = os.system(cmd_cp)
        if rc != 0:
            raise RuntimeError(f"Failed to docker cp benchmark.keystore into client (rc={rc})")

        # 3) escreve client.yaml apontando RPC do gateway
        rpc_url = f"http://{rpc_node.ip_addr}:{rpc_node.rpc_port}"
        yaml_content = f"""---
    keystore:
    File: /app/config/iota.keystore
    envs:
    - alias: fogbed
        rpc: "{rpc_url}"
        ws: ~
        basic_auth: ~
    active_env: fogbed
    """
        self.client_container.cmd(f"cat > /app/config/client.yaml << 'EOF'\n{yaml_content}\nEOF")

        # 4) sanity check (não falha se o CLI não estiver pronto, mas ajuda debug)
        self.client_container.cmd("sh -lc \"iota client envs || true; iota client addresses || true\"")

        logger.info(f"✅ Client configured (RPC: {rpc_url})")



    def _print_network_summary(self) -> None:
        validators = [n for n in self.nodes if n.role == "validator"]
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]

        logger.info("")
        logger.info("📊 Network Summary:")
        logger.info(f" Validators: {len(validators)}")
        for v in validators:
            logger.info(f" - {v.name}: {v.ip_addr} (P2P {v.p2p_port})")

        for gw in fullnodes:
            logger.info(f" Gateway: {gw.name}")
            logger.info(f" - Address: {gw.ip_addr}")
            logger.info(f" - RPC: http://{gw.ip_addr}:{gw.rpc_port}")
            logger.info(f" - Metrics: http://{gw.ip_addr}:{gw.metrics_port}/metrics")
        logger.info("")

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
