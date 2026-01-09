"""
iota_fogbed.py - Módulo de Emulação IOTA para Fogbed
Autor: Paulo (com assistência de IA)
"""
import os
import shutil
import glob
import re
from typing import List, Optional
from fogbed import Container, FogbedExperiment

# --- CONSTANTES DE AMBIENTE ---
IOTA_BASE_DIR = "/home/paulo/iota"
IOTA_BIN_NODE = f"{IOTA_BASE_DIR}/target/release/iota-node"
IOTA_BIN_CLI = f"{IOTA_BASE_DIR}/target/release/iota"
IOTA_BIN_FAUCET = f"{IOTA_BASE_DIR}/target/release/iota-faucet"

WORK_DIR = "/tmp/iota_fogbed_workdir"
GENESIS_DIR = f"{WORK_DIR}/genesis"
LIVE_DATA_DIR = f"{WORK_DIR}/live_data"

class IotaNode(Container):
    def __init__(self, name: str, ip: str, role: str = 'validator', port_offset: int = 0):
        self.role = role
        self.ip_addr = ip
        self.port_offset = port_offset
        self.p2p_port = 2001 + (port_offset * 10)
        self.rpc_port = 9000
        
        volumes = [
            f"{IOTA_BIN_NODE}:/usr/local/bin/iota-node",
            f"{IOTA_BIN_CLI}:/usr/local/bin/iota"
        ]
        
        env = {"RUST_LOG": "info,iota_node=info"}
        
        # --- MUDANÇA CRÍTICA: privileged=True ---
        super().__init__(
            name, 
            dimage='iota-dev:latest', 
            ip=ip, 
            volumes=volumes, 
            environment=env,
            privileged=True 
        )

    def get_config_command(self) -> str:
        return (
            f"nohup iota-node --config-path /custom_config/validator.yaml "
            f"> /app/iota.log 2>&1 &"
        )

class IotaFaucet(Container):
    def __init__(self, name: str, ip: str):
        volumes = [
            f"{IOTA_BIN_FAUCET}:/usr/local/bin/iota-faucet",
            f"{IOTA_BIN_CLI}:/usr/local/bin/iota"
        ]
        super().__init__(
            name, 
            dimage='iota-dev:latest', 
            ip=ip, 
            volumes=volumes,
            privileged=True
        )
        self.ip_addr = ip
        self.port = 9123

class IotaNetworkManager:
    def __init__(self, experiment: FogbedExperiment):
        self.exp = experiment
        self.nodes: List[IotaNode] = []
        self.faucet: Optional[IotaFaucet] = None
        self.client_node: Optional[Container] = None

    def add_node(self, name: str, ip: str, role: str = 'validator') -> IotaNode:
        offset = len(self.nodes)
        node = IotaNode(name, ip, role, port_offset=offset)
        self.nodes.append(node)
        return node

    def add_faucet(self, name: str, ip: str) -> IotaFaucet:
        self.faucet = IotaFaucet(name, ip)
        return self.faucet
    
    def set_client(self, container: Container):
        self.client_node = container

    def start(self):
        print("[IotaManager] --- Iniciando Orquestração ---")
        self._cleanup()
        self._generate_genesis()
        self._prepare_configs()
        self._inject_and_boot()
        self._configure_client()
        print("[IotaManager] --- Rede Operacional ---")

    def _cleanup(self):
        print("[IotaManager] Limpando diretórios temporários...")
        if os.path.exists(WORK_DIR):
            shutil.rmtree(WORK_DIR)
        os.makedirs(GENESIS_DIR, exist_ok=True)
        os.makedirs(LIVE_DATA_DIR, exist_ok=True)

    def _generate_genesis(self):
        print("[IotaManager] Gerando Genesis Block...")
        validators = [n for n in self.nodes if n.role == 'validator']
        ips = [n.ip_addr for n in validators]
        cmd = f"{IOTA_BIN_CLI} genesis --working-dir {GENESIS_DIR} --force --benchmark-ips {' '.join(ips)}"
        if os.system(cmd) != 0:
            raise RuntimeError("Falha crítica ao executar 'iota genesis'.")

    def _prepare_configs(self):
        print("[IotaManager] Processando arquivos de configuração...")
        yaml_files = sorted(glob.glob(f"{GENESIS_DIR}/*.yaml"))
        validator_yamls = [f for f in yaml_files if "fullnode" not in f]
        
        validators = [n for n in self.nodes if n.role == 'validator']
        for i, node in enumerate(validators):
            if i >= len(validator_yamls): break
            node_dir = f"{LIVE_DATA_DIR}/{node.name}"
            os.makedirs(node_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{node_dir}/genesis.blob")
            self._patch_validator_yaml(validator_yamls[i], f"{node_dir}/validator.yaml", node, validators)

        fullnodes = [n for n in self.nodes if n.role == 'fullnode']
        if fullnodes and os.path.exists(f"{GENESIS_DIR}/fullnode.yaml"):
            gateway = fullnodes[0]
            gw_dir = f"{LIVE_DATA_DIR}/{gateway.name}"
            os.makedirs(gw_dir, exist_ok=True)
            shutil.copy(f"{GENESIS_DIR}/genesis.blob", f"{gw_dir}/genesis.blob")
            self._create_gateway_config(f"{GENESIS_DIR}/fullnode.yaml", f"{gw_dir}/validator.yaml", gateway, validators)

    def _patch_validator_yaml(self, source, dest, node, all_nodes):
        with open(source, 'r') as f: lines = f.readlines()
        new_lines = []
        for line in lines:
            if "db-path:" in line:
                path = "/app/consensus_db" if "consensus" in self._get_context(lines, line) else "/app/db"
                new_lines.append(f'  db-path: "{path}"\n' if line.startswith(' ') else f'db-path: "{path}"\n')
            elif "genesis-file-location:" in line:
                new_lines.append('  genesis-file-location: "/custom_config/genesis.blob"\n')
            elif "network-address:" in line:
                new_lines.append('network-address: /ip4/0.0.0.0/tcp/8080/http\n')
            elif "metrics-address:" in line:
                new_lines.append('metrics-address: "0.0.0.0:9184"\n')
            elif "listen-address:" in line:
                new_lines.append(f'  listen-address: "0.0.0.0:{node.p2p_port}"\n')
            elif "external-address:" in line:
                new_lines.append(f'  external-address: /ip4/{node.ip_addr}/udp/{node.p2p_port}\n')
            elif any(k in line for k in ["pruning-period", "num-epochs-to-retain"]):
                continue
            else:
                new_lines.append(line)
        with open(dest, 'w') as f: f.writelines(new_lines)

    def _create_gateway_config(self, source, dest, gateway, validators):
        keys = {}
        with open(source, 'r') as f:
            content = f.read()
            for k in ["authority-key-pair", "protocol-key-pair", "account-key-pair", "network-key-pair"]:
                m = re.search(rf"{k}:\s*\n\s*value:\s*(.+)", content)
                if m: keys[k] = m.group(1).strip()
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
        for v in validators:
            config += f"    - address: /ip4/{v.ip_addr}/udp/{v.p2p_port}\n"
        config += 'genesis:\n  genesis-file-location: "/custom_config/genesis.blob"\n'
        with open(dest, 'w') as f: f.write(config)

    def _inject_and_boot(self):
        print("[IotaManager] Injetando configs e iniciando nós...")
        for node in self.nodes:
            src_dir = f"{LIVE_DATA_DIR}/{node.name}"
            if not os.path.exists(src_dir): continue
            node.cmd("mkdir -p /custom_config")
            os.system(f"docker cp {src_dir}/. mn.{node.name}:/custom_config/")
            print(f"   -> Start {node.name} ({node.role})...")
            node.cmd(node.get_config_command())

    def _configure_client(self):
        if not self.client_node: return
        print("[IotaManager] Configurando Alias 'fognet' no Cliente...")
        rpc_node = next((n for n in self.nodes if n.role == 'fullnode'), self.nodes[0])
        faucet_url = f"http://{self.faucet.ip_addr}:{self.faucet.port}" if self.faucet else "null"
        yaml_content = f"""---
keystore:
  File: /root/.iota/iota.keystore
envs:
  fognet:
    rpc: "http://{rpc_node.ip_addr}:{rpc_node.rpc_port}"
    ws: ~
    basic_auth: ~
    faucet: "{faucet_url}"
active_env: fognet
"""
        self.client_node.cmd("mkdir -p /root/.iota")
        self.client_node.cmd(f"echo '{yaml_content}' > /root/.iota/client.yaml")

    def _get_context(self, lines, current_line):
        idx = lines.index(current_line)
        for i in range(idx, -1, -1):
            if "consensus-config:" in lines[i]: return "consensus"
        return "main"