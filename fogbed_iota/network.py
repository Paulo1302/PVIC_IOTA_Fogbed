# fogbed_iota/network.py
"""
Orquestração de rede IOTA com Fogbed
Gerencia validadores, fullnodes e cliente CLI com logging integrado
"""

import os
import shutil
import glob
import re
import subprocess
import time
from typing import List, Optional
from pathlib import Path
from fogbed_iota.models import create_validator, create_fullnode
from fogbed import Container, FogbedExperiment

# Importar sistema de logging e utilidades
from fogbed_iota.utils import (
    get_logger, 
    docker_copy, 
    docker_exec, 
    docker_logs,
    validate_node_config,
    validate_network_config,
    validate_genesis_blob
)

logger = get_logger('network')

# Diretórios de trabalho locais
WORK_DIR = "/tmp/fogbed_iota_workdir"
GENESIS_DIR = os.path.join(WORK_DIR, "genesis")
LIVE_DATA_DIR = os.path.join(WORK_DIR, "live_data")
DEFAULT_IMAGE = os.getenv("IOTA_DOCKER_IMAGE", "iota-dev:latest")


class IotaNode(Container):
    """
    Container Fogbed que roda um iota-node
    Estende Container com propriedades IOTA específicas
    """

    def __init__(
        self,
        name: str,
        ip: str,
        role: str = "validator",
        port_offset: int = 0,
        image: str = DEFAULT_IMAGE
    ):
        """
        Inicializa um nó IOTA
        
        Args:
            name: Nome do nó
            ip: Endereço IP do nó
            role: 'validator' ou 'fullnode'
            port_offset: Offset para cálculo de portas
            image: Imagem Docker a usar
        """
        # Validar configuração
        valid, errors = validate_node_config(name, ip, role, port_offset)
        if not valid:
            raise ValueError(f"Invalid node config: {errors}")
        
        self.role = role
        self.ip_addr = ip
        self.port_offset = port_offset
        
        # Portas diferenciadas por nó
        self.p2p_port = 2001 + (port_offset * 10)
        self.rpc_port = 9000
        self.metrics_port = 9184
        
        # Variáveis de ambiente
        env = {
            "RUST_LOG": "info,iota_node=info",
            "NODE_TYPE": role
        }
        
        logger.debug(f"Creating IotaNode: {name} ({role}) @ {ip}")
        
        super().__init__(
            name=name,
            dimage=image,
            ip=ip,
            environment=env,
            privileged=True,  # Crítico para Mininet/Fogbed
            dcmd="tail -f /dev/null"  # Mantém container vivo
        )

    def get_config_command(self) -> str:
        """
        Retorna comando para iniciar iota-node
        
        Returns:
            str: Comando de inicialização
        """
        cmd = (
            "nohup iota-node "
            "--config-path /custom_config/validator.yaml "
            "> /app/iota.log 2>&1 &"
        )
        return cmd


class IotaNetwork:
    """
    Orquestrador principal de rede IOTA com Fogbed
    
    Responsabilidades:
    - Gerar genesis automaticamente
    - Configurar YAML para validadores e fullnodes
    - Injetar configs nos containers
    - Iniciar processos iota-node
    - Configurar cliente CLI
    """

    def __init__(self, experiment: FogbedExperiment, image: str = DEFAULT_IMAGE):
        """
        Inicializa orquestrador de rede
        
        Args:
            experiment: FogbedExperiment para adicionar nós
            image: Imagem Docker IOTA a usar
        """
        logger.info(f"Initializing IotaNetwork with image: {image}")
        
        self.exp = experiment
        self.image = image
        self.nodes: List[IotaNode] = []
        self.client_container: Optional[Container] = None
        self._iota_binary_path: Optional[str] = None

    # ========== Construção da Topologia ==========

    def add_validator(self, name: str, ip: str) -> IotaNode:
        """
        Adiciona nó validador à rede
        
        Args:
            name: Nome do validador
            ip: IP do validador
            
        Returns:
            IotaNode: Nó criado
        """
        logger.info(f"Adding validator: {name} @ {ip}")
        
        node = IotaNode(
            name=name,
            ip=ip,
            role="validator",
            port_offset=len(self.nodes),
            image=self.image
        )
        
        self.nodes.append(node)
        logger.debug(f"✅ Validator {name} added (P2P: {node.p2p_port})")
        
        return node

    def add_gateway(self, name: str, ip: str) -> IotaNode:
        """
        Adiciona nó fullnode/gateway à rede
        
        Args:
            name: Nome do gateway
            ip: IP do gateway
            
        Returns:
            IotaNode: Nó criado
        """
        logger.info(f"Adding gateway (fullnode): {name} @ {ip}")
        
        node = IotaNode(
            name=name,
            ip=ip,
            role="fullnode",
            port_offset=len(self.nodes),
            image=self.image
        )
        
        self.nodes.append(node)
        logger.debug(f"✅ Gateway {name} added (RPC: {node.rpc_port}, Metrics: {node.metrics_port})")
        
        return node

    def set_client(self, container: Container) -> None:
        """
        Define container cliente CLI
        
        Args:
            container: Container cliente
        """
        logger.info(f"Setting client container: {container.name}")
        self.client_container = container

    # ========== Ciclo de Vida ==========

    def attach_to_experiment(self, datacenter_name: str = "cloud") -> None:
        """
        Anexa todos os nós ao FogbedExperiment
        
        Args:
            datacenter_name: Nome do datacenter virtual
        """
        logger.info(f"Attaching nodes to datacenter: {datacenter_name}")
        
        try:
            cloud = self.exp.get_virtual_instance(datacenter_name)
        except:
            cloud = None
        
        if cloud is None:
            logger.debug(f"Creating virtual instance: {datacenter_name}")
            cloud = self.exp.add_virtual_instance(datacenter_name)
        
        # Adicionar nós
        for node in self.nodes:
            self.exp.add_docker(node, datacenter=cloud)
            logger.debug(f"✅ Node {node.name} attached")
        
        # Adicionar cliente
        if self.client_container:
            self.exp.add_docker(self.client_container, datacenter=cloud)
            logger.debug(f"✅ Client {self.client_container.name} attached")
        
        logger.info(f"✅ All nodes attached to {datacenter_name}")

    def start(self) -> None:
        """
        Inicia a rede IOTA completa (deve ser chamado após exp.start())
        
        Sequência:
        1. Limpeza de diretórios anteriores
        2. Geração de genesis
        3. Preparação de configs YAML
        4. Injeção de configs em containers
        5. Boot de processos iota-node
        6. Configuração do cliente CLI
        """
        logger.info("="*60)
        logger.info("Starting IOTA Network Initialization")
        logger.info("="*60)
        
        try:
            logger.info("Phase 1/5: Cleanup")
            self._cleanup()
            
            logger.info("Phase 2/5: Genesis Generation")
            self._generate_genesis()
            
            logger.info("Phase 3/5: Config Preparation")
            self._prepare_configs()
            
            logger.info("Phase 4/5: Injection and Boot")
            self._inject_and_boot()
            
            logger.info("Phase 5/5: Client Configuration")
            self._configure_client()
            
            logger.info("="*60)
            logger.info("✅ IOTA Network Successfully Started!")
            logger.info("="*60)
            
            # Mostrar resumo
            self._print_network_summary()
            
        except Exception as e:
            logger.error(f"❌ Critical error during network initialization: {e}")
            raise

    # ========== Métodos Internos ==========

    def _cleanup(self) -> None:
        """Limpa diretórios de trabalho anteriores"""
        logger.debug(f"Cleaning up work directory: {WORK_DIR}")
        
        if os.path.exists(WORK_DIR):
            shutil.rmtree(WORK_DIR)
            logger.debug(f"Removed existing {WORK_DIR}")
        
        os.makedirs(GENESIS_DIR, exist_ok=True)
        os.makedirs(LIVE_DATA_DIR, exist_ok=True)
        
        logger.info(f"✅ Work directories ready")

    def _ensure_iota_binary(self) -> str:
        """
        Garante disponibilidade do binário iota
        
        Prioridade:
        1. Binário no PATH do sistema
        2. Extrair da imagem Docker
        
        Returns:
            str: Caminho para o binário iota
            
        Raises:
            RuntimeError: Se não conseguir obter o binário
        """
        if self._iota_binary_path:
            return self._iota_binary_path
        
        # Tentar encontrar no PATH
        iota_path = shutil.which("iota")
        if iota_path and os.access(iota_path, os.X_OK):
            logger.info(f"✅ Found iota binary: {iota_path}")
            self._iota_binary_path = iota_path
            return iota_path
        
        # Extrair da imagem Docker
        logger.warning("⚠️ iota binary not found in PATH")
        logger.info(f"📦 Extracting binary from image: {self.image}")
        
        temp_bin_dir = "/tmp/fogbed_iota_bin"
        os.makedirs(temp_bin_dir, exist_ok=True)
        
        try:
            # Criar container temporário
            result = subprocess.run(
                ["docker", "create", "--rm", self.image],
                capture_output=True,
                text=True,
                check=True
            )
            
            container_id = result.stdout.strip()
            logger.debug(f"Created temporary container: {container_id[:12]}")
            
            # Copiar binário
            iota_temp_path = f"{temp_bin_dir}/iota"
            subprocess.run(
                ["docker", "cp", f"{container_id}:/usr/local/bin/iota", iota_temp_path],
                check=True,
                capture_output=True
            )
            
            # Remover container
            subprocess.run(["docker", "rm", container_id], check=True, capture_output=True)
            
            # Tornar executável
            os.chmod(iota_temp_path, 0o755)
            
            # Verificar versão
            test_result = subprocess.run(
                [iota_temp_path, "--version"],
                capture_output=True,
                text=True
            )
            
            if test_result.returncode == 0:
                logger.info(f"✅ Binary extracted successfully")
                logger.info(f"   Version: {test_result.stdout.strip()}")
                self._iota_binary_path = iota_temp_path
                return iota_temp_path
            else:
                raise RuntimeError(f"Binary test failed: {test_result.stderr}")
        
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Failed to extract binary: {e}")
            raise RuntimeError(
                f"Cannot extract iota binary from image {self.image}. "
                f"Ensure image exists: docker images | grep {self.image.split(':')[0]}"
            )

    def _generate_genesis(self) -> None:
        """
        Gera arquivo genesis.blob usando o binário iota
        
        Raises:
            RuntimeError: Se falha na geração do genesis
        """
        validators = [n for n in self.nodes if n.role == "validator"]
        ips = [n.ip_addr for n in validators]
        
        if not ips:
            raise RuntimeError("At least one validator required for genesis generation")
        
        iota_binary = self._ensure_iota_binary()
        
        logger.info(f"📊 Generating genesis for {len(validators)} validators")
        logger.debug(f"   Validator IPs: {', '.join(ips)}")
        
        # Construir comando
        cmd = [iota_binary, "genesis", "--working-dir", GENESIS_DIR, "--force"]
        
        for ip in ips:
            cmd.extend(["--benchmark-ips", ip])
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.warning(f"⚠️ Primary genesis command failed, trying alternative...")
            
            # Tentar formato alternativo
            cmd_alt = [
                iota_binary, "genesis",
                "--working-dir", GENESIS_DIR,
                "--force",
                "--with-faucet"
            ]
            
            result = subprocess.run(cmd_alt, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"Genesis command output: {result.stdout}")
                logger.error(f"Genesis command error: {result.stderr}")
                raise RuntimeError(f"Genesis generation failed: {result.stderr}")
        
        # Verificar se genesis.blob foi criado
        genesis_blob = os.path.join(GENESIS_DIR, "genesis.blob")
        
        if not os.path.exists(genesis_blob):
            raise RuntimeError(f"Genesis blob not created at {genesis_blob}")
        
        size_kb = os.path.getsize(genesis_blob) / 1024
        logger.info(f"✅ Genesis generated successfully ({size_kb:.1f} KB)")

    def _prepare_configs(self) -> None:
        """Prepara configurações YAML para todos os nós"""
        logger.info(f"⚙️ Preparing YAML configurations")
        
        yaml_files = sorted(glob.glob(f"{GENESIS_DIR}/*.yaml"))
        validator_yamls = [f for f in yaml_files if "fullnode" not in f]
        validators = [n for n in self.nodes if n.role == "validator"]
        
        logger.debug(f"Found {len(validator_yamls)} validator YAML templates")
        
        # Preparar validadores
        for i, node in enumerate(validators):
            if i >= len(validator_yamls):
                logger.warning(f"⚠️ Not enough YAML templates for {node.name}")
                break
            
            node_dir = f"{LIVE_DATA_DIR}/{node.name}"
            os.makedirs(node_dir, exist_ok=True)
            
            shutil.copy(
                f"{GENESIS_DIR}/genesis.blob",
                f"{node_dir}/genesis.blob"
            )
            
            self._patch_validator_yaml(
                validator_yamls[i],
                f"{node_dir}/validator.yaml",
                node,
                validators
            )
            
            logger.debug(f"✅ Config prepared for {node.name}")
        
        # Preparar gateway (fullnode)
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        fullnode_yaml = f"{GENESIS_DIR}/fullnode.yaml"
        
        if fullnodes and os.path.exists(fullnode_yaml):
            gateway = fullnodes[0]
            gw_dir = f"{LIVE_DATA_DIR}/{gateway.name}"
            os.makedirs(gw_dir, exist_ok=True)
            
            shutil.copy(
                f"{GENESIS_DIR}/genesis.blob",
                f"{gw_dir}/genesis.blob"
            )
            
            self._create_gateway_config(
                fullnode_yaml,
                f"{gw_dir}/validator.yaml",
                gateway,
                validators
            )
            
            logger.debug(f"✅ Config prepared for gateway {gateway.name}")
        
        logger.info(f"✅ All configurations prepared")

    def _patch_validator_yaml(
        self,
        source: str,
        dest: str,
        node: IotaNode,
        all_nodes: List[IotaNode]
    ) -> None:
        """
        Faz patch do YAML de validador
        
        Substitui paths, IPs e portas conforme necessário
        """
        logger.debug(f"Patching YAML: {source} → {dest}")
        
        with open(source, "r") as f:
            lines = f.readlines()
        
        new_lines = []
        
        for line in lines:
            if "db-path:" in line:
                context = self._get_yaml_context(lines, line)
                path = "/app/consensus_db" if "consensus" in context else "/app/db"
                indent = " " * (len(line) - len(line.lstrip()))
                new_lines.append(f'{indent}db-path: "{path}"\n')
            
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
                new_lines.append(
                    f'{indent}external-address: /ip4/{node.ip_addr}/udp/{node.p2p_port}\n'
                )
            
            elif any(k in line for k in ["pruning-period", "num-epochs-to-retain"]):
                # Ignorar linhas de pruning para testes
                continue
            
            else:
                new_lines.append(line)
        
        with open(dest, "w") as f:
            f.writelines(new_lines)
        
        logger.debug(f"✅ YAML patched successfully")

    def _create_gateway_config(
        self,
        source: str,
        dest: str,
        gateway: IotaNode,
        validators: List[IotaNode]
    ) -> None:
        """
        Cria configuração customizada para gateway (fullnode)
        
        Extrai chaves do fullnode.yaml e injeta IPs dos validadores
        """
        logger.debug(f"Creating gateway config: {dest}")
        
        keys = {}
        
        with open(source, "r") as f:
            content = f.read()
        
        # Extrair chaves
        for k in ["authority-key-pair", "protocol-key-pair",
                  "account-key-pair", "network-key-pair"]:
            m = re.search(rf"{k}:\s*\n\s*value:\s*(.+)", content)
            if m:
                keys[k] = m.group(1).strip()
        
        # Montar configuração
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
json-rpc-address: "0.0.0.0:9000"
enable-rest-api: true
metrics-address: "0.0.0.0:9184"
p2p-config:
  listen-address: "0.0.0.0:{gateway.p2p_port}"
  external-address: /ip4/{gateway.ip_addr}/udp/{gateway.p2p_port}
  seed-peers:
"""
        
        # Adicionar validadores como seed peers
        for v in validators:
            config += f"    - address: /ip4/{v.ip_addr}/udp/{v.p2p_port}\n"
        
        config += """genesis:
  genesis-file-location: "/custom_config/genesis.blob"
"""
        
        with open(dest, "w") as f:
            f.write(config)
        
        logger.debug(f"✅ Gateway config created")

    def _inject_and_boot(self) -> None:
        """
        Injeta configs nos containers e inicia processos iota-node
        """
        logger.info(f"🚀 Injecting configs and booting nodes")
        
        for node in self.nodes:
            src_dir = f"{LIVE_DATA_DIR}/{node.name}"
            
            if not os.path.exists(src_dir):
                logger.warning(f"⚠️ Config directory missing for {node.name}")
                continue
            
            logger.debug(f"Processing node: {node.name}")
            
            # Criar diretório no container
            node.cmd("mkdir -p /custom_config")
            
            # Copiar configs (Mininet naming: mn.*)
            cmd = f"docker cp {src_dir}/. mn.{node.name}:/custom_config/"
            result = os.system(cmd)
            
            if result != 0:
                logger.error(f"❌ Failed to copy configs to {node.name}")
                continue
            
            logger.debug(f"✅ Configs copied to {node.name}")
            
            # Esperar container ficar pronto
            time.sleep(1)
            
            # Iniciar iota-node
            logger.info(f"   Starting iota-node on {node.name}...")
            node.cmd(node.get_config_command())
            
            logger.debug(f"✅ iota-node started on {node.name}")
        
        logger.info(f"✅ All nodes booted successfully")

    def _configure_client(self) -> None:
        """Configura container cliente com client.yaml"""
        if not self.client_container:
            logger.debug("No client container to configure")
            return
        
        logger.info(f"📱 Configuring client container")
        
        # Escolher fullnode como RPC, senão o primeiro validador
        rpc_node = next(
            (n for n in self.nodes if n.role == "fullnode"),
            self.nodes[0] if self.nodes else None
        )
        
        if not rpc_node:
            logger.warning("⚠️ No nodes available for client configuration")
            return
        
        yaml_content = f"""---
keystore:
  File: /root/.iota/iota.keystore
envs:
  - alias: fognet
    rpc: "http://{rpc_node.ip_addr}:{rpc_node.rpc_port}"
    ws: ~
    basic_auth: ~
active_env: fognet
"""
        
        self.client_container.cmd("mkdir -p /root/.iota")
        
        # Usar heredoc para evitar problemas de quoting
        cmd = f"cat > /root/.iota/client.yaml << 'EOF'\n{yaml_content}\nEOF"
        self.client_container.cmd(cmd)
        
        logger.info(f"✅ Client configured (RPC: {rpc_node.ip_addr}:{rpc_node.rpc_port})")

    @staticmethod
    def _get_yaml_context(lines: List[str], current_line: str) -> str:
        """Determina contexto YAML (consensus ou main)"""
        try:
            idx = lines.index(current_line)
        except ValueError:
            return "main"
        
        for i in range(idx, -1, -1):
            if "consensus-config:" in lines[i]:
                return "consensus"
        
        return "main"

    def _print_network_summary(self) -> None:
        """Imprime resumo da rede inicializada"""
        validators = [n for n in self.nodes if n.role == "validator"]
        fullnodes = [n for n in self.nodes if n.role == "fullnode"]
        
        logger.info("")
        logger.info("📊 Network Summary:")
        logger.info(f"   Validators: {len(validators)}")
        
        for v in validators:
            logger.info(f"     - {v.name}: {v.ip_addr}:{v.p2p_port}")
        
        if fullnodes:
            for gw in fullnodes:
                logger.info(f"   Gateway: {gw.name}")
                logger.info(f"     - Address: {gw.ip_addr}")
                logger.info(f"     - RPC: http://{gw.ip_addr}:{gw.rpc_port}")
                logger.info(f"     - Metrics: http://{gw.ip_addr}:{gw.metrics_port}/metrics")
        
        logger.info("")

    def get_node_count(self) -> dict:
        """Retorna contagem de nós na rede"""
        return {
            'validators': len([n for n in self.nodes if n.role == "validator"]),
            'fullnodes': len([n for n in self.nodes if n.role == "fullnode"]),
            'total': len(self.nodes)
        }

    class IotaNetwork:
        def add_validator(self, name: str, ip: str):
            validator = create_validator(name, ip, port_offset=len(self.nodes))
            self.nodes.append(validator)
            return validator